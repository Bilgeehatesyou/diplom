"""
Pilot үнэлгээний тайлан — протоколын ground truth-ийг системийн event-үүдтэй тулгана.

Арга зүй
  * Оролцогч PILOT_MODE=1 үед шалгалт өгч, дэлгэцийн заавраар тогтсон үйлдлүүдийг хийнэ.
    Алхам бүрийн эхлэх цагийг сервер `pilot_marks` хүснэгтэд бүртгэнэ (ground truth).
  * Эерэг алхам (жишээ нь "утас гаргах") нь тухайн детекторын event [эхлэл−1с, төгсгөл+tolerance]
    цонхонд ≥1 удаа гарвал ИЛРҮҮЛСЭН (step-level recall).
  * Event бүр: хүлээгдэж буй эерэг алхмын цонхонд бол TP; тухайн алхамд зөвшөөрөгдсөн ("allow")
    эсвэл setup/алгассан алхамд бол саармаг; бусад бүх тохиолдолд FP (event-level precision).
  * Хэвийн ("normal") алхмуудын FP-ийг хугацаанд хувааж цагт ногдох худал дохиоллын тоо гаргана.
  * Хүндрэлтэй сөрөг ("hard_negative": цаасан дээр бичих, чанга унших, гараар бичих) тусад нь.
  * Цөөн түүвэрт тоо тодорхойгүй тул 95% Wilson итгэх интервал хамт гаргана.

Ажиллуулах
  python scripts/evaluation/pilot_report.py                      # бүх pilot session
  python scripts/evaluation/pilot_report.py --sessions 41,42     # зөвхөн эдгээр
  python scripts/evaluation/pilot_report.py --db path/to/aiproctor.db --out results/

Гаралт: <out>/pilot_report.md, pilot_metrics.json, pilot_steps.csv, pilot_matrix.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT        = Path(__file__).resolve().parents[2]
DEFAULT_DB  = ROOT / "backend" / "aiproctor.db"
PROTOCOL    = ROOT / "backend" / "pilot_protocol.json"
DEFAULT_OUT = Path(__file__).resolve().parent / "results"
PRE_SEC     = 1.0   # алхам эхлэхээс 1с өмнөх event-ийг ч тооцно (хүний урьдчилсан хөдөлгөөн)


# ── Helpers ──────────────────────────────────────────────────────────────────
def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("T", " "))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - m) / d), min(1.0, (c + m) / d)


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.0f}%"


def ci(k: int, n: int) -> str:
    w = wilson(k, n)
    return "—" if w is None else f"{100 * w[0]:.0f}–{100 * w[1]:.0f}%"


def quantile(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    v = sorted(vals)
    i = min(len(v) - 1, max(0, math.ceil(q * len(v)) - 1))
    return v[i]


# ── Loading ──────────────────────────────────────────────────────────────────
def load_runs(con: sqlite3.Connection, protocol: dict, session_ids: list[int] | None) -> list[dict]:
    """Session бүрийн хамгийн сүүлийн бүтэн (calibrate-аас эхэлсэн) протоколын гүйлт."""
    spec = {s["id"]: s for s in protocol["steps"]}
    q = ("SELECT m.session_id, m.step_index, m.step_id, m.started_at, m.skipped, s.student_id "
         "FROM pilot_marks m JOIN exam_sessions s ON s.id = m.session_id WHERE m.protocol = ?")
    args: list = [protocol["id"]]
    if session_ids:
        q += f" AND m.session_id IN ({','.join('?' * len(session_ids))})"
        args += session_ids
    q += " ORDER BY m.session_id, m.started_at, m.id"
    by_session: dict[int, list] = defaultdict(list)
    student_of: dict[int, str] = {}
    for sid, idx, step_id, ts, skipped, student in con.execute(q, args):
        by_session[sid].append((idx, step_id, parse_ts(ts), bool(skipped)))
        student_of[sid] = student

    runs = []
    for sid, marks in by_session.items():
        starts = [i for i, m in enumerate(marks) if m[0] == 0 and not m[3]]
        if not starts:
            continue
        marks = marks[starts[-1]:]                       # сүүлийн гүйлт
        skipped_ids = {m[1] for m in marks if m[3]}
        firsts: dict[int, tuple] = {}
        for m in marks:
            if not m[3] and m[0] not in firsts:
                firsts[m[0]] = m
        ordered = [firsts[k] for k in sorted(firsts)]
        steps = []
        for j, (idx, step_id, start, _) in enumerate(ordered):
            if step_id == "end":
                break
            nxt = ordered[j + 1][2] if j + 1 < len(ordered) else start + timedelta(seconds=spec[step_id]["duration"])
            steps.append({"index": idx, "id": step_id, "start": start, "end": nxt,
                          "skipped": step_id in skipped_ids, "spec": spec[step_id]})
        if steps:
            runs.append({"session_id": sid, "student_id": student_of[sid], "steps": steps,
                         "complete": any(m[1] == "end" for m in marks)})
    return runs


def load_events(con: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = con.execute("SELECT event_type, severity, timestamp, confidence FROM risk_events "
                       "WHERE session_id = ? ORDER BY timestamp", (session_id,))
    return [{"type": t, "severity": s, "t": parse_ts(ts), "conf": c} for t, s, ts, c in rows]


# ── Matching ─────────────────────────────────────────────────────────────────
def evaluate(runs: list[dict], protocol: dict, events_of, tolerance: float) -> dict:
    detectors = protocol["detectors"]
    expect = {s["id"]: set(detectors[s["detector"]]["events"]) if s.get("detector") else set()
              for s in protocol["steps"]}
    allow = {s["id"]: set(s.get("allow", [])) for s in protocol["steps"]}
    det_of_event = {e: d for d, spec in detectors.items() for e in spec["events"]}
    tol = timedelta(seconds=tolerance)
    pre = timedelta(seconds=PRE_SEC)

    step_rows = []                                  # нэг мөр = нэг гүйлтийн нэг алхам
    ev_outcome = Counter()                          # (event_type, TP/FP/neutral)
    normal_fp = Counter()                           # event_type → FP during normal steps
    normal_fp_sev = Counter()
    normal_sec = 0.0
    hard_neg = defaultdict(list)                    # step_id → [event types per run]
    matrix = defaultdict(Counter)                   # step_id → event_type counts

    for run in runs:
        steps = run["steps"]
        events = events_of(run["session_id"])
        detected: dict[int, list[float]] = defaultdict(list)   # step list index → latencies
        per_step_events: dict[int, list[str]] = defaultdict(list)

        for st in steps:
            if st["spec"]["category"] == "normal" and not st["skipped"]:
                normal_sec += (st["end"] - st["start"]).total_seconds()

        for ev in events:
            host = next((k for k, st in enumerate(steps) if st["start"] <= ev["t"] < st["end"]), None)
            if host is None and steps and steps[-1]["end"] <= ev["t"] < steps[-1]["end"] + tol:
                host = len(steps) - 1
            if host is None:
                continue                            # протоколоос гадуур
            matrix[steps[host]["id"]][ev["type"]] += 1
            per_step_events[host].append(ev["type"])

            tp_step = next((k for k, st in enumerate(steps)
                            if st["spec"]["category"] == "positive" and not st["skipped"]
                            and ev["type"] in expect[st["id"]]
                            and st["start"] - pre <= ev["t"] <= st["end"] + tol), None)
            if tp_step is not None:
                ev_outcome[(ev["type"], "TP")] += 1
                detected[tp_step].append((ev["t"] - steps[tp_step]["start"]).total_seconds())
                continue
            hs = steps[host]
            if hs["spec"]["category"] == "setup" or hs["skipped"] or ev["type"] in allow[hs["id"]]:
                ev_outcome[(ev["type"], "neutral")] += 1
                continue
            ev_outcome[(ev["type"], "FP")] += 1
            if hs["spec"]["category"] == "normal":
                normal_fp[ev["type"]] += 1
                normal_fp_sev[ev["severity"]] += 1

        for k, st in enumerate(steps):
            cat = st["spec"]["category"]
            if cat == "hard_negative" and not st["skipped"]:
                bad = [t for t in per_step_events[k] if t not in allow[st["id"]]]
                hard_neg[st["id"]].append(bad)
            if cat != "positive":
                continue
            lat = min(detected[k]) if detected[k] else None
            step_rows.append({"session_id": run["session_id"], "student_id": run["student_id"],
                              "step": st["id"], "detector": st["spec"]["detector"],
                              "skipped": st["skipped"], "detected": bool(detected[k]),
                              "latency_sec": round(lat, 1) if lat is not None else None,
                              "events": " ".join(per_step_events[k])})

    # Detector-level metrics
    det_metrics = {}
    for d, spec in detectors.items():
        rows = [r for r in step_rows if r["detector"] == d and not r["skipped"]]
        n, k = len(rows), sum(r["detected"] for r in rows)
        tp = sum(ev_outcome[(e, "TP")] for e in spec["events"])
        fp = sum(ev_outcome[(e, "FP")] for e in spec["events"])
        recall = k / n if n else None
        precision = tp / (tp + fp) if tp + fp else None
        f1 = (2 * precision * recall / (precision + recall)
              if precision is not None and recall is not None and precision + recall > 0 else None)
        lats = [r["latency_sec"] for r in rows if r["latency_sec"] is not None]
        det_metrics[d] = {"label": spec["label"], "steps": n, "detected": k, "recall": recall,
                          "recall_ci": wilson(k, n), "tp_events": tp, "fp_events": fp,
                          "precision": precision, "precision_ci": wilson(tp, tp + fp), "f1": f1,
                          "latency_median": statistics.median(lats) if lats else None,
                          "latency_p90": quantile(lats, 0.9)}

    step_metrics = {}
    for sid in [s["id"] for s in protocol["steps"] if s["category"] == "positive"]:
        rows = [r for r in step_rows if r["step"] == sid and not r["skipped"]]
        lats = [r["latency_sec"] for r in rows if r["latency_sec"] is not None]
        step_metrics[sid] = {"runs": len(rows), "detected": sum(r["detected"] for r in rows),
                             "latency_median": statistics.median(lats) if lats else None}

    hours = normal_sec / 3600
    return {
        "runs": len(runs),
        "students": sorted({r["student_id"] for r in runs}),
        "tolerance_sec": tolerance,
        "detectors": det_metrics,
        "steps": step_metrics,
        "normal": {"seconds": round(normal_sec, 1),
                   "fp_total": sum(normal_fp.values()),
                   "fp_per_hour": sum(normal_fp.values()) / hours if hours else None,
                   "fp_med_high_per_hour": (normal_fp_sev["medium"] + normal_fp_sev["high"]) / hours if hours else None,
                   "fp_by_type": dict(normal_fp.most_common())},
        "hard_negatives": {sid: {"runs": len(v), "runs_with_fp": sum(1 for x in v if x),
                                 "events": dict(Counter(t for x in v for t in x))}
                           for sid, v in hard_neg.items()},
        "event_outcomes": {f"{t}|{o}": c for (t, o), c in sorted(ev_outcome.items())},
        "_step_rows": step_rows,
        "_matrix": {k: dict(v) for k, v in matrix.items()},
        "_det_of_event": det_of_event,
    }


# ── Output ───────────────────────────────────────────────────────────────────
def write_outputs(m: dict, protocol: dict, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    public = {k: v for k, v in m.items() if not k.startswith("_")}
    (out / "pilot_metrics.json").write_text(json.dumps(public, ensure_ascii=False, indent=2, default=str),
                                            encoding="utf-8")
    with open(out / "pilot_steps.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["session_id", "student_id", "step", "detector", "skipped",
                                          "detected", "latency_sec", "events"])
        w.writeheader()
        w.writerows(m["_step_rows"])
    types = sorted({t for row in m["_matrix"].values() for t in row})
    with open(out / "pilot_matrix.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["step"] + types)
        for s in protocol["steps"]:
            if s["id"] in m["_matrix"]:
                w.writerow([s["id"]] + [m["_matrix"][s["id"]].get(t, 0) for t in types])

    L = []
    L.append("# Pilot үнэлгээний тайлан\n")
    L.append(f"_Үүсгэсэн: {datetime.now():%Y-%m-%d %H:%M} · протокол `{protocol['id']}` · "
             f"{m['runs']} гүйлт · оролцогч: {', '.join(m['students']) or '—'} · tolerance {m['tolerance_sec']}с_\n")
    L.append("## Арга зүй\n")
    L.append("Оролцогч шалгалтын үеэр дэлгэцийн заавраар тогтсон үйлдлүүдийг хийж, алхам бүрийн эхлэх цагийг "
             "сервер бүртгэсэн (ground truth). Эерэг алхмын цонхонд [эхлэл−1с, төгсгөл+tolerance] тухайн "
             "детекторын event гарвал илрүүлсэн гэж тооцов (recall). Event бүрийг хүлээгдэж буй алхамд "
             "TP, зөвшөөрөгдсөн бол саармаг, бусад бүх тохиолдолд FP гэж ангилав (precision). "
             "Хаалтанд 95% Wilson итгэх интервал.\n")
    L.append("## Детектор тус бүрээр\n")
    L.append("| Детектор | Recall | 95% CI | Precision | 95% CI | F1 | Хоцролт (медиан / p90) |")
    L.append("|---|---|---|---|---|---|---|")
    for d in m["detectors"].values():
        lat = ("—" if d["latency_median"] is None
               else f"{d['latency_median']:.1f}с / {d['latency_p90']:.1f}с")
        L.append(f"| {d['label']} | {pct(d['recall'])} ({d['detected']}/{d['steps']}) | "
                 f"{ci(d['detected'], d['steps'])} | {pct(d['precision'])} ({d['tp_events']}/"
                 f"{d['tp_events'] + d['fp_events']}) | {ci(d['tp_events'], d['tp_events'] + d['fp_events'])} | "
                 f"{pct(d['f1'])} | {lat} |")
    L.append("\n## Алхам тус бүрээр (эерэг)\n")
    L.append("| Алхам | Илрүүлсэн | Хоцролт (медиан) |")
    L.append("|---|---|---|")
    for sid, s in m["steps"].items():
        lat = "—" if s["latency_median"] is None else f"{s['latency_median']:.1f}с"
        L.append(f"| `{sid}` | {s['detected']}/{s['runs']} | {lat} |")
    n = m["normal"]
    L.append("\n## Хэвийн үеийн худал дохиолол\n")
    L.append(f"- Хэвийн үйлдлийн нийт хугацаа: {n['seconds'] / 60:.1f} мин")
    fph = "—" if n["fp_per_hour"] is None else f"{n['fp_per_hour']:.1f}"
    fph_mh = "—" if n["fp_med_high_per_hour"] is None else f"{n['fp_med_high_per_hour']:.1f}"
    L.append(f"- Худал дохиолол: {n['fp_total']}  →  **{fph} / цаг** (medium+high: {fph_mh} / цаг)")
    if n["fp_by_type"]:
        L.append("- Төрлөөр: " + ", ".join(f"`{t}` {c}" for t, c in n["fp_by_type"].items()))
    L.append("\n## Хүндрэлтэй сөрөг тохиолдол\n")
    L.append("| Алхам | Худал дохиолол гарсан гүйлт | Event-үүд |")
    L.append("|---|---|---|")
    for sid, h in m["hard_negatives"].items():
        evs = ", ".join(f"`{t}` {c}" for t, c in h["events"].items()) or "—"
        L.append(f"| `{sid}` | {h['runs_with_fp']}/{h['runs']} | {evs} |")
    L.append("\n## Хязгаарлалт\n")
    L.append("- Ground truth нь протоколын цагаар тодорхойлогдсон; оролцогч зааврыг яг дагаагүй бол "
             "(хоцорсон, хийгээгүй) алдаа орно. Эргэлзээтэй гүйлтийг `--sessions`-оор хасна уу.")
    L.append("- Оролцогчдын тоо цөөн тул итгэх интервал өргөн; дүгнэлтийг интервалтай нь хамт тайлбарлана.")
    L.append("- Жүжигчилсэн (scripted) үйлдэл нь бодит хуулалтаас илүү тод байдаг тул recall нь бодит "
             "нөхцөлөөс өндөр гарах хандлагатай.")
    report = out / "pilot_report.md"
    report.write_text("\n".join(L) + "\n", encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--protocol", type=Path, default=PROTOCOL)
    ap.add_argument("--sessions", type=str, default="", help="таслалаар тусгаарласан session id")
    ap.add_argument("--tolerance", type=float, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args()

    protocol = json.loads(a.protocol.read_text(encoding="utf-8"))
    con = sqlite3.connect(str(a.db))
    sessions = [int(x) for x in a.sessions.split(",") if x.strip()] or None
    runs = load_runs(con, protocol, sessions)
    if not runs:
        raise SystemExit("Pilot гүйлт олдсонгүй (pilot_marks хоосон). PILOT_MODE=1-ээр туршилт хийсэн эсэхээ шалгана уу.")
    m = evaluate(runs, protocol, lambda sid: load_events(con, sid),
                 a.tolerance if a.tolerance is not None else protocol.get("tolerance_sec", 5))
    report = write_outputs(m, protocol, a.out)
    print(f"{m['runs']} гүйлт → {report}")
    for d in m["detectors"].values():
        print(f"  {d['label']:16s} recall {pct(d['recall']):>5s}  precision {pct(d['precision']):>5s}  F1 {pct(d['f1']):>5s}")
    fph = m["normal"]["fp_per_hour"]
    fph_s = "—" if fph is None else f"{fph:.1f}"
    print(f"  Хэвийн үеийн худал дохиолол: {fph_s} / цаг")


if __name__ == "__main__":
    main()

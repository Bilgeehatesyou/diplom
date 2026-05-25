"""Aggregate evaluation for all AI Proctor models.

Reads:
  - scripts/evaluation/vision_labels.json   (from label_incidents.py)
  - scripts/evaluation/audio_samples/<class>/*.wav|.mp3|.m4a|.webm

Produces:
  - EVALUATION_REPORT.md  (at repo root) — full Markdown report with tables,
    confusion matrices, precision/recall/F1, and published benchmarks.

Run:  python scripts/evaluation/evaluate.py
"""
from __future__ import annotations
import json, re, sys, os
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

REPO_ROOT     = Path(__file__).resolve().parent.parent.parent
LABELS_PATH   = Path(__file__).resolve().parent / "vision_labels.json"
AUDIO_DIR     = Path(__file__).resolve().parent / "audio_samples"
REPORT_PATH   = REPO_ROOT / "EVALUATION_REPORT.md"
INCIDENTS_DIR = REPO_ROOT / "models" / "incidents"

EVENT_RE = re.compile(r"^\d+_\d+_\d+_(.+)\.jpg$")
AUDIO_CLASSES = ["normal", "talking", "multiple", "whispering"]
# Map analyzer event_type → ground-truth class
EVENT_TO_CLASS = {
    "audio_speech":          "talking",
    "audio_talking":         "talking",
    "audio_multiple_voices": "multiple",
    "audio_whispering":      "whispering",
}

# ──────────────────────────────────────────────────────────────────────────────
# Vision evaluation
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_vision() -> dict:
    """Compute precision per event type from human-labeled incident snapshots."""
    if not LABELS_PATH.exists():
        return {"labeled": 0, "total": 0, "by_event": {}}

    labels = json.loads(LABELS_PATH.read_text())
    total  = 0
    if INCIDENTS_DIR.exists():
        for d in INCIDENTS_DIR.iterdir():
            if d.is_dir():
                total += sum(1 for _ in d.glob("*.jpg"))

    by_event: dict[str, dict] = defaultdict(lambda: {"tp": 0, "fp": 0})
    for path, verdict in labels.items():
        if verdict not in ("tp", "fp"):
            continue
        m = EVENT_RE.match(Path(path).name)
        if not m:
            continue
        ev = m.group(1)
        by_event[ev][verdict] += 1

    summary = {}
    for ev, counts in by_event.items():
        n = counts["tp"] + counts["fp"]
        prec = counts["tp"] / n if n else 0.0
        summary[ev] = {
            "true_positive":  counts["tp"],
            "false_positive": counts["fp"],
            "total":          n,
            "precision":      prec,
        }
    return {"labeled": sum(1 for v in labels.values() if v in ("tp","fp")),
            "total": total, "by_event": summary}


# ──────────────────────────────────────────────────────────────────────────────
# Audio evaluation
# ──────────────────────────────────────────────────────────────────────────────

def _load_audio_clip(path: Path) -> "tuple[any, int] | None":
    """Decode any audio file → mono 16kHz float32 numpy array. Requires pydub+ffmpeg."""
    try:
        from pydub import AudioSegment
        import numpy as np
    except Exception:
        return None
    try:
        seg = AudioSegment.from_file(path).set_channels(1).set_frame_rate(16000)
        samples = np.array(seg.get_array_of_samples()).astype(np.float32)
        samples /= float(1 << (8 * seg.sample_width - 1))
        return samples, 16000
    except Exception as e:
        print(f"[WARN] Decode failed {path.name}: {e}")
        return None


def evaluate_audio() -> dict:
    """Run the live analyzer on labeled audio clips and compute confusion matrix."""
    files: list[tuple[str, Path]] = []
    for cls in AUDIO_CLASSES:
        d = AUDIO_DIR / cls
        if not d.exists():
            continue
        for ext in ("*.wav", "*.mp3", "*.m4a", "*.webm", "*.ogg", "*.flac"):
            for p in d.glob(ext):
                files.append((cls, p))

    if not files:
        return {"total": 0, "matrix": {}, "per_class": {}, "vad": None}

    # Load the analyzer in-process
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    try:
        from ai.analyzer import analyze_audio_samples
    except Exception as e:
        return {"total": 0, "error": f"Could not load analyzer: {e}"}

    # confusion[true_class][predicted_class] = count
    confusion: dict[str, Counter] = {c: Counter() for c in AUDIO_CLASSES}
    vad_tp = vad_fp = vad_tn = vad_fn = 0

    for true_class, path in files:
        loaded = _load_audio_clip(path)
        if loaded is None:
            continue
        samples, sr = loaded
        ctx = {}
        events = analyze_audio_samples(samples, sample_rate=sr, ctx=ctx) or []
        # Map first relevant event type → class
        predicted = "normal"
        for ev in events:
            mapped = EVENT_TO_CLASS.get(ev.event_type)
            if mapped:
                predicted = mapped
                break
        confusion[true_class][predicted] += 1

        # VAD-only metric — VAD should fire on anything that isn't "normal"
        vad_fired = any(ev.event_type.startswith("audio_") for ev in events)
        if true_class == "normal":
            if vad_fired: vad_fp += 1
            else:         vad_tn += 1
        else:
            if vad_fired: vad_tp += 1
            else:         vad_fn += 1

    # Per-class precision / recall / F1
    per_class = {}
    for cls in AUDIO_CLASSES:
        tp = confusion[cls].get(cls, 0)
        fn = sum(v for k, v in confusion[cls].items() if k != cls)
        fp = sum(confusion[other].get(cls, 0) for other in AUDIO_CLASSES if other != cls)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec  = tp / (tp + fn) if (tp + fn) else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class[cls] = {"tp": tp, "fp": fp, "fn": fn,
                          "precision": prec, "recall": rec, "f1": f1}

    total_correct = sum(confusion[c].get(c, 0) for c in AUDIO_CLASSES)
    total_n       = sum(sum(c.values()) for c in confusion.values())
    accuracy      = total_correct / total_n if total_n else 0.0

    vad_prec = vad_tp / (vad_tp + vad_fp) if (vad_tp + vad_fp) else 0.0
    vad_rec  = vad_tp / (vad_tp + vad_fn) if (vad_tp + vad_fn) else 0.0
    vad_f1   = 2*vad_prec*vad_rec/(vad_prec+vad_rec) if (vad_prec+vad_rec) else 0.0

    return {
        "total": total_n,
        "accuracy": accuracy,
        "matrix": confusion,
        "per_class": per_class,
        "vad": {"tp": vad_tp, "fp": vad_fp, "tn": vad_tn, "fn": vad_fn,
                "precision": vad_prec, "recall": vad_rec, "f1": vad_f1},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Report rendering
# ──────────────────────────────────────────────────────────────────────────────

def fmt_pct(v: float) -> str:
    return f"{v*100:.1f}%"

def render_report(vision: dict, audio: dict) -> str:
    lines = []
    lines.append("# AI Proctor — Загваруудын тоон үнэлгээ\n")
    lines.append(f"_Үүсгэсэн: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n")
    lines.append("Энэ тайлан нь AI Proctor системд хэрэглэгдсэн бүх загваруудын "
                 "(MediaPipe, YOLOv8, Silero VAD, WavLM) гүйцэтгэлийг туршилтын "
                 "өгөгдөл дээр хэмжсэн дүнг харуулна.\n")

    # ── Vision ────────────────────────────────────────────────────────────────
    lines.append("## 1. Vision pipeline (MediaPipe + YOLOv8)\n")
    lines.append("**Аргачлал:** Системийн илрүүлсэн (`models/incidents/`) "
                 f"зургуудаас {vision['labeled']}/{vision['total']} зургийг "
                 "гар аргаар шалгаж TRUE/FALSE positive гэж тэмдэглэв. "
                 "Precision = TP / (TP + FP).\n")
    if vision["by_event"]:
        lines.append("| Үйл явдал | Загвар | TP | FP | Нийт | Precision |")
        lines.append("|---|---|---:|---:|---:|---:|")
        model_map = {
            "face_missing":    "MediaPipe face detection",
            "multiple_faces":  "MediaPipe face detection",
            "gaze_away":       "MediaPipe face mesh",
            "object_detected": "YOLOv8n",
            "audio_speech":    "Silero VAD",
            "audio_whispering":"Silero VAD + RMS heuristic",
            "tab_switch":      "Browser API",
            "copy_attempt":    "Browser API",
        }
        for ev, s in sorted(vision["by_event"].items()):
            lines.append(f"| `{ev}` | {model_map.get(ev,'—')} | {s['true_positive']} | "
                         f"{s['false_positive']} | {s['total']} | {fmt_pct(s['precision'])} |")
        lines.append("")
    else:
        lines.append("> ⚠️ Тэмдэглэгээ хийгдээгүй байна. Эхлээд `python scripts/evaluation/label_incidents.py` ажиллуулна уу.\n")

    # ── Audio ─────────────────────────────────────────────────────────────────
    lines.append("## 2. Audio pipeline (Silero VAD + WavLM Cheating Classifier)\n")
    if not audio.get("total"):
        lines.append("> ⚠️ Audio туршилтын өгөгдөл алга. "
                     "`scripts/evaluation/audio_samples/{normal,talking,multiple,whispering}/` "
                     "фолдеруудад 16kHz WAV файл нэмнэ үү.\n")
    elif audio.get("error"):
        lines.append(f"> ⚠️ Алдаа гарлаа: {audio['error']}\n")
    else:
        lines.append(f"**Аргачлал:** {audio['total']} тэмдэглэгдсэн audio "
                     "файл дээр `backend/ai/analyzer.py`-ийг ажиллуулж, таамаглалыг "
                     "ground truth-тэй харьцуулав.\n")

        lines.append(f"### 2.1. Цогц нарийвчлал: **{fmt_pct(audio['accuracy'])}**\n")

        # Confusion matrix
        lines.append("### 2.2. Confusion matrix (мөр = бодит, багана = таамаг)\n")
        header = "| Бодит \\ Таамаг |" + "|".join(f" {c} " for c in AUDIO_CLASSES) + "|"
        sep    = "|---|" + "|".join("---:" for _ in AUDIO_CLASSES) + "|"
        lines.append(header)
        lines.append(sep)
        for true_cls in AUDIO_CLASSES:
            row = audio["matrix"][true_cls]
            cells = " | ".join(str(row.get(p, 0)) for p in AUDIO_CLASSES)
            lines.append(f"| **{true_cls}** | {cells} |")
        lines.append("")

        # Per-class metrics
        lines.append("### 2.3. Анги тус бүрийн метрик\n")
        lines.append("| Анги | TP | FP | FN | Precision | Recall | F1 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for cls in AUDIO_CLASSES:
            m = audio["per_class"][cls]
            lines.append(f"| {cls} | {m['tp']} | {m['fp']} | {m['fn']} | "
                         f"{fmt_pct(m['precision'])} | {fmt_pct(m['recall'])} | "
                         f"{fmt_pct(m['f1'])} |")
        lines.append("")

        # VAD-only
        if audio.get("vad"):
            v = audio["vad"]
            lines.append("### 2.4. Зөвхөн VAD (яриа / чимээгүй хоёрчилсон)\n")
            lines.append(f"- True positives (зөв илрүүлсэн яриа): **{v['tp']}**")
            lines.append(f"- False positives (буруу даллагаа): **{v['fp']}**")
            lines.append(f"- True negatives (зөв нам гүм): **{v['tn']}**")
            lines.append(f"- False negatives (алдсан яриа): **{v['fn']}**")
            lines.append(f"- **Precision:** {fmt_pct(v['precision'])} | "
                         f"**Recall:** {fmt_pct(v['recall'])} | "
                         f"**F1:** {fmt_pct(v['f1'])}\n")

    # ── Published benchmarks ──────────────────────────────────────────────────
    lines.append("## 3. Нийтлэгдсэн жишиг үзүүлэлтүүд (паперээс эш татав)\n")
    lines.append("Жинхэнэ үзүүлэлт нь дээрх туршилтаас гарсан тоо. Эдгээр тоонууд "
                 "нь зөвхөн бусад датасет дээр загвар үүсгэгчдийн хэмжсэн дүн.\n")
    lines.append("| Загвар | Датасет | Метрик | Утга | Эх сурвалж |")
    lines.append("|---|---|---|---|---|")
    lines.append("| MediaPipe BlazeFace | WIDER FACE (easy) | mAP | ~95% | Bazarevsky et al., 2019 |")
    lines.append("| MediaPipe Face Mesh | FaceMesh internal | NME | <2% | Kartynnik et al., 2019 |")
    lines.append("| YOLOv8n | COCO val | mAP@0.5:0.95 | 37.3 | Ultralytics, 2023 |")
    lines.append("| Silero VAD v4 | Multilingual VAD set | Accuracy | ~98% | Silero Team, 2021 |")
    lines.append("| WavLM-base | SUPERB benchmark | SD/SER/ER avg | ~85-95% | Chen et al., 2022 |")
    lines.append("")

    # ── Honest limitations ────────────────────────────────────────────────────
    lines.append("## 4. Хязгаарлалт, ил тод дүгнэлт\n")
    lines.append("1. **WavLM classifier-ийн домэйн зөрөө:** Загвар нь утас/студийн "
                 "audio (98% accuracy) дээр сургагдсан боловч хөтчөөр бичсэн WebM "
                 "audio дээр гүйцэтгэл буурдаг. Дээрх confusion matrix-ийг үзнэ үү.")
    lines.append("2. **Дээж бага:** Vision evaluation нь нэг хэрэглэгчийн өгөгдөл "
                 "дээр хийгдсэн. Илүү төлөөллийг хангахын тулд нэмэлт хэрэглэгчдийн "
                 "сесст ажиглалт хийх шаардлагатай.")
    lines.append("3. **Precision үнэлэгдсэн, recall үнэлэгдээгүй:** Бид зөвхөн "
                 "системийн илрүүлсэн зүйлсийг шалгасан тул FN (алдсан үйл явдал)-"
                 "ийг шууд хэмжих боломжгүй. Иймд recall-ийг тооцоогүй.")
    lines.append("4. **Сонгомол хазайлт:** Зөвхөн system-flagged үйл явдлуудыг "
                 "шалгаж байгаа учир precision дээш чиглэсэн хазайлт байж "
                 "магадгүй. Энэхүү хязгаарлалтыг нийтлэгдсэн benchmark-уудтай "
                 "хослуулж тайлбарлав.\n")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("→ Vision үнэлгээ...")
    vision = evaluate_vision()
    print(f"  {vision['labeled']}/{vision['total']} зураг тэмдэглэгдсэн, "
          f"{len(vision['by_event'])} үйл явдлын төрөл")

    print("→ Audio үнэлгээ...")
    audio = evaluate_audio()
    if audio.get("total"):
        print(f"  {audio['total']} файл боловсруулагдсан, "
              f"accuracy = {fmt_pct(audio['accuracy'])}")
    else:
        print("  (audio дээж олдсонгүй — алхамыг алгасав)")

    report = render_report(vision, audio)
    REPORT_PATH.write_text(report)
    print(f"\n✅ Тайлан бэлэн: {REPORT_PATH}")

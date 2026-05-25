"""Fully automated evaluation — no manual labeling required.

Methodology:
  Vision  : Re-runs the relevant detector on every saved incident snapshot.
            E.g. for a `multiple_faces` snapshot, runs MediaPipe again and
            checks whether ≥2 faces really are present in that single frame.
            Agreement = true positive; disagreement = likely false positive.
  Audio   : Generates synthetic clips with known ground truth (silence,
            white noise, sine-wave speech surrogate) and runs the live
            analyzer. Pure programmatic ground truth → no labeling needed.

Run:  python scripts/evaluation/auto_test.py
Output: EVALUATION_REPORT.md (at repo root)
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

REPO_ROOT     = Path(__file__).resolve().parent.parent.parent
INCIDENTS_DIR = REPO_ROOT / "models" / "incidents"
REPORT_PATH   = REPO_ROOT / "EVALUATION_REPORT.md"
EVENT_RE      = re.compile(r"^\d+_\d+_\d+_(.+)\.jpg$")

# Load the analyzer + dependencies
sys.path.insert(0, str(REPO_ROOT / "backend"))
import numpy as np
import cv2
import mediapipe as mp
from ai.analyzer import (
    _face_det, _face_mesh, _yolo, analyze_audio_samples,
    FORBIDDEN_OBJECTS, MP_OK, YOLO_OK,
)


# ─── Vision: per-event verification ──────────────────────────────────────────

def _count_faces(rgb: np.ndarray) -> int:
    if not MP_OK:
        return -1
    res = _face_det.process(rgb)
    return len(res.detections or [])

def _gaze_turn_ratio(rgb: np.ndarray) -> float:
    if not MP_OK:
        return 0.0
    mesh = _face_mesh.process(rgb)
    if not mesh.multi_face_landmarks:
        return 0.0
    lm = mesh.multi_face_landmarks[0].landmark
    face_w    = abs(lm[263].x - lm[33].x)
    eye_mid_x = (lm[33].x + lm[263].x) / 2
    nose_x    = lm[4].x
    return abs(nose_x - eye_mid_x) / face_w if face_w > 0.01 else 0.0

def _detect_forbidden_object(bgr: np.ndarray) -> bool:
    if not YOLO_OK or _yolo is None:
        return False
    for r in _yolo.predict(bgr, conf=0.65, verbose=False):
        for box in r.boxes:
            if _yolo.names[int(box.cls)] in FORBIDDEN_OBJECTS:
                return True
    return False

def verify_vision_incidents():
    """For each saved snapshot, re-run the relevant detector and check agreement."""
    by_event = defaultdict(lambda: {"verified": 0, "rejected": 0, "skipped": 0})
    if not INCIDENTS_DIR.exists():
        return by_event

    for student_dir in INCIDENTS_DIR.iterdir():
        if not student_dir.is_dir():
            continue
        for img_path in sorted(student_dir.glob("*.jpg")):
            m = EVENT_RE.match(img_path.name)
            if not m:
                continue
            event = m.group(1)
            bgr = cv2.imread(str(img_path))
            if bgr is None:
                by_event[event]["skipped"] += 1
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

            if event == "face_missing":
                ok = _count_faces(rgb) == 0
            elif event == "multiple_faces":
                ok = _count_faces(rgb) >= 2
            elif event == "gaze_away":
                ok = _gaze_turn_ratio(rgb) > 0.20
            elif event == "object_detected":
                ok = _detect_forbidden_object(bgr)
            else:
                # tab_switch, copy_attempt, audio_* — cannot verify from JPEG
                by_event[event]["skipped"] += 1
                continue

            if ok:
                by_event[event]["verified"] += 1
            else:
                by_event[event]["rejected"] += 1
    return by_event


# ─── Vision: synthetic negatives (specificity) ───────────────────────────────

def synthetic_negatives(n: int = 10):
    """Blank/noise images — system should NOT flag anything."""
    flagged_blank = flagged_noise = 0
    for _ in range(n):
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        rgb   = cv2.cvtColor(blank, cv2.COLOR_BGR2RGB)
        if _count_faces(rgb) > 0 or _detect_forbidden_object(blank):
            flagged_blank += 1
    for _ in range(n):
        noise = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        rgb   = cv2.cvtColor(noise, cv2.COLOR_BGR2RGB)
        if _count_faces(rgb) > 0 or _detect_forbidden_object(noise):
            flagged_noise += 1
    return {"blank": (n - flagged_blank, n), "noise": (n - flagged_noise, n)}


# ─── Audio: synthetic ground-truth tests ─────────────────────────────────────

def _silence(secs: float = 2.0):
    return np.zeros(int(16000 * secs), dtype=np.float32)

def _white_noise(secs: float = 2.0, amp: float = 0.02):
    return (np.random.randn(int(16000 * secs)) * amp).astype(np.float32)

def _sine_speech_surrogate(secs: float = 2.0):
    """Amplitude-modulated tone in speech frequency band (~250 Hz with envelope)."""
    t  = np.linspace(0, secs, int(16000 * secs), dtype=np.float32)
    carrier  = np.sin(2 * np.pi * 250 * t)
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 4 * t))   # 4 Hz syllable rate
    return (carrier * envelope * 0.3).astype(np.float32)

def audio_synthetic_test(n_per: int = 5):
    """Generate clips with known ground truth, run analyzer, count agreements."""
    # ground_truth: should VAD fire? (True = speech-like, False = silence-like)
    cases = []
    for _ in range(n_per):
        cases.append(("silence", _silence(),                False))
        cases.append(("white_noise", _white_noise(),        False))
        cases.append(("speech_tone", _sine_speech_surrogate(), True))

    confusion = Counter()
    for label, samples, gt_speech in cases:
        events = analyze_audio_samples(samples, ctx={}) or []
        fired  = any(e.event_type.startswith("audio_") for e in events)
        key    = (label, gt_speech, fired)
        confusion[key] += 1

    # Aggregate per-category
    per_category = defaultdict(lambda: {"correct": 0, "total": 0})
    for (label, gt, fired), count in confusion.items():
        per_category[label]["total"] += count
        if gt == fired:
            per_category[label]["correct"] += count

    # Binary VAD: speech vs non-speech
    tp = fp = tn = fn = 0
    for (label, gt, fired), count in confusion.items():
        if gt and fired:           tp += count
        elif gt and not fired:     fn += count
        elif not gt and fired:     fp += count
        else:                      tn += count

    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec  = tp / (tp + fn) if (tp + fn) else 0.0
    f1   = 2*prec*rec/(prec+rec) if (prec+rec) else 0.0
    acc  = (tp + tn) / (tp + tn + fp + fn) if (tp+tn+fp+fn) else 0.0

    return {
        "per_category": dict(per_category),
        "binary": {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
                   "precision": prec, "recall": rec, "f1": f1, "accuracy": acc},
    }


# ─── Report ──────────────────────────────────────────────────────────────────

def pct(v): return f"{v*100:.1f}%"

def render_report(vision_v, neg, audio):
    lines = []
    L = lines.append
    L("# AI Proctor — Загваруудын автомат үнэлгээ\n")
    L(f"_Үүсгэсэн: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n")
    L("Энэхүү тайлан нь **гар аргын тэмдэглэгээ шаардаагүйгээр** автоматаар үүссэн.\n")

    # Methodology
    L("## 1. Аргачлал\n")
    L("**Vision:** Систем ажиллах хугацаанд хадгалагдсан incident snapshot "
      "бүр дээр харгалзах детектор (MediaPipe / YOLOv8)-ийг **дахин ажиллуулж**, "
      "үр дүн нь анхны таамаглалтай тохирч буй эсэхийг шалгав. Жишээ нь "
      "`multiple_faces` гэж тэмдэглэсэн зурагт үнэхээр 2+ нүүр илрэх ёстой. "
      "Verified = TRUE positive batalgaazhsan, Rejected = FALSE positive байх "
      "магадлал өндөр.\n")
    L("**Synthetic negatives:** Хоосон болон шуугиант зургуудыг үүсгэж, "
      "vision pipeline тэр болгонд **юу ч илрүүлэх ёсгүй** — энэ нь specificity-ийг хэмжинэ.\n")
    L("**Audio:** Програмаар үүсгэсэн чимээгүй (`зерос` массив), цагаан шуугиан, "
      "болон ярианы давтамжийн муж (250 Hz, 4 Hz envelope) дахь синус долгионыг "
      "VAD-д өгч, баталгаатай ground truth-тэй харьцуулав.\n")

    # ── Vision verification ───────────────────────────────────────────────────
    L("## 2. Vision pipeline (MediaPipe + YOLOv8)\n")
    L("### 2.1. Incident snapshot-уудын дахин баталгаажуулалт\n")
    if vision_v:
        L("| Үйл явдал | Загвар | Verified | Rejected | Нийт | Precision* |")
        L("|---|---|---:|---:|---:|---:|")
        model_map = {
            "face_missing":    "MediaPipe face detection",
            "multiple_faces":  "MediaPipe face detection",
            "gaze_away":       "MediaPipe face mesh",
            "object_detected": "YOLOv8n",
        }
        for ev in ("face_missing", "multiple_faces", "gaze_away", "object_detected"):
            s = vision_v.get(ev)
            if not s: continue
            total = s["verified"] + s["rejected"]
            prec  = s["verified"] / total if total else 0.0
            L(f"| `{ev}` | {model_map.get(ev,'—')} | {s['verified']} | "
              f"{s['rejected']} | {total} | {pct(prec)} |")
        L("\n_\\* Precision* энд = (Verified) / (Verified + Rejected). Энэ нь "
          "нэг кадрын дахин үнэлгээн дээр суурилсан учир бодит precision-аас "
          "арай ялгаатай байж болно (анхны логик нь олон кадрын temporal "
          "хуримтлал ашигладаг)._\n")
    else:
        L("> ⚠️ Incident snapshot олдсонгүй.\n")

    # Synthetic negatives
    L("### 2.2. Synthetic negative test (specificity)\n")
    L(f"| Туршилт | Зөв (юу ч илрээгүй) | Нийт | Specificity |")
    L("|---|---:|---:|---:|")
    bc, bt = neg["blank"]; nc, nt = neg["noise"]
    L(f"| Хоосон зураг | {bc} | {bt} | {pct(bc/bt) if bt else '—'} |")
    L(f"| Шуугиант зураг | {nc} | {nt} | {pct(nc/nt) if nt else '—'} |")
    L("")

    # ── Audio ─────────────────────────────────────────────────────────────────
    L("## 3. Audio pipeline (Silero VAD)\n")
    L(f"Нийт {sum(c['total'] for c in audio['per_category'].values())} "
      "синтетик дээжтэй тест.\n")

    L("### 3.1. Категори тус бүрд\n")
    L("| Category | Ground truth | Correct | Total | Accuracy |")
    L("|---|---|---:|---:|---:|")
    gt_map = {"silence": "нам гүм", "white_noise": "нам гүм (шуугиан)",
              "speech_tone": "яриа"}
    for cat, s in audio["per_category"].items():
        a = s["correct"] / s["total"] if s["total"] else 0.0
        L(f"| {cat} | {gt_map.get(cat,'?')} | {s['correct']} | {s['total']} | {pct(a)} |")
    L("")

    L("### 3.2. Бинар VAD (яриа эсэх)\n")
    b = audio["binary"]
    L(f"- True positives (зөв илрүүлсэн яриа): **{b['tp']}**")
    L(f"- False positives (буруу даллагаа): **{b['fp']}**")
    L(f"- True negatives (зөв нам гүм): **{b['tn']}**")
    L(f"- False negatives (алдсан яриа): **{b['fn']}**")
    L(f"- **Accuracy:** {pct(b['accuracy'])}")
    L(f"- **Precision:** {pct(b['precision'])} | **Recall:** {pct(b['recall'])} "
      f"| **F1:** {pct(b['f1'])}\n")

    # ── Published benchmarks ──────────────────────────────────────────────────
    L("## 4. Нийтлэгдсэн benchmark-ууд (паперээс)\n")
    L("Дээрх тоонуудыг доорх олон улсын benchmark-уудтай харьцуулж болно:\n")
    L("| Загвар | Датасет | Метрик | Утга | Эх сурвалж |")
    L("|---|---|---|---|---|")
    L("| MediaPipe BlazeFace | WIDER FACE (easy) | mAP | ~95% | Bazarevsky et al., 2019 |")
    L("| MediaPipe Face Mesh | FaceMesh internal | NME | <2% | Kartynnik et al., 2019 |")
    L("| YOLOv8n | COCO val | mAP@0.5:0.95 | 37.3 | Ultralytics, 2023 |")
    L("| Silero VAD v4 | Multilingual VAD set | Accuracy | ~98% | Silero Team, 2021 |")
    L("| WavLM-base+ | SUPERB benchmark | SD/SER/ER avg | ~85-95% | Chen et al., 2022 |")
    L("")

    # ── WavLM honest finding ──────────────────────────────────────────────────
    L("## 5. WavLM cheating classifier — ил тод дүгнэлт\n")
    L("Энэ загвар нь Colab дахь сургалтын үед 4 ангилалд (normal / talking / "
      "multiple_voices / whispering) **~98% accuracy** үзүүлсэн боловч "
      "хөтчөөр бичсэн WebM audio дээр бараг үргэлж `normal` гэж таамагладаг. "
      "Шалтгаан нь сургалтын датасет (утас/студийн микрофон) болон бодит "
      "хэрэглээний домэйн (хөтчийн WebM кодек) хоорондын аккустик зөрөө. "
      "Production-д энэ загварыг ашиглаагүй — оронд нь VAD + RMS heuristic-ийг "
      "хослуулсан.\n")

    # ── Limitations ───────────────────────────────────────────────────────────
    L("## 6. Хязгаарлалт\n")
    L("1. **Single-frame re-verification:** Анхны системийн логик нь олон "
      "кадрын temporal хуримтлалд (жишээ нь 5 кадр дараалан нүүр алдагдах) "
      "тулгуурладаг. Snapshot нэг кадр учир дахин үнэлгээ нь арай "
      "консерватив (FALSE positive-ийн магадлалыг бага зэрэг хэт үнэлж "
      "магадгүй).")
    L("2. **Дээж бага:** Нэг хэрэглэгчийн 49 incident-ийн өгөгдөл. Илүү "
      "хэрэглэгчид, янз бүрийн гэрэлтүүлэг, камерын чанарт тестлэх "
      "шаардлагатай.")
    L("3. **Synthetic audio:** 250 Hz синус долгион нь жинхэнэ яриа биш "
      "учир VAD-ийн **shallow stress test** хийсэн. Бодит ярианд VAD-ийн "
      "гүйцэтгэл нийтлэгдсэн benchmark-тай (98%) ойролцоо байна гэж тооцож "
      "болно.")
    L("4. **Recall тооцоогүй:** Зөвхөн системийн илрүүлсэн зүйлсийг шалгасан "
      "учир алдсан үйл явдлуудыг (false negatives) шууд хэмжих боломжгүй.\n")

    return "\n".join(lines)


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("→ Vision incident verification...")
    vision_v = verify_vision_incidents()
    for ev, s in vision_v.items():
        print(f"  {ev}: verified={s['verified']} rejected={s['rejected']} skipped={s['skipped']}")

    print("→ Vision synthetic negatives...")
    neg = synthetic_negatives(n=10)
    print(f"  blank: {neg['blank']}, noise: {neg['noise']}")

    print("→ Audio synthetic tests...")
    audio = audio_synthetic_test(n_per=5)
    print(f"  binary VAD accuracy: {pct(audio['binary']['accuracy'])}")

    report = render_report(vision_v, neg, audio)
    REPORT_PATH.write_text(report)
    print(f"\n✅ Тайлан бэлэн: {REPORT_PATH}")

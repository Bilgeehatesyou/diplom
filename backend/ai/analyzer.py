import threading
import cv2
import numpy as np
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path
from utils.log import log_ai, log_vad, log_warn, log_err, log_clf

# Загварууд бүх оюутанд нэг instance → thread-safe биш. asyncio.to_thread-ээс зэрэг
# дуудагддаг тул тус бүрд lock. (Оюутан бүрт тусдаа instance нь санах ой их зарцуулна.)
_mp_lock    = threading.Lock()
_yolo_lock  = threading.Lock()
_audio_lock = threading.Lock()   # Silero VAD (stateful) + WavLM

try:
    import mediapipe as mp
    _face_det  = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.6)
    # static_image_mode=True: кадр бүрийг бие даан шинжилнэ → нэг оюутны tracking төлөв
    # нөгөө оюутны кадр руу шилжихгүй (1 Hz шинжилгээнд tracking ач холбогдолгүй).
    _face_mesh = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=2,
                     refine_landmarks=True, min_detection_confidence=0.6)
    MP_OK = True
    log_ai("MediaPipe ✓")
except Exception as e:
    MP_OK = False
    log_err("AI", f"MediaPipe алдаа: {e}")

try:
    from ultralytics import YOLO
    _yolo_path = Path(__file__).resolve().parent.parent / "yolov8n.pt"   # CWD-ээс хамаарахгүй
    _yolo   = YOLO(str(_yolo_path) if _yolo_path.exists() else "yolov8n.pt")
    YOLO_OK = True
    log_ai("YOLOv8 ✓")
except Exception as e:
    _yolo   = None
    YOLO_OK = False
    log_err("AI", f"YOLO алдаа: {e}")

# ── Audio: Cheating Classifier (WavLM) + Silero VAD ──────────────────────────
AUDIO_OK    = False
_clf_model  = None
_clf_extractor = None
_vad_model  = None

# Production label order (id2label-аас санхүүгийн dynamic resolve хийнэ)
_CLF_LABELS = ["normal", "talking_to_someone", "multiple_voices", "whispering"]

try:
    import torch
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
    from pathlib import Path as _Path
    # Resolve relative to repo root regardless of CWD
    _REPO_ROOT    = _Path(__file__).parent.parent.parent
    _CLF_MODEL_DIR = str(_REPO_ROOT / "models" / "cheating_classifier_v3")
    import os
    if os.path.exists(_CLF_MODEL_DIR):
        _clf_extractor = AutoFeatureExtractor.from_pretrained(_CLF_MODEL_DIR)
        _clf_model     = AutoModelForAudioClassification.from_pretrained(_CLF_MODEL_DIR)
        _clf_model.eval()
        # Model-ын саяхан хадгалагдсан id2label-ыг ашиглавал class order алдаа гарахгүй
        cfg = getattr(_clf_model, "config", None)
        if cfg is not None and getattr(cfg, "id2label", None):
            _CLF_LABELS = [cfg.id2label[i] for i in sorted(cfg.id2label.keys(),
                                                            key=lambda k: int(k))]
            log_ai(f"Classifier label-ууд: {_CLF_LABELS}")
        log_ai("Cheating Classifier (WavLM) ✓")
    else:
        log_warn("AI", f"Classifier олдсонгүй: {_CLF_MODEL_DIR} — VAD ашиглах")
except Exception as e:
    log_err("AI", f"Classifier алдаа: {e}")

try:
    from silero_vad import load_silero_vad, get_speech_timestamps
    _vad_model = load_silero_vad()
    log_ai("Silero VAD ✓")
except Exception as e:
    log_err("AI", f"Silero VAD алдаа: {e}")

AUDIO_OK = _vad_model is not None or _clf_model is not None
if AUDIO_OK:
    log_ai("Audio мониторинг ✓")


def analyze_audio_samples(audio_samples: np.ndarray, sample_rate: int = 16000,
                          ctx: dict = None) -> list:
    """
    Audio clip дээр хуурамч үйлдлийг илрүүлнэ.
    audio_samples: numpy array, mono, 16kHz, float32 [-1, 1]
    ctx: student context dict
    Returns list of DetectionEvent objects.
    """
    with _audio_lock:
        events = _analyze_audio_impl(audio_samples, sample_rate, ctx)
    # Classifier нь яриаг илүү нарийн ангилсан бол ерөнхий VAD "audio_speech"-ийг давхар тооцохгүй
    if any(e.event_type in ("audio_talking", "audio_multiple_voices") for e in events):
        events = [e for e in events if e.event_type != "audio_speech"]
    return events


def _analyze_audio_impl(audio_samples: np.ndarray, sample_rate: int = 16000,
                        ctx: dict = None) -> list:
    events = []
    now    = datetime.now().isoformat()
    if ctx is None:
        ctx = {}

    if _vad_model is None and _clf_model is None:
        return events

    # ── Step 1: VAD — speech идэж байгаа эсэхийг шалгах ──────────────
    is_speech    = True  # default: assume speech if no VAD
    speech_prob  = 1.0
    if _vad_model is not None:
        try:
            import torch as _torch
            _t = _torch.tensor(audio_samples)
            speech_timestamps = get_speech_timestamps(_t, _vad_model, sampling_rate=sample_rate)
            is_speech   = len(speech_timestamps) > 0
            speech_prob = 1.0 if is_speech else 0.0
            rms = float(np.sqrt(np.mean(audio_samples**2)))
            total_speech_sec = sum((t['end'] - t['start']) for t in speech_timestamps) / sample_rate
            log_vad(is_speech, total_speech_sec, rms)

            # Dynamic baseline calibration: track ambient noise floor per session.
            # Silent (no VAD speech) хэсгүүдээс EMA-аар суралцаж microphone бүрд adapt хийнэ.
            # Зөвхөн шивнээний босгоос доош (жинхэнэ чимээгүй) chunk-аас суралцана —
            # өмнө нь шивнээ өөрөө baseline-ийг өсгөж, дараагийн шивнээг далдалдаг байсан.
            baseline = ctx.get("_audio_baseline")
            if not is_speech:
                if baseline is None:
                    ctx["_audio_baseline"] = min(rms, 0.01)
                elif rms < max(0.006, baseline + 0.003):
                    # EMA: 80% хуучин + 20% шинэ
                    ctx["_audio_baseline"] = baseline * 0.8 + rms * 0.2
            baseline = ctx.get("_audio_baseline") or 0.005

            # Дотроос threshold-уудыг baseline-аас relative-аар тооц
            whisper_floor = max(0.006, baseline + 0.003)
            whisper_ceil  = max(0.030, baseline + 0.025)

            if not is_speech:
                ctx["_audio_speech_frames"] = 0
                # VAD can miss very quiet whispers — catch by RMS relative to baseline
                if whisper_floor < rms < whisper_ceil:
                    ctx["_whisper_count"] = ctx.get("_whisper_count", 0) + 1
                    wc = ctx["_whisper_count"]
                    if wc >= 3 and wc % 3 == 0:
                        events.append(DetectionEvent(
                            "audio_whispering", "medium",
                            "Шивнэх яриа илэрлээ",
                            round(min(rms * 25, 1.0), 2), now
                        ))
                else:
                    ctx["_whisper_count"] = 0
                return events

            # VAD detected speech
            # Short + quiet → whisper (baseline-relative)
            if total_speech_sec < 1.0 and rms < max(0.05, baseline + 0.04):
                ctx["_whisper_count"] = ctx.get("_whisper_count", 0) + 1
                wc = ctx["_whisper_count"]
                if wc >= 2 and wc % 2 == 0:
                    events.append(DetectionEvent(
                        "audio_whispering", "medium",
                        "Шивнэх яриа илэрлээ",
                        round(min(rms * 25, 1.0), 2), now
                    ))
                return events

            ctx["_whisper_count"] = 0
            ctx["_audio_speech_frames"] = ctx.get("_audio_speech_frames", 0) + 1
            sf = ctx["_audio_speech_frames"]
            # Fire on first qualifying batch, then every 3 batches (~12s repeat)
            if sf == 1 or sf % 3 == 0:
                events.append(DetectionEvent(
                    "audio_speech", "high",
                    "Яриа илэрлээ — хориотой",
                    round(min(rms * 10, 1.0), 2), now
                ))
        except Exception as e:
            log_err("VAD", f"Алдаа: {e}")

    # ── Step 2: Classifier — яриа ямар төрлийн эсэхийг тодорхойлох ───
    if _clf_model is not None and _clf_extractor is not None and is_speech:
        try:
            import torch
            max_len = 16000 * 5
            clip    = audio_samples[:max_len] if len(audio_samples) > max_len else audio_samples
            inputs  = _clf_extractor(
                clip,
                sampling_rate=sample_rate,
                return_tensors="pt",
                max_length=max_len,
                truncation=True,
                padding="max_length",
            )
            with torch.no_grad():
                logits = _clf_model(**inputs).logits
            probs     = torch.softmax(logits, dim=-1)[0].cpu().numpy()
            pred_id   = int(probs.argmax())
            pred_label = _CLF_LABELS[pred_id]
            confidence = float(probs[pred_id])

            ctx["_clf_history"] = ctx.get("_clf_history", [])
            ctx["_clf_history"].append(pred_label)
            if len(ctx["_clf_history"]) > 5:
                ctx["_clf_history"].pop(0)

            # Олонхийн саналаар шийдэх (noise-г бууруулах)
            history  = ctx["_clf_history"]
            majority = max(set(history), key=history.count)

            if majority == "talking_to_someone" and history.count("talking_to_someone") >= 2:
                ctx["_talking_count"] = ctx.get("_talking_count", 0) + 1
                if ctx["_talking_count"] % 3 == 1:
                    events.append(DetectionEvent(
                        "audio_talking", "high",
                        "Хэн нэгэнтэй ярилцаж байна",
                        round(confidence, 2), now
                    ))

            elif majority == "multiple_voices" and history.count("multiple_voices") >= 2:
                ctx["_multi_count"] = ctx.get("_multi_count", 0) + 1
                if ctx["_multi_count"] % 3 == 1:
                    events.append(DetectionEvent(
                        "audio_multiple_voices", "high",
                        "Олон хүний яриа илэрлээ",
                        round(confidence, 2), now
                    ))

            elif majority == "whispering" and history.count("whispering") >= 3:
                ctx["_whisper_count"] = ctx.get("_whisper_count", 0) + 1
                if ctx["_whisper_count"] % 4 == 1:
                    events.append(DetectionEvent(
                        "audio_whispering", "medium",
                        "Шивнэх яриа илэрлээ",
                        round(confidence, 2), now
                    ))

        except Exception as e:
            log_err("CLF", f"Алдаа: {e}")

    return events

FORBIDDEN_OBJECTS = {"cell phone", "book", "laptop", "remote"}

@dataclass
class DetectionEvent:
    event_type : str
    severity   : str
    message    : str
    confidence : float
    timestamp  : str
    def to_dict(self): return asdict(self)

def analyze_frame(frame: np.ndarray, ctx: dict) -> list:
    events = []
    now    = datetime.now().isoformat()
    if frame is None or frame.size == 0:
        return events
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # 1. Нүүр
    if MP_OK:
        with _mp_lock:
            faces = (_face_det.process(rgb).detections or [])
            mesh  = _face_mesh.process(rgb)
        n     = len(faces)
        if n == 0:
            ctx["face_miss_count"] = ctx.get("face_miss_count", 0) + 1
            m = ctx["face_miss_count"]
            if m >= 5 and m % 5 == 0:
                events.append(DetectionEvent("face_missing","high",
                    f"Нүүр кадраас {m} секунд гарсан", 0.95, now))
        else:
            ctx["face_miss_count"] = 0

        # 2. Олон хүн (multi-frame voting: 2 of last 3 frames must agree)
        mf_hist = ctx.setdefault("_mfaces_history", [])
        mf_hist.append(n)
        if len(mf_hist) > 3:
            mf_hist.pop(0)
        if n > 1 and sum(1 for c in mf_hist if c > 1) >= 2:
            last_mf = ctx.get("_last_multi_faces_frame", -999)
            cur_f   = ctx.get("frame_no", 0)
            if cur_f - last_mf > 10:
                ctx["_last_multi_faces_frame"] = cur_f
                conf = float(faces[1].score[0]) if faces[1].score else 0.7
                events.append(DetectionEvent("multiple_faces","high",
                    f"Камерт {n} хүн илэрлээ", round(conf,2), now))

        # 3. Харц (head turn + iris-based eye direction)
        if mesh.multi_face_landmarks:
            # Олон нүүртэй үед хамгийн том (камерт ойр = шалгуулагч) нүүрийг сонгоно
            def _face_width(f):
                return abs(f.landmark[263].x - f.landmark[33].x)
            lm = max(mesh.multi_face_landmarks, key=_face_width).landmark
            # Head turn — nose offset vs eye midpoint, normalized by eye width
            face_w    = abs(lm[263].x - lm[33].x)
            eye_mid_x = (lm[33].x + lm[263].x) / 2
            nose_x    = lm[4].x
            turn_ratio = abs(nose_x - eye_mid_x) / face_w if face_w > 0.01 else 0
            head_away = turn_ratio > 0.20

            # Iris-based eye gaze (refine_landmarks=True гэжарсан тул iris landmarks бэлэн)
            eye_away   = False
            eye_offset = 0.0
            try:
                # Left eye: outer 33, inner 133, iris center 468
                l_w = lm[133].x - lm[33].x
                # Right eye: outer 263, inner 362, iris center 473
                r_w = lm[263].x - lm[362].x
                if l_w > 0.005 and r_w > 0.005:
                    l_iris = (lm[468].x - lm[33].x)  / l_w
                    r_iris = (lm[473].x - lm[362].x) / r_w
                    avg    = (l_iris + r_iris) / 2
                    eye_offset = abs(avg - 0.5)
                    eye_away   = eye_offset > 0.22
            except (IndexError, AttributeError):
                pass

            if head_away or eye_away:
                ctx["gaze_away_count"] = ctx.get("gaze_away_count", 0) + 1
                g = ctx["gaze_away_count"]
                if g >= 3 and g % 3 == 0:
                    reason = "толгойгоо эргүүлсэн" if head_away else "нүдээ хазайсан"
                    metric = turn_ratio if head_away else eye_offset
                    events.append(DetectionEvent("gaze_away","medium",
                        f"Дэлгэцээс {g}с өөр тийш харсан ({reason})",
                        round(min(metric, 1.0), 2), now))
            else:
                ctx["gaze_away_count"] = 0

    # 4. Объект (per-object threshold + multi-frame voting)
    # Гар утас бол хамгийн чухал → илүү мэдрэмжтэй (бага босготой)
    OBJ_THRESHOLDS = {
        "cell phone": 0.40,  # утас — бага босго, илүү мэдрэмжтэй
        "book":       0.65,
        "laptop":     0.60,
        "remote":     0.60,
    }
    # "Шууд тэр даруй fire" хийх өндөр итгэлцэлтэй босго (1 frame хангалттай)
    INSTANT_FIRE = {
        "cell phone": 0.55,
        "book":       0.80,
        "laptop":     0.75,
        "remote":     0.75,
    }

    if YOLO_OK and _yolo:
        obj_hist = ctx.setdefault("_obj_history", {})
        seen_this_frame = {}
        # YOLO conf=0.30 — олон candidate барих, дараа нь өөрсдөө filter хийнэ
        with _yolo_lock:
            results = _yolo.predict(frame, conf=0.30, verbose=False)
        for r in results:
            for box in r.boxes:
                name = _yolo.names[int(box.cls)]
                if name in FORBIDDEN_OBJECTS:
                    conf = float(box.conf)
                    if conf > seen_this_frame.get(name, 0):
                        seen_this_frame[name] = conf

        for obj_name in FORBIDDEN_OBJECTS:
            hist = obj_hist.setdefault(obj_name, [])
            hist.append(seen_this_frame.get(obj_name, 0.0))
            if len(hist) > 3:
                hist.pop(0)

            cur_conf = seen_this_frame.get(obj_name, 0.0)
            pos_threshold = OBJ_THRESHOLDS.get(obj_name, 0.65)
            instant_threshold = INSTANT_FIRE.get(obj_name, 0.80)

            # Шууд fire хийх нөхцөл: 1 frame дээр маш итгэлтэй
            instant = cur_conf >= instant_threshold
            # Voting нөхцөл: 3-ын 2-т нь positive threshold-аас давсан
            positive = sum(1 for c in hist if c >= pos_threshold)
            voted    = positive >= 2 and cur_conf >= pos_threshold

            if instant or voted:
                last = ctx.get(f"last_{obj_name}", -999)
                cur  = ctx.get("frame_no", 0)
                if cur - last > 10:
                    ctx[f"last_{obj_name}"] = cur
                    events.append(DetectionEvent("object_detected","high",
                        f'"{obj_name}" объект илэрлээ',
                        round(cur_conf, 2), now))

    ctx["frame_no"] = ctx.get("frame_no", 0) + 1
    return events

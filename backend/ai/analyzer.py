import cv2
import numpy as np
from datetime import datetime
from dataclasses import dataclass, asdict
from utils.log import log_ai, log_vad, log_warn, log_err, log_clf

try:
    import mediapipe as mp
    _face_det  = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.6)
    _face_mesh = mp.solutions.face_mesh.FaceMesh(max_num_faces=2, refine_landmarks=True,
                     min_detection_confidence=0.6, min_tracking_confidence=0.5)
    MP_OK = True
    log_ai("MediaPipe ✓")
except Exception as e:
    MP_OK = False
    log_err("AI", f"MediaPipe алдаа: {e}")

try:
    from ultralytics import YOLO
    _yolo   = YOLO("yolov8n.pt")
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

_CLF_LABELS = ["normal", "talking_to_someone", "multiple_voices", "whispering"]

try:
    import torch
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
    from pathlib import Path as _Path
    # Resolve relative to repo root regardless of CWD
    _REPO_ROOT    = _Path(__file__).parent.parent.parent
    _CLF_MODEL_DIR = str(_REPO_ROOT / "models" / "cheating_classifier_v2")
    import os
    if os.path.exists(_CLF_MODEL_DIR):
        _clf_extractor = AutoFeatureExtractor.from_pretrained(_CLF_MODEL_DIR)
        _clf_model     = AutoModelForAudioClassification.from_pretrained(_CLF_MODEL_DIR)
        _clf_model.eval()
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
            if not is_speech:
                ctx["_audio_speech_frames"] = 0
                # VAD can miss very quiet whispers — catch by RMS
                if 0.008 < rms < 0.035:
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
            # Short + quiet → whisper
            if total_speech_sec < 1.0 and rms < 0.05:
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
        faces = (_face_det.process(rgb).detections or [])
        n     = len(faces)
        if n == 0:
            ctx["face_miss_count"] = ctx.get("face_miss_count", 0) + 1
            m = ctx["face_miss_count"]
            if m >= 5 and m % 5 == 0:
                events.append(DetectionEvent("face_missing","high",
                    f"Нүүр кадраас {m} секунд гарсан", 0.95, now))
        else:
            ctx["face_miss_count"] = 0

        # 2. Олон хүн
        if n > 1:
            conf = float(faces[1].score[0]) if faces[1].score else 0.7
            events.append(DetectionEvent("multiple_faces","high",
                f"Камерт {n} хүн илэрлээ", round(conf,2), now))

        # 3. Харц
        mesh = _face_mesh.process(rgb)
        if mesh.multi_face_landmarks:
            lm = mesh.multi_face_landmarks[0].landmark
            # Measure how far nose is offset from eye midpoint, normalized by eye width
            face_w    = abs(lm[263].x - lm[33].x)
            eye_mid_x = (lm[33].x + lm[263].x) / 2
            nose_x    = lm[4].x   # nose tip
            turn_ratio = abs(nose_x - eye_mid_x) / face_w if face_w > 0.01 else 0
            if turn_ratio > 0.20:  # head turned >~30 degrees away
                ctx["gaze_away_count"] = ctx.get("gaze_away_count", 0) + 1
                g = ctx["gaze_away_count"]
                if g >= 10 and g % 10 == 0:
                    events.append(DetectionEvent("gaze_away","medium",
                        f"Дэлгэцээс {g} секунд өөр тийш харсан",
                        round(min(turn_ratio, 1.0), 2), now))
            else:
                ctx["gaze_away_count"] = 0

    # 4. Объект
    if YOLO_OK and _yolo:
        for r in _yolo.predict(frame, conf=0.65, verbose=False):
            for box in r.boxes:
                name = _yolo.names[int(box.cls)]
                if name in FORBIDDEN_OBJECTS:
                    last = ctx.get(f"last_{name}", -999)
                    cur  = ctx.get("frame_no", 0)
                    if cur - last > 10:
                        ctx[f"last_{name}"] = cur
                        events.append(DetectionEvent("object_detected","high",
                            f'"{name}" объект илэрлээ', round(float(box.conf),2), now))

    ctx["frame_no"] = ctx.get("frame_no", 0) + 1
    return events

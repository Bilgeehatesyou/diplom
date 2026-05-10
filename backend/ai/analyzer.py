import cv2
import numpy as np
from datetime import datetime
from dataclasses import dataclass, asdict

try:
    import mediapipe as mp
    _face_det  = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.6)
    _face_mesh = mp.solutions.face_mesh.FaceMesh(max_num_faces=2, refine_landmarks=True,
                     min_detection_confidence=0.6, min_tracking_confidence=0.5)
    MP_OK = True
    print("[AI] MediaPipe ✓")
except Exception as e:
    MP_OK = False
    print(f"[AI] MediaPipe алдаа: {e}")

try:
    from ultralytics import YOLO
    _yolo   = YOLO("yolov8n.pt")
    YOLO_OK = True
    print("[AI] YOLOv8 ✓")
except Exception as e:
    _yolo   = None
    YOLO_OK = False
    print(f"[AI] YOLO алдаа: {e}")

# ── Audio: Wav2Vec2 + Silero VAD ──────────────────────────────────────────────
AUDIO_OK = False
_wav2vec = None
_vad_model = None

try:
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    _AUD_MODEL_DIR = "./models/wav2vec2-mn"
    import os
    if os.path.exists(_AUD_MODEL_DIR):
        _wav2vec_proc = Wav2Vec2Processor.from_pretrained(_AUD_MODEL_DIR)
        _wav2vec      = Wav2Vec2ForCTC.from_pretrained(_AUD_MODEL_DIR)
        print("[AI] Wav2Vec2 Mongolian ✓")
    else:
        print(f"[AI] Wav2Vec2 загвар олдсонгүй: {_AUD_MODEL_DIR} — Silero VAD ашиглах")
except Exception as e:
    print(f"[AI] Wav2Vec2 алдаа: {e}")

try:
    import silero_vad
    _vad_model = silero_vad.load_vad()
    print("[AI] Silero VAD ✓")
except Exception as e:
    print(f"[AI] Silero VAD алдаа: {e}")

AUDIO_OK = _vad_model is not None or _wav2vec is not None
if AUDIO_OK:
    print("[AI] Audio мониторинг ✓")


def analyze_audio_samples(audio_samples: np.ndarray, sample_rate: int = 16000,
                          ctx: dict = None) -> list:
    """
    Audio clip дээр гадны яриа / олон хүн / чанга яриаг илрүүлнэ.
    audio_samples: numpy array, mono, 16kHz, float32 [-1, 1]
    ctx: student context dict (frame_no, audio_speech_count гэх мэт)
    Returns list of DetectionEvent objects.
    """
    events = []
    now = datetime.now().isoformat()
    if ctx is None:
        ctx = {}

    if _vad_model is None and _wav2vec is None:
        return events

    # ── VAD: speech detection ──────────────────────────────────────────
    if _vad_model is not None:
        try:
            speech_prob = _vad_model.forward(audio_samples, sample_rate).item()
            is_speech = speech_prob > 0.5

            # Хэт удаан speech (гадны яриа чанга яриж байж боломжтой)
            ctx["_audio_speech_frames"] = ctx.get("_audio_speech_frames", 0)
            if is_speech:
                ctx["_audio_speech_frames"] += 1
                speech_sec = ctx["_audio_speech_frames"] * (len(audio_samples) / sample_rate)
                if speech_sec > 5.0 and speech_sec < 10.0 and speech_sec % 2 < 0.5:
                    events.append(DetectionEvent(
                        "audio_speech_detected", "medium",
                        f"Чанга яриа {int(speech_sec)} секунд илэрлээ",
                        round(speech_prob, 2), now
                    ))
            else:
                ctx["_audio_speech_frames"] = 0
        except Exception as e:
            print(f"[VAD] Алдаа: {e}")

    # ── Wav2Vec2: гадны хэл / гадны хүн илрүүлэх ──────────────────────
    if _wav2vec is not None and _wav2vec_proc is not None:
        try:
            import torch
            inputs = _wav2vec_proc(
                audio_samples,
                sampling_rate=sample_rate,
                return_tensors="pt",
                padding=True
            )
            with torch.no_grad():
                logits = _wav2vec(inputs.input_values).logits
            predicted_ids = torch.argmax(logits, dim=-1)
            transcription = _wav2vec_proc.batch_decode(predicted_ids)[0]

            # Mongolian бус текст илэрвэл
            mongolian_chars = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяүөӨАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯҮӨ")
            non_mn = sum(1 for c in transcription if c.isalpha() and c not in mongolian_chars)
            if non_mn > len(transcription) * 0.3 and len(transcription.strip()) > 5:
                ctx["_foreign_audio_count"] = ctx.get("_foreign_audio_count", 0) + 1
                fc = ctx["_foreign_audio_count"]
                if fc % 3 == 0:
                    events.append(DetectionEvent(
                        "foreign_audio", "high",
                        f"Гадны яриа/хэл илэрлээ: '{transcription}'",
                        0.85, now
                    ))
        except Exception as e:
            print(f"[Wav2Vec2] Алдаа: {e}")

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
            dx = abs(lm[263].x - lm[33].x)
            dy = abs(lm[1].y - (lm[33].y + lm[263].y) / 2)
            if dx < 0.06 or dy > 0.08:
                ctx["gaze_away_count"] = ctx.get("gaze_away_count", 0) + 1
                g = ctx["gaze_away_count"]
                if g >= 15 and g % 15 == 0:
                    events.append(DetectionEvent("gaze_away","medium",
                        f"Дэлгэцээс {g} секунд өөр тийш харсан",
                        round(max(0, 1 - dx / 0.1), 2), now))
            else:
                ctx["gaze_away_count"] = 0

    # 4. Объект
    if YOLO_OK and _yolo:
        for r in _yolo.predict(frame, conf=0.45, verbose=False):
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

import os
import queue
import threading
import time
from contextlib import contextmanager
import cv2
import numpy as np
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path
from utils.log import log_ai, log_vad, log_warn, log_err, log_clf
from ai.gaze import gaze_step
from ai import audio_features as af
from ai import liveness

FACE_MISSING_SEC = 5    # 5с (бодит цаг) тасралтгүй нүүр алга бол face_missing
GAZE_AWAY_SEC    = 3    # 3с тасралтгүй өөр тийш харвал gaze_away
LOOKING_DOWN_SEC = 15   # 15с тасралтгүй доош харвал looking_down (low)
OBJECT_EVERY     = max(1, int(os.getenv("OBJECT_EVERY", "2")))   # YOLO-г хэдэн шинжилгээ тутамд

CLF_WINDOW_SEC         = 5    # классификаторт өгөх гүйдэг цонх (сургалтын клипийн урт)
SPEECH_HIST_CHUNKS     = 3    # ~6с (2с chunk × 3)
SHORT_SPEECH_SEC       = 1.0  # үүнээс богино яриа = "аан", ханиалга, шивнээ
SUSTAINED_SPEECH_RATIO = 0.4  # сүүлийн ~6с-ийн 40%+ нь яриа бол тасралтгүй яриа (high)

# ── Загварын pool ─────────────────────────────────────────────────────────────
# MediaPipe / YOLO / Silero VAD нь thread-safe биш. Өмнө нь нэг instance + lock ашигладаг байсан тул
# бүх оюутны шинжилгээ дараалан хийгдэж, CPU ~15% ачаалалтай үед 10+ оюутанд хоцордог байв
# (scripts/loadtest). Одоо AI_WORKERS ширхэг instance-ийн pool: нэг instance-ийг нэг thread ашиглана,
# өөр өөр оюутны кадр зэрэгцээ шинжлэгдэнэ.
# Хэмжилтээр (scripts/loadtest) 2-оос дээш instance нь бараг ашиггүй: YOLO аль хэдийн олон цөм
# ашигладаг тул нийт багтаамж ~15 кадр/с-д тулдаг. 2 нь санах ой/хурдны сайн тэнцвэр.
AI_WORKERS = int(os.getenv("AI_WORKERS") or 2)


class _Pool:
    def __init__(self, items: list):
        self._q: queue.Queue = queue.Queue()
        for it in items:
            self._q.put(it)
        self.size = len(items)

    @contextmanager
    def acquire(self):
        item = self._q.get()
        try:
            yield item
        finally:
            self._q.put(item)


_clf_lock = threading.Lock()     # WavLM (~380MB) нэг л instance — зөвхөн яриа илэрсэн үед ажиллана

try:
    import torch as _torch_threads
    # Pool-ийн instance бүр PyTorch-ийн бүх цөмийг булаалдахгүйн тулд thread-ийг хуваана
    _torch_threads.set_num_threads(max(2, (os.cpu_count() or 4) // AI_WORKERS))
except Exception:
    pass

try:
    import mediapipe as mp
    # static_image_mode=True: кадр бүрийг бие даан шинжилнэ → нэг оюутны tracking төлөв
    # нөгөө оюутны кадр руу шилжихгүй (1 Hz шинжилгээнд tracking ач холбогдолгүй).
    _mp_pool = _Pool([
        (mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.6),
         mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=2,
                                         refine_landmarks=True, min_detection_confidence=0.6))
        for _ in range(AI_WORKERS)])
    MP_OK = True
    log_ai(f"MediaPipe ✓ (pool {AI_WORKERS})")
except Exception as e:
    MP_OK = False
    log_err("AI", f"MediaPipe алдаа: {e}")

try:
    from ultralytics import YOLO
    _yolo_path = Path(__file__).resolve().parent.parent / "yolov8n.pt"   # CWD-ээс хамаарахгүй
    _yolo_pool = _Pool([YOLO(str(_yolo_path) if _yolo_path.exists() else "yolov8n.pt")
                        for _ in range(AI_WORKERS)])
    with _yolo_pool.acquire() as _y:
        _yolo = _y                       # ангиллын нэр (names) унших зориулалттай
    YOLO_OK = True
    log_ai(f"YOLOv8 ✓ (pool {AI_WORKERS})")
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
    _vad_pool  = _Pool([load_silero_vad() for _ in range(AI_WORKERS)])   # stateful → instance бүр тусдаа
    _vad_model = True                    # байгаа эсэхийн туг
    log_ai(f"Silero VAD ✓ (pool {AI_WORKERS})")
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
    events = _analyze_audio_impl(audio_samples, sample_rate, ctx)
    # Classifier нь яриаг илүү нарийн ангилсан бол ерөнхий VAD "audio_speech"-ийг давхар тооцохгүй
    if any(e.event_type in ("audio_talking", "audio_multiple_voices") for e in events):
        events = [e for e in events if e.event_type not in ("audio_speech", "audio_short_speech")]
    return events


def _analyze_audio_impl(audio_samples: np.ndarray, sample_rate: int = 16000,
                        ctx: dict = None) -> list:
    events = []
    now    = datetime.now().isoformat()
    if ctx is None:
        ctx = {}

    if _vad_model is None and _clf_model is None:
        return events

    # Гүйдэг цонх: сүүлийн CLF_WINDOW_SEC секундын бодит дуу. Классификатор 5с клип дээр
    # сурсан тул 2с chunk-ийг 3с тэгээр дүүргэхийн оронд энэ цонхыг өгнө.
    win = ctx.get("_pcm_window")
    win = audio_samples if win is None else np.concatenate([win, audio_samples])
    ctx["_pcm_window"] = win[-CLF_WINDOW_SEC * sample_rate:]

    # ── Step 1: VAD — speech идэж байгаа эсэхийг шалгах ──────────────
    is_speech    = True  # default: assume speech if no VAD
    speech_prob  = 1.0
    if _vad_model is not None:
        try:
            import torch as _torch
            _t = _torch.tensor(audio_samples)
            with _vad_pool.acquire() as vad:
                speech_timestamps = get_speech_timestamps(_t, vad, sampling_rate=sample_rate)
            is_speech   = len(speech_timestamps) > 0
            speech_prob = 1.0 if is_speech else 0.0
            rms = float(np.sqrt(np.mean(audio_samples**2)))
            total_speech_sec = sum((t['end'] - t['start']) for t in speech_timestamps) / sample_rate
            log_vad(is_speech, total_speech_sec, rms)

            # Сүүлийн ~6с-д яриа эзэлсэн хувь (3 chunk) — нэг удаагийн "аан"-ыг
            # тасралтгүй ярианаас ялгана.
            hist = ctx.setdefault("_speech_hist", [])
            hist.append((len(audio_samples) / sample_rate, total_speech_sec))
            del hist[:-SPEECH_HIST_CHUNKS]
            speech_ratio = sum(s for _, s in hist) / max(sum(d for d, _ in hist), 1e-6)
            feat = af.features(audio_samples, sample_rate)

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
                # VAD can miss very quiet whispers — catch by RMS relative to baseline,
                # гэхдээ зөвхөн ярианы хэмнэлтэй үед (гарын товшилт, сэнс → биш)
                if whisper_floor < rms < whisper_ceil and af.is_speech_like(feat):
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
            if total_speech_sec < SHORT_SPEECH_SEC:
                # Ханиалга, ширээ тогших зэрэг цохилтот дууг VAD заримдаа яриа гэж андуурна
                if af.is_impulsive(feat):
                    ctx["_whisper_count"] = 0
                    return events
                # Short + quiet → whisper (baseline-relative)
                if rms < max(0.05, baseline + 0.04):
                    ctx["_whisper_count"] = ctx.get("_whisper_count", 0) + 1
                    wc = ctx["_whisper_count"]
                    if wc >= 2 and wc % 2 == 0:
                        events.append(DetectionEvent(
                            "audio_whispering", "medium",
                            "Шивнэх яриа илэрлээ",
                            round(min(rms * 25, 1.0), 2), now
                        ))
                # Богино чанга дуу ("аан", дуу алдах) → бүртгэхгүй
                return events

            ctx["_whisper_count"] = 0
            if speech_ratio >= SUSTAINED_SPEECH_RATIO:
                # Тасралтгүй яриа (сүүлийн ~6с-ийн 40%+) → high
                ctx["_audio_speech_frames"] = ctx.get("_audio_speech_frames", 0) + 1
                sf = ctx["_audio_speech_frames"]
                # Fire on first qualifying batch, then every 3 batches (~6s repeat, dedup 10s)
                if sf == 1 or sf % 3 == 0:
                    events.append(DetectionEvent(
                        "audio_speech", "high",
                        f"Тасралтгүй яриа илэрлээ (сүүлийн 6с-ийн {speech_ratio:.0%})",
                        round(min(1.0, 0.5 + speech_ratio / 2), 2), now
                    ))
            else:
                # Ганц удаагийн богино хэллэг (жишээ нь асуултаа уншиж байгаад дуугарах) → low
                ctx["_audio_speech_frames"] = 0
                events.append(DetectionEvent(
                    "audio_short_speech", "low",
                    "Богино яриа илэрлээ",
                    0.5, now
                ))
        except Exception as e:
            log_err("VAD", f"Алдаа: {e}")

    # ── Step 2: Classifier — яриа ямар төрлийн эсэхийг тодорхойлох ───
    if _clf_model is not None and _clf_extractor is not None and is_speech:
        try:
            import torch
            max_len = sample_rate * CLF_WINDOW_SEC
            # Сүүлийн 5с-ийн бодит дуу (эхний секундүүдэд л богино байж, pad хийгдэнэ)
            clip    = ctx.get("_pcm_window", audio_samples)[-max_len:]
            inputs  = _clf_extractor(
                clip,
                sampling_rate=sample_rate,
                return_tensors="pt",
                max_length=max_len,
                truncation=True,
                padding="max_length",
            )
            with _clf_lock, torch.no_grad():
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
# Багшид харагдах нэр. YOLO (COCO) гар утсыг ихэвчлэн "remote" гэж андуурдаг (pilot туршилтаар
# ажиглагдсан), тиймээс "remote"-ийг утас төстэй объект гэж харуулна.
OBJECT_LABELS_MN = {
    "cell phone": "Гар утас",
    "book":       "Ном/дэвтэр",
    "laptop":     "Зөөврийн компьютер",
    "remote":     "Утас төстэй объект",
}

@dataclass
class DetectionEvent:
    event_type : str
    severity   : str
    message    : str
    confidence : float
    timestamp  : str
    def to_dict(self): return asdict(self)

def _sustained(ctx: dict, key: str, active: bool, min_sec: float, now_t: float) -> float | None:
    """Нөхцөл min_sec-ээс удаан ТАСРАЛТГҮЙ үргэлжилбэл (бодит цагаар) үргэлжилсэн хугацааг буцаана;
    дараа нь min_sec тутамд дахин. Өмнө нь кадрын тоогоор тоолдог байсан тул сервер ачааллаас болж
    секундэд 1-ээс цөөн кадр шинжилбэл "5 секунд" нь бодитоор 10 секунд болдог байв."""
    since_k, fired_k = f"_{key}_since", f"_{key}_fired"
    if not active:
        ctx.pop(since_k, None)
        ctx.pop(fired_k, None)
        return None
    elapsed = now_t - ctx.setdefault(since_k, now_t)
    if elapsed < min_sec:
        return None
    last = ctx.get(fired_k)
    if last is None or now_t - last >= min_sec:
        ctx[fired_k] = now_t
        return elapsed
    return None


def analyze_frame(frame: np.ndarray, ctx: dict) -> list:
    events = []
    now    = datetime.now().isoformat()
    now_t  = time.monotonic()
    if frame is None or frame.size == 0:
        return events
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # 1. Нүүр
    if MP_OK:
        with _mp_pool.acquire() as (face_det, face_mesh):
            faces = (face_det.process(rgb).detections or [])
            mesh  = face_mesh.process(rgb)
        n     = len(faces)
        missing_for = _sustained(ctx, "face_missing", n == 0, FACE_MISSING_SEC, now_t)
        if missing_for is not None:
            events.append(DetectionEvent("face_missing","high",
                f"Нүүр кадраас {missing_for:.0f} секунд гарсан", 0.95, now))

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

        # 3. Харц — толгойн байрлал (yaw/pitch°) + iris, оюутан бүрийн калибровктой (ai/gaze.py)
        ctx["_looking_down_now"] = False
        if mesh.multi_face_landmarks:
            # Олон нүүртэй үед хамгийн том (камерт ойр = шалгуулагч) нүүрийг сонгоно
            def _face_width(f):
                return abs(f.landmark[263].x - f.landmark[33].x)
            lm = max(mesh.multi_face_landmarks, key=_face_width).landmark
            h, w = frame.shape[:2]
            g = gaze_step(lm, w, h, ctx)

            if g["state"] == "tracking" and liveness.active(ctx):
                # Liveness даалгавар биелүүлж буй үед толгой эргүүлэх нь хүлээгдэж буй үйлдэл
                liveness.observe(ctx, g["d_yaw"])
                _sustained(ctx, "gaze", False, GAZE_AWAY_SEC, now_t)
            elif g["state"] == "tracking":
                away_for = _sustained(ctx, "gaze", g["away"], GAZE_AWAY_SEC, now_t)
                if away_for is not None:
                    events.append(DetectionEvent("gaze_away", "medium",
                        f"Дэлгэцээс {away_for:.0f}с өөр тийш харсан ({g['reason']})",
                        g["conf"], now))

                # Доош харах нь (бичих, бодох) хэвийн → зөвхөн удаан үргэлжилбэл low
                ctx["_looking_down_now"] = bool(g["down"])
                down_for = _sustained(ctx, "down", g["down"], LOOKING_DOWN_SEC, now_t)
                if down_for is not None:
                    events.append(DetectionEvent("looking_down", "low",
                        f"{down_for:.0f}с доош харж байна (доош {g['d_pitch']:.0f}°)",
                        0.5, now))
        else:
            _sustained(ctx, "gaze", False, GAZE_AWAY_SEC, now_t)
            _sustained(ctx, "down", False, LOOKING_DOWN_SEC, now_t)

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

    # YOLO нь шинжилгээний ~80%-ийг эзэлдэг тул OBJECT_EVERY шинжилгээ тутамд нэг удаа (default 2 → ~0.5 Hz).
    # Утас/ном хэдэн секунд харагддаг тул илрүүлэлтэд бага нөлөөтэй, харин серверийн багтаамж ~1.7 дахин өснө.
    run_yolo = ctx.get("frame_no", 0) % OBJECT_EVERY == 0
    if YOLO_OK and _yolo and run_yolo:
        obj_hist = ctx.setdefault("_obj_history", {})
        seen_this_frame = {}
        # YOLO conf=0.30 — олон candidate барих, дараа нь өөрсдөө filter хийнэ
        with _yolo_pool.acquire() as yolo:
            results = yolo.predict(frame, conf=0.30, verbose=False)
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
                        f"{OBJECT_LABELS_MN.get(obj_name, obj_name)} илэрлээ ({obj_name})",
                        round(cur_conf, 2), now))

        # Хосолсон нотолгоо: доош харж байх үед утасны сул (≥0.30) илрүүлэлт ч хангалттай —
        # өвөр дээрх утас ихэвчлэн кадрын доод ирмэгт хэсэгчлэн л харагддаг.
        # "remote"-ийг утас гэж тооцно (YOLO утсыг ихэвчлэн remote гэж андуурдаг)
        phone_conf = max(seen_this_frame.get("cell phone", 0.0), seen_this_frame.get("remote", 0.0))
        already = any(e.event_type == "object_detected"
                      and ("(cell phone)" in e.message or "(remote)" in e.message) for e in events)
        if ctx.get("_looking_down_now") and phone_conf > 0 and not already:
            last = ctx.get("_last_down_phone", -999)
            cur  = ctx.get("frame_no", 0)
            if cur - last > 10:
                ctx["_last_down_phone"] = cur
                events.append(DetectionEvent("looking_down_phone", "high",
                    "Доош харж байх үед утас илэрлээ",
                    round(max(phone_conf, 0.5), 2), now))

    ctx["frame_no"] = ctx.get("frame_no", 0) + 1
    return events

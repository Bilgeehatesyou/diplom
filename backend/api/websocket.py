import asyncio, json, shutil, os, tempfile, time
from collections import deque
from datetime import datetime
from pathlib import Path
import cv2, numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from utils.log import log_ws, log_db, log_audio, log_incident, log_decay, log_warn, log_err

# Auto-detect ffmpeg across platforms (Windows / macOS / Linux)
def _locate_ffmpeg():
    p = shutil.which('ffmpeg')
    if p:
        return os.path.dirname(p)
    candidates = [
        "/opt/homebrew/bin",                          # macOS Apple Silicon
        "/usr/local/bin",                             # macOS Intel / Linux
        "/usr/bin",                                   # Linux
        r"C:\Program Files\ffmpeg\bin",
        r"C:\ffmpeg\bin",
        r"C:\ProgramData\chocolatey\bin",
    ]
    winget = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(winget):
        for pkg in os.listdir(winget):
            if 'ffmpeg' in pkg.lower():
                for root, _, files in os.walk(os.path.join(winget, pkg)):
                    if 'ffmpeg.exe' in files or 'ffmpeg' in files:
                        candidates.append(root)
    for c in candidates:
        if os.path.isdir(c) and (os.path.isfile(os.path.join(c, 'ffmpeg.exe')) or os.path.isfile(os.path.join(c, 'ffmpeg'))):
            return c
    return None

_FFMPEG_BIN = _locate_ffmpeg()
if _FFMPEG_BIN:
    os.environ['PATH'] = _FFMPEG_BIN + os.pathsep + os.environ.get('PATH', '')
    log_audio(f"ffmpeg: {_FFMPEG_BIN}")
else:
    log_warn("AUDIO", "ffmpeg олдсонгүй")

from sqlalchemy import select, update, func
from db import AsyncSessionLocal, RiskEvent, ExamSession
from ai.analyzer import analyze_frame, analyze_audio_samples, DetectionEvent
from auth import decode_token
from exams import DEFAULT_EXAM_ID
from exam_service import get_active_session, is_expired, finalize_session, close_expired_sessions

router = APIRouter()

# ── Tuning ────────────────────────────────────────────────────────────────────
_DEDUP_WINDOW_SEC  = 10        # same event type within 10s → skip
_DECAY_PER_TICK    = 1.0       # points to subtract per tick
_DECAY_TICK_SEC    = 30        # decay every 30s
_ANALYSIS_PERIOD   = 1.0       # AI шинжилгээ секундэд 1 удаа (кадрын тоогоор биш, цагаар)
_VIDEO_STALL_SEC   = 6         # энэ хугацаанд кадр ирэхгүй бол → video_stalled
_AUDIO_STALL_SEC   = 12        # энэ хугацаанд дуу ирэхгүй бол → audio_stalled
_STREAM_LOST_SEC   = 10        # салснаас хойш энэ хугацаанд эргэж холбогдохгүй бол → stream_lost
_SEND_TIMEOUT_SEC  = 2.0       # удаан client бусдыгаа хаахгүй
_SEVERITY_POINTS   = {"high": 15, "medium": 7, "low": 3}
_INCIDENTS_DIR     = Path(__file__).resolve().parent.parent.parent / "models" / "incidents"
_INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)

# Client (browser) талаас мэдээлэх боломжтой event-үүд → (severity, message)
_CLIENT_EVENTS = {
    "tab_switch":      ("medium", "Цонх солигдсон"),
    "fullscreen_exit": ("medium", "Бүтэн дэлгэцээс гарсан"),
    "focus_lost":      ("low",    "Шалгалтын цонхноос гарсан"),
    "copy_attempt":    ("low",    "Хуулах/буулгах оролдлого"),
    "mic_denied":      ("high",   "Микрофон зөвшөөрөгдөөгүй — дуу хянагдахгүй байна"),
    "mic_ended":       ("high",   "Микрофон салгагдсан"),
    "camera_ended":    ("high",   "Камер салгагдсан"),
    "virtual_camera":  ("high",   "Виртуал камер ашиглаж байна"),
}


class _Peer:
    """WebSocket + send lock (олон task нэг socket руу зэрэг бичихээс хамгаална)."""
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self._lock = asyncio.Lock()

    async def send_json(self, data: dict) -> bool:
        return await self._send(text=json.dumps(data, ensure_ascii=False))

    async def send_bytes(self, data: bytes) -> bool:
        return await self._send(data=data)

    async def _send(self, text: str | None = None, data: bytes | None = None) -> bool:
        try:
            async with self._lock:
                coro = self.ws.send_text(text) if text is not None else self.ws.send_bytes(data)
                await asyncio.wait_for(coro, timeout=_SEND_TIMEOUT_SEC)
            return True
        except Exception:
            return False


class StudentConn(_Peer):
    def __init__(self, ws: WebSocket, student_id: str, exam_id: str, sess_id: int):
        super().__init__(ws)
        self.student_id = student_id
        self.exam_id    = exam_id
        self.sess_id    = sess_id
        self.ctx: dict  = {"frame_no": 0, "face_miss_count": 0, "gaze_away_count": 0}
        self.audio_init: bytes | None = None
        self.audio_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)
        self.awaiting_audio = False
        self.mic_denied     = False
        self.latest_frame: bytes | None = None
        self.frame_seq      = 0
        self.connected_at   = time.monotonic()
        self.last_frame_at: float | None = None
        self.last_audio_at: float | None = None
        self.stalls: set[str] = set()
        self.tasks: list[asyncio.Task] = []


class TeacherConn(_Peer):
    def __init__(self, ws: WebSocket, name: str):
        super().__init__(ws)
        self.name = name
        self.watching: str | None = None
        self.frame_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)   # зөвхөн хамгийн сүүлийн кадр
        self.sender: asyncio.Task | None = None


# ── State ─────────────────────────────────────────────────────────────────────
_students       : dict[str, StudentConn] = {}       # student_id → live connection
_teachers       : set[TeacherConn]       = set()    # олон багш зэрэг холбогдож болно
_last_event_at  : dict[str, dict]        = {}       # student_id → {event_type → epoch}
_latest_frame   : dict[str, bytes]       = {}       # student_id → сүүлийн JPEG (offline үед ч snapshot-д)
_teacher_buffer : deque                  = deque(maxlen=100)   # багш offline үеийн event-үүд
_gaze_baselines : dict[int, dict]        = {}       # session_id → харцын калибровк (reconnect-д хадгална)
_bg_task        : asyncio.Task | None    = None


def online_students() -> set[str]:
    return set(_students.keys())


async def _authenticate(websocket: WebSocket, role: str, query_token: str) -> dict | None:
    """Token-ийг эхний мессежээр ({"type":"auth","token":...}) хүлээн авна — URL query-д
    тавивал uvicorn-ийн access log-д үлддэг. Query token-ийг хэрэгслүүдэд зориулж дэмжинэ."""
    token = query_token
    if not token:
        try:
            first = await asyncio.wait_for(websocket.receive_text(), timeout=5)
            msg = json.loads(first)
            token = msg.get("token", "") if isinstance(msg, dict) and msg.get("type") == "auth" else ""
        except Exception:
            token = ""
    claims = decode_token(token)
    if not claims or claims["role"] != role:
        try: await websocket.close(code=4401, reason="unauthorized")
        except Exception: pass
        return None
    return claims


# ── Background: decay + expired sessions + score push ─────────────────────────
async def _background_loop():
    while True:
        try:
            await asyncio.sleep(_DECAY_TICK_SEC)
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ExamSession)
                    .where(ExamSession.ended_at.is_(None), ExamSession.risk_score > 0)
                    .values(risk_score=func.max(ExamSession.risk_score - _DECAY_PER_TICK, 0.0))
                )
                await db.commit()
                rows = (await db.execute(
                    select(ExamSession.student_id, ExamSession.risk_score)
                    .where(ExamSession.ended_at.is_(None))
                )).all()
            if rows:
                await _to_teachers_meta({"meta": "scores",
                                         "scores": {sid: round(score, 1) for sid, score in rows}})

            for sid, sess_id in await close_expired_sessions():
                log_db(f"Session {sess_id} ({sid}) хугацаа дуусч автоматаар илгээгдлээ")
                conn = _students.get(sid)
                if conn and conn.sess_id == sess_id:
                    await conn.send_json({"type": "exam_ended", "reason": "time_over"})
                await _to_teachers_meta({"meta": "submitted", "student_id": sid, "auto": True})
        except asyncio.CancelledError:
            break
        except Exception as e:
            log_err("BG", f"алдаа: {e}")


def _ensure_background_started():
    global _bg_task
    if _bg_task is None or _bg_task.done():
        _bg_task = asyncio.get_running_loop().create_task(_background_loop())


# ── Helpers (sync — thread дээр ажиллана) ─────────────────────────────────────
def _save_incident(student_id: str, event_type: str, frame_bytes: bytes | None):
    """Flag хийгдсэн мөчийн JPEG-ийг хадгална. 'student_id/filename.jpg' буцаана."""
    if not frame_bytes:
        return None
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        student_dir = _INCIDENTS_DIR / student_id
        student_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{ts}_{event_type}.jpg"
        out_path = student_dir / filename
        out_path.write_bytes(frame_bytes)
        log_incident(f"saved {out_path.name} ({len(frame_bytes)}B)")
        return f"{student_id}/{filename}"
    except Exception as e:
        log_err("INCIDENT", f"save error: {e}")
        return None


def _decode_webm(raw: bytes) -> np.ndarray | None:
    """WebM/Opus → 16kHz mono float32. ffmpeg subprocess тул заавал thread дээр дуудна."""
    tmp_path = None
    try:
        from pydub import AudioSegment
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f:
            f.write(raw)
            tmp_path = f.name
        audio = AudioSegment.from_file(tmp_path, format="webm")
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        return np.frombuffer(audio.raw_data, np.int16).astype(np.float32) / 32768.0
    except Exception as e:
        log_err("AUDIO", f"Декод алдаа: {e}")
        return None
    finally:
        if tmp_path:
            try: os.unlink(tmp_path)
            except OSError: pass


def _decode_jpeg(jpg: bytes):
    return cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)


def _should_dedupe(student_id: str, event_type: str) -> bool:
    """Return True if this event type fired too recently for this student."""
    now = time.time()
    last_map = _last_event_at.setdefault(student_id, {})
    if now - last_map.get(event_type, 0.0) < _DEDUP_WINDOW_SEC:
        return True
    last_map[event_type] = now
    return False


# ── Event pipeline ────────────────────────────────────────────────────────────
async def _emit(student_id: str, exam_id: str, sess_id: int, ev: DetectionEvent,
                frame_no: int = 0, with_snapshot: bool = True):
    if _should_dedupe(student_id, ev.event_type):
        return
    d = ev.to_dict()
    snapshot_path = None
    if with_snapshot:
        snapshot_path = await asyncio.to_thread(
            _save_incident, student_id, ev.event_type, _latest_frame.get(student_id))
    if snapshot_path:
        d['snapshot'] = snapshot_path

    score = await _log(sess_id, student_id, exam_id, ev, frame_no, snapshot_path)

    conn = _students.get(student_id)
    if conn and conn.sess_id == sess_id:
        await conn.send_json({"type": "event", **{k: d[k] for k in ("event_type", "severity", "message", "timestamp")}})
    await _to_teachers({"student_id": student_id, "event": d, "risk_score": score})


async def _log(sess_id: int, student_id: str, exam_id: str, ev: DetectionEvent,
               frame_no: int, snapshot: str | None = None) -> float | None:
    # Оноо = severity жин × confidence (0.5–1.0 хооронд хязгаарласан) — сул итгэлтэй илрүүлэлт бага оноо авна
    conf   = ev.confidence if ev.confidence is not None else 1.0
    points = _SEVERITY_POINTS.get(ev.severity, 0) * min(1.0, max(0.5, conf))
    async with AsyncSessionLocal() as db:
        db.add(RiskEvent(session_id=sess_id, student_id=student_id, exam_id=exam_id,
                         event_type=ev.event_type, severity=ev.severity,
                         message=ev.message, timestamp=datetime.fromisoformat(ev.timestamp),
                         frame_no=frame_no, confidence=ev.confidence, snapshot=snapshot))
        await db.execute(update(ExamSession)
            .where(ExamSession.id == sess_id, ExamSession.ended_at.is_(None))
            .values(risk_score=func.min(ExamSession.risk_score + points, 100.0)))
        await db.commit()
        score = (await db.execute(
            select(ExamSession.risk_score).where(ExamSession.id == sess_id))).scalar()
    from utils.log import C
    sev_color = {"high": C.BRED, "medium": C.BYELLOW, "low": C.CYAN}.get(ev.severity, C.RESET)
    log_db(f"{student_id} | {ev.event_type} | {sev_color}{ev.severity}{C.RESET} | conf={ev.confidence}")
    return round(score, 1) if score is not None else None


# ── Per-student workers ───────────────────────────────────────────────────────
async def _video_worker(conn: StudentConn):
    """Сүүлийн кадрыг 1 Hz-ээр шинжилнэ. Receive loop-ийг хэзээ ч хаахгүй."""
    last_seq = 0
    next_t = time.monotonic()
    while True:
        next_t += _ANALYSIS_PERIOD
        await asyncio.sleep(max(0.0, next_t - time.monotonic()))
        if conn.frame_seq == last_seq or conn.latest_frame is None:
            continue
        last_seq = conn.frame_seq
        try:
            frame = await asyncio.to_thread(_decode_jpeg, conn.latest_frame)
            if frame is None:
                continue
            events = await asyncio.to_thread(analyze_frame, frame, conn.ctx)
            if conn.ctx.get("gaze_calibrated") and not conn.ctx.get("_calib_notified"):
                conn.ctx["_calib_notified"] = True
                _gaze_baselines[conn.sess_id] = conn.ctx["gaze_baseline"]
                await conn.send_json({"type": "calibrated"})
            for ev in events:
                await _emit(conn.student_id, conn.exam_id, conn.sess_id, ev, conn.ctx.get("frame_no", 0))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log_err("AI", f"video worker ({conn.student_id}): {e}")
        if time.monotonic() - next_t > 5:   # удаан сервер → хуримтлагдахгүй
            next_t = time.monotonic()


async def _audio_worker(conn: StudentConn):
    """Audio chunk-уудыг thread дээр decode + шинжилнэ (pydub/ffmpeg event loop-ийг хаадаг байсан)."""
    while True:
        chunks = [await conn.audio_q.get()]
        while not conn.audio_q.empty():
            chunks.append(conn.audio_q.get_nowait())
        raw = b"".join(chunks)
        if conn.audio_init and not raw.startswith(conn.audio_init):
            raw = conn.audio_init + raw
        try:
            audio_arr = await asyncio.to_thread(_decode_webm, raw)
            if audio_arr is None:
                continue
            events = await asyncio.to_thread(analyze_audio_samples, audio_arr, 16000, conn.ctx)
            for ev in events:
                await _emit(conn.student_id, conn.exam_id, conn.sess_id, ev, conn.ctx.get("frame_no", 0))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log_err("AUDIO", f"audio worker ({conn.student_id}): {e}")


async def _watchdog(conn: StudentConn):
    """Client кадр/дуу илгээхээ зогсоовол (DevTools, камер унтраах) серверт бүртгэнэ."""
    while True:
        await asyncio.sleep(2)
        now = time.monotonic()
        checks = [("video", conn.last_frame_at, _VIDEO_STALL_SEC, "video_stalled", "high",
                   "Камерын дүрс {s}с ирээгүй")]
        if not conn.mic_denied:
            checks.append(("audio", conn.last_audio_at, _AUDIO_STALL_SEC, "audio_stalled", "medium",
                           "Микрофоны дуу {s}с ирээгүй"))
        for key, last, limit, etype, sev, msg in checks:
            gap = now - (last or conn.connected_at)
            if gap > limit:
                if key not in conn.stalls:
                    conn.stalls.add(key)
                    ev = DetectionEvent(etype, sev, msg.format(s=int(gap)), 1.0, datetime.now().isoformat())
                    await _emit(conn.student_id, conn.exam_id, conn.sess_id, ev, with_snapshot=False)
            else:
                conn.stalls.discard(key)


async def _stream_lost_check(student_id: str, exam_id: str, sess_id: int):
    """Салсан оюутан _STREAM_LOST_SEC дотор эргэж холбогдохгүй бол зөрчил бүртгэнэ."""
    await asyncio.sleep(_STREAM_LOST_SEC)
    if student_id in _students:
        return
    async with AsyncSessionLocal() as db:
        sess = (await db.execute(select(ExamSession).where(ExamSession.id == sess_id))).scalar_one_or_none()
        if sess is None or sess.ended_at is not None:
            return   # илгээгээд гарсан — хэвийн
    ev = DetectionEvent("stream_lost", "high",
                        f"Хяналтын холболт {_STREAM_LOST_SEC}с-ээс удаан тасарсан",
                        1.0, datetime.now().isoformat())
    await _emit(student_id, exam_id, sess_id, ev, with_snapshot=False)


# ── Student WebSocket ─────────────────────────────────────────────────────────
@router.websocket("/ws/student")
async def student_ws(websocket: WebSocket, token: str = "", exam_id: str = DEFAULT_EXAM_ID):
    await websocket.accept()
    claims = await _authenticate(websocket, "student", token)
    if claims is None:
        return
    student_id = claims["sub"]           # token-оос — URL-аас биш
    _ensure_background_started()

    # Session-ийг зөвхөн REST /api/exam/start үүсгэнэ; WS нь идэвхтэйг нь л ашиглана.
    async with AsyncSessionLocal() as db:
        sess = await get_active_session(db, student_id, exam_id)
        if sess is not None and is_expired(sess, 30):
            await finalize_session(db, sess, auto=True)
            sess = None
    if sess is None:
        await websocket.close(code=4409, reason="no active session")
        return

    # Нэг оюутны хуучин холболт (өөр tab) байвал хаана — шинэ нь эзэмшинэ.
    old = _students.get(student_id)
    if old is not None:
        await old.send_json({"type": "replaced"})
        try: await old.ws.close(code=4000, reason="replaced")
        except Exception: pass

    conn = StudentConn(websocket, student_id, exam_id, sess.id)
    # Reconnect: өмнөх калибровкийг ашиглана — дахин холбогдохдоо хажуу тийш харж
    # baseline-ийг "сургах" боломжгүй.
    if sess.id in _gaze_baselines:
        conn.ctx["gaze_baseline"] = _gaze_baselines[sess.id]
        conn.ctx["gaze_calibrated"] = True
    _students[student_id] = conn
    log_ws(f"✓ Оюутан: {student_id} (session {sess.id}, risk={sess.risk_score})")
    conn.tasks = [asyncio.create_task(_video_worker(conn)),
                  asyncio.create_task(_audio_worker(conn)),
                  asyncio.create_task(_watchdog(conn))]
    await _to_teachers_meta({"meta": "online", "student_id": student_id})
    await conn.send_json({"type": "ready", "session_id": sess.id})

    try:
        while True:
            data = await websocket.receive()
            if data.get("type") == "websocket.disconnect":
                break

            if data.get("text"):
                try:
                    msg = json.loads(data["text"])
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("_audio"):
                    conn.awaiting_audio = True
                    continue
                etype = msg.get("event")
                if etype in _CLIENT_EVENTS:
                    if etype == "mic_denied":
                        conn.mic_denied = True
                    sev, label = _CLIENT_EVENTS[etype]
                    detail = str(msg.get("detail", ""))[:80]
                    ev = DetectionEvent(etype, sev, f"{label} ({detail})" if detail else label,
                                        1.0, datetime.now().isoformat())
                    await _emit(student_id, exam_id, conn.sess_id, ev, conn.ctx.get("frame_no", 0))

            elif data.get("bytes"):
                chunk = data["bytes"]
                if conn.awaiting_audio:
                    conn.awaiting_audio = False
                    if conn.audio_init is None:
                        if chunk[:4] != b'\x1a\x45\xdf\xa3':
                            continue            # EBML header-гүй эхний chunk → декод хийх боломжгүй
                        conn.audio_init = chunk
                    conn.last_audio_at = time.monotonic()
                    if conn.audio_q.full():
                        conn.audio_q.get_nowait()   # сервер хоцорвол хамгийн хуучныг хаяна
                    conn.audio_q.put_nowait(chunk)
                    continue

                # Video frame — зөвхөн хадгалаад шууд дараагийнхыг хүлээнэ
                conn.latest_frame = chunk
                conn.frame_seq += 1
                conn.last_frame_at = time.monotonic()
                _latest_frame[student_id] = chunk
                for t in _teachers:
                    if t.watching == student_id:
                        if t.frame_q.full():
                            t.frame_q.get_nowait()
                        t.frame_q.put_nowait(chunk)

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for t in conn.tasks:
            t.cancel()
        # Зөвхөн ӨӨРИЙН бүртгэлийг цэвэрлэнэ (шинэ холболт аль хэдийн орлосон байж болно)
        if _students.get(student_id) is conn:
            del _students[student_id]
            log_ws(f"Оюутан салсан: {student_id}")
            await _to_teachers_meta({"meta": "offline", "student_id": student_id})
            asyncio.create_task(_stream_lost_check(student_id, exam_id, conn.sess_id))


async def notify_submitted(student_id: str, auto: bool = False):
    """REST /exam/submit-ээс дуудна: багшид мэдэгдэнэ."""
    await _to_teachers_meta({"meta": "submitted", "student_id": student_id, "auto": auto})


# ── Teacher WebSocket ─────────────────────────────────────────────────────────
async def _teacher_sender(t: TeacherConn):
    while True:
        frame = await t.frame_q.get()
        await t.send_bytes(frame)


@router.websocket("/ws/teacher")
async def teacher_ws(websocket: WebSocket, token: str = ""):
    await websocket.accept()
    claims = await _authenticate(websocket, "teacher", token)
    if claims is None:
        return
    _ensure_background_started()
    t = TeacherConn(websocket, claims.get("name") or claims["sub"])
    t.sender = asyncio.create_task(_teacher_sender(t))
    _teachers.add(t)
    log_ws(f"✓ Багш холбогдсон: {t.name}")

    for sid in list(_students.keys()):
        await t.send_json({"meta": "online", "student_id": sid})

    if _teacher_buffer:
        log_ws(f"Replaying {len(_teacher_buffer)} buffered events")
        for item in list(_teacher_buffer):
            await t.send_json(item)
        _teacher_buffer.clear()

    try:
        while True:
            text = await websocket.receive_text()
            try:
                cmd = json.loads(text)
            except ValueError:
                continue
            if not isinstance(cmd, dict):
                continue

            action = cmd.get("action")
            if action == "decide":
                sid, decision = cmd.get("student_id"), cmd.get("decision")
                if not isinstance(sid, str) or decision not in ("pending", "flagged", "cleared"):
                    await t.send_json({"error": "invalid decide payload"})
                    continue
                async with AsyncSessionLocal() as db:
                    latest = (await db.execute(
                        select(ExamSession)
                        .where(ExamSession.student_id == sid,
                               ExamSession.decision.not_in(("archived", "reset")))
                        .order_by(ExamSession.started_at.desc())
                    )).scalars().first()
                    if latest:
                        values = {"decision": decision}
                        # Cleared = багш бүх flag-ийг false positive гэж үзсэн → оноог тэглэнэ
                        if decision == "cleared":
                            values["risk_score"] = 0.0
                        await db.execute(update(ExamSession)
                            .where(ExamSession.id == latest.id).values(**values))
                        await db.commit()
                log_db(f"Шийдвэр ({t.name}): {sid} → {decision}")
                await t.send_json({"ack": "decide", "student_id": sid, "decision": decision})

            elif action == "watch":
                sid = cmd.get("student_id")
                t.watching = sid if isinstance(sid, str) else None
                if t.watching:
                    jpg = _latest_frame.get(t.watching)
                    if jpg:
                        await t.send_bytes(jpg)

            elif action == "unwatch":
                t.watching = None

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _teachers.discard(t)
        if t.sender:
            t.sender.cancel()
        log_ws(f"Багш салсан: {t.name}")


async def _to_teachers(payload: dict):
    if not _teachers:
        _teacher_buffer.append(payload)      # багш эргэж холбогдоход replay хийнэ
        return
    await asyncio.gather(*(t.send_json(payload) for t in list(_teachers)))


async def _to_teachers_meta(payload: dict):
    """UI-only signals (online/offline/scores) — never buffered, never stored."""
    if _teachers:
        await asyncio.gather(*(t.send_json(payload) for t in list(_teachers)))

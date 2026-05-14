import asyncio, json, shutil, os, tempfile, time
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

from sqlalchemy import select, update
from db import AsyncSessionLocal, RiskEvent, ExamSession
from ai.analyzer import analyze_frame, analyze_audio_samples, DetectionEvent

router = APIRouter()

# Connection / state maps
_conns           : dict[str, WebSocket] = {}    # student_id (and "teacher") → WebSocket
_ctx             : dict[str, dict]      = {}    # per-student AI context
_audio_bufs      : dict[str, list]      = {}
_audio_init      : dict[str, bytes]     = {}
_last_event_at   : dict[str, dict]      = {}    # student_id → {event_type → epoch_seconds}
_latest_frame    : dict[str, bytes]     = {}    # student_id → latest JPEG bytes (for teacher preview)
_teacher_buffer  : list                 = []    # events while teacher offline (last 100)
_teacher_watching: str | None           = None  # which student the teacher is viewing
_decay_task      : asyncio.Task | None  = None

# Tuning
_DEDUP_WINDOW_SEC  = 10        # same event type within 10s → skip
_DECAY_PER_TICK    = 1.0       # points to subtract per tick
_DECAY_TICK_SEC    = 30        # decay every 30s
_INCIDENTS_DIR     = Path(__file__).resolve().parent.parent.parent / "models" / "incidents"
_INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)


async def _decay_loop():
    """Decay risk_score over time for active sessions."""
    while True:
        try:
            await asyncio.sleep(_DECAY_TICK_SEC)
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ExamSession)
                    .where(ExamSession.ended_at.is_(None), ExamSession.risk_score > 0)
                    .values(risk_score=ExamSession.risk_score - _DECAY_PER_TICK)
                )
                await db.commit()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log_err("DECAY", f"алдаа: {e}")


def _ensure_decay_started():
    global _decay_task
    if _decay_task is None or _decay_task.done():
        try:
            loop = asyncio.get_running_loop()
            _decay_task = loop.create_task(_decay_loop())
        except RuntimeError:
            pass


def _save_incident(student_id: str, event_type: str, frame_bytes: bytes | None):
    """Persist a JPEG snapshot of the flagged moment for teacher review.
    Returns a relative path 'student_id/filename.jpg' that maps to /api/incident/..."""
    if not frame_bytes:
        log_warn("INCIDENT", f"no frame in buffer for {student_id} / {event_type}")
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


def _should_dedupe(student_id: str, event_type: str) -> bool:
    """Return True if this event type fired too recently for this student."""
    now = time.time()
    last_map = _last_event_at.setdefault(student_id, {})
    last = last_map.get(event_type, 0.0)
    if now - last < _DEDUP_WINDOW_SEC:
        return True
    last_map[event_type] = now
    return False


async def _process_audio(student_id: str, exam_id: str):
    buf = _audio_bufs.get(student_id, [])
    if not buf:
        return
    raw = b"".join(buf)
    _audio_bufs[student_id] = []

    init = _audio_init.get(student_id, b'')
    if init and raw[:len(init)] != init:
        raw = init + raw

    tmp_path = None
    try:
        from pydub import AudioSegment
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f:
            f.write(raw)
            tmp_path = f.name
        audio = AudioSegment.from_file(tmp_path, format="webm")
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        raw_pcm = audio.raw_data
        audio_arr = np.frombuffer(raw_pcm, np.int16).astype(np.float32) / 32768.0
        sr = 16000
    except Exception as e:
        log_err("AUDIO", f"Декод алдаа: {e}")
        return
    finally:
        if tmp_path:
            try: os.unlink(tmp_path)
            except: pass

    events = await asyncio.to_thread(analyze_audio_samples, audio_arr, sr, _ctx[student_id])
    for ev in events:
        if _should_dedupe(student_id, ev.event_type):
            continue
        await _emit(student_id, exam_id, ev)


async def _emit(student_id: str, exam_id: str, ev: DetectionEvent):
    d = ev.to_dict()
    snapshot_path = _save_incident(student_id, ev.event_type, _latest_frame.get(student_id))
    if snapshot_path:
        d['snapshot'] = snapshot_path

    ws = _conns.get(student_id)
    if ws:
        await _safe_send(ws, d)
    await _log(student_id, exam_id, ev, _ctx[student_id].get("frame_no", 0), snapshot_path)
    await _to_teacher(student_id, d)


@router.websocket("/ws/student/{student_id}")
async def student_ws(websocket: WebSocket, student_id: str, exam_id: str = "exam_001"):
    await websocket.accept()
    _ensure_decay_started()
    _conns[student_id] = websocket
    _ctx[student_id]   = {"frame_no": 0, "face_miss_count": 0, "gaze_away_count": 0}
    _audio_bufs[student_id] = []
    _audio_init.pop(student_id, None)
    _last_event_at[student_id] = {}
    log_ws(f"✓ Оюутан: {student_id}")

    # Reuse most recent active session (within 30 min) so reconnects don't reset risk
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(ExamSession)
            .where(ExamSession.student_id == student_id,
                   ExamSession.exam_id == exam_id,
                   ExamSession.ended_at.is_(None))
            .order_by(ExamSession.started_at.desc())
        )).scalars().first()
        if existing:
            sess_id = existing.id
            log_db(f"Reusing session {sess_id} for {student_id} (risk={existing.risk_score})")
        else:
            sess = ExamSession(student_id=student_id, exam_id=exam_id, started_at=datetime.now())
            db.add(sess)
            await db.commit()
            sess_id = sess.id

    # Notify teacher (UI only, NOT stored in DB)
    await _to_teacher_meta({"meta": "online", "student_id": student_id})

    try:
        while True:
            data = await websocket.receive()

            if "text" in data and data["text"]:
                try:
                    msg = json.loads(data["text"])
                except:
                    continue
                if msg.get("_audio"):
                    _ctx[student_id]["_awaiting_audio"] = True
                    continue
                etype = msg.get("event")
                if etype in ("tab_switch", "fullscreen_exit", "copy_attempt"):
                    if _should_dedupe(student_id, etype):
                        continue
                    labels = {"tab_switch": "Цонх солигдсон",
                              "fullscreen_exit": "Fullscreen-ээс гарсан",
                              "copy_attempt": "Хуулах оролдлого"}
                    ev = DetectionEvent(etype,
                                        "medium" if etype == "tab_switch" else "low",
                                        labels.get(etype, etype), 1.0,
                                        datetime.now().isoformat())
                    await _emit(student_id, exam_id, ev)

            elif "bytes" in data and data["bytes"]:
                if _ctx[student_id].pop("_awaiting_audio", False):
                    chunk = data["bytes"]
                    if student_id not in _audio_init:
                        if chunk[:4] == b'\x1a\x45\xdf\xa3':
                            _audio_init[student_id] = chunk
                        else:
                            continue
                    _audio_bufs[student_id].append(chunk)
                    await _process_audio(student_id, exam_id)
                    continue

                # Video frame
                frame_bytes = data["bytes"]
                _latest_frame[student_id] = frame_bytes

                # Push EVERY frame to teacher (smooth video) if watching — binary for speed
                if _teacher_watching == student_id:
                    teacher_ws = _conns.get("teacher")
                    if teacher_ws:
                        try:
                            await teacher_ws.send_bytes(frame_bytes)
                        except: pass

                # Throttle AI analysis to ~1 Hz (every 10th frame at 10 fps)
                _ctx[student_id]["_rx_count"] = _ctx[student_id].get("_rx_count", 0) + 1
                if _ctx[student_id]["_rx_count"] % 10 != 0:
                    continue

                arr   = np.frombuffer(frame_bytes, np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                events = await asyncio.to_thread(analyze_frame, frame, _ctx[student_id])
                for ev in events:
                    if _should_dedupe(student_id, ev.event_type):
                        continue
                    await _emit(student_id, exam_id, ev)

    except (WebSocketDisconnect, RuntimeError):
        log_ws(f"Оюутан салсан: {student_id}")
    finally:
        _conns.pop(student_id, None)
        _audio_bufs.pop(student_id, None)
        _audio_init.pop(student_id, None)
        _latest_frame.pop(student_id, None)
        _last_event_at.pop(student_id, None)
        await _to_teacher_meta({"meta": "offline", "student_id": student_id})
        # Don't end the session immediately — give 60s grace period for reconnect.
        # Session is only finalized if no new WS connection arrives.
        async def _finalize():
            await asyncio.sleep(60)
            if student_id in _conns:
                return  # student reconnected
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ExamSession)
                    .where(ExamSession.id == sess_id, ExamSession.ended_at.is_(None))
                    .values(ended_at=datetime.now())
                )
                await db.commit()
            log_db(f"Session {sess_id} ended (grace expired)")
        asyncio.create_task(_finalize())


@router.websocket("/ws/teacher")
async def teacher_ws(websocket: WebSocket):
    global _teacher_watching
    await websocket.accept()
    _conns["teacher"] = websocket
    log_ws("✓ Багш холбогдсон")

    # Send current online state for all students so UI rehydrates
    for sid in list(_conns.keys()):
        if sid != "teacher":
            await _safe_send(websocket, {"meta": "online", "student_id": sid})

    # Flush buffered events from while teacher was offline
    if _teacher_buffer:
        log_ws(f"Replaying {len(_teacher_buffer)} buffered events")
        for item in _teacher_buffer:
            await _safe_send(websocket, item)
        _teacher_buffer.clear()

    try:
        while True:
            text = await websocket.receive_text()
            try:
                cmd = json.loads(text)
            except:
                continue

            action = cmd.get("action")
            if action == "decide":
                sid = cmd["student_id"]
                decision = cmd["decision"]
                async with AsyncSessionLocal() as db:
                    # Apply to most recent session (active OR ended)
                    latest = (await db.execute(
                        select(ExamSession)
                        .where(ExamSession.student_id == sid)
                        .order_by(ExamSession.started_at.desc())
                    )).scalars().first()
                    if latest:
                        values = {"decision": decision}
                        # Cleared = teacher dismissed all flags as false positives → zero out score
                        if decision == "cleared":
                            values["risk_score"] = 0.0
                        await db.execute(update(ExamSession)
                            .where(ExamSession.id == latest.id)
                            .values(**values))
                        await db.commit()
                log_db(f"Шийдвэр: {sid} → {decision}")
                await _safe_send(websocket, {"ack": "decide",
                                              "student_id": sid,
                                              "decision": decision})

            elif action == "watch":
                sid = cmd.get("student_id")
                _teacher_watching = sid
                log_ws(f"Багш харж байна: {sid}")
                # Immediately send latest frame as binary
                if sid:
                    jpg = _latest_frame.get(sid)
                    if jpg:
                        try: await websocket.send_bytes(jpg)
                        except: pass

            elif action == "unwatch":
                _teacher_watching = None

    except (WebSocketDisconnect, RuntimeError):
        log_ws("Багш салсан")
    finally:
        _conns.pop("teacher", None)
        _teacher_watching = None


async def _log(student_id, exam_id, ev: DetectionEvent, frame_no: int, snapshot: str | None = None):
    from sqlalchemy import func as _func
    score = {"high": 15, "medium": 7, "low": 3}.get(ev.severity, 0)
    async with AsyncSessionLocal() as db:
        db.add(RiskEvent(student_id=student_id, exam_id=exam_id,
                         event_type=ev.event_type, severity=ev.severity,
                         message=ev.message, timestamp=datetime.fromisoformat(ev.timestamp),
                         frame_no=frame_no, confidence=ev.confidence, snapshot=snapshot))
        # Cap risk_score at 100
        await db.execute(update(ExamSession)
            .where(ExamSession.student_id == student_id, ExamSession.ended_at.is_(None))
            .values(risk_score=_func.min(ExamSession.risk_score + score, 100.0)))
        await db.commit()
    from utils.log import C
    sev_color = {"high": C.BRED, "medium": C.BYELLOW, "low": C.CYAN}.get(ev.severity, C.RESET)
    log_db(f"{student_id} | {ev.event_type} | {sev_color}{ev.severity}{C.RESET} | conf={ev.confidence}")


async def _to_teacher(sid, d):
    payload = {"student_id": sid, "event": d}
    ws = _conns.get("teacher")
    if ws:
        await _safe_send(ws, payload)
    else:
        # Buffer for replay when teacher reconnects (cap at 100)
        _teacher_buffer.append(payload)
        if len(_teacher_buffer) > 100:
            _teacher_buffer.pop(0)


async def _to_teacher_meta(payload: dict):
    """UI-only signals (online/offline) — never buffered, never stored."""
    ws = _conns.get("teacher")
    if ws:
        await _safe_send(ws, payload)


async def _safe_send(ws, data):
    try: await ws.send_text(json.dumps(data, ensure_ascii=False))
    except: pass

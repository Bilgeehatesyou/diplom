import asyncio, json
from datetime import datetime
import cv2, numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update
from db import AsyncSessionLocal, RiskEvent, ExamSession
from ai.analyzer import analyze_frame, DetectionEvent

router      = APIRouter()
_conns      : dict[str, WebSocket] = {}
_ctx        : dict[str, dict]      = {}

@router.websocket("/ws/student/{student_id}")
async def student_ws(websocket: WebSocket, student_id: str, exam_id: str = "exam_001"):
    await websocket.accept()
    _conns[student_id] = websocket
    _ctx[student_id]   = {"frame_no": 0, "face_miss_count": 0, "gaze_away_count": 0}
    print(f"[WS] ✓ Оюутан: {student_id}")

    async with AsyncSessionLocal() as db:
        sess = ExamSession(student_id=student_id, exam_id=exam_id, started_at=datetime.now())
        db.add(sess)
        await db.commit()
        sess_id = sess.id

    try:
        while True:
            data = await websocket.receive()

            if "bytes" in data and data["bytes"]:
                arr   = np.frombuffer(data["bytes"], np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None: continue
                events = await asyncio.to_thread(analyze_frame, frame, _ctx[student_id])
                for ev in events:
                    d = ev.to_dict()
                    await _safe_send(websocket, d)
                    await _log(student_id, exam_id, ev, _ctx[student_id].get("frame_no",0))
                    await _to_teacher(student_id, d)

            elif "text" in data and data["text"]:
                try:
                    msg = json.loads(data["text"])
                except: continue
                etype = msg.get("event")
                if etype in ("tab_switch","fullscreen_exit","copy_attempt"):
                    labels = {"tab_switch":"Цонх солигдсон","fullscreen_exit":"Fullscreen-ээс гарсан","copy_attempt":"Хуулах оролдлого"}
                    ev = DetectionEvent(etype,"medium" if etype=="tab_switch" else "low",
                                        labels.get(etype,etype), 1.0, datetime.now().isoformat())
                    d  = ev.to_dict()
                    await _safe_send(websocket, d)
                    await _log(student_id, exam_id, ev, _ctx[student_id].get("frame_no",0))
                    await _to_teacher(student_id, d)

    except WebSocketDisconnect:
        print(f"[WS] Оюутан салсан: {student_id}")
    finally:
        _conns.pop(student_id, None)
        async with AsyncSessionLocal() as db:
            await db.execute(update(ExamSession).where(ExamSession.id==sess_id).values(ended_at=datetime.now()))
            await db.commit()

@router.websocket("/ws/teacher")
async def teacher_ws(websocket: WebSocket):
    await websocket.accept()
    _conns["teacher"] = websocket
    print("[WS] ✓ Багш холбогдсон")
    try:
        while True:
            text = await websocket.receive_text()
            try:
                cmd = json.loads(text)
                if cmd.get("action") == "decide":
                    async with AsyncSessionLocal() as db:
                        await db.execute(update(ExamSession)
                            .where(ExamSession.student_id==cmd["student_id"])
                            .values(decision=cmd["decision"]))
                        await db.commit()
                    print(f"[DB] Шийдвэр: {cmd['student_id']} → {cmd['decision']}")
            except: pass
    except WebSocketDisconnect:
        _conns.pop("teacher", None)

async def _log(student_id, exam_id, ev: DetectionEvent, frame_no: int):
    score = {"high":15,"medium":7,"low":3}.get(ev.severity,0)
    async with AsyncSessionLocal() as db:
        db.add(RiskEvent(student_id=student_id, exam_id=exam_id,
                         event_type=ev.event_type, severity=ev.severity,
                         message=ev.message, timestamp=datetime.fromisoformat(ev.timestamp),
                         frame_no=frame_no, confidence=ev.confidence))
        await db.execute(update(ExamSession)
            .where(ExamSession.student_id==student_id, ExamSession.ended_at.is_(None))
            .values(risk_score=ExamSession.risk_score + score))
        await db.commit()
    print(f"[DB] {student_id} | {ev.event_type} | {ev.severity} | conf={ev.confidence}")

async def _to_teacher(sid, d):
    ws = _conns.get("teacher")
    if ws: await _safe_send(ws, {"student_id": sid, "event": d})

async def _safe_send(ws, data):
    try: await ws.send_text(json.dumps(data, ensure_ascii=False))
    except: pass

#!/bin/bash
# ════════════════════════════════════════════════════════════
#  AI Proctor — AI + Лог засвар суулгах скрипт
#  Ажиллуулах: ai-proctor/ folder дотор байгаа үед
#  bash patch.sh
# ════════════════════════════════════════════════════════════

set -e
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${YELLOW}▶ AI + Лог засвар суулгаж байна...${NC}"

# Зөв folder дотор байгаа эсэх шалгах
if [ ! -f "docker-compose.yml" ]; then
  echo -e "${RED}Алдаа: ai-proctor/ folder дотор ажиллуулна уу${NC}"
  exit 1
fi

# ════════════════════════════════════════
# 1. requirements.txt шинэчлэх
# ════════════════════════════════════════
cat > backend/requirements.txt << 'EOF'
fastapi==0.111.0
uvicorn==0.30.0
websockets==12.0
opencv-python-headless==4.9.0.80
mediapipe==0.10.14
ultralytics==8.2.0
sqlalchemy==2.0.30
aiosqlite==0.20.0
python-dotenv==1.0.1
numpy==1.26.4
Pillow==10.3.0
EOF
echo -e "${GREEN}✓ requirements.txt${NC}"

# ════════════════════════════════════════
# 2. db.py — Өгөгдлийн сан (SQLite async)
# ════════════════════════════════════════
cat > backend/db.py << 'PYEOF'
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, DateTime, Text, func
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./aiproctor.db")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class ExamSession(Base):
    __tablename__ = "exam_sessions"
    id         : Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id : Mapped[str]            = mapped_column(String(64), index=True)
    exam_id    : Mapped[str]            = mapped_column(String(64), default="exam_001")
    started_at : Mapped[datetime]       = mapped_column(DateTime, default=func.now())
    ended_at   : Mapped[datetime|None]  = mapped_column(DateTime, nullable=True)
    risk_score : Mapped[float]          = mapped_column(Float, default=0.0)
    decision   : Mapped[str]            = mapped_column(String(16), default="pending")

class RiskEvent(Base):
    __tablename__ = "risk_events"
    id         : Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id : Mapped[str]            = mapped_column(String(64), index=True)
    exam_id    : Mapped[str]            = mapped_column(String(64))
    event_type : Mapped[str]            = mapped_column(String(32))
    severity   : Mapped[str]            = mapped_column(String(8))
    message    : Mapped[str]            = mapped_column(Text)
    timestamp  : Mapped[datetime]       = mapped_column(DateTime, default=func.now())
    frame_no   : Mapped[int|None]       = mapped_column(Integer, nullable=True)
    confidence : Mapped[float|None]     = mapped_column(Float, nullable=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[DB] Хүснэгтүүд бэлэн ✓")

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
PYEOF
echo -e "${GREEN}✓ db.py${NC}"

# ════════════════════════════════════════
# 3. ai/analyzer.py — MediaPipe + YOLO
# ════════════════════════════════════════
mkdir -p backend/ai
touch backend/ai/__init__.py

cat > backend/ai/analyzer.py << 'PYEOF'
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
PYEOF
echo -e "${GREEN}✓ ai/analyzer.py${NC}"

# ════════════════════════════════════════
# 4. api/__init__.py
# ════════════════════════════════════════
mkdir -p backend/api
touch backend/api/__init__.py

# ════════════════════════════════════════
# 5. api/websocket.py — AI + DB холбосон
# ════════════════════════════════════════
cat > backend/api/websocket.py << 'PYEOF'
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
PYEOF
echo -e "${GREEN}✓ api/websocket.py${NC}"

# ════════════════════════════════════════
# 6. api/routes.py — Лог харах API
# ════════════════════════════════════════
cat > backend/api/routes.py << 'PYEOF'
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from datetime import datetime
from db import get_db, RiskEvent, ExamSession

router = APIRouter()

@router.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@router.get("/logs/{student_id}")
async def student_logs(student_id: str, exam_id: str = "exam_001",
                       limit: int = 100, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(RiskEvent)
        .where(RiskEvent.student_id==student_id, RiskEvent.exam_id==exam_id)
        .order_by(desc(RiskEvent.timestamp)).limit(limit)
    )).scalars().all()
    return {
        "student_id": student_id, "total": len(rows),
        "events": [{"id":r.id,"event_type":r.event_type,"severity":r.severity,
                    "message":r.message,"timestamp":r.timestamp.isoformat(),
                    "frame_no":r.frame_no,"confidence":r.confidence} for r in rows]
    }

@router.get("/report/{exam_id}")
async def exam_report(exam_id: str, db: AsyncSession = Depends(get_db)):
    sessions = (await db.execute(
        select(ExamSession).where(ExamSession.exam_id==exam_id)
    )).scalars().all()
    if not sessions:
        raise HTTPException(404, "Шалгалт олдсонгүй")
    counts = (await db.execute(
        select(RiskEvent.event_type, RiskEvent.severity, func.count())
        .where(RiskEvent.exam_id==exam_id)
        .group_by(RiskEvent.event_type, RiskEvent.severity)
    )).all()
    return {
        "exam_id": exam_id,
        "generated_at": datetime.now().isoformat(),
        "total_students": len(sessions),
        "students": [{"student_id":s.student_id,"risk_score":round(s.risk_score,1),
                      "decision":s.decision,"started_at":s.started_at.isoformat() if s.started_at else None,
                      "ended_at":s.ended_at.isoformat() if s.ended_at else None} for s in sessions],
        "event_summary": [{"event_type":r[0],"severity":r[1],"count":r[2]} for r in counts]
    }

@router.get("/stats")
async def live_stats(exam_id: str = "exam_001", db: AsyncSession = Depends(get_db)):
    active = (await db.execute(select(func.count()).select_from(ExamSession)
        .where(ExamSession.exam_id==exam_id, ExamSession.ended_at.is_(None)))).scalar() or 0
    high   = (await db.execute(select(func.count()).select_from(ExamSession)
        .where(ExamSession.exam_id==exam_id, ExamSession.risk_score>60,
               ExamSession.ended_at.is_(None)))).scalar() or 0
    flags  = (await db.execute(select(func.count()).select_from(RiskEvent)
        .where(RiskEvent.exam_id==exam_id))).scalar() or 0
    return {"exam_id":exam_id,"active":active,"high_risk":high,"total_flags":flags}
PYEOF
echo -e "${GREEN}✓ api/routes.py${NC}"

# ════════════════════════════════════════
# 7. main.py шинэчлэх
# ════════════════════════════════════════
cat > backend/main.py << 'PYEOF'
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db import init_db
from api.websocket import router as ws_router
from api.routes    import router as api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("[APP] AI Proctor backend эхэллээ ✓")
    yield

app = FastAPI(title="AI Proctor", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(ws_router)
app.include_router(api_router, prefix="/api")

@app.get("/")
def root():
    return {"status": "running", "docs": "/docs"}
PYEOF
echo -e "${GREEN}✓ main.py${NC}"

# ════════════════════════════════════════
# 8. pip суулгах
# ════════════════════════════════════════
echo ""
echo -e "${YELLOW}▶ Python хамаарлуудыг суулгаж байна...${NC}"
cd backend
python3 -m pip install -r requirements.txt -q
echo -e "${GREEN}✓ pip install дууслаа${NC}"
cd ..

# ════════════════════════════════════════
# ДУУСЛАА
# ════════════════════════════════════════
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✓ AI + Лог засвар амжилттай суулгагдлаа!           ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Одоо backend-г дахин эхлүүлнэ үү:"
echo ""
echo "  cd backend"
echo "  uvicorn main:app --reload --port 8000"
echo ""
echo "Лог шалгах:"
echo "  http://localhost:8000/api/logs/student_001"
echo "  http://localhost:8000/api/stats"
echo "  http://localhost:8000/api/report/exam_001"
echo "  http://localhost:8000/docs   ← Бүх API жагсаалт"
echo ""
echo "Терминал дотор real-time лог харагдана:"
echo "  [DB] student_001 | face_missing | high | conf=0.95"
echo "  [DB] student_001 | tab_switch   | medium | conf=1.0"

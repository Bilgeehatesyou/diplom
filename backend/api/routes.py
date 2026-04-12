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

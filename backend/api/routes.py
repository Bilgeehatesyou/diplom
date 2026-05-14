from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from datetime import datetime
from db import get_db, RiskEvent, ExamSession, Student, Teacher

_INCIDENTS_DIR = Path(__file__).resolve().parent.parent.parent / "models" / "incidents"

router = APIRouter()

class StudentLogin(BaseModel):
    student_id: str
    password: str

class TeacherLogin(BaseModel):
    name: str
    password: str

@router.post("/login/student")
async def login_student(body: StudentLogin, db: AsyncSession = Depends(get_db)):
    s = (await db.execute(select(Student).where(Student.id == body.student_id))).scalar_one_or_none()
    if not s or s.password != body.password:
        raise HTTPException(401, "Нэвтрэх мэдээлэл буруу")
    # End any stale active session so a fresh login = clean state
    from sqlalchemy import update as _update
    await db.execute(
        _update(ExamSession)
        .where(ExamSession.student_id == s.id, ExamSession.ended_at.is_(None))
        .values(ended_at=datetime.now())
    )
    await db.commit()
    return {"student_id": s.id, "name": s.name, "department": s.department}

@router.post("/login/teacher")
async def login_teacher(body: TeacherLogin, db: AsyncSession = Depends(get_db)):
    t = (await db.execute(select(Teacher).where(Teacher.name == body.name))).scalar_one_or_none()
    if not t or t.password != body.password:
        raise HTTPException(401, "Нэвтрэх мэдээлэл буруу")
    return {"teacher_id": t.id, "name": t.name}

@router.get("/students")
async def list_students(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Student))).scalars().all()
    return [{"id": s.id, "name": s.name, "department": s.department} for s in rows]

@router.get("/session/{student_id}/current")
async def current_session(student_id: str, exam_id: str = "exam_001", db: AsyncSession = Depends(get_db)):
    """Returns the student's currently-active session + its event count (not all-time)."""
    sess = (await db.execute(
        select(ExamSession)
        .where(ExamSession.student_id == student_id,
               ExamSession.exam_id == exam_id,
               ExamSession.ended_at.is_(None))
        .order_by(desc(ExamSession.started_at))
    )).scalars().first()
    if not sess:
        return {"active": False, "flag_count": 0, "risk_score": 0}
    cnt = (await db.execute(
        select(func.count()).select_from(RiskEvent)
        .where(RiskEvent.student_id == student_id,
               RiskEvent.exam_id == exam_id,
               RiskEvent.timestamp >= sess.started_at)
    )).scalar() or 0
    return {
        "active": True,
        "session_id": sess.id,
        "started_at": sess.started_at.isoformat(),
        "flag_count": cnt,
        "risk_score": round(sess.risk_score, 1),
    }


@router.get("/dashboard")
async def dashboard(exam_id: str = "exam_001", db: AsyncSession = Depends(get_db)):
    """For teacher: returns each student + ONLY their most-recent session's events."""
    students = (await db.execute(select(Student))).scalars().all()

    # Latest session per student
    sessions_q = (await db.execute(
        select(ExamSession).where(ExamSession.exam_id == exam_id)
        .order_by(desc(ExamSession.started_at))
    )).scalars().all()
    latest_by_student: dict[str, ExamSession] = {}
    for s in sessions_q:
        latest_by_student.setdefault(s.student_id, s)

    result = []
    for st in students:
        sess = latest_by_student.get(st.id)
        events = []
        if sess:
            # Only events from THIS session (timestamp >= started_at, and if ended, <= ended_at)
            q = select(RiskEvent).where(
                RiskEvent.student_id == st.id,
                RiskEvent.exam_id == exam_id,
                RiskEvent.timestamp >= sess.started_at,
            )
            if sess.ended_at is not None:
                q = q.where(RiskEvent.timestamp <= sess.ended_at)
            rows = (await db.execute(q.order_by(desc(RiskEvent.timestamp)).limit(100))).scalars().all()
            events = [{
                "event_type": ev.event_type, "severity": ev.severity,
                "message": ev.message, "timestamp": ev.timestamp.isoformat(),
                "confidence": ev.confidence, "snapshot": ev.snapshot,
            } for ev in rows]

        result.append({
            "id": st.id,
            "name": st.name,
            "department": st.department,
            "risk_score": round(sess.risk_score, 1) if sess else 0,
            "decision": sess.decision if sess else "pending",
            "online": bool(sess and sess.ended_at is None),
            "started_at": sess.started_at.isoformat() if sess and sess.started_at else None,
            "ended_at": sess.ended_at.isoformat() if sess and sess.ended_at else None,
            "events": events,
        })
    return result


@router.get("/report/student/{student_id}.csv")
async def student_report_csv(student_id: str, exam_id: str = "exam_001", db: AsyncSession = Depends(get_db)):
    """Download all events for a student's most recent session as CSV."""
    from fastapi.responses import Response

    sess = (await db.execute(
        select(ExamSession)
        .where(ExamSession.student_id == student_id, ExamSession.exam_id == exam_id)
        .order_by(desc(ExamSession.started_at))
    )).scalars().first()
    if not sess:
        raise HTTPException(404, "Session олдсонгүй")

    q = select(RiskEvent).where(
        RiskEvent.student_id == student_id,
        RiskEvent.exam_id == exam_id,
        RiskEvent.timestamp >= sess.started_at,
    )
    if sess.ended_at is not None:
        q = q.where(RiskEvent.timestamp <= sess.ended_at)
    rows = (await db.execute(q.order_by(RiskEvent.timestamp))).scalars().all()

    import io, csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp", "event_type", "severity", "message", "confidence", "snapshot"])
    for ev in rows:
        w.writerow([ev.timestamp.isoformat(), ev.event_type, ev.severity,
                    ev.message, ev.confidence or "", ev.snapshot or ""])

    csv_data = "﻿" + buf.getvalue()  # BOM for Excel Cyrillic support
    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="report_{student_id}.csv"'},
    )


@router.get("/incident/{student_id}/{filename}")
async def get_incident(student_id: str, filename: str):
    if ".." in student_id or ".." in filename or "\\" in student_id or "\\" in filename:
        raise HTTPException(400, "Буруу зам")
    path = _INCIDENTS_DIR / student_id / filename
    if not path.is_file():
        raise HTTPException(404, "Зураг олдсонгүй")
    return FileResponse(path, media_type="image/jpeg")


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

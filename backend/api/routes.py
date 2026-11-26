import io, csv
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import issue_token, verify_password, require_student, require_teacher
from db import get_db, RiskEvent, ExamSession, Student, Teacher, Submission
from exams import DEFAULT_EXAM_ID, get_exam, public_exam
from exam_service import (ExamError, SUBMIT_GRACE_SEC, start_or_resume, get_active_session,
                          get_submission, load_answers, save_answers, finalize_session,
                          is_expired, remaining_sec, deadline_of)

_INCIDENTS_DIR = Path(__file__).resolve().parent.parent.parent / "models" / "incidents"

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────
class StudentLogin(BaseModel):
    student_id: str = Field(max_length=64)
    password: str = Field(max_length=128)

class TeacherLogin(BaseModel):
    name: str = Field(max_length=128)
    password: str = Field(max_length=128)

class ExamStart(BaseModel):
    exam_id: str = DEFAULT_EXAM_ID

class AnswersBody(BaseModel):
    exam_id: str = DEFAULT_EXAM_ID
    answers: dict[str, str] = Field(default_factory=dict)


def _clean_answers(exam_id: str, answers: dict[str, str]) -> dict[str, str]:
    """Зөвхөн тухайн шалгалтын асуултын id-тай, хэт урт биш хариултыг хадгална."""
    exam = get_exam(exam_id)
    valid_ids = {str(q["id"]) for q in exam["questions"]} if exam else set()
    return {k: str(v)[:20000] for k, v in answers.items() if k in valid_ids}


def _event_json(ev: RiskEvent) -> dict:
    return {"event_type": ev.event_type, "severity": ev.severity,
            "message": ev.message, "timestamp": ev.timestamp.isoformat(),
            "confidence": ev.confidence, "snapshot": ev.snapshot}


def _online(student_id: str) -> bool:
    from api.websocket import online_students
    return student_id in online_students()


# ── Auth ──────────────────────────────────────────────────────────────────────
@router.post("/login/student")
async def login_student(body: StudentLogin, db: AsyncSession = Depends(get_db)):
    s = (await db.execute(select(Student).where(Student.id == body.student_id.strip()))).scalar_one_or_none()
    if not s or not verify_password(body.password, s.password):
        raise HTTPException(401, "Нэвтрэх мэдээлэл буруу")
    # Анхаар: login нь идэвхтэй session-ийг ДУУСГАХГҮЙ — дахин нэвтэрч оноо/таймер reset хийх боломжгүй.
    return {"student_id": s.id, "name": s.name, "department": s.department,
            "token": issue_token(s.id, "student", s.name)}


@router.post("/login/teacher")
async def login_teacher(body: TeacherLogin, db: AsyncSession = Depends(get_db)):
    t = (await db.execute(select(Teacher).where(Teacher.name == body.name.strip()))).scalar_one_or_none()
    if not t or not verify_password(body.password, t.password):
        raise HTTPException(401, "Нэвтрэх мэдээлэл буруу")
    return {"teacher_id": t.id, "name": t.name, "token": issue_token(str(t.id), "teacher", t.name)}


# ── Student: exam lifecycle ───────────────────────────────────────────────────
@router.post("/exam/start")
async def exam_start(body: ExamStart, user=Depends(require_student), db: AsyncSession = Depends(get_db)):
    """Шалгалт эхлүүлэх эсвэл үргэлжлүүлэх (refresh / reconnect / дахин нэвтрэх үед ижил session)."""
    if get_exam(body.exam_id) is None:
        raise HTTPException(404, "Шалгалт олдсонгүй")
    try:
        sess = await start_or_resume(db, user["sub"], body.exam_id)
    except ExamError as e:
        raise HTTPException(e.status, {"code": e.code, "message": e.message})
    sub = await get_submission(db, sess.id)
    flag_count = (await db.execute(
        select(func.count()).select_from(RiskEvent).where(RiskEvent.session_id == sess.id)
    )).scalar() or 0
    return {
        "session_id": sess.id,
        "started_at": sess.started_at.isoformat(),
        "deadline": deadline_of(sess).isoformat(),
        "remaining_sec": remaining_sec(sess),
        "answers": load_answers(sub),
        "flag_count": flag_count,
        "exam": public_exam(body.exam_id),
    }


@router.put("/exam/answers")
async def exam_autosave(body: AnswersBody, user=Depends(require_student), db: AsyncSession = Depends(get_db)):
    sess = await get_active_session(db, user["sub"], body.exam_id)
    if sess is None:
        raise HTTPException(409, {"code": "no_active_session", "message": "Идэвхтэй шалгалт алга"})
    if is_expired(sess, SUBMIT_GRACE_SEC):
        await finalize_session(db, sess, auto=True)
        raise HTTPException(409, {"code": "time_over", "message": "Шалгалтын хугацаа дууссан"})
    await save_answers(db, sess, _clean_answers(body.exam_id, body.answers))
    await db.commit()
    return {"ok": True, "saved_at": datetime.now().isoformat(), "remaining_sec": remaining_sec(sess)}


@router.post("/exam/submit")
async def exam_submit(body: AnswersBody, user=Depends(require_student), db: AsyncSession = Depends(get_db)):
    sess = await get_active_session(db, user["sub"], body.exam_id)
    if sess is None:
        # Давтан илгээлт (сүлжээний retry) → idempotent
        last = (await db.execute(
            select(Submission).where(Submission.student_id == user["sub"],
                                     Submission.exam_id == body.exam_id,
                                     Submission.submitted_at.is_not(None))
            .order_by(desc(Submission.submitted_at))
        )).scalars().first()
        if last:
            return {"ok": True, "status": "already_submitted", "submitted_at": last.submitted_at.isoformat()}
        raise HTTPException(409, {"code": "no_active_session", "message": "Идэвхтэй шалгалт алга"})

    from api.websocket import notify_submitted
    if is_expired(sess, SUBMIT_GRACE_SEC):
        # Хугацаа хэтэрсэн илгээлтийг хүлээн авахгүй — autosave хийгдсэн хариулт л илгээгдэнэ
        await finalize_session(db, sess, auto=True)
        await notify_submitted(user["sub"], auto=True)
        raise HTTPException(409, {"code": "time_over",
                                  "message": "Хугацаа дууссан — сүүлд хадгалагдсан хариулт илгээгдлээ"})
    await finalize_session(db, sess, auto=False, answers=_clean_answers(body.exam_id, body.answers))
    await notify_submitted(user["sub"])
    return {"ok": True, "status": "submitted", "submitted_at": datetime.now().isoformat()}


# ── Teacher ───────────────────────────────────────────────────────────────────
@router.get("/students")
async def list_students(_=Depends(require_teacher), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Student))).scalars().all()
    return [{"id": s.id, "name": s.name, "department": s.department} for s in rows]


@router.get("/dashboard")
async def dashboard(exam_id: str = DEFAULT_EXAM_ID, _=Depends(require_teacher),
                    db: AsyncSession = Depends(get_db)):
    """
    For teacher: returns each student + ONLY their most-recent NON-ARCHIVED session.
    Архивласан session-ууд /api/history-д харагдана.
    """
    students = (await db.execute(select(Student))).scalars().all()

    sessions_q = (await db.execute(
        select(ExamSession).where(ExamSession.exam_id == exam_id,
                                  ExamSession.decision != "archived")
        .order_by(desc(ExamSession.started_at))
    )).scalars().all()
    latest_by_student: dict[str, ExamSession] = {}
    for s in sessions_q:
        latest_by_student.setdefault(s.student_id, s)

    result = []
    for st in students:
        sess = latest_by_student.get(st.id)
        events, submitted_at = [], None
        # "reset" session-ий event-ууд DB-д хадгалагдсан хэвээр (audit), dashboard-д нуугдана.
        is_reset = bool(sess and sess.decision == "reset")
        if sess and not is_reset:
            rows = (await db.execute(
                select(RiskEvent).where(RiskEvent.session_id == sess.id)
                .order_by(desc(RiskEvent.timestamp)).limit(100)
            )).scalars().all()
            events = [_event_json(ev) for ev in rows]
            sub = await get_submission(db, sess.id)
            if sub and sub.submitted_at:
                submitted_at = sub.submitted_at.isoformat()

        result.append({
            "id": st.id,
            "name": st.name,
            "department": st.department,
            "session_id": sess.id if sess and not is_reset else None,
            "risk_score": 0 if is_reset else (round(sess.risk_score, 1) if sess else 0),
            "decision": "pending" if is_reset else (sess.decision if sess else "pending"),
            "online": _online(st.id),
            "active": bool(sess and sess.ended_at is None),
            "started_at": sess.started_at.isoformat() if sess and sess.started_at else None,
            "ended_at": sess.ended_at.isoformat() if sess and sess.ended_at else None,
            "submitted_at": submitted_at,
            "events": events,
        })
    return result


@router.get("/session/{session_id}/submission")
async def session_submission(session_id: int, _=Depends(require_teacher), db: AsyncSession = Depends(get_db)):
    """Оюутны хариулт + асуултууд (багшид)."""
    sess = (await db.execute(select(ExamSession).where(ExamSession.id == session_id))).scalar_one_or_none()
    if not sess:
        raise HTTPException(404, "Session олдсонгүй")
    sub = await get_submission(db, session_id)
    exam = get_exam(sess.exam_id)
    answers = load_answers(sub)
    return {
        "session_id": sess.id,
        "student_id": sess.student_id,
        "exam_id": sess.exam_id,
        "submitted_at": sub.submitted_at.isoformat() if sub and sub.submitted_at else None,
        "auto_submitted": bool(sub and sub.auto_submitted),
        "updated_at": sub.updated_at.isoformat() if sub and sub.updated_at else None,
        "items": [{"id": q["id"], "text": q["text"], "type": q["type"],
                   "answer": answers.get(str(q["id"]), "")}
                  for q in (exam["questions"] if exam else [])],
    }


@router.post("/session/{student_id}/clear")
async def clear_session(student_id: str, exam_id: str = DEFAULT_EXAM_ID,
                        _=Depends(require_teacher), db: AsyncSession = Depends(get_db)):
    """
    Дууссан session-ийг 'reset' болгоно: event-ууд DB-д үлдэнэ (audit), dashboard-аас нуугдана,
    оюутан шалгалтыг дахин өгөх боломжтой болно. Идэвхтэй шалгалтыг цэвэрлэхгүй.
    """
    sess = (await db.execute(
        select(ExamSession)
        .where(ExamSession.student_id == student_id, ExamSession.exam_id == exam_id)
        .order_by(desc(ExamSession.started_at))
    )).scalars().first()
    if not sess:
        raise HTTPException(404, "Session олдсонгүй")
    if sess.ended_at is None:
        raise HTTPException(409, "Шалгалт явагдаж байна — дууссаны дараа цэвэрлэнэ. "
                                 "Одоо бол 'Зөрчилгүй баталгаажуулах'-ыг ашиглана уу.")
    await db.execute(update(ExamSession).where(ExamSession.id == sess.id)
                     .values(decision="reset", risk_score=0.0))
    await db.commit()
    return {"ok": True, "session_id": sess.id}


@router.post("/dashboard/archive")
async def archive_all_dashboard(exam_id: str = DEFAULT_EXAM_ID,
                                _=Depends(require_teacher), db: AsyncSession = Depends(get_db)):
    """
    Бүх дууссан (ended_at != NULL) session-уудыг archive хийнэ.
    Архивласан session-ууд /api/dashboard-аас нуугдаж, /api/history-д харагдана.
    Идэвхтэй (active) session-уудыг хөнддөггүй.
    """
    res = await db.execute(
        update(ExamSession)
        .where(ExamSession.exam_id == exam_id,
               ExamSession.ended_at.is_not(None),
               ExamSession.decision != "archived")
        .values(decision="archived")
    )
    await db.commit()
    return {"ok": True, "archived": res.rowcount or 0}


@router.get("/history")
async def history(exam_id: str = DEFAULT_EXAM_ID, limit: int = 200,
                  _=Depends(require_teacher), db: AsyncSession = Depends(get_db)):
    """Архивласан (өнгөрсөн) шалгалтын session-уудыг буцаана. Хамгийн сүүлийнхээс эхлэн."""
    sessions = (await db.execute(
        select(ExamSession)
        .where(ExamSession.exam_id == exam_id,
               ExamSession.decision.in_(("archived", "reset", "flagged", "cleared")))
        .order_by(desc(ExamSession.started_at))
        .limit(min(limit, 1000))
    )).scalars().all()

    student_ids = list({s.student_id for s in sessions})
    students = (await db.execute(
        select(Student).where(Student.id.in_(student_ids))
    )).scalars().all() if student_ids else []
    student_map = {s.id: s for s in students}

    counts = dict((await db.execute(
        select(RiskEvent.session_id, func.count())
        .where(RiskEvent.session_id.in_([s.id for s in sessions]))
        .group_by(RiskEvent.session_id)
    )).all()) if sessions else {}

    result = []
    for sess in sessions:
        st = student_map.get(sess.student_id)
        result.append({
            "session_id": sess.id,
            "student_id": sess.student_id,
            "student_name": st.name if st else sess.student_id,
            "department": st.department if st else "—",
            "exam_id": sess.exam_id,
            "risk_score": round(sess.risk_score, 1),
            "decision": sess.decision,
            "started_at": sess.started_at.isoformat() if sess.started_at else None,
            "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
            "event_count": counts.get(sess.id, 0),
        })
    return result


@router.get("/history/session/{session_id}")
async def history_session_detail(session_id: int, _=Depends(require_teacher),
                                 db: AsyncSession = Depends(get_db)):
    """Нэг архивласан session-ийн дэлгэрэнгүй event жагсаалт."""
    sess = (await db.execute(
        select(ExamSession).where(ExamSession.id == session_id)
    )).scalar_one_or_none()
    if not sess:
        raise HTTPException(404, "Session олдсонгүй")
    events = (await db.execute(
        select(RiskEvent).where(RiskEvent.session_id == sess.id)
        .order_by(desc(RiskEvent.timestamp)).limit(500)
    )).scalars().all()
    return {
        "session_id": sess.id,
        "student_id": sess.student_id,
        "risk_score": round(sess.risk_score, 1),
        "decision": sess.decision,
        "started_at": sess.started_at.isoformat() if sess.started_at else None,
        "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
        "events": [_event_json(ev) for ev in events],
    }


def _csv_response(rows: list[RiskEvent], filename: str) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp", "event_type", "severity", "message", "confidence", "snapshot"])
    for ev in rows:
        w.writerow([ev.timestamp.isoformat(), ev.event_type, ev.severity,
                    ev.message, ev.confidence or "", ev.snapshot or ""])
    return Response(
        content="﻿" + buf.getvalue(),  # BOM for Excel Cyrillic support
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/report/student/{student_id}.csv")
async def student_report_csv(student_id: str, exam_id: str = DEFAULT_EXAM_ID,
                             session_id: int | None = None,
                             _=Depends(require_teacher), db: AsyncSession = Depends(get_db)):
    """Оюутны сүүлийн (эсвэл session_id-аар заасан) session-ий бүх event-ийг CSV-ээр."""
    q = select(ExamSession).where(ExamSession.student_id == student_id, ExamSession.exam_id == exam_id)
    if session_id is not None:
        q = q.where(ExamSession.id == session_id)
    sess = (await db.execute(q.order_by(desc(ExamSession.started_at)))).scalars().first()
    if not sess:
        raise HTTPException(404, "Session олдсонгүй")
    rows = (await db.execute(
        select(RiskEvent).where(RiskEvent.session_id == sess.id).order_by(RiskEvent.timestamp)
    )).scalars().all()
    return _csv_response(rows, f"report_{student_id}_s{sess.id}.csv")


@router.get("/incident/{student_id}/{filename}")
async def get_incident(student_id: str, filename: str, _=Depends(require_teacher)):
    base = _INCIDENTS_DIR.resolve()
    path = (base / student_id / filename).resolve()
    if base not in path.parents or path.suffix.lower() != ".jpg":
        raise HTTPException(400, "Буруу зам")
    if not path.is_file():
        raise HTTPException(404, "Зураг олдсонгүй")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@router.get("/logs/{student_id}")
async def student_logs(student_id: str, exam_id: str = DEFAULT_EXAM_ID, limit: int = 100,
                       _=Depends(require_teacher), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(RiskEvent)
        .where(RiskEvent.student_id == student_id, RiskEvent.exam_id == exam_id)
        .order_by(desc(RiskEvent.timestamp)).limit(min(limit, 1000))
    )).scalars().all()
    return {
        "student_id": student_id, "total": len(rows),
        "events": [{"id": r.id, "session_id": r.session_id, "event_type": r.event_type,
                    "severity": r.severity, "message": r.message,
                    "timestamp": r.timestamp.isoformat(), "frame_no": r.frame_no,
                    "confidence": r.confidence} for r in rows]
    }


@router.get("/report/{exam_id}")
async def exam_report(exam_id: str, _=Depends(require_teacher), db: AsyncSession = Depends(get_db)):
    sessions = (await db.execute(
        select(ExamSession).where(ExamSession.exam_id == exam_id)
    )).scalars().all()
    if not sessions:
        raise HTTPException(404, "Шалгалт олдсонгүй")
    counts = (await db.execute(
        select(RiskEvent.event_type, RiskEvent.severity, func.count())
        .where(RiskEvent.exam_id == exam_id)
        .group_by(RiskEvent.event_type, RiskEvent.severity)
    )).all()
    return {
        "exam_id": exam_id,
        "generated_at": datetime.now().isoformat(),
        "total_sessions": len(sessions),
        "students": [{"session_id": s.id, "student_id": s.student_id, "risk_score": round(s.risk_score, 1),
                      "decision": s.decision, "started_at": s.started_at.isoformat() if s.started_at else None,
                      "ended_at": s.ended_at.isoformat() if s.ended_at else None} for s in sessions],
        "event_summary": [{"event_type": r[0], "severity": r[1], "count": r[2]} for r in counts]
    }


@router.get("/stats")
async def live_stats(exam_id: str = DEFAULT_EXAM_ID, _=Depends(require_teacher),
                     db: AsyncSession = Depends(get_db)):
    active = (await db.execute(select(func.count()).select_from(ExamSession)
        .where(ExamSession.exam_id == exam_id, ExamSession.ended_at.is_(None)))).scalar() or 0
    high   = (await db.execute(select(func.count()).select_from(ExamSession)
        .where(ExamSession.exam_id == exam_id, ExamSession.risk_score > 60,
               ExamSession.ended_at.is_(None)))).scalar() or 0
    flags  = (await db.execute(select(func.count()).select_from(RiskEvent)
        .where(RiskEvent.exam_id == exam_id))).scalar() or 0
    return {"exam_id": exam_id, "active": active, "high_risk": high, "total_flags": flags}

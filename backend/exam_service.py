"""
Шалгалтын session-ийн амьдралын мөчлөг — REST болон WebSocket хоёул эндээс ашиглана.

Дүрэм:
  * Нэг оюутан нэг шалгалтад нэг л идэвхтэй session (DB partial unique index).
  * Дахин нэвтрэх / refresh / сүлжээ тасрах нь session-ийг ДУУСГАХГҮЙ — оноо, таймер хэвээр.
  * Session зөвхөн (а) оюутан илгээх, (б) серверийн хугацаа дуусах үед хаагдана.
  * Хугацааг сервер started_at + duration-аар тооцно; client-ийн цагт итгэхгүй.
  * Илгээсэн шалгалтыг дахин өгөхгүй — багш "Цэвэрлэх" (reset) хийсэн эсвэл ALLOW_RETAKE=1 үед л болно.
"""
import json
import os
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSessionLocal, ExamSession, Submission
from exams import exam_duration

ALLOW_RETAKE     = os.getenv("ALLOW_RETAKE", "0") == "1"
SUBMIT_GRACE_SEC = 30   # сүлжээний саатлыг тооцож илгээлтийг deadline-аас хойш 30с хүлээн авна


class ExamError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def deadline_of(sess: ExamSession) -> datetime:
    return sess.started_at + timedelta(seconds=exam_duration(sess.exam_id))


def remaining_sec(sess: ExamSession, now: datetime | None = None) -> int:
    now = now or datetime.now()
    return max(0, int((deadline_of(sess) - now).total_seconds()))


def is_expired(sess: ExamSession, grace_sec: int = 0, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return now > deadline_of(sess) + timedelta(seconds=grace_sec)


async def get_active_session(db: AsyncSession, student_id: str, exam_id: str) -> ExamSession | None:
    return (await db.execute(
        select(ExamSession)
        .where(ExamSession.student_id == student_id,
               ExamSession.exam_id == exam_id,
               ExamSession.ended_at.is_(None))
        .order_by(ExamSession.started_at.desc())
    )).scalars().first()


async def get_submission(db: AsyncSession, session_id: int) -> Submission | None:
    return (await db.execute(
        select(Submission).where(Submission.session_id == session_id)
    )).scalar_one_or_none()


def load_answers(sub: Submission | None) -> dict:
    if not sub or not sub.answers:
        return {}
    try:
        data = json.loads(sub.answers)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


async def has_completed(db: AsyncSession, student_id: str, exam_id: str) -> bool:
    row = (await db.execute(
        select(Submission.id)
        .join(ExamSession, ExamSession.id == Submission.session_id)
        .where(Submission.student_id == student_id,
               Submission.exam_id == exam_id,
               Submission.submitted_at.is_not(None),
               ExamSession.decision != "reset")
        .limit(1)
    )).first()
    return row is not None


async def save_answers(db: AsyncSession, sess: ExamSession, answers: dict) -> Submission:
    now = datetime.now()
    sub = await get_submission(db, sess.id)
    if sub is None:
        sub = Submission(session_id=sess.id, student_id=sess.student_id, exam_id=sess.exam_id,
                         answers="{}", updated_at=now)
        db.add(sub)
    sub.answers = json.dumps(answers, ensure_ascii=False)
    sub.updated_at = now
    return sub


async def finalize_session(db: AsyncSession, sess: ExamSession, *, auto: bool,
                           answers: dict | None = None) -> None:
    """Session-ийг хааж, хариултыг илгээсэн гэж тэмдэглэнэ.
    auto=True → хугацаа дууссан (autosave хийгдсэн хариулт илгээгдэнэ)."""
    now = datetime.now()
    sub = await get_submission(db, sess.id)
    if answers is not None:
        sub = await save_answers(db, sess, answers)
    if sub is not None and sub.submitted_at is None:
        sub.submitted_at = min(now, deadline_of(sess)) if auto else now
        sub.auto_submitted = auto
    sess.ended_at = min(now, deadline_of(sess)) if auto else now
    await db.commit()


async def start_or_resume(db: AsyncSession, student_id: str, exam_id: str) -> ExamSession:
    sess = await get_active_session(db, student_id, exam_id)
    if sess is not None and is_expired(sess, SUBMIT_GRACE_SEC):
        await finalize_session(db, sess, auto=True)
        sess = None
    if sess is not None:
        return sess

    if not ALLOW_RETAKE and await has_completed(db, student_id, exam_id):
        raise ExamError(409, "already_submitted", "Та энэ шалгалтыг аль хэдийн өгсөн байна")

    sess = ExamSession(student_id=student_id, exam_id=exam_id, started_at=datetime.now())
    db.add(sess)
    try:
        await db.flush()
        # Draft хариулт мөрийг шууд үүсгэнэ → шалгалт "эхэлсэн" гэдэг нь бүртгэгдэнэ,
        # хугацаа дуусахад автоматаар илгээгдэнэ (асуултыг хараад гараад дахин эхлэх боломжгүй).
        db.add(Submission(session_id=sess.id, student_id=student_id, exam_id=exam_id,
                          answers="{}", updated_at=datetime.now()))
        await db.commit()
    except IntegrityError:
        # Зэрэг ирсэн хоёр хүсэлт (React StrictMode, хоёр tab) → unique index нэгийг нь зогсооно
        await db.rollback()
        sess = await get_active_session(db, student_id, exam_id)
        if sess is None:
            raise
    return sess


async def close_expired_sessions() -> list[tuple[str, int]]:
    """Хугацаа нь дууссан идэвхтэй session-уудыг хаана (startup + 30с тутам).
    Хаасан (student_id, session_id)-ийн жагсаалтыг буцаана."""
    closed: list[tuple[str, int]] = []
    async with AsyncSessionLocal() as db:
        active = (await db.execute(
            select(ExamSession).where(ExamSession.ended_at.is_(None))
        )).scalars().all()
        for sess in active:
            if is_expired(sess, SUBMIT_GRACE_SEC):
                await finalize_session(db, sess, auto=True)
                closed.append((sess.student_id, sess.id))
    return closed

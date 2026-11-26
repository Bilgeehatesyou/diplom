"""Шалгалтын session-ий дүрэм — түр SQLite DB дээр (P0-2, P0-3, P0-5)."""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta

_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP}/test.db".replace("\\", "/")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from sqlalchemy import select, func, update  # noqa: E402

import exam_service as es  # noqa: E402
from db import AsyncSessionLocal, Base, engine, ExamSession, Submission  # noqa: E402

EXAM = "exam_001"


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def fresh_db():
    async def reset():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    run(reset())
    yield


def test_start_creates_session_and_draft_submission():
    async def go():
        async with AsyncSessionLocal() as db:
            s = await es.start_or_resume(db, "S1", EXAM)
            sub = await es.get_submission(db, s.id)
            return s, sub
    s, sub = run(go())
    assert s.ended_at is None and sub is not None and sub.submitted_at is None


def test_relogin_resumes_same_session_without_reset():
    async def go():
        async with AsyncSessionLocal() as db:
            s1 = await es.start_or_resume(db, "S1", EXAM)
            await db.execute(update(ExamSession).where(ExamSession.id == s1.id).values(risk_score=42.0))
            await db.commit()
        async with AsyncSessionLocal() as db:            # "дахин нэвтэрсэн" шинэ хүсэлт
            s2 = await es.start_or_resume(db, "S1", EXAM)
            return s1.id, s2.id, s2.risk_score, s1.started_at, s2.started_at
    id1, id2, score, t1, t2 = run(go())
    assert id1 == id2 and score == 42.0 and t1 == t2


def test_concurrent_starts_create_one_session():
    async def one():
        async with AsyncSessionLocal() as db:
            return (await es.start_or_resume(db, "S1", EXAM)).id
    async def go():
        ids = await asyncio.gather(*(one() for _ in range(5)))
        async with AsyncSessionLocal() as db:
            n = (await db.execute(select(func.count()).select_from(ExamSession)
                                  .where(ExamSession.ended_at.is_(None)))).scalar()
        return set(ids), n
    ids, active = run(go())
    assert len(ids) == 1 and active == 1


def test_submit_blocks_retake_until_teacher_reset():
    async def go():
        async with AsyncSessionLocal() as db:
            s = await es.start_or_resume(db, "S1", EXAM)
            await es.finalize_session(db, s, auto=False, answers={"1": "x"})
        async with AsyncSessionLocal() as db:
            with pytest.raises(es.ExamError) as e:
                await es.start_or_resume(db, "S1", EXAM)
            code = e.value.code
            await db.execute(update(ExamSession).where(ExamSession.id == s.id).values(decision="reset"))
            await db.commit()
            s2 = await es.start_or_resume(db, "S1", EXAM)
            return code, s.id, s2.id
    code, old, new = run(go())
    assert code == "already_submitted" and new != old


def test_expired_session_is_auto_submitted():
    async def go():
        async with AsyncSessionLocal() as db:
            s = await es.start_or_resume(db, "S1", EXAM)
            await es.save_answers(db, s, {"1": "autosaved"})
            await db.execute(update(ExamSession).where(ExamSession.id == s.id)
                             .values(started_at=datetime.now() - timedelta(hours=2)))
            await db.commit()
        closed = await es.close_expired_sessions()
        async with AsyncSessionLocal() as db:
            sess = (await db.execute(select(ExamSession).where(ExamSession.id == s.id))).scalar_one()
            sub = await es.get_submission(db, s.id)
            return closed, sess, sub
    closed, sess, sub = run(go())
    assert closed and sess.ended_at is not None
    assert sub.submitted_at is not None and sub.auto_submitted and es.load_answers(sub) == {"1": "autosaved"}


def test_remaining_time_comes_from_server_start():
    s = ExamSession(student_id="S1", exam_id=EXAM, started_at=datetime.now() - timedelta(minutes=10))
    assert 39 * 60 <= es.remaining_sec(s) <= 40 * 60
    assert not es.is_expired(s)

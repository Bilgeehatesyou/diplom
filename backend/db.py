from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import (String, Integer, Float, DateTime, Text, Boolean, ForeignKey, Index,
                        func, text)
from datetime import datetime
import os
from utils.log import log_db, log_warn

_DEFAULT_DB_URL = "sqlite+aiosqlite:///./aiproctor.db"


def _resolve_db_url() -> str:
    url = os.getenv("DATABASE_URL", _DEFAULT_DB_URL)
    # Async driver-гүй URL (жишээ нь "postgresql://") backend-ийг унагаадаг байсан.
    if url.startswith(("sqlite+aiosqlite://", "postgresql+asyncpg://")):
        return url
    log_warn("DB", f"DATABASE_URL async driver-гүй байна ({url.split(':', 1)[0]}://...) — SQLite ашиглана")
    return _DEFAULT_DB_URL


DATABASE_URL = _resolve_db_url()
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Student(Base):
    __tablename__ = "students"
    id         : Mapped[str]            = mapped_column(String(64), primary_key=True)  # e.g. B22FA1260
    name       : Mapped[str]            = mapped_column(String(128))
    department : Mapped[str]            = mapped_column(String(128), default="")
    password   : Mapped[str]            = mapped_column(String(128))   # bcrypt hash


class Teacher(Base):
    __tablename__ = "teachers"
    id         : Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    name       : Mapped[str]            = mapped_column(String(128), unique=True)
    password   : Mapped[str]            = mapped_column(String(128))   # bcrypt hash


class ExamSession(Base):
    __tablename__ = "exam_sessions"
    id         : Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id : Mapped[str]            = mapped_column(String(64), index=True)
    exam_id    : Mapped[str]            = mapped_column(String(64), default="exam_001")
    started_at : Mapped[datetime]       = mapped_column(DateTime, default=func.now())
    ended_at   : Mapped[datetime|None]  = mapped_column(DateTime, nullable=True)
    risk_score : Mapped[float]          = mapped_column(Float, default=0.0)
    decision   : Mapped[str]            = mapped_column(String(16), default="pending")

    # Нэг оюутан нэг шалгалтад зөвхөн НЭГ идэвхтэй session-тэй байна (race condition-оос хамгаална).
    __table_args__ = (
        Index("uq_active_session", "student_id", "exam_id", unique=True,
              sqlite_where=text("ended_at IS NULL"),
              postgresql_where=text("ended_at IS NULL")),
    )


class RiskEvent(Base):
    __tablename__ = "risk_events"
    id         : Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id : Mapped[int|None]       = mapped_column(ForeignKey("exam_sessions.id"), nullable=True, index=True)
    student_id : Mapped[str]            = mapped_column(String(64), index=True)
    exam_id    : Mapped[str]            = mapped_column(String(64))
    event_type : Mapped[str]            = mapped_column(String(32))
    severity   : Mapped[str]            = mapped_column(String(8))
    message    : Mapped[str]            = mapped_column(Text)
    timestamp  : Mapped[datetime]       = mapped_column(DateTime, default=func.now())
    frame_no   : Mapped[int|None]       = mapped_column(Integer, nullable=True)
    confidence : Mapped[float|None]     = mapped_column(Float, nullable=True)
    snapshot   : Mapped[str|None]       = mapped_column(String(256), nullable=True)


class Submission(Base):
    """Шалгалтын хариулт. Autosave нь answers-ийг шинэчилнэ, илгээхэд submitted_at тавигдана."""
    __tablename__ = "submissions"
    id             : Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id     : Mapped[int]           = mapped_column(ForeignKey("exam_sessions.id"), unique=True)
    student_id     : Mapped[str]           = mapped_column(String(64), index=True)
    exam_id        : Mapped[str]           = mapped_column(String(64))
    answers        : Mapped[str]           = mapped_column(Text, default="{}")   # JSON {question_id: answer}
    updated_at     : Mapped[datetime]      = mapped_column(DateTime, default=func.now())
    submitted_at   : Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    auto_submitted : Mapped[bool]          = mapped_column(Boolean, default=False)


async def _migrate(conn):
    """Хуучин aiproctor.db-г шинэ schema руу шилжүүлэх (SQLite, idempotent)."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    cols = {r[1] for r in (await conn.exec_driver_sql("PRAGMA table_info(risk_events)")).fetchall()}
    if "session_id" not in cols:
        await conn.exec_driver_sql("ALTER TABLE risk_events ADD COLUMN session_id INTEGER REFERENCES exam_sessions(id)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_risk_events_session_id ON risk_events(session_id)")
        log_db("Migration: risk_events.session_id нэмлээ")

    # Давхардсан идэвхтэй session-уудыг хаах (хамгийн сүүлийнхийг үлдээнэ) — unique index-ээс өмнө.
    res = await conn.exec_driver_sql("""
        UPDATE exam_sessions SET ended_at = COALESCE(
            (SELECT MIN(s2.started_at) FROM exam_sessions s2
              WHERE s2.student_id = exam_sessions.student_id AND s2.exam_id = exam_sessions.exam_id
                AND s2.ended_at IS NULL AND s2.started_at > exam_sessions.started_at),
            datetime('now', 'localtime'))
        WHERE ended_at IS NULL AND EXISTS (
            SELECT 1 FROM exam_sessions s3
             WHERE s3.student_id = exam_sessions.student_id AND s3.exam_id = exam_sessions.exam_id
               AND s3.ended_at IS NULL AND s3.id <> exam_sessions.id
               AND (s3.started_at > exam_sessions.started_at
                    OR (s3.started_at = exam_sessions.started_at AND s3.id > exam_sessions.id)))
    """)
    if res.rowcount:
        log_db(f"Migration: {res.rowcount} давхардсан идэвхтэй session хаалаа")
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_active_session "
        "ON exam_sessions(student_id, exam_id) WHERE ended_at IS NULL")

    # Хуучин event-уудыг session-д нь холбох (өмнө нь зөвхөн цагийн интервалаар таамагладаг байсан)
    res = await conn.exec_driver_sql("""
        UPDATE risk_events SET session_id = (
            SELECT s.id FROM exam_sessions s
             WHERE s.student_id = risk_events.student_id AND s.exam_id = risk_events.exam_id
               AND risk_events.timestamp >= s.started_at
               AND (s.ended_at IS NULL OR risk_events.timestamp <= s.ended_at)
             ORDER BY s.started_at DESC LIMIT 1)
        WHERE session_id IS NULL
    """)
    if res.rowcount:
        log_db(f"Migration: {res.rowcount} event-ийг session-д холболоо")


async def init_db():
    from auth import hash_password, is_hashed

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)

    from sqlalchemy import select as _select
    async with AsyncSessionLocal() as db:
        # Seed default user accounts (bcrypt hash-тай)
        existing_student = (await db.execute(_select(Student).where(Student.id == "B22FA1260"))).scalar_one_or_none()
        if not existing_student:
            db.add(Student(id="B22FA1260", name="Г.Билгээ",
                           department="Мэдээллийн систем менежмент тэнхим",
                           password=hash_password("123456")))
        existing_teacher = (await db.execute(_select(Teacher).where(Teacher.name == "Tsetsegee"))).scalar_one_or_none()
        if not existing_teacher:
            db.add(Teacher(name="Tsetsegee", password=hash_password("123456")))

        # Plaintext нууц үгтэй хуучин бүртгэлүүдийг hash болгох
        migrated = 0
        for model in (Student, Teacher):
            for row in (await db.execute(_select(model))).scalars().all():
                if row.password and not is_hashed(row.password):
                    row.password = hash_password(row.password)
                    migrated += 1
        await db.commit()
        if migrated:
            log_db(f"Migration: {migrated} plaintext нууц үгийг bcrypt болголоо")

    from exam_service import close_expired_sessions
    closed = await close_expired_sessions()
    if closed:
        log_db(f"Хугацаа нь дууссан {len(closed)} session хаалаа")
    log_db("Хүснэгтүүд бэлэн ✓")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

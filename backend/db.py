from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, DateTime, Text, func
from datetime import datetime
import os
from utils.log import log_db

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./aiproctor.db")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Student(Base):
    __tablename__ = "students"
    id         : Mapped[str]            = mapped_column(String(64), primary_key=True)  # e.g. B22FA1260
    name       : Mapped[str]            = mapped_column(String(128))
    department : Mapped[str]            = mapped_column(String(128), default="")
    password   : Mapped[str]            = mapped_column(String(128))

class Teacher(Base):
    __tablename__ = "teachers"
    id         : Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    name       : Mapped[str]            = mapped_column(String(128), unique=True)
    password   : Mapped[str]            = mapped_column(String(128))

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
    snapshot   : Mapped[str|None]       = mapped_column(String(256), nullable=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed default user accounts
    from sqlalchemy import select as _select
    async with AsyncSessionLocal() as db:
        existing_student = (await db.execute(_select(Student).where(Student.id == "B22FA1260"))).scalar_one_or_none()
        if not existing_student:
            db.add(Student(id="B22FA1260", name="Г.Билгээ",
                           department="Мэдээллийн систем менежмент тэнхим",
                           password="123456"))
        existing_teacher = (await db.execute(_select(Teacher).where(Teacher.name == "Tsetsegee"))).scalar_one_or_none()
        if not existing_teacher:
            db.add(Teacher(name="Tsetsegee", password="123456"))
        await db.commit()
    log_db("Хүснэгтүүд бэлэн ✓")

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

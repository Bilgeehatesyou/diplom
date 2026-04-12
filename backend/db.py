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

from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class RiskEvent(Base):
    __tablename__ = "risk_events"
    id         = Column(Integer, primary_key=True, index=True)
    student_id = Column(String, index=True)
    exam_id    = Column(String, index=True)
    event_type = Column(String)
    severity   = Column(String)
    timestamp  = Column(DateTime, default=datetime.utcnow)
    message    = Column(Text)
    meta       = Column(JSON)

class ExamSession(Base):
    __tablename__ = "exam_sessions"
    id         = Column(Integer, primary_key=True, index=True)
    student_id = Column(String, index=True)
    exam_id    = Column(String)
    started_at = Column(DateTime)
    ended_at   = Column(DateTime, nullable=True)
    risk_score = Column(Float, default=0.0)
    decision   = Column(String, default="pending")  # pending | flagged | cleared

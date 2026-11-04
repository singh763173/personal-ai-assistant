"""SQLAlchemy models for the Bee backend."""
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    transcript = Column(Text)
    summary = Column(Text, nullable=True)
    reply = Column(Text, nullable=True)
    todos = Column(Text, nullable=True)
    raw_llm_response = Column(Text, nullable=True)
    image_path = Column(Text, nullable=True)


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, index=True)
    name = Column(String, nullable=True)
    api_key_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(DateTime, nullable=True)
    enabled = Column(Integer, default=1)

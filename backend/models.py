"""SQLAlchemy models for the Bee backend."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
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
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    last_seen_at = Column(DateTime, nullable=True)
    enabled = Column(Integer, default=1)

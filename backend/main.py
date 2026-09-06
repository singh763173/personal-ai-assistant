"""
FastAPI backend for the Ollama Bee Device.
- Receives WAV chunks from the device
- Transcribes with faster-whisper (local)
- Sends transcript to Ollama for summary/to-do extraction
- Stores conversations in SQLite
- Serves a minimal dashboard
"""
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional

import requests
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from faster_whisper import WhisperModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

app = FastAPI(title="Ollama Bee Backend")

# Config
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "kimi-k2.7-code:cloud")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

# Database
DB_PATH = Path(__file__).parent / "bee.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    transcript = Column(Text)
    summary = Column(Text, nullable=True)
    todos = Column(Text, nullable=True)  # JSON list
    raw_llm_response = Column(Text, nullable=True)


Base.metadata.create_all(bind=engine)

# Load models
print(f"Loading Whisper model: {WHISPER_MODEL} ({WHISPER_DEVICE}/{WHISPER_COMPUTE})...")
whisper_model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
print("Whisper loaded.")


class UploadResponse(BaseModel):
    conversation_id: int
    transcript: str
    summary: Optional[str]
    todos: List[str]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def transcribe(path: Path) -> str:
    segments, _ = whisper_model.transcribe(str(path), language="en", beam_size=5)
    return " ".join([seg.text.strip() for seg in segments]).strip()


def ask_ollama(transcript: str) -> dict:
    """Send transcript to Ollama and request summary + to-dos."""
    prompt = f"""You are a helpful personal AI assistant reviewing an audio transcript captured from the user's day.
Transcript:
{transcript}

Tasks:
1. Write a concise 2-3 sentence summary of what was discussed or happened.
2. Extract any actionable to-do items. Return an empty list if none.
3. Classify the conversation type (e.g., meeting, note, reminder, casual).

Respond ONLY as valid JSON with this exact structure:
{{
  "summary": "...",
  "todos": ["..."],
  "type": "..."
}}"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.3, "num_ctx": 4096},
    }
    try:
        r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        raw = data.get("response", "")
        parsed = json.loads(raw)
        return {
            "summary": parsed.get("summary", ""),
            "todos": parsed.get("todos", []),
            "type": parsed.get("type", "unknown"),
            "raw": raw,
        }
    except Exception as e:
        return {"summary": f"LLM error: {e}", "todos": [], "type": "error", "raw": str(e)}


@app.post("/upload", response_model=UploadResponse)
async def upload_audio(
    audio: UploadFile = File(...),
    device_id: str = Form("unknown"),
):
    if not audio.filename.endswith(".wav"):
        raise HTTPException(status_code=400, detail="Only .wav files supported")

    tmp_dir = Path("/tmp/bee-uploads")
    tmp_dir.mkdir(exist_ok=True)
    wav_path = tmp_dir / f"{datetime.now(timezone.utc).isoformat()}-{audio.filename}"

    with open(wav_path, "wb") as f:
        f.write(await audio.read())

    try:
        transcript = transcribe(wav_path)
        llm_result = ask_ollama(transcript)

        db = next(get_db())
        conv = Conversation(
            device_id=device_id,
            transcript=transcript,
            summary=llm_result["summary"],
            todos=json.dumps(llm_result["todos"]),
            raw_llm_response=llm_result["raw"],
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
        db.close()

        return UploadResponse(
            conversation_id=conv.id,
            transcript=transcript,
            summary=llm_result["summary"],
            todos=llm_result["todos"],
        )
    finally:
        wav_path.unlink(missing_ok=True)


@app.get("/conversations")
async def list_conversations(limit: int = 50, device_id: Optional[str] = None):
    db = next(get_db())
    query = db.query(Conversation)
    if device_id:
        query = query.filter(Conversation.device_id == device_id)
    rows = query.order_by(Conversation.created_at.desc()).limit(limit).all()
    db.close()
    return [
        {
            "id": r.id,
            "device_id": r.device_id,
            "created_at": r.created_at.isoformat(),
            "transcript": r.transcript,
            "summary": r.summary,
            "todos": json.loads(r.todos or "[]"),
        }
        for r in rows
    ]


@app.get("/health")
async def health():
    return {"status": "ok", "ollama_model": OLLAMA_MODEL, "whisper_model": WHISPER_MODEL}


# Optional static dashboard
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

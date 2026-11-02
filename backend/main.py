"""
FastAPI backend for the Ollama Bee Device.
- Receives WAV chunks from the device
- Transcribes with faster-whisper (local)
- Sends transcript to Ollama for summary/to-do extraction
- Stores conversations in SQLite
- Serves a dashboard for device onboarding and transcript review
"""
import os
import json
import secrets
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import requests
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from faster_whisper import WhisperModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

app = FastAPI(title="Ollama Bee Backend")
security = HTTPBearer(auto_error=False)

# Config
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "kimi-k2.7-code:cloud")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
API_KEY_HEADER = os.getenv("BEE_API_KEY_HEADER", "Authorization")

# Security
MAX_UPLOAD_BYTES = int(os.getenv("BEE_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))  # 20 MB
MAX_DEVICES = int(os.getenv("BEE_MAX_DEVICES", "50"))
RATE_LIMIT_SECONDS = float(os.getenv("BEE_RATE_LIMIT_SECONDS", "5"))
ADMIN_TOKEN = os.getenv("BEE_ADMIN_TOKEN", "")

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
    todos = Column(Text, nullable=True)
    raw_llm_response = Column(Text, nullable=True)


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, index=True)
    name = Column(String, nullable=True)
    api_key_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(DateTime, nullable=True)
    enabled = Column(Integer, default=1)


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


class OnboardRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    name: Optional[str] = Field(None, max_length=128)


class OnboardResponse(BaseModel):
    device_id: str
    api_key: str


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)

def _extract_token(request: Request, credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    # FastAPI HTTPBearer strips the scheme; also accept raw header value.
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token
    raw = request.headers.get("authorization") or request.headers.get("Authorization", "")
    if raw:
        raw = raw.strip()
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
        return raw
    return ""


def _require_admin(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Admin token not configured")
    if _extract_token(request, credentials) != ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    return True


def _require_device(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), db: SessionLocal = Depends(get_db)):
    key = _extract_token(request, credentials)
    if not key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    key_hash = _hash_key(key)
    device = db.query(Device).filter(Device.api_key_hash == key_hash, Device.enabled == 1).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or disabled API key")
    device.last_seen_at = _now()
    db.commit()
    return device


def _rate_limit(request: Request, device: Device = Depends(_require_device)):
    # Simple in-memory per-device rate limit
    now = _now()
    last = getattr(app.state, "rate_limit_cache", {})
    key = device.device_id
    last_time = last.get(key)
    if last_time and (now - last_time).total_seconds() < RATE_LIMIT_SECONDS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    last[key] = now
    app.state.rate_limit_cache = last
    return device


def transcribe(path: Path) -> str:
    segments, _ = whisper_model.transcribe(str(path), language="en", beam_size=5)
    return " ".join([seg.text.strip() for seg in segments]).strip()


def ask_ollama(transcript: str) -> dict:
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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.post("/api/v1/onboard", response_model=OnboardResponse, dependencies=[Depends(_require_admin)])
async def onboard_device(req: OnboardRequest, db: SessionLocal = Depends(get_db)):
    if db.query(Device).count() >= MAX_DEVICES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Maximum {MAX_DEVICES} devices reached")
    existing = db.query(Device).filter(Device.device_id == req.device_id).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device already exists")
    api_key = "bee_" + secrets.token_urlsafe(32)
    device = Device(
        device_id=req.device_id,
        name=req.name,
        api_key_hash=_hash_key(api_key),
    )
    db.add(device)
    db.commit()
    return OnboardResponse(device_id=req.device_id, api_key=api_key)


@app.get("/api/v1/devices", dependencies=[Depends(_require_admin)])
async def list_devices(db: SessionLocal = Depends(get_db)):
    rows = db.query(Device).order_by(Device.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "device_id": r.device_id,
            "name": r.name,
            "enabled": bool(r.enabled),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
        }
        for r in rows
    ]


@app.post("/api/v1/devices/{device_id}/rotate", dependencies=[Depends(_require_admin)])
async def rotate_device_key(device_id: str, db: SessionLocal = Depends(get_db)):
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    api_key = "bee_" + secrets.token_urlsafe(32)
    device.api_key_hash = _hash_key(api_key)
    db.commit()
    return {"device_id": device_id, "api_key": api_key}


@app.post("/api/v1/devices/{device_id}/toggle", dependencies=[Depends(_require_admin)])
async def toggle_device(device_id: str, db: SessionLocal = Depends(get_db)):
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    device.enabled = 0 if device.enabled else 1
    db.commit()
    return {"device_id": device_id, "enabled": bool(device.enabled)}


@app.post("/api/v1/upload", response_model=UploadResponse)
async def upload_audio(
    request: Request,
    audio: UploadFile = File(...),
    device_id: str = Form("unknown"),
    device: Device = Depends(_rate_limit),
):
    if not audio.filename.endswith(".wav"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .wav files supported")

    body = await audio.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Max upload size is {MAX_UPLOAD_BYTES} bytes")

    tmp_dir = Path("/tmp/bee-uploads")
    tmp_dir.mkdir(exist_ok=True)
    wav_path = tmp_dir / f"{_now().isoformat()}-{audio.filename}"

    with open(wav_path, "wb") as f:
        f.write(body)

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


@app.get("/api/v1/conversations")
async def list_conversations(limit: int = 50, device_id: Optional[str] = None, db: SessionLocal = Depends(get_db)):
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


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "ollama_model": OLLAMA_MODEL, "whisper_model": WHISPER_MODEL, "version": "1.1.0"}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    dashboard_path = Path(__file__).parent / "static" / "dashboard.html"
    if dashboard_path.exists():
        return HTMLResponse(content=dashboard_path.read_text())
    return HTMLResponse(content="<h1>Dashboard not found</h1>")


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

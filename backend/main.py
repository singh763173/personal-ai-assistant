"""
FastAPI backend for the Ollama Bee Device.
- Receives WAV chunks from the device
- Transcribes with faster-whisper (local)
- Sends transcript to Ollama for summary/to-do extraction
- Stores conversations in SQLite
- Serves a dashboard for device onboarding and transcript review
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
import requests
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from faster_whisper import WhisperModel
from jose import JWTError, jwt
from models import Base, Conversation, Device
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

app = FastAPI(title="Ollama Bee Backend")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
    return HTMLResponse(
        status_code=exc.status_code,
        content=f"""<!DOCTYPE html>
<html><head><title>{exc.status_code}</title></head>
<body style="font-family:system-ui; background:#0f172a; color:#e2e8f0; padding:2rem;">
<h1>{exc.status_code}</h1>
<p>{exc.detail}</p>
</body></html>""",
        headers=exc.headers,
    )


security = HTTPBearer(auto_error=False)

# Config
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "kimi-k2.7-code:cloud")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "moondream:latest")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_URL = os.getenv("WHISPER_URL", "")  # e.g. http://192.168.1.86:8001/transcribe
WHISPER_API_KEY = os.getenv("WHISPER_API_KEY", "")
WHISPER_LOCAL = not WHISPER_URL

# TTS config
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "edge").lower()
PIPER_VOICE_MODEL = os.getenv("PIPER_VOICE_MODEL", "/opt/bee-backend/voices/en_US-amy-medium.onnx")


ADMIN_USERNAME = os.getenv("BEE_ADMIN_USERNAME", "")
ADMIN_PASSWORD_HASH = os.getenv("BEE_ADMIN_PASSWORD_HASH", "")
SECRET_KEY = os.getenv("BEE_SECRET_KEY", "")
SESSION_COOKIE_NAME = "bee_session"
SESSION_MAX_AGE_HOURS = 7 * 24


# Retry helper for external network calls
def _retry(max_attempts: int = 3, delay: float = 0.5, backoff: float = 2.0, exceptions=(Exception,)):
    def decorator(func):
        def wrapper(*args, **kwargs):
            wait = delay
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    print(f"[retry] {func.__name__} attempt {attempt} failed: {e}; retrying in {wait:.1f}s")
                    time.sleep(wait)
                    wait *= backoff
            raise last_exc

        return wrapper

    return decorator


def _retry_async(max_attempts: int = 3, delay: float = 0.5, backoff: float = 2.0, exceptions=(Exception,)):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            wait = delay
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    print(f"[retry async] {func.__name__} attempt {attempt} failed: {e}; retrying in {wait:.1f}s")
                    await asyncio.sleep(wait)
                    wait *= backoff
            raise last_exc

        return wrapper

    return decorator


# Security
MAX_UPLOAD_BYTES = int(os.getenv("BEE_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
MAX_DEVICES = int(os.getenv("BEE_MAX_DEVICES", "50"))
RATE_LIMIT_SECONDS = float(os.getenv("BEE_RATE_LIMIT_SECONDS", "5"))

if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(32)
    print(f"[WARN] BEE_SECRET_KEY not set; generated one-time key: {SECRET_KEY[:8]}...")

# Database
DB_PATH = Path(__file__).parent / "bee.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(bind=engine)

# Load models
if WHISPER_LOCAL:
    print(f"Loading Whisper model: {WHISPER_MODEL} ({WHISPER_DEVICE}/{WHISPER_COMPUTE})...")
    whisper_model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
    print("Whisper loaded.")
else:
    print(f"Using remote Whisper service at {WHISPER_URL}")
    whisper_model = None


class UploadResponse(BaseModel):
    conversation_id: int
    transcript: str
    summary: str | None = None
    reply: str | None = None
    todos: list[str]
    audio_url: str | None = None


class OnboardRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    name: str | None = Field(None, max_length=128)


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


def _safe_device_id(device_id: str) -> str:
    """Sanitize a device id for use in filenames."""
    return "".join(c for c in device_id if c.isalnum() or c in "-_").rstrip()[:64] or "unknown"


def _now() -> datetime:
    return datetime.now(UTC)


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _create_session_token(username: str) -> str:
    exp = _now() + timedelta(hours=SESSION_MAX_AGE_HOURS)
    return jwt.encode({"sub": username, "exp": exp}, SECRET_KEY, algorithm="HS256")


def _get_session_user(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None


def _extract_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str:
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


def _require_admin_session(request: Request):
    user = _get_session_user(request)
    if user != ADMIN_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _require_device(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: SessionLocal = Depends(get_db),
):
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
    now = _now()
    last = getattr(app.state, "rate_limit_cache", {})
    key = device.device_id
    last_time = last.get(key)
    if last_time and (now - last_time).total_seconds() < RATE_LIMIT_SECONDS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    last[key] = now
    app.state.rate_limit_cache = last
    return device


def _load_local_whisper():
    global whisper_model
    if whisper_model is not None:
        return
    print(f"Loading Whisper model: {WHISPER_MODEL} ({WHISPER_DEVICE}/{WHISPER_COMPUTE})...")
    whisper_model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
    print("Whisper loaded.")


@_retry(max_attempts=2, delay=0.3, backoff=1.5, exceptions=(Exception,))
def transcribe(path: Path) -> str:
    if WHISPER_LOCAL:
        _load_local_whisper()
        segments, _ = whisper_model.transcribe(str(path), language="en", beam_size=1)
        return " ".join([seg.text.strip() for seg in segments]).strip()

    # Remote Whisper service on the LAN
    try:
        with open(path, "rb") as f:
            files = {"audio": (path.name, f, "audio/wav")}
            headers = {"Authorization": WHISPER_API_KEY} if WHISPER_API_KEY else {}
            resp = requests.post(WHISPER_URL, files=files, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.json().get("transcript", "")
    except Exception as e:
        print(f"Remote Whisper failed: {e}; falling back to local")
        _load_local_whisper()
        segments, _ = whisper_model.transcribe(str(path), language="en", beam_size=1)
        return " ".join([seg.text.strip() for seg in segments]).strip()
        return " ".join([seg.text.strip() for seg in segments]).strip()


@_retry(max_attempts=3, delay=0.5, backoff=2.0, exceptions=(Exception,))
def ask_ollama(transcript: str) -> dict:
    """Legacy summary/to-do extraction. Kept for /api/v1/upload compatibility."""
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
        if not raw or not raw.strip():
            return {"summary": "No response from model", "todos": [], "type": "empty", "raw": raw}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`").strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
            parsed = json.loads(cleaned)
        return {
            "summary": parsed.get("summary", ""),
            "todos": parsed.get("todos", []),
            "type": parsed.get("type", "unknown"),
            "raw": raw,
        }
    except Exception as e:
        return {"summary": f"LLM error: {e}", "todos": [], "type": "error", "raw": str(e)}


@_retry(max_attempts=3, delay=0.5, backoff=2.0, exceptions=(Exception,))
def ask_llm(transcript: str) -> str:
    """Send transcript to a conversational LLM and return a spoken reply."""
    now = datetime.now(UTC).strftime("%H:%M:%S UTC on %A, %d %B %Y")
    prompt = f"""You are a helpful voice assistant in a wearable device. The user just spoke to you.
Current date and time: {now}.

User: {transcript}

Reply as if speaking aloud. Keep it concise (1-3 sentences), friendly, and clear. Do not include markdown or lists."""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.7, "num_ctx": 4096},
    }
    try:
        r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        return data.get("response", "").strip()
    except Exception as e:
        return f"Sorry, I couldn't get a response right now. Error: {e}"


@_retry(max_attempts=3, delay=0.5, backoff=2.0, exceptions=(Exception,))
def ask_vision_llm(transcript: str, image_base64: str) -> str:
    """Send image + transcript to a vision model and return a spoken reply."""
    now = datetime.now(UTC).strftime("%H:%M:%S UTC on %A, %d %B %Y")
    prompt = f"""You are a helpful voice assistant in a wearable camera. The user took a photo and asked you about it.
Current date and time: {now}.

User question: {transcript}

Describe what you see in the image and answer the question. Reply as if speaking aloud. Keep it concise (2-4 sentences), clear, and friendly."""

    payload = {
        "model": OLLAMA_VISION_MODEL,
        "prompt": prompt,
        "stream": False,
        "images": [image_base64],
        "options": {"temperature": 0.7, "num_ctx": 4096},
    }
    try:
        r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=180)
        r.raise_for_status()
        data = r.json()
        return data.get("response", "").strip()
    except Exception as e:
        return f"Sorry, I couldn't analyze the image right now. Error: {e}"


@_retry_async(max_attempts=3, delay=0.5, backoff=2.0, exceptions=(Exception,))
async def text_to_speech(text: str, out_path: Path) -> bool:
    """Generate audio from text. Supports edge-tts (MP3) and piper-tts (WAV)."""
    try:
        if TTS_PROVIDER == "piper":
            import io
            import os
            import subprocess as sp
            import wave

            from piper import PiperVoice

            # Constrain ONNX threads before loading the session
            os.environ.setdefault("OMP_NUM_THREADS", "1")
            os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
            voice = PiperVoice.load(PIPER_VOICE_MODEL)
            # Suppress verbose ONNX logs
            import onnxruntime as ort

            ort.set_default_logger_severity(3)
            from piper.voice import SynthesisConfig

            syn_config = SynthesisConfig(
                length_scale=1.0,
                noise_scale=0.667,
                noise_w_scale=0.333,
                speaker_id=0,
            )
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(22050)
                voice.synthesize_wav(text, w, syn_config=syn_config)
            wav_bytes = buf.getvalue()
            tmp_wav = out_path.with_suffix(".wav")
            tmp_wav.write_bytes(wav_bytes)
            sp.run(
                ["ffmpeg", "-y", "-i", str(tmp_wav), "-b:a", "64k", str(out_path)],
                stdout=sp.DEVNULL,
                stderr=sp.DEVNULL,
                check=True,
            )
            tmp_wav.unlink(missing_ok=True)
            return out_path.exists() and out_path.stat().st_size > 0
        else:
            import edge_tts

            communicate = edge_tts.Communicate(text, "en-GB-SoniaNeural")
            await communicate.save(str(out_path))
            return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        print(f"TTS failed: {e}")
        return False


async def _generate_tts(conversation_id: int, text: str) -> str:
    """Generate TTS audio for a reply and return the relative URL."""
    if not text:
        return ""
    out_dir = Path(__file__).parent / "audio_replies"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{conversation_id}.mp3"
    success = await text_to_speech(text, out_path)
    if success:
        return f"/api/v1/audio/{conversation_id}.mp3"
    return ""


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.middleware("http")
async def admin_gate(request: Request, call_next):
    """Require admin session for all browser-facing and admin endpoints.

    Publicly accessible:
      - /api/v1/health       (uptime probe)
      - /api/v1/upload       (wearable devices via API key)
      - /login               (login form/page)
      - /api/v1/login        (login submission)
    Everything else requires an authenticated session.
    """
    path = request.url.path
    public_paths = {
        "/api/v1/health",
        "/api/v1/upload",
        "/api/v1/upload-image",
        "/api/v1/ask",
        "/api/v1/audio",
        "/api/v1/metrics",
        "/login",
        "/api/v1/login",
    }
    if any(path == p or path.startswith(p + "/") for p in public_paths):
        return await call_next(request)

    # Static assets are only served after authentication below.
    user = _get_session_user(request)
    if user != ADMIN_USERNAME:
        if request.headers.get("accept", "").startswith("application/json"):
            return JSONResponse(
                status_code=401, content={"detail": "Login required"}, headers={"WWW-Authenticate": "Bearer"}
            )
        return RedirectResponse(url="/login", status_code=302)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    login_path = Path(__file__).parent / "static" / "login.html"
    if login_path.exists():
        return HTMLResponse(content=login_path.read_text())
    return HTMLResponse(
        content="""<!DOCTYPE html>
<html><head><title>Login</title></head>
<body style="font-family:system-ui; background:#0f172a; color:#e2e8f0; padding:2rem;">
<h1>Login</h1>
<form method="post" action="/api/v1/login">
<input name="username" placeholder="Username" style="padding:0.5rem; margin:0.25rem;" required><br>
<input name="password" type="password" placeholder="Password" style="padding:0.5rem; margin:0.25rem;" required><br>
<button type="submit" style="padding:0.5rem 1rem; margin:0.25rem;">Login</button>
</form>
</body></html>"""
    )


# Simple in-memory brute-force protection for admin login
_login_attempts: dict[str, tuple[int, float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300


def _check_login_rate(client_ip: str) -> bool:
    now = time.time()
    count, locked_until = _login_attempts.get(client_ip, (0, 0.0))
    if now < locked_until:
        return False
    if now - locked_until > LOGIN_LOCKOUT_SECONDS and count >= MAX_LOGIN_ATTEMPTS:
        # reset after lockout expires
        _login_attempts[client_ip] = (0, 0.0)
    return True


def _record_login_failure(client_ip: str):
    count, _ = _login_attempts.get(client_ip, (0, 0.0))
    count += 1
    locked_until = time.time() + LOGIN_LOCKOUT_SECONDS if count >= MAX_LOGIN_ATTEMPTS else 0.0
    _login_attempts[client_ip] = (count, locked_until)


@app.post("/api/v1/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    client_ip = request.client.host if request.client else "unknown"
    if not _check_login_rate(client_ip):
        return RedirectResponse(url="/login?error=Too+many+failed+attempts.+Try+again+in+5+minutes.", status_code=302)
    if not ADMIN_USERNAME or not ADMIN_PASSWORD_HASH:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Admin credentials not configured")
    if username != ADMIN_USERNAME or not _verify_password(password, ADMIN_PASSWORD_HASH):
        _record_login_failure(client_ip)
        return RedirectResponse(url="/login?error=Invalid+username+or+password", status_code=302)
    token = _create_session_token(username)
    response = RedirectResponse(url="/dashboard", status_code=302)
    secure_cookie = request.url.scheme == "https"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=SESSION_MAX_AGE_HOURS * 3600,
    )
    return response


@app.post("/api/v1/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return RedirectResponse(url="/login", status_code=302)


@app.post("/api/v1/onboard", response_model=OnboardResponse, dependencies=[Depends(_require_admin_session)])
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


@app.get("/api/v1/devices", dependencies=[Depends(_require_admin_session)])
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


@app.post("/api/v1/devices/{device_id}/rotate", dependencies=[Depends(_require_admin_session)])
async def rotate_device_key(device_id: str, db: SessionLocal = Depends(get_db)):
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    api_key = "bee_" + secrets.token_urlsafe(32)
    device.api_key_hash = _hash_key(api_key)
    db.commit()
    return {"device_id": device_id, "api_key": api_key}


@app.post("/api/v1/devices/{device_id}/toggle", dependencies=[Depends(_require_admin_session)])
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
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Max upload size is {MAX_UPLOAD_BYTES} bytes"
        )

    tmp_dir = Path("/tmp/bee-uploads")
    tmp_dir.mkdir(exist_ok=True)
    wav_path = tmp_dir / f"{_now().strftime('%Y%m%d-%H%M%S-%f')}-{_safe_device_id(device_id)}-{audio.filename}"

    with open(wav_path, "wb") as f:
        f.write(body)

    db = next(get_db())
    try:
        transcript = transcribe(wav_path)
        llm_result = ask_ollama(transcript)

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

        return UploadResponse(
            conversation_id=conv.id,
            transcript=transcript,
            summary=llm_result["summary"],
            todos=llm_result["todos"],
        )
    finally:
        db.close()
        wav_path.unlink(missing_ok=True)


@app.post("/api/v1/ask", response_model=UploadResponse)
async def ask_endpoint(
    request: Request,
    audio: UploadFile = File(...),
    image: UploadFile | None = File(None),
    device_id: str = Form("unknown"),
    device: Device = Depends(_rate_limit),
):
    """Voice (and optional vision) Q&A endpoint. Returns transcript + spoken reply + audio URL."""
    if not audio.filename.endswith(".wav"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .wav files supported")

    audio_body = await audio.read()
    if len(audio_body) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Max upload size is {MAX_UPLOAD_BYTES} bytes"
        )

    tmp_dir = Path("/tmp/bee-uploads")
    tmp_dir.mkdir(exist_ok=True)
    wav_path = tmp_dir / f"{_now().strftime('%Y%m%d-%H%M%S-%f')}-{_safe_device_id(device_id)}-{audio.filename}"
    image_path = None
    image_b64 = None

    with open(wav_path, "wb") as f:
        f.write(audio_body)

    try:
        if image and image.filename:
            img_ext = Path(image.filename).suffix.lower()
            if img_ext not in (".jpg", ".jpeg", ".png"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Only .jpg/.jpeg/.png images supported"
                )
            img_body = await image.read()
            if len(img_body) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Max image size is {MAX_UPLOAD_BYTES} bytes",
                )
            image_path = (
                tmp_dir / f"{_now().strftime('%Y%m%d-%H%M%S-%f')}-{_safe_device_id(device_id)}-{image.filename}"
            )
            with open(image_path, "wb") as f:
                f.write(img_body)
            image_b64 = base64.b64encode(img_body).decode("utf-8")

        transcript = transcribe(wav_path)

        reply = ask_vision_llm(transcript, image_b64) if image_b64 else ask_llm(transcript)

        # Generate spoken reply
        audio_dir = Path(__file__).parent / "audio_replies"
        audio_dir.mkdir(exist_ok=True)
        mp3_path = audio_dir / f"{_now().strftime('%Y%m%d-%H%M%S-%f')}-{device_id}.mp3"
        tts_ok = await text_to_speech(reply, mp3_path)

        db = next(get_db())
        try:
            conv = Conversation(
                device_id=device_id,
                transcript=transcript,
                summary="",
                reply=reply,
                todos=json.dumps([]),
                raw_llm_response=reply,
                image_path=str(image_path) if image_path else None,
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)

            # Rename MP3 to use conversation id for easy serving
            final_mp3_path = audio_dir / f"{conv.id}.mp3"
            if tts_ok:
                mp3_path.rename(final_mp3_path)
            else:
                final_mp3_path = None

            audio_url = f"/api/v1/audio/{conv.id}.mp3" if final_mp3_path and final_mp3_path.exists() else None

            return UploadResponse(
                conversation_id=conv.id,
                transcript=transcript,
                summary="",
                reply=reply,
                todos=[],
                audio_url=audio_url,
            )
        finally:
            db.close()
    finally:
        wav_path.unlink(missing_ok=True)


@app.get("/api/v1/audio/{conversation_id}.mp3")
async def get_audio_reply(conversation_id: int):
    audio_path = Path(__file__).parent / "audio_replies" / f"{conversation_id}.mp3"
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio reply not found")
    return FileResponse(audio_path, media_type="audio/mpeg", filename=f"reply-{conversation_id}.mp3")


@app.get("/api/v1/conversations", dependencies=[Depends(_require_admin_session)])
async def list_conversations(limit: int = 50, device_id: str | None = None, db: SessionLocal = Depends(get_db)):
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
            "reply": r.reply,
            "audio_url": f"/api/v1/audio/{r.id}.mp3" if r.reply else None,
            "todos": json.loads(r.todos or "[]"),
        }
        for r in rows
    ]


@app.post("/api/v1/upload-image", response_model=UploadResponse)
async def upload_image(
    request: Request,
    image: UploadFile = File(...),
    device_id: str = Form("unknown"),
    device: Device = Depends(_rate_limit),
):
    """Vision-only endpoint: describe what the camera sees and reply with spoken audio."""
    tmp_dir = Path("/tmp/bee-uploads")
    tmp_dir.mkdir(exist_ok=True)
    img_path = tmp_dir / f"{_now().strftime('%Y%m%d-%H%M%S-%f')}-{_safe_device_id(device_id)}-{image.filename}"

    body = await image.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Max upload size is {MAX_UPLOAD_BYTES} bytes"
        )

    with open(img_path, "wb") as f:
        f.write(body)

    transcript = "[image]"
    try:
        img_b64 = base64.b64encode(Path(img_path).read_bytes()).decode("utf-8")
        reply = ask_vision_llm(transcript, img_b64)
    except Exception as e:
        reply = f"Sorry, I couldn't analyze the image right now. Error: {e}"

    db = next(get_db())
    try:
        conv = Conversation(
            device_id=device_id,
            transcript=transcript,
            summary="",
            reply=reply,
            todos=json.dumps([]),
            raw_llm_response="",
            image_path=str(img_path),
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

        # Generate TTS audio
        audio_rel_path = await _generate_tts(conv.id, reply)

        return UploadResponse(
            conversation_id=conv.id,
            transcript=transcript,
            summary="",
            reply=reply,
            todos=[],
            audio_url=audio_rel_path,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
def _cleanup_old_files():
    """Remove stale temp uploads and audio replies beyond retention."""
    now = time.time()
    retention_seconds = 7 * 24 * 3600  # 7 days for audio replies
    temp_retention_seconds = 24 * 3600  # 1 day for /tmp uploads

    # Clean /tmp/bee-uploads
    tmp_dir = Path("/tmp/bee-uploads")
    if tmp_dir.exists():
        for p in tmp_dir.iterdir():
            try:
                if p.is_file() and (now - p.stat().st_mtime) > temp_retention_seconds:
                    p.unlink()
            except Exception as e:
                print(f"Cleanup temp failed for {p}: {e}")

    # Clean audio_replies older than retention
    audio_dir = Path(__file__).parent / "audio_replies"
    if audio_dir.exists():
        for p in audio_dir.iterdir():
            try:
                if p.is_file() and (now - p.stat().st_mtime) > retention_seconds:
                    p.unlink()
            except Exception as e:
                print(f"Cleanup audio failed for {p}: {e}")


@app.middleware("http")
async def cleanup_middleware(request: Request, call_next):
    # Run cleanup infrequently (every ~100 requests) to avoid overhead
    if getattr(app.state, "request_count", 0) % 100 == 0:
        _cleanup_old_files()
    app.state.request_count = getattr(app.state, "request_count", 0) + 1
    return await call_next(request)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
async def _require_admin_or_device(
    request: Request,
    user: str | None = Depends(_require_admin_session),
    device: Device | None = Depends(_require_device),
):
    """Allow either a logged-in admin or an authenticated device to view metrics."""
    if user or device:
        return user or device
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")


@app.get("/api/v1/metrics", dependencies=[Depends(_require_admin_or_device)])
async def metrics(db: SessionLocal = Depends(get_db)):
    """Basic operational metrics for the backend."""
    conv_count = db.query(Conversation).count()
    device_count = db.query(Device).count()
    audio_dir = Path(__file__).parent / "audio_replies"
    audio_size = sum(f.stat().st_size for f in audio_dir.iterdir() if f.is_file()) if audio_dir.exists() else 0
    db_size = Path(__file__).parent.joinpath("bee.db").stat().st_size
    whisper_healthy = False
    try:
        if WHISPER_URL:
            headers = {"Authorization": WHISPER_API_KEY} if WHISPER_API_KEY else {}
            r = requests.get(f"{WHISPER_URL.replace('/transcribe', '/health')}", headers=headers, timeout=5)
            whisper_healthy = r.status_code == 200
    except Exception:
        pass
    return {
        "conversations": conv_count,
        "devices": device_count,
        "audio_replies_bytes": audio_size,
        "database_bytes": db_size,
        "request_count": getattr(app.state, "request_count", 0),
        "whisper_healthy": whisper_healthy,
        "timestamp": _now().isoformat(),
    }


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "ollama_model": OLLAMA_MODEL, "whisper_model": WHISPER_MODEL, "version": "1.2.0"}


@app.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(_require_admin_session)])
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

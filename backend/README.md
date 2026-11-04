# Ollama Bee Backend Setup

## Run locally (testing)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export OLLAMA_URL=http://localhost:11434
export OLLAMA_MODEL=kimi-k2.7-code:cloud
export OLLAMA_VISION_MODEL=moondream:latest
export WHISPER_URL=http://192.168.1.86:8001/transcribe  # optional LAN Whisper service
export WHISPER_API_KEY=your-shared-secret                # if Whisper service requires auth
export WHISPER_MODEL=base
export WHISPER_DEVICE=cpu
export BEE_ADMIN_USERNAME=admin
export BEE_ADMIN_PASSWORD_HASH='$2b$12$...'  # bcrypt hash
export BEE_SECRET_KEY=$(openssl rand -hex 32)

uvicorn main:app --host 0.0.0.0 --port 8000
```

## Pi Device Setup

Flash Raspberry Pi OS Lite (64-bit), enable SSH, then run the one-shot installer on the Pi:

```bash
curl -fsSL https://raw.githubusercontent.com/singh763173/personal-ai-assistant/main/firmware/install.sh | sudo bash
```

The installer will:
- Install the PiSugar Whisplay HAT driver
- Install the PiSugar power manager for battery monitoring
- Enable I2C and Camera Module 3 overlay
- Create a Python virtual environment with the firmware dependencies
- Configure and enable the `bee-device` systemd service

## Run as a systemd service on Proxmox VM / LXC / AIServer01

1. Create a dedicated user and directory:

```bash
sudo useradd -r -s /bin/false bee-backend
sudo mkdir -p /opt/bee-backend
sudo chown bee-backend:bee-backend /opt/bee-backend
```

2. Copy `backend/` contents to `/opt/bee-backend`.

3. Create `/opt/bee-backend/.env`:

```ini
OLLAMA_URL=http://192.168.1.86:11434
OLLAMA_MODEL=kimi-k2.7-code:cloud
OLLAMA_VISION_MODEL=moondream:latest
WHISPER_URL=http://192.168.1.86:8001/transcribe
WHISPER_API_KEY=your-shared-secret
WHISPER_MODEL=base
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
BEE_ADMIN_USERNAME=admin
BEE_ADMIN_PASSWORD_HASH=$2b$12$...
BEE_SECRET_KEY=...
```

4. Create `/etc/systemd/system/bee-backend.service`:

```ini
[Unit]
Description=Bee Pioneer Backend
After=network.target

[Service]
Type=simple
User=bee-backend
WorkingDirectory=/opt/bee-backend
EnvironmentFile=/opt/bee-backend/.env
ExecStart=/opt/bee-backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

5. Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bee-backend
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `kimi-k2.7-code:cloud` | Model for voice Q&A |
| `OLLAMA_VISION_MODEL` | `moondream:latest` | Model for vision Q&A |
| `WHISPER_URL` | `""` | Optional LAN Whisper service URL |
| `WHISPER_API_KEY` | `""` | Shared secret for the Whisper service |
| `WHISPER_MODEL` | `base` | faster-whisper model size if running locally |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8`, `float16`, `int8_float16` |
| `BEE_ADMIN_USERNAME` | `""` | Dashboard username |
| `BEE_ADMIN_PASSWORD_HASH` | `""` | bcrypt hash of dashboard password |
| `BEE_SECRET_KEY` | random | JWT session signing key |

## API Endpoints

- `POST /api/v1/ask` — voice Q&A (device). Returns transcript, reply, and audio URL.
- `POST /api/v1/upload-image` — vision-only request (device).
- `POST /api/v1/upload` — legacy transcript summary/to-do (device).
- `GET /api/v1/conversations` — list conversations (admin session).
- `POST /api/v1/onboard` — create device API key (admin session).
- `GET /api/v1/audio/{id}.mp3` — play spoken reply.
- `GET /api/v1/health` — health check.
- `GET /dashboard` — admin dashboard.

## Notes

- First upload will be slow as faster-whisper downloads the model.
- For better accuracy at the cost of RAM/CPU, use `small` or `medium`.
- If you run out of RAM on a small VM, use `tiny` or `base`.
- Transcription happens on the LAN Whisper service (or locally if `WHISPER_URL` is empty).

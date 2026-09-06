# Ollama Bee Backend Setup

## Run locally (testing)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Download Whisper model (base ~150 MB)
# faster-whisper downloads automatically on first use

export OLLAMA_URL=http://localhost:11434
export OLLAMA_MODEL=kimi-k2.7-code:cloud
export WHISPER_MODEL=base
export WHISPER_DEVICE=cpu

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
- Prompt for your backend URL and device ID

## Run as a systemd service on Proxmox VM / LXC / AIServer01

1. Create a dedicated user and directory:

```bash
sudo useradd -r -s /bin/false bee-backend
sudo mkdir -p /opt/bee-backend
sudo chown bee-backend:bee-backend /opt/bee-backend
```

2. Copy `backend/` contents to `/opt/bee-backend`.

3. Create `/etc/systemd/system/bee-backend.service`:

```ini
[Unit]
Description=Bee Pioneer Backend
After=network.target

[Service]
Type=simple
User=bee-backend
WorkingDirectory=/opt/bee-backend
Environment=OLLAMA_URL=http://localhost:11434
Environment=OLLAMA_MODEL=kimi-k2.7-code:cloud
Environment=WHISPER_MODEL=base
Environment=WHISPER_DEVICE=cpu
Environment=WHISPER_COMPUTE_TYPE=int8
ExecStart=/opt/bee-backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

4. Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bee-backend
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `kimi-k2.7-code:cloud` | Model for summary/to-do extraction |
| `WHISPER_MODEL` | `base` | faster-whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8`, `float16`, `int8_float16` |

For GPU inference, set `WHISPER_DEVICE=cuda WHISPER_COMPUTE_TYPE=float16`.

## API Endpoints

- `POST /upload` — receive `.wav` from device, return transcript + summary + to-dos
- `GET /conversations` — list stored conversations
- `GET /health` — health check

## Notes

- First upload will be slow as faster-whisper downloads the model.
- For better accuracy at the cost of RAM/CPU, use `small` or `medium`.
- If you run out of RAM on a small VM, use `tiny` or `base`.
- Transcription happens locally on the backend. Only the transcript is sent to the cloud LLM via Ollama.

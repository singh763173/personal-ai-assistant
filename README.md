# Ollama Bee Device

A self-hosted, wearable AI companion that streams audio to a local backend for transcription (faster-whisper) and sends the transcript to Ollama for summarization and action extraction.

**Default LLM:** `kimi-k2.7-code:cloud` via Ollama (cloud-hosted Kimi).  
**Transcription:** `faster-whisper` running locally on the backend.  
**Audio + display + button:** PiSugar Whisplay HAT.  
**Power:** PiSugar 3 battery HAT.  
**Camera:** Raspberry Pi Camera Module 3.

## Hardware Stack

- Raspberry Pi Zero W or Zero 2 W
- PiSugar Whisplay HAT
- PiSugar 3 1200 mAh battery HAT
- Raspberry Pi Camera Module 3
- Raspberry Pi Zero camera adapter cable
- 3D-printed PETG case + lanyard or magnetic badge clip

## Project Structure

```
ollama-bee-device/
├── backend/       FastAPI server + transcription + Ollama integration
├── firmware/      Raspberry Pi device software + one-shot installer
├── hardware/      BOM, build guides, compatibility check, shopping list
├── case/          3D-printable enclosure designs
└── docs/          Build and setup instructions
```

## Quick Start

### 1. Backend

On your Proxmox VM/LXC or AIServer01 host:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

The backend defaults to `OLLAMA_MODEL=kimi-k2.7-code:cloud`.

### 2. Pi Device

Flash Raspberry Pi OS Lite (64-bit), enable SSH, then run:

```bash
curl -fsSL https://raw.githubusercontent.com/singh763173/ollama-bee-device/main/firmware/install.sh | sudo bash
```

The installer will:
- Install the PiSugar Whisplay HAT driver
- Install the PiSugar power manager for battery monitoring
- Enable I2C and Camera Module 3 overlay
- Create a Python virtual environment with the firmware dependencies
- Configure and enable the `bee-device` systemd service
- Prompt for your backend URL and device ID

### 3. Use

| Gesture | Action |
|---------|--------|
| Single click | Toggle mute / recording |
| Double click | Capture and upload a photo |
| Long press | Safe shutdown |

View conversations:

```bash
curl http://YOUR_BACKEND_IP:8000/conversations
```

## Privacy

Audio is transcribed locally on your backend. Only the text transcript is sent to the cloud LLM via Ollama. No audio recordings leave your network unless you choose a cloud transcription provider.

## Documentation

- `hardware/BUILD_GUIDE_WHISPLAY.md` — full hardware build guide
- `hardware/HARDWARE_COMPATIBILITY.md` — BOM and compatibility matrix
- `hardware/SHOPPING_LIST.md` — product links to buy everything
- `backend/README.md` — backend setup and deployment
- `firmware/install.sh` — one-shot Pi setup script

## License

MIT

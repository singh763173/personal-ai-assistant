#!/bin/bash
#
# One-shot setup script for the Ollama Bee Device (PiSugar Whisplay HAT + PiSugar 3 + Camera Module 3).
# Run on a fresh Raspberry Pi OS Lite (64-bit) install on a Pi Zero W / Zero 2 W.
#
# What this does:
#   - Installs system dependencies (alsa, i2c, libcamera, ffmpeg, etc.)
#   - Installs the PiSugar Whisplay HAT driver
#   - Installs the PiSugar power manager for battery monitoring
#   - Enables I2C and camera overlays
#   - Creates a Python venv with project dependencies
#   - Downloads the firmware files from GitHub if not already present
#   - Configures and enables the bee-device systemd service
#   - Prompts for the backend URL
#   - Uses the Kimi k2.7-code:cloud model via Ollama
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/YOUR_REPO/main/install.sh | sudo bash
#   OR
#   sudo bash install.sh
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_DIR="/opt/bee-device"
BACKEND_URL="${BEE_BACKEND_URL:-http://192.168.1.86:8000}"
DEVICE_ID="${BEE_DEVICE_ID:-bee-pioneer-01}"
OLLAMA_MODEL="${OLLAMA_MODEL:-kimi-k2.7-code:cloud}"
GITHUB_REPO="${BEE_GITHUB_REPO:-https://github.com/singh763173/ollama-bee-device}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root. Try: sudo bash install.sh"
    exit 1
fi

log_info "Ollama Bee Device one-shot installer"
log_info "Target directory: $PROJECT_DIR"
log_info "Default backend: $BACKEND_URL"
log_info "Default Ollama model: $OLLAMA_MODEL"

# Ask for backend URL
read -rp "Enter backend URL [$BACKEND_URL]: " input_backend
BACKEND_URL="${input_backend:-$BACKEND_URL}"

# Ask for device ID
read -rp "Enter device ID [$DEVICE_ID]: " input_device
DEVICE_ID="${input_device:-$DEVICE_ID}"

# ---------------------------------------------------------------------------
# 1. Update system
# ---------------------------------------------------------------------------
log_info "Updating system packages..."
apt update
apt full-upgrade -y

# ---------------------------------------------------------------------------
# 2. Install system dependencies
# ---------------------------------------------------------------------------
log_info "Installing system dependencies..."
apt install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    git \
    wget \
    curl \
    i2c-tools \
    libcamera-dev \
    alsa-utils \
    arecord \
    ffmpeg

# ---------------------------------------------------------------------------
# 3. Enable interfaces and camera overlay
# ---------------------------------------------------------------------------
log_info "Configuring /boot/firmware/config.txt..."
CONFIG=/boot/firmware/config.txt

# Enable I2C
if ! grep -q "^dtparam=i2c_arm=on" "$CONFIG"; then
    echo "dtparam=i2c_arm=on" >> "$CONFIG"
fi

# Camera Module 3 overlay
if ! grep -q "^dtoverlay=imx708" "$CONFIG"; then
    echo "dtoverlay=imx708" >> "$CONFIG"
    echo "start_x=1" >> "$CONFIG"
    echo "gpu_mem=128" >> "$CONFIG"
fi

# Optional: disable Bluetooth if you want lower power consumption (uncomment if desired)
# echo "dtoverlay=disable-bt" >> "$CONFIG"

# ---------------------------------------------------------------------------
# 4. Install PiSugar Whisplay HAT driver
# ---------------------------------------------------------------------------
log_info "Installing PiSugar Whisplay HAT driver..."
WHISPLAY_DIR="/tmp/Whisplay"
if [[ -d "$WHISPLAY_DIR" ]]; then
    rm -rf "$WHISPLAY_DIR"
fi
git clone --depth 1 https://github.com/PiSugar/Whisplay.git "$WHISPLAY_DIR"
cd "$WHISPLAY_DIR"
bash install_driver.sh

# ---------------------------------------------------------------------------
# 5. Install PiSugar power manager (battery monitoring)
# ---------------------------------------------------------------------------
log_info "Installing PiSugar power manager..."
if ! command -v pisugar-power-manager &> /dev/null; then
    curl -fsSL https://cdn.pisugar.com/release/Pisugar-power-manager.sh | bash
fi
systemctl enable --now pisugar-server || log_warn "pisugar-server may already be running or needs a reboot"

# ---------------------------------------------------------------------------
# 6. Create project directory and download firmware
# ---------------------------------------------------------------------------
log_info "Setting up project directory: $PROJECT_DIR..."
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# If running from a cloned repo, copy files. Otherwise, download from GitHub.
if [[ -f "${BASH_SOURCE[0]:-$0}" ]] && [[ -d "$(dirname "${BASH_SOURCE[0]:-$0}")/firmware" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
    cp -r "$SCRIPT_DIR/firmware"/* "$PROJECT_DIR/"
    log_info "Copied firmware from local directory."
else
    log_info "Downloading firmware from GitHub..."
    TMP_DIR=$(mktemp -d)
    git clone --depth 1 "$GITHUB_REPO" "$TMP_DIR"
    cp -r "$TMP_DIR/firmware"/* "$PROJECT_DIR/"
    rm -rf "$TMP_DIR"
fi

# ---------------------------------------------------------------------------
# 7. Create Python virtual environment
# ---------------------------------------------------------------------------
log_info "Creating Python virtual environment..."
python3 -m venv "$PROJECT_DIR/venv"
source "$PROJECT_DIR/venv/bin/activate"
pip install --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 8. Configure environment file
# ---------------------------------------------------------------------------
log_info "Writing environment configuration..."
cat > "$PROJECT_DIR/.env" <<EOF
BEE_BACKEND_URL=$BACKEND_URL
BEE_DEVICE_ID=$DEVICE_ID
BEE_CHUNK_SECONDS=30
BEE_SAMPLE_RATE=16000
BEE_AUDIO_CHANNELS=2
BEE_AUDIO_CARD=whisplay-soundcard
BEE_ENABLE_CAMERA=true
BEE_CAMERA_INTERVAL=300
BEE_PISUGAR_API=http://localhost:8423
EOF

# ---------------------------------------------------------------------------
# 9. Create systemd service
# ---------------------------------------------------------------------------
log_info "Creating bee-device systemd service..."
cat > /etc/systemd/system/bee-device.service <<EOF
[Unit]
Description=Bee Pioneer AI Recorder (Whisplay HAT + PiSugar 3)
After=network.target whisplay-daemon.service pisugar-server.service

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/venv/bin/python $PROJECT_DIR/recorder.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bee-device.service

# ---------------------------------------------------------------------------
# 10. Create backend configuration note
# ---------------------------------------------------------------------------
log_info "Writing backend configuration reminder..."
cat > "$PROJECT_DIR/BACKEND_SETUP.md" <<EOF
# Backend Setup Required

The Pi firmware is configured to send audio/images to:

  $BACKEND_URL

You must run the backend on that host. Steps:

1. Copy the 'backend/' directory to the host.
2. Install dependencies:
     python3 -m venv venv
     source venv/bin/activate
     pip install -r requirements.txt
3. Set environment variables:
     export OLLAMA_URL=http://localhost:11434
     export OLLAMA_MODEL=$OLLAMA_MODEL
     export WHISPER_MODEL=base
     export WHISPER_DEVICE=cpu
4. Run:
     uvicorn main:app --host 0.0.0.0 --port 8000

Or use the provided backend/README.md for systemd service setup.
EOF

# ---------------------------------------------------------------------------
# 11. Reboot
# ---------------------------------------------------------------------------
log_info "Installation complete. A reboot is required to load device-tree overlays and drivers."
read -rp "Reboot now? [Y/n]: " reboot_now
reboot_now="${reboot_now:-Y}"
if [[ "$reboot_now" =~ ^[Yy]$ ]]; then
    log_info "Rebooting..."
    reboot
else
    log_warn "Please reboot manually when ready: sudo reboot"
fi

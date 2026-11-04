#!/bin/bash
#
# One-shot setup script for the Personal AI Assistant (PiSugar Whisplay HAT + PiSugar 3 + Camera Module 3).
# Run on a fresh Raspberry Pi OS Lite (64-bit) install on a Pi Zero W / Zero 2 W.
#
# What this does:
#   - Updates system packages
#   - Installs system dependencies (alsa, i2c, libcamera, ffmpeg, etc.)
#   - Installs the PiSugar Whisplay HAT driver
#   - Installs the PiSugar power manager for battery monitoring
#   - Enables I2C, SPI, I2S and camera overlays
#   - Adds the pi user to required hardware groups
#   - Creates a Python venv with project dependencies
#   - Downloads the firmware files from GitHub if not already present
#   - Configures and enables the bee-device systemd service
#
# Environment variables (all optional):
#   BEE_BACKEND_URL   - backend URL (default: http://192.168.1.86:8000)
#   BEE_DEVICE_ID     - device identifier (default: bee-pioneer-01)
#   BEE_GITHUB_REPO   - source repo (default: https://github.com/singh763173/personal-ai-assistant)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/singh763173/personal-ai-assistant/main/firmware/install.sh | sudo bash
#   OR (with custom backend):
#   curl -fsSL ... | sudo BEE_BACKEND_URL=http://192.168.1.10:8000 BEE_DEVICE_ID=bedside-01 bash
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_DIR="/opt/bee-device"
SERVICE_USER="bee-device"
BACKEND_URL="${BEE_BACKEND_URL:-http://192.168.1.86:8000}"
DEVICE_ID="${BEE_DEVICE_ID:-bee-pioneer-01}"
API_KEY="${BEE_API_KEY:-}"
GITHUB_REPO="${BEE_GITHUB_REPO:-https://github.com/singh763173/personal-ai-assistant}"
SKIP_UPDATE="${BEE_SKIP_UPDATE:-0}"

# The PiSugar Whisplay unified driver exposes the ALSA card 'whisplaysound'.
AUDIO_CARD="whisplaysound"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root. Try: sudo bash install.sh"
    exit 1
fi

if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    log_warn "This installer is intended for Raspberry Pi. Continuing anyway..."
fi

log_info "Personal AI Assistant one-shot installer"
log_info "Backend URL:   $BACKEND_URL"
log_info "Device ID:     $DEVICE_ID"
log_info "Source repo:   $GITHUB_REPO"

# ---------------------------------------------------------------------------
# 1. Update system
# ---------------------------------------------------------------------------
if [[ "$SKIP_UPDATE" != "1" ]]; then
  log_step "Updating system packages..."
  apt update
  apt full-upgrade -y
else
  log_info "Skipping system update (BEE_SKIP_UPDATE=1)"
fi

# ---------------------------------------------------------------------------
# 2. Install system dependencies
# ---------------------------------------------------------------------------
log_step "Installing system dependencies..."
apt install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    git \
    wget \
    curl \
    i2c-tools \
    libcamera-dev \
    libcamera-apps-lite \
    alsa-utils \
    ffmpeg \
    linux-headers-rpi-v8 \
    dkms \
    build-essential

# ---------------------------------------------------------------------------
# 3. Enable hardware interfaces
# ---------------------------------------------------------------------------
log_step "Configuring /boot/firmware/config.txt..."
CONFIG=/boot/firmware/config.txt

ensure_config() {
    local key="$1"
    local value="$2"
    if ! grep -q "^${value}" "$CONFIG" 2>/dev/null; then
        echo "$value" >> "$CONFIG"
    fi
}

# Core buses used by Whisplay HAT and PiSugar
ensure_config "dtparam=i2c_arm"  "dtparam=i2c_arm=on"
ensure_config "dtparam=spi"      "dtparam=spi=on"
ensure_config "dtparam=i2s"      "dtparam=i2s=on"

# Camera Module 3
ensure_config "dtoverlay=imx708" "dtoverlay=imx708"

# Legacy camera stack settings (harmless on Bookworm, required on Bullseye)
ensure_config "start_x=1"        "start_x=1"
ensure_config "gpu_mem=128"      "gpu_mem=128"

# ---------------------------------------------------------------------------
# 4. Add pi user to hardware groups
# ---------------------------------------------------------------------------
log_step "Adding 'pi' user to hardware groups..."
for group in gpio i2c spi audio video input; do
    usermod -aG "$group" pi 2>/dev/null || true
done

# ---------------------------------------------------------------------------
# 5. Install PiSugar Whisplay HAT driver
# ---------------------------------------------------------------------------
log_step "Installing PiSugar Whisplay HAT driver..."
WHISPLAY_DIR="/tmp/Whisplay"
rm -rf "$WHISPLAY_DIR"

if ! git clone --depth 1 https://github.com/PiSugar/Whisplay.git "$WHISPLAY_DIR"; then
    log_error "Failed to clone PiSugar/Whisplay repository. Check network."
    exit 1
fi

cd "$WHISPLAY_DIR"
# The installer prompts "Proceed? [y/N]"; pre-answer yes for unattended operation.
if ! bash install_driver.sh <<< "y"; then
    # Accept failure if the card is already configured / will load after reboot
    if aplay -l 2>/dev/null | grep -qi "whisplay" ||        grep -q "^dtoverlay=whisplay-soundcard" /boot/firmware/config.txt 2>/dev/null; then
        log_warn "Whisplay installer returned non-zero, but sound card is configured. Continuing."
    else
        log_error "Whisplay driver installation failed. See output above."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# 6. Install PiSugar power manager (battery monitoring)
# ---------------------------------------------------------------------------
log_step "Installing PiSugar power manager..."
if ! command -v pisugar-power-manager &> /dev/null; then
    if ! curl -fsSL https://cdn.pisugar.com/release/Pisugar-power-manager.sh | bash; then
        log_warn "PiSugar power manager install failed. Battery metrics may not be available."
    fi
fi
systemctl enable --now pisugar-server 2>/dev/null || log_warn "pisugar-server may need a reboot before it starts cleanly"

# ---------------------------------------------------------------------------
# 7. Create project directory and download firmware
# ---------------------------------------------------------------------------
log_step "Setting up project directory: $PROJECT_DIR..."
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
    if ! git clone --depth 1 "$GITHUB_REPO" "$TMP_DIR"; then
        log_error "Failed to clone $GITHUB_REPO"
        exit 1
    fi
    cp -r "$TMP_DIR/firmware"/* "$PROJECT_DIR/"
    rm -rf "$TMP_DIR"
fi

# ---------------------------------------------------------------------------
# 8. Create dedicated service user
# ---------------------------------------------------------------------------
log_step "Creating $SERVICE_USER service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /bin/false -G gpio,i2c,spi,audio,video,input "$SERVICE_USER"
fi
usermod -aG gpio,i2c,spi,audio,video,input "$SERVICE_USER" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 9. Create Python virtual environment
# ---------------------------------------------------------------------------
log_step "Creating Python virtual environment..."
python3 -m venv "$PROJECT_DIR/venv"
source "$PROJECT_DIR/venv/bin/activate"
pip install --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 10. Configure environment file
# ---------------------------------------------------------------------------
log_step "Writing environment configuration..."
cat > "$PROJECT_DIR/.env" <<EOF
BEE_BACKEND_URL=$BACKEND_URL
BEE_DEVICE_ID=$DEVICE_ID
BEE_API_KEY=${API_KEY}
BEE_CHUNK_SECONDS=30
BEE_SAMPLE_RATE=16000
BEE_AUDIO_CHANNELS=2
BEE_AUDIO_CARD=$AUDIO_CARD
BEE_ENABLE_CAMERA=true
BEE_CAMERA_INTERVAL=300
BEE_PISUGAR_API=http://localhost:8423
EOF

chown -R "$SERVICE_USER:$SERVICE_USER" "$PROJECT_DIR"

# ---------------------------------------------------------------------------
# 11. Create systemd service
# ---------------------------------------------------------------------------
log_step "Creating bee-device systemd service..."
cat > /etc/systemd/system/bee-device.service <<EOF
[Unit]
Description=Personal AI Assistant Recorder (Whisplay HAT + PiSugar 3)
After=network.target whisplay-daemon.service pisugar-server.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
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
# 12. Post-install verification
# ---------------------------------------------------------------------------
log_step "Post-install checks..."

if aplay -l 2>/dev/null | grep -qi "whisplay"; then
    log_info "Whisplay sound card detected in ALSA."
else
    log_warn "Whisplay sound card not visible yet. A reboot is required."
fi

if i2cdetect -y 1 2>/dev/null | grep -qE "[0-9a-f]{2}"; then
    log_info "I2C bus is active."
else
    log_warn "I2C devices not detected yet. Reboot required."
fi

# ---------------------------------------------------------------------------
# 13. Final instructions
# ---------------------------------------------------------------------------
cat <<EOF

$(log_info "Installation complete.")

A reboot is required to load device-tree overlays and the Whisplay driver.
Run:

  ${YELLOW}sudo reboot${NC}

After reboot, verify the hardware:

  ${YELLOW}aplay -l | grep -i whisplay${NC}
  ${YELLOW}i2cdetect -y 1${NC}
  ${YELLOW}libcamera-hello --list-cameras${NC}
  ${YELLOW}curl http://localhost:8423/api/power${NC}

Then check the service:

  ${YELLOW}sudo systemctl status bee-device${NC}

Backend is configured to:

  ${YELLOW}$BACKEND_URL${NC}

Make sure the backend is installed, Ollama is authorized, and the backend is running.
EOF

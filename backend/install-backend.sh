#!/bin/bash
#
# One-shot backend setup script for the Personal AI Assistant.
# Run on an Ubuntu/Debian host (VM, LXC, or bare metal) that will receive
# audio and images from the Pi device.
#
# What this does:
#   - Installs system dependencies (Python, ffmpeg)
#   - Installs Ollama if not already installed
#   - Creates the backend project directory
#   - Installs Python dependencies including faster-whisper
#   - Configures the backend with API key auth and dashboard
#   - Creates and enables the bee-backend systemd service
#   - Installs cloudflared if tunnel token is provided
#
# Environment variables (all optional):
#   OLLAMA_MODEL          - default: kimi-k2.7-code:cloud
#   WHISPER_MODEL         - default: base
#   WHISPER_URL           - default: http://192.168.1.86:8001/transcribe (LAN-only AIServer01)
#   WHISPER_API_KEY       - shared secret with the LAN Whisper service (default: empty)
#   OLLAMA_URL            - default: http://localhost:11434
#   BEE_ADMIN_USERNAME    - dashboard username (default: admin)
#   BEE_ADMIN_PASSWORD    - dashboard password (prompted if not set)
#   CLOUDFLARE_TUNNEL_TOKEN - optional, creates cloudflared service if set
#   BEE_GITHUB_REPO       - default: https://github.com/singh763173/personal-ai-assistant
#
set -euo pipefail

BACKEND_DIR="${BACKEND_DIR:-/opt/bee-backend}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-kimi-k2.7-code:cloud}"
OLLAMA_VISION_MODEL="${OLLAMA_VISION_MODEL:-moondream:latest}"
WHISPER_URL="${WHISPER_URL:-http://192.168.1.86:8001/transcribe}"
TTS_PROVIDER="${TTS_PROVIDER:-piper}"
WHISPER_API_KEY="${WHISPER_API_KEY:-}"
WHISPER_MODEL="${WHISPER_MODEL:-base}"
BEE_ADMIN_USERNAME="${BEE_ADMIN_USERNAME:-admin}"
BEE_ADMIN_PASSWORD="${BEE_ADMIN_PASSWORD:-}"
CLOUDFLARE_TUNNEL_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"
GITHUB_REPO="${BEE_GITHUB_REPO:-https://github.com/singh763173/personal-ai-assistant}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root. Try: sudo bash install-backend.sh"
    exit 1
fi

if [[ -z "$BEE_ADMIN_PASSWORD" ]]; then
    log_warn "No BEE_ADMIN_PASSWORD set."
    read -rsp "Enter dashboard password for user '$BEE_ADMIN_USERNAME': " BEE_ADMIN_PASSWORD
    echo
fi
if [[ -z "$BEE_ADMIN_PASSWORD" ]]; then
    log_error "Dashboard password is required. Set BEE_ADMIN_PASSWORD and re-run."
    exit 1
fi

log_info "Personal AI Assistant backend installer"
log_info "Backend directory: $BACKEND_DIR"
log_info "Ollama URL:        $OLLAMA_URL"
log_info "Ollama model:      $OLLAMA_MODEL"
log_info "Ollama vision:     $OLLAMA_VISION_MODEL"
log_info "Whisper URL:       $WHISPER_URL"
log_info "Tunnel token set:  $([[ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]] && echo yes || echo no)"

# ---------------------------------------------------------------------------
# 1. Update system
# ---------------------------------------------------------------------------
log_step "Updating system packages..."
apt update
apt full-upgrade -y
apt install -y curl wget git python3-pip python3-venv ffmpeg net-tools

# ---------------------------------------------------------------------------
# 2. Install Ollama if not present
# ---------------------------------------------------------------------------
if ! command -v ollama &> /dev/null; then
    log_step "Installing Ollama..."
    if ! curl -fsSL https://ollama.com/install.sh | sh; then
        log_error "Ollama installation failed."
        exit 1
    fi
else
    log_info "Ollama is already installed: $(ollama --version)"
fi

log_step "Starting Ollama service..."
systemctl enable --now ollama

log_step "Waiting for Ollama API..."
for i in {1..30}; do
    if curl -s "$OLLAMA_URL/api/tags" > /dev/null 2>&1; then
        log_info "Ollama API is reachable at $OLLAMA_URL"
        break
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# 3. Create backend directory and download project files
# ---------------------------------------------------------------------------
log_step "Setting up backend directory: $BACKEND_DIR..."
mkdir -p "$BACKEND_DIR"
cd "$BACKEND_DIR"

if [[ -f "${BASH_SOURCE[0]:-$0}" ]] && [[ -d "$(dirname "${BASH_SOURCE[0]:-$0}")/../backend" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
    cp -r "$SCRIPT_DIR/backend"/* "$BACKEND_DIR/"
    log_info "Copied backend files from local directory."
else
    log_info "Downloading backend files from GitHub..."
    TMP_DIR=$(mktemp -d)
    if ! git clone --depth 1 "$GITHUB_REPO" "$TMP_DIR"; then
        log_error "Failed to clone $GITHUB_REPO"
        exit 1
    fi
    cp -r "$TMP_DIR/backend"/* "$BACKEND_DIR/"
    rm -rf "$TMP_DIR"
fi

# ---------------------------------------------------------------------------
# 4. Create Python virtual environment
# ---------------------------------------------------------------------------
log_step "Creating Python virtual environment..."
python3 -m venv "$BACKEND_DIR/venv"
source "$BACKEND_DIR/venv/bin/activate"
pip install --upgrade pip
pip install -r "$BACKEND_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 4b. Download Piper TTS voice model (optional)
# ---------------------------------------------------------------------------
if [[ "$TTS_PROVIDER" == "piper" ]]; then
    log_step "Downloading Piper TTS voice model..."
    mkdir -p "$BACKEND_DIR/voices"
    PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium"
    if [[ ! -f "$BACKEND_DIR/voices/en_US-amy-medium.onnx" ]]; then
        curl -fsSL "$PIPER_BASE/en_US-amy-medium.onnx" -o "$BACKEND_DIR/voices/en_US-amy-medium.onnx"
        curl -fsSL "$PIPER_BASE/en_US-amy-medium.onnx.json" -o "$BACKEND_DIR/voices/en_US-amy-medium.onnx.json"
    fi
fi

# ---------------------------------------------------------------------------
# 5. Configure environment file
# ---------------------------------------------------------------------------
log_step "Writing backend environment configuration..."
HEALTH_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo '127.0.0.1')"
cat > "$BACKEND_DIR/.env" <<EOF
OLLAMA_URL=$OLLAMA_URL
OLLAMA_MODEL=$OLLAMA_MODEL
OLLAMA_VISION_MODEL=$OLLAMA_VISION_MODEL
WHISPER_URL=${WHISPER_URL:-http://192.168.1.86:8001/transcribe}
WHISPER_API_KEY=$WHISPER_API_KEY
WHISPER_MODEL=$WHISPER_MODEL
TTS_PROVIDER=$TTS_PROVIDER
PIPER_VOICE_MODEL=$BACKEND_DIR/voices/en_US-amy-medium.onnx
OMP_NUM_THREADS=1
OMP_WAIT_POLICY=PASSIVE
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
BEE_ADMIN_USERNAME=$BEE_ADMIN_USERNAME
BEE_ADMIN_PASSWORD_HASH=$(python3 -c "import bcrypt, sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt(rounds=12)).decode())" "$BEE_ADMIN_PASSWORD")
BEE_SECRET_KEY=$(openssl rand -hex 32)
EOF

chown -R bee-backend:bee-backend "$BACKEND_DIR" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 6. Create systemd service
# ---------------------------------------------------------------------------
log_step "Creating bee-backend systemd service..."
useradd -r -s /bin/false bee-backend 2>/dev/null || log_warn "bee-backend user already exists"
chown -R bee-backend:bee-backend "$BACKEND_DIR"

cat > /etc/systemd/system/bee-backend.service <<EOF
[Unit]
Description=Personal AI Assistant Backend
After=network.target ollama.service

[Service]
Type=simple
User=bee-backend
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$BACKEND_DIR/.env
ExecStart=$BACKEND_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Environment=OMP_NUM_THREADS=1
Environment=OMP_WAIT_POLICY=PASSIVE
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bee-backend.service

# ---------------------------------------------------------------------------
# 7. Optional cloudflared tunnel
# ---------------------------------------------------------------------------
if [[ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]]; then
    log_step "Installing cloudflared..."
    if ! command -v cloudflared &> /dev/null; then
        curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
        dpkg -i /tmp/cloudflared.deb || apt-get install -f -y
        rm -f /tmp/cloudflared.deb
    fi

    cat > /etc/systemd/system/cloudflared-bee-backend.service <<EOF
[Unit]
Description=Cloudflare Tunnel for Bee Backend
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate run --token $CLOUDFLARE_TUNNEL_TOKEN
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable --now cloudflared-bee-backend.service
    log_info "cloudflared service started."
fi

# ---------------------------------------------------------------------------
# 7b. Optional nightly backup cron
# ---------------------------------------------------------------------------
if command -v ssh > /dev/null 2>&1; then
    log_step "Installing nightly backup cron..."
    (
        crontab -l 2>/dev/null || true
        echo "0 3 * * * $BACKEND_DIR/backup.sh >> /var/log/bee-backup.log 2>&1"
    ) | crontab -
    log_info "Backup cron installed at 03:00 daily."
else
    log_warn "ssh not installed; skipping backup cron."
fi

# ---------------------------------------------------------------------------
# 8. Start backend and print instructions
# ---------------------------------------------------------------------------
log_step "Starting backend service..."
systemctl start bee-backend.service || log_warn "Backend service failed to start; check logs with: journalctl -u bee-backend -n 50"

sleep 2

log_info "Backend setup complete."
echo ""
echo -e "${YELLOW}Admin username:${NC} ${BEE_ADMIN_USERNAME}"
echo -e "${YELLOW}Local health check:${NC} curl http://$HEALTH_IP:8000/api/v1/health"
echo -e "${YELLOW}Dashboard:${NC} http://$HEALTH_IP:8000/dashboard"
if [[ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]]; then
    echo -e "${YELLOW}Tunnel:${NC} cloudflared should connect shortly. Check with: systemctl status cloudflared-bee-backend"
fi
echo ""
log_info "Setup complete."

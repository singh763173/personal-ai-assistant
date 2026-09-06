#!/bin/bash
#
# One-shot backend setup script for the Ollama Bee Device / AI Assistant.
# Run on an Ubuntu/Debian host (VM, LXC, or bare metal) that will receive
# audio and images from the Pi device.
#
# What this does:
#   - Installs system dependencies (Python, ffmpeg)
#   - Installs Ollama if not already installed
#   - Creates the backend project directory
#   - Installs Python dependencies including faster-whisper
#   - Configures the backend to use kimi-k2.7-code:cloud via Ollama
#   - Creates and enables the bee-backend systemd service
#   - Prints clear instructions for authorizing Ollama.com cloud models
#
# IMPORTANT: You must manually log into ollama.com and add an API key before
#            cloud models like kimi-k2.7-code:cloud will work.
#
set -euo pipefail

BACKEND_DIR="${BACKEND_DIR:-/opt/bee-backend}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-kimi-k2.7-code:cloud}"
WHISPER_MODEL="${WHISPER_MODEL:-base}"
GITHUB_REPO="${BEE_GITHUB_REPO:-https://github.com/singh763173/ollama-bee-device}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root. Try: sudo bash install-backend.sh"
    exit 1
fi

log_info "Ollama Bee / AI Assistant backend installer"

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
    curl -fsSL https://ollama.com/install.sh | sh
else
    log_info "Ollama is already installed: $(ollama --version)"
fi

# Ensure Ollama service is running
log_step "Starting Ollama service..."
systemctl enable --now ollama

# Wait for Ollama to be reachable
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
    git clone --depth 1 "$GITHUB_REPO" "$TMP_DIR"
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
# 5. Configure environment file
# ---------------------------------------------------------------------------
log_step "Writing backend environment configuration..."
cat > "$BACKEND_DIR/.env" <<EOF
OLLAMA_URL=$OLLAMA_URL
OLLAMA_MODEL=$OLLAMA_MODEL
WHISPER_MODEL=$WHISPER_MODEL
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
EOF

# ---------------------------------------------------------------------------
# 6. Create systemd service
# ---------------------------------------------------------------------------
log_step "Creating bee-backend systemd service..."
useradd -r -s /bin/false bee-backend 2>/dev/null || log_warn "bee-backend user already exists"
chown -R bee-backend:bee-backend "$BACKEND_DIR"

cat > /etc/systemd/system/bee-backend.service <<EOF
[Unit]
Description=Bee Pioneer / AI Assistant Backend
After=network.target ollama.service
Requires=ollama.service

[Service]
Type=simple
User=bee-backend
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$BACKEND_DIR/.env
ExecStart=$BACKEND_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bee-backend.service

# ---------------------------------------------------------------------------
# 7. Print cloud authorization instructions
# ---------------------------------------------------------------------------
cat <<EOF

$(log_warn "ACTION REQUIRED: Authorize Ollama Cloud Access")

This backend uses the cloud-hosted model: ${YELLOW}$OLLAMA_MODEL${NC}

Before it can work, you must:

1. Open a browser and go to: ${BLUE}https://ollama.com${NC}
2. Sign in or create an account.
3. Go to your account/API keys page.
4. Generate an API key.
5. Add the API key to Ollama on this machine by running:

   ${YELLOW}ollama login${NC}

   Then paste your API key when prompted.

6. Verify the cloud model is available:

   ${YELLOW}ollama list${NC}

   You should see "$OLLAMA_MODEL" in the list.

7. Start the backend service:

   ${YELLOW}sudo systemctl start bee-backend${NC}

8. Test the backend health endpoint:

   ${YELLOW}curl http://$(hostname -I | awk '{print $1}'):8000/health${NC}

EOF

log_info "Backend setup is complete. Ollama is installed but cloud authorization is still required."

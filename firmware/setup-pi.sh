#!/bin/bash
# setup-pi.sh
# Run once on the Raspberry Pi Zero 2 W after flashing Raspberry Pi OS Lite.
set -e

echo "=== Bee Pioneer Pi Setup (Whisplay HAT + PiSugar 3) ==="

# Update system
sudo apt update && sudo apt full-upgrade -y

# Install system dependencies
sudo apt install -y \
    python3-pip python3-venv python3-dev \
    alsa-utils arecord \
    git i2c-tools libcamera-dev ffmpeg curl

# Install PiSugar Whisplay HAT drivers
if [ ! -d /tmp/Whisplay ]; then
    git clone --depth 1 https://github.com/PiSugar/Whisplay.git /tmp/Whisplay
fi
cd /tmp/Whisplay
sudo bash install_driver.sh

# Install PiSugar power manager for battery monitoring
curl -sSL https://cdn.pisugar.com/release/Pisugar-power-manager.sh | sudo bash
sudo systemctl enable --now pisugar-server

# Camera overlay for Pi Zero
echo "dtoverlay=imx708" | sudo tee -a /boot/firmware/config.txt

echo "Added Whisplay driver, PiSugar power manager, and camera overlay. Reboot required after setup."

# Create project directory and venv
PROJECT_DIR="$HOME/bee-device"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Setup complete. Reboot now, then test: ==="
echo "  arecord -l                 (find whisplay-soundcard card/device)"
echo "  arecord -D hw:whisplay-soundcard -c2 -r16000 -f S16_LE -d 5 test.wav"
echo "  python3 /tmp/Whisplay/example/test.py"
echo "  libcamera-jpeg -o test.jpg --width 1640 --height 1232"
echo "  curl -s http://localhost:8423/api/power"

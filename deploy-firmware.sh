#!/bin/bash
set -euo pipefail
PROJECT_DIR="/home/ajay/ollama-bee-device"
PI_IP="192.168.10.193"
PI_USER="ajay"
PI_KEY="/home/ajay/.ssh/bee-pi"
PI_DIR="/opt/bee-device"

cd "$PROJECT_DIR"
git add -A
git commit -m "deploy firmware: $(date -Iseconds)" || true
git push origin main

TMP_TAR="/tmp/bee-firmware-deploy.tar.gz"
 tar -czf "$TMP_TAR" -C "$PROJECT_DIR" firmware

scp -i "$PI_KEY" -o ConnectTimeout=10 "$TMP_TAR" "$PI_USER@$PI_IP:/tmp/bee-firmware-deploy.tar.gz"
ssh -i "$PI_KEY" -o ConnectTimeout=10 "$PI_USER@$PI_IP" "sudo systemctl stop bee-device; sudo rm -rf $PI_DIR/assets; sudo tar -xzf /tmp/bee-firmware-deploy.tar.gz -C /opt --overwrite; sudo chown -R bee-device:bee-device $PI_DIR; sudo systemctl start bee-device"
rm -f "$TMP_TAR"
echo "Firmware deployed."

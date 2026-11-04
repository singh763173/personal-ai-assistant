#!/bin/bash
set -euo pipefail
PROJECT_DIR="/home/ajay/ollama-bee-device"
PVE_HOST="192.168.1.14"
PVE_KEY="/home/ajay/.ssh/proxmox_manager"
LXC_ID=300
BACKEND_DIR="/opt/bee-backend"

cd "$PROJECT_DIR"
git add -A
git commit -m "deploy: $(date -Iseconds)" || true
git push origin main

TMP_TAR="/tmp/bee-backend-deploy.tar.gz"
 tar -czf "$TMP_TAR" -C "$PROJECT_DIR" backend

scp -i "$PVE_KEY" -o ConnectTimeout=10 "$TMP_TAR" "root@$PVE_HOST:/tmp/bee-backend-deploy.tar.gz"
ssh -i "$PVE_KEY" -o ConnectTimeout=10 "root@$PVE_HOST" "pct push $LXC_ID /tmp/bee-backend-deploy.tar.gz /tmp/bee-backend-deploy.tar.gz && pct exec $LXC_ID -- bash -c 'systemctl stop bee-backend; tar -xzf /tmp/bee-backend-deploy.tar.gz -C /opt --overwrite; chown -R bee-backend:bee-backend $BACKEND_DIR; systemctl start bee-backend'"
rm -f "$TMP_TAR"
echo "Backend deployed."

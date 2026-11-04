#!/bin/bash
# Backup Bee backend data to the Synology NAS via tar over SSH stdin
set -euo pipefail

SRC_DIR="/opt/bee-backend"
BACKUP_HOST="192.168.1.199"
BACKUP_USER="singh763173"
BACKUP_PATH="/volume1/homes/singh763173/bee-backend-backups"
SSH_PORT=2222
RETENTION_DAYS=14

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
TMP_DIR=$(mktemp -d)
trap "rm -rf \$TMP_DIR" EXIT

mkdir -p "$TMP_DIR/bee-backup-$TIMESTAMP"
cp "$SRC_DIR/bee.db" "$TMP_DIR/bee-backup-$TIMESTAMP/"
if [[ -d "$SRC_DIR/audio_replies" ]]; then
    cp -r "$SRC_DIR/audio_replies" "$TMP_DIR/bee-backup-$TIMESTAMP/"
fi

tar -czf "$TMP_DIR/bee-backup-$TIMESTAMP.tar.gz" -C "$TMP_DIR" "bee-backup-$TIMESTAMP"

# Create remote directory and upload via stdin over SSH
ssh -p "$SSH_PORT" -o ConnectTimeout=10 "$BACKUP_USER@$BACKUP_HOST" "mkdir -p $BACKUP_PATH" < /dev/null
ssh -p "$SSH_PORT" -o ConnectTimeout=10 "$BACKUP_USER@$BACKUP_HOST" "cat > $BACKUP_PATH/bee-backup-$TIMESTAMP.tar.gz" < "$TMP_DIR/bee-backup-$TIMESTAMP.tar.gz"

# Prune old backups
ssh -p "$SSH_PORT" -o ConnectTimeout=10 "$BACKUP_USER@$BACKUP_HOST" "find $BACKUP_PATH -maxdepth 1 -name 'bee-backup-*.tar.gz' -mtime +$RETENTION_DAYS -delete"

echo "Backup completed: bee-backup-$TIMESTAMP.tar.gz"

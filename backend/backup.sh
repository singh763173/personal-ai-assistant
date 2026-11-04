#!/bin/bash
# Backup Bee backend data to the Synology NAS
set -euo pipefail

SRC_DIR="/opt/bee-backend"
BACKUP_HOST="192.168.1.199"
BACKUP_USER="singh763173"
BACKUP_PATH="/volume1/backup/bee-backend"
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

ssh -p "$SSH_PORT" -o ConnectTimeout=10 "$BACKUP_USER@$BACKUP_HOST" "mkdir -p $BACKUP_PATH" < /dev/null
scp -P "$SSH_PORT" -o ConnectTimeout=10 "$TMP_DIR/bee-backup-$TIMESTAMP.tar.gz" "$BACKUP_USER@$BACKUP_HOST:$BACKUP_PATH/"

# Prune old backups on NAS
ssh -p "$SSH_PORT" -o ConnectTimeout=10 "$BACKUP_USER@$BACKUP_HOST" "find $BACKUP_PATH -maxdepth 1 -name 'bee-backup-*.tar.gz' -mtime +$RETENTION_DAYS -delete"

echo "Backup completed: bee-backup-$TIMESTAMP.tar.gz"

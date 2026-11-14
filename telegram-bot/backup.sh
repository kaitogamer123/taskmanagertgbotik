#!/usr/bin/env bash
# Ежедневный бэкап баз пользователей. Запускается по cron и из /backup.
set -euo pipefail

cd "$(dirname "$0")"

BACKUP_DIR="${BACKUP_DIR:-/root/backups/telegram-bot}"
KEEP="${KEEP:-14}"
mkdir -p "$BACKUP_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/planesuser-$STAMP.tar.gz"

tar czf "$OUT" PlanesUser
# Оставляем только последние KEEP архивов
ls -1t "$BACKUP_DIR"/planesuser-*.tar.gz 2>/dev/null \
    | tail -n +$((KEEP + 1)) \
    | xargs -r rm -f

echo "$OUT"

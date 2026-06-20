#!/usr/bin/env bash
# Daily Postgres backup for tg-bot-afisha.
#
# Dumps the afisha database from the running `postgres` container, gzips it into BACKUP_DIR, and
# prunes dumps older than RETENTION_DAYS. pg_dump runs INSIDE the container over the local socket
# (trust auth), so the DB password never touches this script or its argv/logs.
#
# Install on the server (daily at 04:00, logged):
#   ( crontab -l 2>/dev/null; echo '0 4 * * * /var/www1/tg-bot-afisha/scripts/pg_backup.sh >> /var/log/tg-bot-afisha-backup.log 2>&1' ) | crontab -
#
# Restore a dump:
#   gunzip -c /var/backups/tg-bot-afisha/afisha-YYYYmmdd-HHMMSS.sql.gz | docker compose exec -T postgres psql -U afisha -d afisha
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/var/www1/tg-bot-afisha}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/tg-bot-afisha}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
DB_USER="${POSTGRES_USER:-afisha}"
DB_NAME="${POSTGRES_DB:-afisha}"

mkdir -p "$BACKUP_DIR"
ts="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/afisha-$ts.sql.gz"

cd "$PROJECT_DIR"
# -T: no TTY. --no-owner/--no-privileges keep the dump portable across roles on restore.
docker compose exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-privileges | gzip > "$out"

# Guard against a silent failure (auth/role error) leaving a tiny/empty file masquerading as a backup.
size="$(stat -c%s "$out" 2>/dev/null || echo 0)"
if [ "$size" -lt 10000 ]; then
  echo "ERROR: backup looks empty (${size} bytes), removing: $out" >&2
  rm -f "$out"
  exit 1
fi

find "$BACKUP_DIR" -name 'afisha-*.sql.gz' -mtime +"$RETENTION_DAYS" -delete
echo "backup ok: $out ($(du -h "$out" | cut -f1)) — pruned dumps older than ${RETENTION_DAYS}d"

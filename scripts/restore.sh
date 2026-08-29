#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then echo "Usage: ./scripts/restore.sh backups/file.dump"; exit 1; fi
test -f "$1"
docker compose exec -T db pg_restore -U "${POSTGRES_USER:-elinor}" -d "${POSTGRES_DB:-elinor}" --clean --if-exists --no-owner < "$1"
echo "Restore completed."

#!/bin/sh
set -eu
mkdir -p backups
stamp=$(date +%Y%m%d_%H%M%S)
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-elinor}" -d "${POSTGRES_DB:-elinor}" -Fc > "backups/elinor_${stamp}.dump"
echo "Backup created: backups/elinor_${stamp}.dump"


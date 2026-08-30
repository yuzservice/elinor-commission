#!/bin/sh
set -eu

mkdir -p /app/media/branding /app/media/profiles /app/media/evidence /app/staticfiles
chown -R app:app /app/media /app/staticfiles
chmod -R 775 /app/media

gosu app python manage.py migrate --noinput
gosu app python manage.py collectstatic --noinput

exec gosu app "$@"

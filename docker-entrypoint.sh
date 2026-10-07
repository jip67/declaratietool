#!/bin/sh
set -e

case "$1" in
  web)
    # Database bijwerken naar de nieuwste versie (veilig om vaker te draaien).
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    exec python -m app.worker
    ;;
  *)
    exec "$@"
    ;;
esac

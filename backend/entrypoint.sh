#!/bin/sh
set -e

# Кэш маршрутов живёт в volume; новые участки из репозитория в него доливаются
if [ -n "${ROUTING_CACHE_PATH:-}" ]; then
  python -m core.merge_routing_cache /solution/data/routing_cache.json "$ROUTING_CACHE_PATH"
fi

echo "Running migrations..."
alembic upgrade head

# Профили rRAPTOR (общественный транспорт) — в Postgres, один раз на версию фида
python -m core.load_transit_profiles /solution/data/transit_profiles.bin   || echo "WARNING: профили rRAPTOR не загружены — общественный транспорт по расписанию на 10:00"

echo "Starting API..."
exec uvicorn main:app --host 0.0.0.0 --port 8000

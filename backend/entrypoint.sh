#!/bin/sh
set -e

# Кэш маршрутов живёт в volume; новые участки из репозитория в него доливаются
if [ -n "${ROUTING_CACHE_PATH:-}" ]; then
  python -m core.merge_routing_cache /solution/data/routing_cache.json "$ROUTING_CACHE_PATH"
fi

echo "Running migrations..."
alembic upgrade head

echo "Starting API..."
exec uvicorn main:app --host 0.0.0.0 --port 8000

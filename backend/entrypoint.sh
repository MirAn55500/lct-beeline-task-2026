#!/bin/sh
set -e

# Кэш маршрутов живёт в volume; пустой volume заполняется кэшем из репозитория
if [ -n "${ROUTING_CACHE_PATH:-}" ] && [ ! -f "$ROUTING_CACHE_PATH" ]; then
  mkdir -p "$(dirname "$ROUTING_CACHE_PATH")"
  cp /solution/data/routing_cache.json "$ROUTING_CACHE_PATH"
  echo "Routing cache seeded: $ROUTING_CACHE_PATH"
fi

echo "Running migrations..."
alembic upgrade head

echo "Starting API..."
exec uvicorn main:app --host 0.0.0.0 --port 8000

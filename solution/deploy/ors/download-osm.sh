#!/usr/bin/env sh
# Выгрузка OpenStreetMap для графов openrouteservice.
#
#   ./download-osm.sh                 # Центральный ФО (Москва + область) ~1 ГБ
#   ./download-osm.sh moscow          # только Москва, ~150 МБ — быстрее собирается,
#                                     # но заявки в Кашире и Домодедово окажутся вне графа
#
# Файл кладётся в ./files/region.osm.pbf — именно этот путь прописан в ors-config.yml.
set -eu

REGION="${1:-central}"
DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="$DIR/files/region.osm.pbf"

case "$REGION" in
  central)
    URL="https://download.geofabrik.de/russia/central-fed-district-latest.osm.pbf"
    ;;
  moscow)
    URL="https://download.bbbike.org/osm/bbbike/Moscow/Moscow.osm.pbf"
    ;;
  *)
    echo "Неизвестный регион: $REGION (ожидается central или moscow)" >&2
    exit 1
    ;;
esac

mkdir -p "$DIR/files"

if [ -f "$TARGET" ]; then
  echo "Файл уже есть: $TARGET"
  echo "Удалите его, если нужна свежая выгрузка."
  exit 0
fi

echo "Скачиваю $URL"
if command -v curl >/dev/null 2>&1; then
  curl -L --fail --progress-bar "$URL" -o "$TARGET.part"
else
  wget --show-progress -O "$TARGET.part" "$URL"
fi
mv "$TARGET.part" "$TARGET"

echo "Готово: $TARGET"
echo "Дальше: docker compose up -d  (первая сборка графов — 20-40 минут)"

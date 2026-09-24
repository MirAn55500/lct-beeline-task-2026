#!/bin/sh
# Подготовка volume ORS перед стартом lct-ors (сервис ors-init в корневом docker-compose.yml).
#
# Всё лежит в volume, а не в рабочей папке: actions/checkout на деплое чистит и
# игнорируемые файлы, и графы (6 ГБ, до 45 минут сборки) собирались бы каждый раз.
#
# * выгрузка OSM — скачивается один раз; свежая: удалить volume или сам файл;
# * GTFS — из репозитория (files/gtfs.zip); сменился — пересобирается только
#   граф public-transport; фида нет — профиль выключается, иначе ORS не стартует;
# * конфиг — всегда свежий из репозитория.
set -eu

SRC=/src
ORS_HOME=/home/ors
FILES="$ORS_HOME/files"
GRAPHS="$ORS_HOME/graphs"
CONFIG="$ORS_HOME/config/ors-config.yml"
GTFS_STAMP="$FILES/gtfs.sha256"

mkdir -p "$FILES" "$GRAPHS" "$ORS_HOME/config"

OSM_TARGET="$FILES/region.osm.pbf" sh "$SRC/download-osm.sh" "${OSM_REGION:-central}"

if [ -f "$SRC/files/gtfs.zip" ]; then
  new=$(sha256sum "$SRC/files/gtfs.zip" | cut -d' ' -f1)
  old=$(cat "$GTFS_STAMP" 2>/dev/null || true)
  if [ "$new" != "$old" ]; then
    echo "GTFS изменился — граф public-transport будет собран заново"
    cp "$SRC/files/gtfs.zip" "$FILES/gtfs.zip"
    rm -rf "$GRAPHS/public-transport"
    echo "$new" > "$GTFS_STAMP"
  fi
  tr -d '\r' < "$SRC/ors-config.yml" > "$CONFIG"
else
  echo "Нет files/gtfs.zip — профиль public-transport выключен"
  rm -f "$FILES/gtfs.zip" "$GTFS_STAMP"
  rm -rf "$GRAPHS/public-transport"
  tr -d '\r' < "$SRC/ors-config.yml" \
    | sed '/^      public-transport:/{n;s/enabled: true/enabled: false/;}' > "$CONFIG"
fi

echo "ORS volume готов"

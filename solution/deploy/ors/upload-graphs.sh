#!/usr/bin/env sh
# Залить локально собранные графы ORS (./ors-docker/graphs) в volume стенда:
# собрать их на стенде не хватит памяти, а если хватит — это 30-45 минут.
#
#   ./upload-graphs.sh user@host                                  # все профили
#   ./upload-graphs.sh user@host driving-car foot-walking cycling-regular
#
# Графы совместимы, пока совпадают версия образа ORS, ors-config.yml, выгрузка OSM
# и files/gtfs.zip. Отметка GTFS пишется в volume, иначе ors-init сочтёт фид
# изменившимся и удалит граф public-transport.
set -eu

HOST="${1:?укажите ssh-хост стенда}"
shift
DIR="$(cd "$(dirname "$0")" && pwd)"
GRAPHS="$DIR/ors-docker/graphs"
[ -d "$GRAPHS" ] || { echo "Нет $GRAPHS — сначала соберите графы локально" >&2; exit 1; }
PROFILES="${*:-$(ls "$GRAPHS")}"
for profile in $PROFILES; do
  [ -d "$GRAPHS/$profile" ] || { echo "Нет графа $profile" >&2; exit 1; }
done
GTFS_SHA="$(sha256sum "$DIR/files/gtfs.zip" | cut -d' ' -f1)"

# Имя volume зависит от имени папки, из которой деплой запускает compose
VOLUME="${ORS_VOLUME:-$(ssh "$HOST" "docker volume ls -q | grep -m1 '_ors-data\$'" || true)}"
VOLUME="${VOLUME:-lct-beeline-task-2026_ors-data}"
echo "Volume на стенде: $VOLUME; профили: $PROFILES"

ssh "$HOST" "docker stop lct-ors >/dev/null 2>&1 || true"
# shellcheck disable=SC2086
echo "Передаю графы ($(cd "$GRAPHS" && du -shc $PROFILES | tail -1 | cut -f1))..."
# shellcheck disable=SC2086
tar -C "$GRAPHS" -cf - $PROFILES | gzip -1 | ssh "$HOST" \
  "docker run --rm -i -v '$VOLUME:/home/ors' alpine sh -c \
   'rm -rf /home/ors/graphs && mkdir -p /home/ors/graphs /home/ors/files \
    && gunzip | tar -C /home/ors/graphs -xf - \
    && echo $GTFS_SHA > /home/ors/files/gtfs.sha256 && du -sh /home/ors/graphs/*'"

# ORS_START=0 — не запускать: контейнер со старыми настройками пересоздаст деплой
if [ "${ORS_START:-1}" != 1 ]; then
  echo "Готово: lct-ors не запускался, его пересоздаст следующий деплой"
elif ssh "$HOST" "docker start lct-ors >/dev/null 2>&1"; then
  echo "Готово: lct-ors перезапущен на залитых графах"
else
  echo "Готово: контейнера lct-ors ещё нет — его поднимет следующий деплой"
fi

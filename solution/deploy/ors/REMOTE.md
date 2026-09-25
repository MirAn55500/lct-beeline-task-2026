# ORS на отдельной машине для стенда

> **Для общественного транспорта больше не нужна.** С 24.09.2026 расписания считаются
> прямо в backend (RAPTOR/rRAPTOR по `gtfs.zip`, см. `solution/docs/transit-raptor.md`):
> известные пары — профили rRAPTOR из Postgres, новые адреса — RAPTOR на 10:00.
> Отдельная машина может пригодиться только как более мощный ORS для авто, пешком и
> велосипеда; инструкция ниже оставлена для этого случая. Разделы про досчёт расписаний
> (`transit_warmup`, `TRANSIT_WORKERS`) устарели.

Стенд (3.8 ГБ RAM) не вмещает граф общественного транспорта, поэтому openrouteservice
со всеми профилями живёт на отдельной машине, а стенд ходит к нему по сети.

```
стенд: backend ──HTTP + Authorization: <токен>──▶ ORS-машина: nginx :8081 ──▶ ORS :8082
             └──если основной не отвечает──▶ ORS стенда (запасной: авто, пешком, велосипед)
```

## Как считается маршрутизация

| | Известные адреса | Новые адреса |
|---|---|---|
| Авто, пешком, велосипед | кэш маршрутов, без запросов | ORS-машина; не отвечает — запасной ORS стенда |
| Общественный транспорт | кэш, прогрет на все дни недели | сразу — по координатам; в фоне досчитывается на ORS-машине, затем план пересчитывается новой версией |

Доступность основного backend проверяет по `/v2/health` (таймаут 3 с, ответ помнит
30 с). Досчёт расписаний возможен только на ORS-машине: если она не отвечает, задача
повторяется каждые 10 минут до 6 раз, дальше — со следующей загрузки или пересчёта.

Фоновый досчёт (`backend/modules/planning/transit_warmup.py`) запрашивает только
пары с новыми точками и пишет их в раздел кэша того же дня недели. Пары «вне фида»
(Кашира и другие адреса вне московского GTFS) запоминаются и не повторяются.
Замер: один новый адрес — 132 пары, ~80 с в 2 потока на занятом ORS; на выделенной
машине в 6 потоков должно быть заметно быстрее (не замерялось).

## 1. Машина

| | Минимум | Рекомендуется |
|---|---|---|
| RAM | 12 ГБ (`ORS_XMX=8g`) | 16 ГБ (`ORS_XMX=10g`) |
| CPU | 2 vCPU | 4 vCPU |
| Диск | 20 ГБ | 30 ГБ SSD |
| ОС | Ubuntu 22.04 / 24.04 | |

Графы в памяти занимают ~7.5 ГБ, плюс запас Java. Сеть: стенд (`111.88.151.0`)
должен доходить до машины на порт `8081`. Лучше всего — частная сеть облака, тогда
порт наружу не открывается вовсе.

## 2. Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"      # перелогиниться после этого
docker compose version               # нужен compose v2
```

## 3. Файлы

Нужна папка `solution/deploy/ors` из репозитория: `ors-config.yml`, `files/gtfs.zip`,
`download-osm.sh`, `remote/`. Репозиторий приватный — либо клонировать с доступом:

```bash
git clone https://github.com/Keberson/lct-beeline-task-2026.git ~/lct
cd ~/lct/solution/deploy/ors
```

либо скопировать одну папку со своей машины:

```bash
# из корня репозитория на своей машине (Git Bash)
tar -C solution/deploy -czf - --exclude=ors/ors-docker --exclude=ors/files/region.osm.pbf ors \
  | ssh user@ORS-HOST "mkdir -p ~/lct/solution/deploy && tar -C ~/lct/solution/deploy -xzf -"
```

Выгрузка OSM (877 МБ, Центральный ФО):

```bash
cd ~/lct/solution/deploy/ors
./download-osm.sh
```

## 4. Графы

**Вариант А — залить готовые (быстро, ~10 минут передачи).** Графы 6.2 ГБ лежат у
вас локально в `solution/deploy/ors/ors-docker/graphs`. Локальный ORS на время копии
**обязательно остановить**: граф общественного транспорта хранит расписания в MapDB,
и копия открытого хранилища не запустится (`Wrong index checksum, store was not
closed properly`).

```bash
# на своей машине, из solution/deploy/ors (Git Bash)
docker stop lct-ors
tar -C ors-docker -czf - graphs | ssh user@ORS-HOST \
  "mkdir -p ~/lct/solution/deploy/ors/ors-docker && tar -C ~/lct/solution/deploy/ors/ors-docker -xzf -"
docker start lct-ors
```

Графы совместимы, пока совпадают версия образа (`v10.0.0`), `ors-config.yml`,
выгрузка OSM и `files/gtfs.zip`.

**Вариант Б — собрать на месте (30-45 минут, нужны все 16 ГБ).** Ничего не копировать:
при первом старте ORS сам соберёт графы из `files/region.osm.pbf` и `files/gtfs.zip`.

## 5. Запуск

```bash
cd ~/lct/solution/deploy/ors/remote
cp .env.example .env
sed -i "s/^ORS_TOKEN=.*/ORS_TOKEN=$(openssl rand -hex 32)/" .env
grep ORS_TOKEN .env                  # этот токен понадобится на шаге 7
docker compose up -d
docker compose logs -f ors           # с готовыми графами — старт за 1-2 минуты
```

## 6. Файрвол

Порт 8081 — только для стенда. В облаке это группа безопасности; на самой машине:

```bash
sudo ufw allow OpenSSH
sudo ufw allow from 111.88.151.0 to any port 8081 proto tcp
sudo ufw enable
```

> Docker публикует порты в обход `ufw`. Если машина с публичным IP и без группы
> безопасности, ограничьте доступ в самом Docker: в `remote/.env` задайте
> `ORS_PORT=<частный IP машины>:8081`, либо настройте правило в цепочке `DOCKER-USER`.

## 7. Проверка

На ORS-машине:

```bash
TOKEN=$(grep ORS_TOKEN .env | cut -d= -f2)
curl -s http://127.0.0.1:8081/ors/v2/health                         # {"status":"ready"}
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/ors/v2/status   # 401 без токена
curl -s -H "Authorization: $TOKEN" -H "Content-Type: application/json" \
  -d '{"coordinates":[[37.6176,55.7558],[37.6649,55.7300]],"departure":"2026-08-17T10:00:00","walking_time":"PT30M"}' \
  http://127.0.0.1:8081/ors/v2/directions/public-transport/geojson | head -c 200   # маршрут, не ошибка
```

Со стенда (`ssh keberson@111.88.151.0`):

```bash
curl -s http://ORS-HOST:8081/ors/v2/health                          # {"status":"ready"}
```

## 8. Подключить стенд

В GitHub → Settings → Secrets and variables → Actions:

| Тип | Имя | Значение |
|---|---|---|
| variable | `ORS_URL` | `http://ORS-HOST:8081/ors` |
| secret | `ORS_API_KEY` | токен из `remote/.env` |
| variable | `TRANSIT_WORKERS` | `6` |

Затем перезапустить Deploy (Actions → Deploy → Run workflow) или сделать push. Деплой
увидит внешний `ORS_URL` и сделает `lct-ors` стенда запасным (`ORS_FALLBACK_URL`):
он продолжает работать и подхватывает авто, пешком и велосипед, если ORS-машина
недоступна. Удалять его и его volume не нужно.

Проверка на стенде после деплоя:

```bash
docker exec lct-backend sh -c 'echo $ORS_URL $ORS_FALLBACK_URL'   # ORS-машина и http://ors:8082/ors
docker logs -f lct-backend | grep -i "досчёт"         # после загрузки файла с новыми адресами:
# INFO: modules.planning.transit_warmup: Досчёт расписаний: регион 1, 2026-08-17 — 132 новых пар, пересчитываю план
```

## 9. Обслуживание

* **Обновился `files/gtfs.zip`** — пересобрать только граф транспорта:
  ```bash
  cd ~/lct && git pull
  cd solution/deploy/ors/remote
  docker compose stop ors && rm -rf ../ors-docker/graphs/public-transport && docker compose up -d
  ```
  Сборка ~15 минут; всё это время стенд считает общественный транспорт по кэшу.
* **Свежая выгрузка OSM** — `rm ../files/region.osm.pbf && ../download-osm.sh`, затем
  `REBUILD_GRAPHS` в `docker-compose.yml` на `"True"` на один запуск (30-45 минут).
* **Недоступна ORS-машина** — стенд не падает: известные адреса по кэшу; новые на авто,
  пешком и велосипеде — через запасной ORS стенда (в логе backend
  `ORS … не отвечает — матрицы считаются по запасному`), общественный транспорт — по
  координатам, пока досчёт не пройдёт при одном из повторов.
* **Логи**: `docker compose logs --tail=100 ors proxy`.

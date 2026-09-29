# Деплой

Инструкция по развёртыванию стека локально и на стенде, а также разбор типовых
сбоев при старте. Алгоритм и бизнес-логика описаны в
[solution/README.md](solution/README.md).

## Требования к машине

| Режим | RAM | CPU | Диск (свободно) | Примечание |
|---|---|---|---|---|
| Полный стек на стенде | **4 ГБ** | **2 vCPU** | **20 ГБ** | ORS в режиме `MMAP`, графы залиты готовыми; `ORS_TRANSIT=false` |
| Стек без ORS | **2 ГБ** | **2 vCPU** | **5 ГБ** | расстояния из `routing-cache` или по координатам |
| Сборка графов ORS | **12 ГБ** | **2 vCPU** | **30 ГБ** | heap ORS по умолчанию до 10 ГБ; OSM ЦФО ~0,9 ГБ |
| Только алгоритм | **512 МБ** | **1 CPU** | **1 ГБ** | Python >= 3.10, stdlib; лимит расчёта 5 с |

Подтверждённый минимум полного стека: **3,8 ГБ RAM, 2 vCPU** на одной ВМ.

Потребление в покое (режим стенда, `MMAP`, без public-transport у ORS):

| Контейнер | RAM |
|---|---|
| openrouteservice | 0,7-0,8 ГБ (потолок контейнера 2 ГБ; heap 512 МБ / 1 ГБ) |
| backend (FastAPI + планировщик) | ~80 МБ; с расписанием дня RAPTOR ~300 МБ |
| PostgreSQL 16 | ~40 МБ |
| frontend (nginx) | ~3 МБ |

Сборка графов на машине с 4 ГБ невозможна: документация ORS для трёх профилей ЦФО
запрашивает не менее 6 ГБ heap. На стенде графы готовятся на отдельной машине и
заливаются скриптом `solution/deploy/ors/upload-graphs.sh`.

ПО: Docker Engine и Compose v2. Свободные порты по умолчанию: `8080` (UI),
`8000` (API), `5432` (Postgres только на localhost), `8081` (ORS на localhost).

---

## Что поднимается

| Сервис | Образ / сборка | Порт с хоста | Профиль |
|---|---|---|---|
| Postgres 16 | `postgres:16-alpine` | `127.0.0.1:5432` | `local-db` |
| backend | `backend/Dockerfile` (+ planner из `solution/`) | `8000` | всегда |
| frontend | nginx + статика Vite | `8080` | всегда |
| ors-init | curl, готовит volume OSM/GTFS | нет | `ors` |
| ors | `openrouteservice:v10.0.0` | `127.0.0.1:8081` | `ors` |

Сеть compose: `lct-net`. Порт Postgres снаружи слушает только `127.0.0.1`; доступ
с рабочей станции: `ssh -L 5432:127.0.0.1:5432 ...`. Публиковать `0.0.0.0:5432`
не следует.

Volumes:

* `pgdata`: база данных
* `routing-cache`: кэш матриц и линий ORS (сохраняется между пересборками образа)
* `ors-data`: pbf и графы ORS

При старте backend (`entrypoint.sh`):

1. доливает новые пары в `routing-cache` из `solution/data/routing_cache.json`;
2. `alembic upgrade head`;
3. загружает профили rRAPTOR в Postgres (при наличии `transit_profiles.bin`);
4. запускает uvicorn на `:8000`.

Frontend проксирует `/api/`, `/docs`, `/redoc`, `/openapi.json` на backend.

---

## 1. Локальный полный стек

```bash
git clone <repo> && cd lct-beeline-task-2026
cp .env.example .env
```

Минимальный `.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/lct
DEBUG=false
BACKEND_PORT=8000
FRONTEND_PORT=8080
CORS_ORIGINS=["http://localhost:5173","http://localhost:8080"]
ORS_URL=http://ors:8082/ors
```

Пароль в URL необходимо URL-кодировать (`@` -> `%40`, `:` -> `%3A` и т.д.), иначе
asyncpg получит некорректный host.

Запуск приложения и собственной БД:

```bash
docker compose --profile local-db up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8080/api/catalogs/health
```

* UI: http://localhost:8080
* Swagger: http://localhost:8000/docs или http://localhost:8080/docs

При непрохождении healthcheck backend:

```bash
docker compose logs --tail=200 backend
docker compose logs --tail=100 db
```

Типичные причины:

* `DATABASE_URL` указывает на `localhost` внутри контейнера: требуется хост `db`
  (имя сервиса) или IP узла в сети compose;
* Postgres ещё не готов: healthcheck повторяет проверку, ожидание 10-20 с;
* порт занят: изменить `BACKEND_PORT` / `FRONTEND_PORT` в `.env`.

Остановка:

```bash
docker compose --profile local-db --profile ors down
# volumes (БД, кэш, графы) сохраняются
# полный сброс: docker compose --profile local-db --profile ors down -v
```

---

## 2. openrouteservice

Без ORS план строится: матрицы из volume `routing-cache`, отсутствующие пары по
координатам. Участки без геометрии на карте отображаются прямой или пунктиром.
Для линий по улицам необходим ORS.

### 2.1. Сборка графов на машине (>=12 ГБ RAM)

```bash
# в .env (значения из .env.example):
# ORS_XMS=4g  ORS_XMX=10g  ORS_MEM_LIMIT=16g
# ORS_GRAPHS_DATA_ACCESS=RAM_STORE  ORS_TRANSIT=true

docker compose --profile ors up -d
docker compose --profile ors logs -f ors
```

`ors-init` один раз загружает OSM ЦФО (~0,9 ГБ) и размещает GTFS/конфиг.
Первая сборка графов: **30-45 минут**, healthcheck с `start_period: 45m`.
До готовности ORS backend отвечает и считает план по кэшу.

Готовность:

```bash
curl -fsS http://127.0.0.1:8081/ors/v2/health
# {"status":"ready"}
```

Конфигурация и профили: [solution/deploy/ors/README.md](solution/deploy/ors/README.md).

### 2.2. Стенд 4 ГБ (готовые графы)

На машине стенда графы не собираются. Порядок:

1. Собрать графы на машине с >=12 ГБ RAM:
   `cd solution/deploy/ors && ./download-osm.sh && docker compose up -d`
2. Залить на стенд:
   ```bash
   ORS_START=0 ./upload-graphs.sh user@stand driving-car foot-walking cycling-regular
   ```
3. В `.env` / GitHub vars на стенде:
   ```env
   ORS_GRAPHS_DATA_ACCESS=MMAP
   ORS_XMS=512m
   ORS_XMX=1g
   ORS_MEM_LIMIT=2g
   ORS_TRANSIT=false
   ORS_URL=http://ors:8082/ors
   ```
4. `docker compose --profile ors up -d ors`

`MMAP` читает графы с диска через page cache ОС: контейнер занимает 0,7-0,8 ГБ
вместо 6+ ГБ. Профиль общественного транспорта у ORS отключён: расписание считает
RAPTOR в backend (профили в Postgres).

ORS на отдельной машине (nginx + API key): [solution/deploy/ors/REMOTE.md](solution/deploy/ors/REMOTE.md).
В этом случае `ORS_URL` указывает на удалённый инстанс, `ORS_API_KEY` задаёт токен;
локальный ors остаётся запасным (`ORS_FALLBACK_URL` выставляет deploy workflow).

---

## 3. Ручной деплой (docker compose)

Основной способ поднять стенд без GitHub Actions: репозиторий на машине,
файл `.env` в корне, `docker compose`. Workflow из п. 4 делает то же самое,
только собирает `.env` из GitHub vars/secrets.

### 3.1. Подготовка

```bash
git clone <repo> && cd lct-beeline-task-2026
# либо git pull на уже существующей копии
cp .env.example .env
chmod 600 .env
```

Файл `.env` в git не коммитится (см. `.gitignore`). Права `600`: пароли и ключи
API не должны быть readable для прочих пользователей ОС.

Перед первым запуском ORS на машине с 4 ГБ: залить готовые графы (п. 2.2).
Без графов и без ORS приложение стартует, линии на карте будут неполными.

### 3.2. Переменные и секреты в `.env`

Compose читает корневой `.env`. Значения с `$`, `%` и спецсимволами в пароле
лучше заключать в одинарные кавычки: `'...'` (compose не интерполирует их
содержимое). Пароль Postgres в `DATABASE_URL` обязан быть URL-encoded.

**Обязательные**

| Переменная | Секрет | Назначение |
|---|---|---|
| `DATABASE_URL` | да | `postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DB` |
| `POSTGRES_USER` | нет* | пользователь БД (нужен сервису `db` и для сборки URL) |
| `POSTGRES_PASSWORD` | да | пароль БД |
| `POSTGRES_DB` | нет* | имя БД |
| `POSTGRES_HOST` | нет | `db` при профиле `local-db`, иначе хост/IP внешнего Postgres |
| `POSTGRES_PORT` | нет | обычно `5432` |

\* не секрет сами по себе, но вместе с паролем задают доступ к БД.

Сборка `DATABASE_URL` (если пароль содержит `@`, `:`, `/`, `%`):

```bash
python3 - <<'PY'
from urllib.parse import quote
user, password, host, port, db = "postgres", "p@ss:word", "db", "5432", "lct"
print(
    "postgresql+asyncpg://"
    f"{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{db}"
)
PY
```

**Опциональные (приложение)**

| Переменная | Секрет | По умолчанию / стенд 4 ГБ | Назначение |
|---|---|---|---|
| `DEBUG` | нет | `false` | подробные ошибки API |
| `BACKEND_PORT` | нет | `8000` | порт API на хосте |
| `FRONTEND_PORT` | нет | `8080` | порт UI на хосте |
| `CORS_ORIGINS` | нет | `["http://localhost:8080"]` | JSON-массив origin'ов |
| `DADATA_API_KEY` | да | пусто | геокодирование (dadata.ru) |
| `DADATA_SECRET_KEY` | да | пусто | стандартизация адресов (платный режим DaData) |
| `GEOCODER_OSM_ENABLED` | нет | `true` | запасной геокодер Photon/Nominatim |

**Опциональные (ORS)**

| Переменная | Секрет | Стенд 4 ГБ | Сборка графов | Назначение |
|---|---|---|---|---|
| `ORS_URL` | нет | `http://ors:8082/ors` | то же | база ORS; пусто: только кэш/координаты |
| `ORS_API_KEY` | да | пусто | пусто | токен, если ORS за nginx на другой машине |
| `ORS_FALLBACK_URL` | нет | пусто* | пусто | запасной ORS при недоступности основного |
| `ORS_GRAPHS_DATA_ACCESS` | нет | `MMAP` | `RAM_STORE` | чтение графов с диска / в heap |
| `ORS_XMS` / `ORS_XMX` | нет | `512m` / `1g` | `4g` / `10g` | heap JVM |
| `ORS_MEM_LIMIT` | нет | `2g` | `16g` | потолок контейнера |
| `ORS_TRANSIT` | нет | `false` | `true` | профиль public-transport у ORS |

\* если `ORS_URL` указывает на удалённый инстанс, имеет смысл
`ORS_FALLBACK_URL=http://ors:8082/ors` (локальный контейнер как запасной).

### 3.3. Пример `.env` для стенда (4 ГБ, Postgres в compose)

```env
DATABASE_URL='postgresql+asyncpg://postgres:CHANGE_ME@db:5432/lct'
POSTGRES_USER='postgres'
POSTGRES_PASSWORD='CHANGE_ME'
POSTGRES_DB='lct'
POSTGRES_HOST='db'
POSTGRES_PORT='5432'

DEBUG='false'
BACKEND_PORT='8000'
FRONTEND_PORT='8080'
CORS_ORIGINS='["http://111.88.151.0:8080","http://localhost:8080"]'

ORS_URL='http://ors:8082/ors'
ORS_API_KEY=''
ORS_FALLBACK_URL=''
ORS_GRAPHS_DATA_ACCESS='MMAP'
ORS_XMS='512m'
ORS_XMX='1g'
ORS_MEM_LIMIT='2g'
ORS_TRANSIT='false'

DADATA_API_KEY=''
DADATA_SECRET_KEY=''
GEOCODER_OSM_ENABLED='true'
```

`CHANGE_ME` заменить на пароль; при спецсимволах сначала получить URL-encoded
форму (п. 3.2) и подставить её в `DATABASE_URL`. Origin в `CORS_ORIGINS`
должен совпадать с URL, по которому открывают UI.

Без DaData: оставить ключи пустыми. Геокодирование пойдёт через кэш
`solution/data/geocache.json` и OSM (медленнее на новых адресах).

### 3.4. Пример `.env` при внешнем Postgres

```env
DATABASE_URL='postgresql+asyncpg://lct_app:ENCODED_PASSWORD@10.0.0.5:5432/lct'
POSTGRES_USER='lct_app'
POSTGRES_PASSWORD='raw-password'
POSTGRES_DB='lct'
POSTGRES_HOST='10.0.0.5'
POSTGRES_PORT='5432'
# ... остальные ключи как в п. 3.3
```

Профиль `local-db` в этом случае не поднимать: хост `db` в сети compose
отсутствует. Сервис `backend` должен иметь сетевой доступ до `POSTGRES_HOST`.

### 3.5. Команды запуска

Из корня репозитория (рядом с `docker-compose.yml` и `.env`):

```bash
# 1. БД, если Postgres в compose
docker compose --profile local-db up -d --wait db

# 2. Приложение
docker compose up -d --build backend frontend

# 3. Проверка
docker compose ps
docker compose logs --tail=80 backend
curl -fsS "http://127.0.0.1:${BACKEND_PORT:-8000}/health"
curl -fsS "http://127.0.0.1:${FRONTEND_PORT:-8080}/api/catalogs/health"

# 4. ORS (после приложения; ждать ready не обязательно)
docker compose --profile ors up -d ors
docker compose --profile ors ps ors
```

Обновление уже развёрнутого стенда после `git pull`:

```bash
docker compose up -d --build backend frontend
# ORS пересобирать не нужно, если образ/графы не менялись
```

Остановка:

```bash
docker compose --profile local-db --profile ors down
# с удалением volumes (БД, кэш, графы): добавить -v
```

Важно: не экспортировать в shell пустые одноимённые переменные
(`export ORS_XMX=` и т.п.). Для compose переменные окружения процесса имеют
приоритет над `.env`; пустое значение из shell перебьёт файл и подставит
дефолт из `docker-compose.yml` (например `ORS_XMX=10g`).

### 3.6. Проверка после деплоя

```bash
curl -fsS http://127.0.0.1:8080/api/catalogs/health
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/docs -o /dev/null -w "%{http_code}\n"
docker compose ps
docker compose logs --tail=80 backend
```

При открытых портах: UI на `:8080`, API и Swagger на `:8000`.

---

## 4. Деплой через GitHub Actions

Автоматизация того же процесса, что в п. 3. Workflow:
[.github/workflows/deploy.yml](.github/workflows/deploy.yml).

Триггер: push в `main` (пути `backend/`, `frontend/`, `solution/planner/`,
compose, workflow) или `workflow_dispatch`. Runner: **self-hosted** на той же
машине, где выполняется compose.

### 4.1. Требования к runner

* Docker и compose plugin
* checkout репозитория (выполняет Actions)
* доступ к Docker socket без интерактивного sudo в job
* свободные `BACKEND_PORT` / `FRONTEND_PORT` (обычно 8000 / 8080)
* ресурсы по таблице в начале документа (полный стек: 4 ГБ / 2 vCPU)

### 4.2. Variables и secrets в GitHub

Имена совпадают с ключами `.env` (п. 3.2). Job собирает корневой `.env`,
URL-кодирует пароль в `DATABASE_URL`, снимает одноимённые переменные из
окружения job (чтобы пустые vars не перебили файл) и выполняет те же
`docker compose` команды, что в п. 3.5.

**Обязательные**

| Имя | Где | Пример |
|---|---|---|
| `POSTGRES_USER` | variable | `postgres` |
| `POSTGRES_PASSWORD` | secret | ... |
| `POSTGRES_DB` | variable | `lct` |
| `POSTGRES_HOST` | variable | `db` или IP внешнего PG |
| `POSTGRES_PORT` | variable | `5432` |

**Опциональные**

| Имя | Где | Назначение |
|---|---|---|
| `BACKEND_PORT` / `FRONTEND_PORT` | variable | порты на хосте |
| `CORS_ORIGINS` | variable | JSON-массив origin'ов UI |
| `DEBUG` | variable | `false` на стенде |
| `ORS_URL` | variable | `http://ors:8082/ors` или remote |
| `ORS_API_KEY` | secret | при remote за nginx |
| `ORS_XMS` / `ORS_XMX` / `ORS_MEM_LIMIT` | variable | см. п. 2.2 |
| `ORS_GRAPHS_DATA_ACCESS` | variable | `MMAP` / `RAM_STORE` |
| `ORS_TRANSIT` | variable | на стенде 4 ГБ: `false` |
| `DADATA_API_KEY` / `DADATA_SECRET_KEY` | secret | геокодер |
| `GEOCODER_OSM_ENABLED` | variable | `true` |

Проверка после job: те же `curl`, что в п. 3.6.

Ручной деплой и Actions взаимозаменяемы: достаточно поддерживать актуальный
`.env` на машине (Actions перезаписывает его при каждом запуске workflow).

---

## 5. Backend без compose (разработка)

```bash
docker compose --profile local-db up -d db

cd backend
python -m venv .venv && source .venv/bin/activate   # Win: .venv\Scripts\activate
pip install -r requirements.txt

# .env: DATABASE_URL на localhost, не db
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/lct

alembic upgrade head
# при необходимости профили транспорта:
# python -m core.load_transit_profiles ../solution/data/transit_profiles.bin

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Swagger: http://127.0.0.1:8000/docs

Пакет `planner` должен быть доступен по пути, как в Docker (каталог `solution/`
рядом). В образе пути заданы при сборке. Для локальной отладки интеграции
рекомендуется backend через compose, frontend через `npm run dev` с proxy на `:8000`.

---

## 6. Frontend без compose (разработка)

```bash
cd frontend
npm ci          # Node 24 LTS
npm run dev     # 127.0.0.1:5173, proxy /api → :8000
```

Production-сборка:

```bash
npm run build
npm run preview
```

В образе nginx раздаёт `dist/` и проксирует API/Swagger на `backend:8000`
(`frontend/nginx.conf`).

---

## 7. Только алгоритм (без UI и БД)

```bash
cd solution
python -m pytest tests -q
python viz/export.py --region east    # при необходимости артефакт плана
```

Зависимости: стандартная библиотека Python и pytest. Тот же код подключается
в backend.

Минимальные требования: Python >= 3.10, 512 МБ RAM, 1 CPU. Внешних MIP/CP-солверов,
GPU и сетевых ключей нет.

---

## 8. Демо-данные на стенде

Порядок из [demo-scenarios/SCENARIOS.md](demo-scenarios/SCENARIOS.md):

1. Персонал → бригада Юго-восток → импорт `00-engineers-southeast.csv`
   (либо `python -m modules.personnel.seed_southeast` из каталога `backend/`).
2. Обзор дня → загрузка `01-southeast-full.csv` или `02-southeast-mini.csv`,
   уровень «Свободный».
3. Ожидание фонового расчёта → Гант / карта / сравнение.
4. События: аварийная заявка, отмена, «недоступен с ...».

Дата в сценарии задана явно; актуальную дату брать из `SCENARIOS.md`.

---

## 9. Типовые поломки

| Симптом | Действие |
|---|---|
| frontend up, API 502 | `docker compose logs backend`; миграции; `DATABASE_URL` |
| `gaierror` / wrong host в asyncpg | пароль с `@:` не закодирован; host = `db` в compose |
| пустые регионы / 500 на catalogs | миграции не применились; лог `Running migrations...` |
| план есть, линии на карте прямые | ORS не ready или нет кэша; штатно на старте |
| ORS OOM / процесс без ответа | режим стенда: MMAP + залитые графы; в compose уже `-XX:+ExitOnOutOfMemoryError` |
| геокод новых адресов медленный | нет `DADATA_API_KEY`, OSM; известные адреса из `geocache.json` |
| деплой Actions: missing settings | не заданы `POSTGRES_*` vars/secret |
| два расчёта одного дня | API отвечает 409, пока занят `background`; дождаться завершения |

Откат: на runner выполнить `git checkout <sha>` и
`docker compose up -d --build backend frontend` с тем же `.env`. Volumes
очищать не требуется.

---

## 10. Сводка по режимам ORS

| Параметр | Стенд 4 ГБ | Машина сборки графов |
|---|---|---|
| `ORS_GRAPHS_DATA_ACCESS` | `MMAP` | `RAM_STORE` |
| `ORS_XMS` / `ORS_XMX` | `512m` / `1g` | `4g` / `10g` |
| `ORS_MEM_LIMIT` | `2g` | `16g` |
| `ORS_TRANSIT` | `false` | `true` (по необходимости) |
| Источник графов | `upload-graphs.sh` | локальная сборка 30-45 мин |

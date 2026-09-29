# Помощник диспетчера «Билайн Бизнес»

Кейс ЛЦТ 2026: планирование маршрутов выездных инженеров с учётом окон клиента,
навыков, транспорта и обеда.

Сервис принимает заявки и инженеров, считает план дня, рисует Гант и карту,
перестраивает день при событиях и объясняет назначение (или причину отказа).

| | |
|---|---|
| Стенд | http://111.88.151.0:8080 |
| API / Swagger | http://111.88.151.0:8000/docs (через UI: `/docs`) |
| Алгоритм | [solution/README.md](solution/README.md) |
| Контракт планировщика | [solution/SPEC.md](solution/SPEC.md) |
| Деплой | [DEPLOY.md](DEPLOY.md) |
| Демо-сценарий | [demo-scenarios/SCENARIOS.md](demo-scenarios/SCENARIOS.md) |
| Защита (кратко) | [solution/PRESENTATION.md](solution/PRESENTATION.md) |

---

## Требования к машине

| Режим | RAM | CPU | Диск (свободно) | ПО |
|---|---|---|---|---|
| Полный стек на стенде (Postgres + backend + frontend + ORS в режиме MMAP, графы залиты готовыми) | **4 ГБ** | **2 vCPU** | **20 ГБ** | Docker Engine, Compose v2 |
| Тот же стек без ORS (расстояния из кэша / по координатам) | **2 ГБ** | **2 vCPU** | **5 ГБ** | Docker Engine, Compose v2 |
| Сборка графов ORS с нуля (профили driving-car, foot-walking, cycling-regular по ЦФО) | **12 ГБ** | **2 vCPU** | **30 ГБ** | Docker Engine, Compose v2 |
| Только алгоритм (`solution/planner`) | **512 МБ** | **1 CPU** | **1 ГБ** | Python **>= 3.10** |

На стенде подтверждена работа полного стека при **3,8 ГБ RAM / 2 vCPU** (ORS: `MMAP`, heap 512 МБ / 1 ГБ, `mem_limit` 2 ГБ, без профиля public-transport у ORS; транспорт считает RAPTOR в backend).

Планировщик использует стандартную библиотеку Python, внешних солверов нет.
Лимит поиска плана по умолчанию: **5 с** на расчёт (`time_limit_seconds`).

Подробности по памяти контейнеров и режимам ORS: [DEPLOY.md](DEPLOY.md#требования-к-машине).

---

## Состав репозитория

```
backend/          FastAPI + Postgres (Alembic)
frontend/         React 19 + Vite + MapLibre
solution/         планировщик (чистый Python), ORS, тесты, SPEC
demo-scenarios/   CSV/JSON для прогона на стенде
docs/             база знаний по данным и требованиям
docker-compose.yml
```

Планировщик находится в `solution/planner/` и не зависит от FastAPI/БД. Backend
подключает его как библиотеку и отдаёт результат во фронт.

Описание алгоритма (regret-вставка, локальный поиск, перепланирование, ORS,
RAPTOR), метрики по контрольным выгрузкам и соответствие ТЗ:
**[solution/README.md](solution/README.md)**.

---

## Быстрый старт (локально)

Необходимы Docker и Docker Compose v2. Порты по умолчанию: `8080`, `8000`, `5432`.

```bash
cp .env.example .env
# в .env задать, например:
#   DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/lct

docker compose --profile local-db up -d --build
```

Адреса после старта:

* UI: http://localhost:8080
* Swagger: http://localhost:8000/docs (либо http://localhost:8080/docs)

Проверка:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8080/api/catalogs/health
```

ORS (матрицы и линии авто/пешком/велосипед) поднимается профилем `ors`.
Первая сборка графов на машине занимает 30-45 минут и требует не менее 12 ГБ RAM:

```bash
docker compose --profile ors up -d
```

На стенде (4 ГБ) графы собираются на отдельной машине и заливаются готовыми;
порядок описан в [DEPLOY.md](DEPLOY.md).

Демонстрационный прогон: [demo-scenarios/SCENARIOS.md](demo-scenarios/SCENARIOS.md).

---

## Разработка без Docker

**Backend** (Postgres уже доступен, например через `docker compose --profile local-db up -d db`):

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # DATABASE_URL → localhost, не host db
alembic upgrade head
uvicorn main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm ci
npm run dev    # http://127.0.0.1:5173, /api → :8000
```

**Только алгоритм:**

```bash
cd solution
python -m pytest tests -q
```

---

## API

Все эндпоинты под префиксом `/api`. Интерактивная схема: Swagger UI
(`/docs`) и ReDoc (`/redoc`). Сырой OpenAPI: `/openapi.json`.

| Тег | Префикс | Назначение |
|---|---|---|
| catalogs | `/api/catalogs` | регионы, health |
| personnel | `/api/personnel` | бригады, инженеры, адреса |
| tickets | `/api/tickets` | загрузка и список заявок |
| planning | `/api/planning` | план дня, пересчёт, события, Гант |

Авторизация в прототипе не требуется.

---

## Переменные окружения

Файл [.env.example](.env.example). Обязателен `DATABASE_URL`
(`postgresql+asyncpg://...`). Остальное опционально:

* `ORS_URL`: openrouteservice; пустое значение: кэш / координаты
* `DADATA_API_KEY`: геокодирование новых адресов; без ключа: кэш + OSM
* `CORS_ORIGINS`: JSON-массив или список через запятую

Полный список и значения для стенда: [DEPLOY.md](DEPLOY.md).

---

## Деплой

Два равноценных способа:

1. **Вручную:** `.env` в корне (переменные и секреты) + `docker compose`
   ([DEPLOY.md](DEPLOY.md#3-ручной-деплой-docker-compose)).
2. **GitHub Actions** (self-hosted runner при пуше в `main`): собирает тот же
   `.env` из vars/secrets и выполняет те же команды compose
   ([DEPLOY.md](DEPLOY.md#4-деплой-через-github-actions)).

ORS, экономный режим 4 ГБ, заливка графов: [DEPLOY.md](DEPLOY.md).
ORS отдельно: [solution/deploy/ors/README.md](solution/deploy/ors/README.md).

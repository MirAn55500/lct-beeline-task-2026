# Backend

FastAPI + SQLModel + Alembic. Планировщик подключается из `../solution/planner`
(в Docker: `COPY --from=solution`).

## Запуск

Через корневой compose, см. [../DEPLOY.md](../DEPLOY.md).
Локально без контейнера backend:

```bash
pip install -r requirements.txt
# DATABASE_URL в .env → Postgres на localhost
alembic upgrade head
uvicorn main:app --reload --port 8000
```

## Swagger / OpenAPI

После старта:

| URL | Что |
|---|---|
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/redoc | ReDoc |
| http://localhost:8000/openapi.json | схема |

В полном стеке те же пути доступны через frontend: http://localhost:8080/docs.

Теги в схеме: `catalogs`, `personnel`, `tickets`, `planning`, `system`.
Описание методов в docstring'ах роутеров; тела запросов/ответов в Pydantic
схемах `modules/*/schemas.py`.

Экспорт схемы без UI (нужен поднятый процесс или импорт приложения):

```bash
python -c "from main import app; import json; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > openapi.json
```

## Модули

| Пакет | Префикс |
|---|---|
| `modules.catalogs` | `/api/catalogs` |
| `modules.personnel` | `/api/personnel` |
| `modules.tickets` | `/api/tickets` |
| `modules.planning` | `/api/planning` |
| `modules.geocoding` | используется из personnel/tickets, отдельного роутера нет |

Миграции: `alembic/`. Конфиг: `core/config.py` (env / `.env`).

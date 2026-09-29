"""Точка входа FastAPI.

Swagger UI: /docs  ·  ReDoc: /redoc  ·  схема: /openapi.json
Через frontend-nginx те же пути проксируются с :8080.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.router import api_router
from core.config import get_settings
from core.database import engine
from core.exceptions import register_exception_handlers
from modules.geocoding import suggest as address_suggest
from modules.geocoding.recheck import recheck_addresses
from modules.planning import routing_cache

# Сообщения модулей (геокодер, маршрутизация) пишутся в лог контейнера рядом с uvicorn
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # строка на каждый запрос к DaData

OPENAPI_TAGS = [
    {
        "name": "catalogs",
        "description": "Справочники: регионы присутствия, health модуля.",
    },
    {
        "name": "personnel",
        "description": (
            "Бригады и инженеры: CRUD, импорт CSV/JSON, подсказки адресов "
            "и обратное геокодирование."
        ),
    },
    {
        "name": "tickets",
        "description": (
            "Заявки: список/фильтры, ручное создание (в т.ч. авария), "
            "загрузка файла с фоновым пересчётом плана."
        ),
    },
    {
        "name": "planning",
        "description": (
            "Планы дня: обзор и метрики, пересчёт, события перепланирования, "
            "выгрузка для Ганта/карты, окна вставки и ручные ходы."
        ),
    },
    {
        "name": "system",
        "description": "Служебные эндпоинты процесса (вне /api).",
    },
]

APP_DESCRIPTION = """
REST API помощника диспетчера (ЛЦТ 2026, «Билайн Бизнес»).

Префикс бизнес-методов: `/api`. Авторизация в прототипе не нужна.

Типовой поток:
1. `POST /api/personnel/engineers/upload`: инженеры бригады;
2. `POST /api/tickets/upload`: заявки (расчёт плана уходит в фон);
3. `GET /api/planning/day-overview`: статус и метрики;
4. `GET /api/planning/plan`: маршруты для Ганта и карты.

Алгоритм планирования: пакет `solution/planner` (см. README в `solution/`).
""".strip()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # В фоне: старт и healthcheck не ждут геокодера
    recheck = asyncio.create_task(recheck_addresses())
    warm = asyncio.create_task(address_suggest.warm_up())
    # Кэш маршрутов (15 МБ JSON) грузим в память сразу, а не первым ходом на Ганте
    routes = asyncio.create_task(asyncio.to_thread(routing_cache.shared))
    yield
    recheck.cancel()
    warm.cancel()
    routes.cancel()
    # Отложенная запись кэша маршрутов до выхода
    await asyncio.to_thread(routing_cache.close)
    await address_suggest.close()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Помощник диспетчера · API",
        description=APP_DESCRIPTION,
        version="1.0.0",
        lifespan=lifespan,
        openapi_tags=OPENAPI_TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        swagger_ui_parameters={
            "docExpansion": "list",
            "defaultModelsExpandDepth": 1,
            "displayRequestDuration": True,
            "filter": True,
        },
    )
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health", tags=["system"], summary="Liveness")
    async def health() -> dict[str, str]:
        """Процесс жив. Не проверяет БД и ORS; для этого модульные `/api/*/health`."""
        return {"status": "ok"}

    return app


app = create_app()

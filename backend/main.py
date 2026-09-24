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
from modules.geocoding.recheck import recheck_addresses
from modules.planning import transit_warmup

# Сообщения модулей (геокодер, маршрутизация) — в лог контейнера рядом с uvicorn
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # строка на каждый запрос к DaData


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # В фоне: старт и healthcheck не ждут геокодера
    recheck = asyncio.create_task(recheck_addresses())
    warmup = asyncio.create_task(transit_warmup.worker())
    yield
    recheck.cancel()
    warmup.cancel()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

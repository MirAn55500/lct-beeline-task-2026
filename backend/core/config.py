from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "lct-beeline-backend"
    debug: bool = False
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/lct"
    cors_origins: list[str] = ["http://localhost:5173"]
    # openrouteservice (solution/deploy/ors). Пусто — расчёт на кэше маршрутов или по координатам
    ors_url: str | None = None
    # Токен ORS на отдельной машине (nginx перед ним проверяет заголовок Authorization)
    ors_api_key: str | None = None
    # Параллельных запросов фонового досчёта расписаний: 2 — ORS на стенде рядом с
    # backend; на отдельной машине под ORS — 6-8
    transit_workers: int = 2
    # Где хранить кэш ответов ORS; не задан — solution/data/routing_cache.json
    routing_cache_path: str | None = None
    # Геокодирование: DaData (ключ с dadata.ru; секрет включает стандартизацию), резерв — OSM
    dadata_api_key: str | None = None
    dadata_secret_key: str | None = None
    geocoder_osm_enabled: bool = True
    geocoder_user_agent: str = "lct-beeline-planner/1.0"
    geocoder_timeout: float = 10.0

    @field_validator("database_url", mode="before")
    @classmethod
    def use_asyncpg_driver(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        for prefix in (
            "postgresql+psycopg2://",
            "postgresql+psycopg://",
            "postgresql://",
            "postgres://",
        ):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                import json

                return json.loads(raw)
            return [item.strip() for item in raw.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

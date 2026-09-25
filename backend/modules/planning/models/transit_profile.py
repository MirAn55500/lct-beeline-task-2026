from sqlalchemy import Column, Integer, LargeBinary, SmallInteger, String
from sqlmodel import Field

from core.base_model import BaseTable


class TransitFeed(BaseTable, table=True):
    """Версия фида GTFS, для которой в базе лежат профили rRAPTOR, и их окно выезда."""

    __tablename__ = "transit_feed"

    feed_version: str = Field(sa_column=Column(String(16), primary_key=True))
    first_second: int = Field(sa_column=Column(Integer, nullable=False))
    last_second: int = Field(sa_column=Column(Integer, nullable=False))
    pairs: int = Field(sa_column=Column(Integer, nullable=False))
    source: str = Field(sa_column=Column(String(16), nullable=False))
    """Хэш загруженного файла профилей: пересчитанный файл того же фида — другой хэш."""


class TransitProfile(BaseTable, table=True):
    """Профиль rRAPTOR пары точек: время в пути на любой момент выезда (planner.transit_profiles)."""

    __tablename__ = "transit_profile"

    feed_version: str = Field(sa_column=Column(String(16), primary_key=True))
    weekday: int = Field(sa_column=Column(SmallInteger, primary_key=True))
    origin: str = Field(sa_column=Column(String(32), primary_key=True))
    dest: str = Field(sa_column=Column(String(32), primary_key=True))
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))

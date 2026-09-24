from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    module: str
    status: str


class CounterPair(BaseModel):
    assigned: int | None = None
    total: int


class EngineersCounter(BaseModel):
    engaged: int | None = None
    total: int


class RemakeLevel(StrEnum):
    """Уровень перестроения плана (Figma: Фикс / Инженерный / Свободный)."""

    FIX = "fix"
    ENGINEER = "engineer"
    FREE = "free"


class Distribution(StrEnum):
    """Распределение заявок (Figma: Равномерное / Эффективное)."""

    EVEN = "even"
    EFFICIENT = "efficient"


class RecalculateResponse(BaseModel):
    plan_id: int
    version: int
    assigned: int
    unassigned: int


class PlanVersionResponse(BaseModel):
    plan_id: int
    version: int
    created_at: datetime


class DayOverviewResponse(BaseModel):
    plan_id: int | None = None
    plan_version: int | None = None
    has_plan: bool
    tickets: CounterPair
    engineers: EngineersCounter
    planned_dates: list[date] = Field(default_factory=list)
    plans: list[PlanVersionResponse] = Field(default_factory=list)

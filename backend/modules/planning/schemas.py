from datetime import date, datetime

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

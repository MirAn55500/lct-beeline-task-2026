from datetime import date, datetime, time
from enum import StrEnum
from typing import Literal

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
    """Распределение заявок (Figma: Базовое / Эффективное)."""

    EVEN = "even"
    EFFICIENT = "efficient"


class ComparisonLine(BaseModel):
    label: str
    baseline: str
    optimized: str
    verdict: str


class PlanComparison(BaseModel):
    """Базовый алгоритм против сохранённого плана. Критерий — в `summary`."""

    summary: str
    lines: list[ComparisonLine] = Field(default_factory=list)


class RecalculateResponse(BaseModel):
    plan_id: int
    version: int
    assigned: int
    unassigned: int
    comparison: PlanComparison | None = None


class PlanVersionResponse(BaseModel):
    plan_id: int
    version: int
    created_at: datetime
    """even — базовый, efficient — эффективный; null у старых версий."""
    distribution: Literal["even", "efficient"] | None = None


class DayOverviewResponse(BaseModel):
    plan_id: int | None = None
    plan_version: int | None = None
    has_plan: bool
    tickets: CounterPair
    engineers: EngineersCounter
    planned_dates: list[date] = Field(default_factory=list)
    plans: list[PlanVersionResponse] = Field(default_factory=list)
    planning: bool = False
    """План на этот день считается в фоне после загрузки заявок."""
    planning_error: str | None = None
    planning_eta_seconds: int | None = None
    """Примерно через сколько секунд фоновый расчёт закончится (с очередью других дней)."""
    """Почему последний фоновый расчёт не удался."""
    rebuild_eta_seconds: int | None = None
    """Примерно сколько секунд займёт «Обновить план» — для индикатора, пока он идёт."""
    travel_minutes: float | None = None
    distance_km: float | None = None


# --- План дня для карты и Ганта: та же форма, что у выгрузки планировщика в моках
# frontend (frontend/src/features/planning/mocks/index.ts, тип PlanExport). Координаты —
# [lon, lat], времена — ISO в поясе региона.


class PlanEngineerExport(BaseModel):
    id: str
    name: str
    start: list[float]
    workIntervals: list[list[str]]
    skills: list[str]
    skillLevels: list[list[str]] = Field(default_factory=list)
    transport: str
    equipment: list[str] = Field(default_factory=list)


class PlanRequestExport(BaseModel):
    id: str
    point: list[float]
    window: list[str]
    address: str
    type: str
    skill: str
    duration: int
    priority: str
    equipment: list[str] = Field(default_factory=list)


class PlanVisitExport(BaseModel):
    requestId: str
    geometryRange: list[int] | None = None
    departureAt: str
    arrivalAt: str
    serviceStartAt: str
    serviceEndAt: str
    travelMinutes: float
    distanceKm: float
    waitingMinutes: float
    idleMinutes: float
    transit: list[str] = Field(default_factory=list)
    explanation: str = ""


class PlanLunchExport(BaseModel):
    """Обед в маршруте: после скольких визитов, когда и где."""

    afterPosition: int
    departureAt: str
    arrivalAt: str
    startAt: str
    endAt: str
    travelMinutes: float = 0.0
    distanceKm: float = 0.0
    place: str = "last_request"
    """last_request — у последней заявки, office — в офисе, point — в своей точке."""
    address: str = ""
    point: list[float]
    detour: bool = False
    """К месту обеда своя дорога (офис, своя точка) — у неё свой срез линии маршрута."""
    locked: bool = False
    geometryRange: list[int] | None = None
    transit: list[str] = Field(default_factory=list)


class PlanRouteExport(BaseModel):
    engineerId: str
    startAt: str | None
    endAt: str | None
    utilization: float
    geometrySource: str = "straight"
    polyline: list[list[float]]
    geometry: list[list[float]] = Field(default_factory=list)
    visits: list[PlanVisitExport]
    lunch: PlanLunchExport | None = None


class PlanUnassignedExport(BaseModel):
    requestId: str
    reason: str
    explanation: str


class PlanExportResponse(BaseModel):
    planId: int
    version: int
    key: str
    region: str
    date: date
    engineers: list[PlanEngineerExport]
    requests: list[PlanRequestExport]
    routes: list[PlanRouteExport]
    unassigned: list[PlanUnassignedExport]


# --- Ручная правка плана на Ганте. Времена — минуты от полуночи дня плана в поясе региона,
# как на ленте Ганта.


class RequestSlotsExport(BaseModel):
    requestId: str
    movable: bool
    reason: str = ""
    slots: dict[str, list[list[float]]] = Field(
        default_factory=dict,
        description="engineerId → [[позиция, раньше всего, позже всего, выезд, минут в пути], …]",
    )
    refusals: dict[str, str] = Field(default_factory=dict)


class PlanSlotsResponse(BaseModel):
    planId: int
    requests: list[RequestSlotsExport]


class MoveRequest(BaseModel):
    requestId: str
    engineerId: str | None = None
    start: float | None = Field(default=None, description="Начало работ; без него — лучшее место в окне клиента")
    position: int | None = Field(default=None, description="Место в маршруте с 0; без него — по времени")
    release: list[str] = Field(default_factory=list, description="Снять с маршрутов, чтобы освободить место")
    commit: bool = Field(default=False, description="false — только проверка с превью, true — новая версия плана")


class MoveVisitExport(BaseModel):
    requestId: str
    engineerId: str
    position: int
    departure: float
    arrival: float
    start: float
    end: float
    travelMinutes: float


class MoveLunchExport(BaseModel):
    """Обед после хода: обед сам уезжает, если заявку поставили на его время."""

    engineerId: str
    afterPosition: int
    departure: float
    arrival: float
    start: float
    end: float


class MoveResponse(BaseModel):
    ok: bool
    reason: str = ""
    outsideWindow: bool = False
    windowShift: float = Field(
        default=0.0,
        description="На сколько минут переехало окно клиента: согласованное время — новое окно той же длины",
    )
    engineers: list[str] = Field(default_factory=list)
    visits: list[MoveVisitExport] = Field(default_factory=list)
    released: list[str] = Field(default_factory=list)
    lunches: list[MoveLunchExport] = Field(
        default_factory=list,
        description="Обеды изменившихся маршрутов; у кого из engineers обеда здесь нет — обеда нет",
    )
    planId: int | None = None
    version: int | None = None


class PlanEventType(StrEnum):
    CANCEL_REQUEST = "cancel_request"
    ENGINEER_UNAVAILABLE = "engineer_unavailable"


class PlanEventRequest(BaseModel):
    type: Literal["cancel_request", "engineer_unavailable"]
    request_id: int | None = None
    engineer_id: int | None = None
    at: time | None = Field(
        default=None,
        description="Местное время события. Без него — 12:00 дня плана",
    )


class PlanEventResponse(BaseModel):
    plan_id: int
    version: int
    assigned: int
    unassigned: int
    summary: str
    warnings: list[str] = Field(default_factory=list)

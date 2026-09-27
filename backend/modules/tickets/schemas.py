from datetime import date as date_type, datetime, time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from modules.planning.schemas import RemakeLevel


class HealthResponse(BaseModel):
    module: str
    status: str


class UploadTicketsResult(BaseModel):
    created: int
    updated: int
    skipped: int
    date: date_type | None = None
    planning: bool = False
    """План на даты из файла поставлен в расчёт; готовность — `planning` в обзоре дня."""
    planning_eta_seconds: int | None = None
    """Примерно сколько секунд считаться плану на `date` — вместе с днями перед ним в очереди."""


class CreateTicketRequest(BaseModel):
    """Одна заявка из окна «Добавить заявку»: адрес, окно клиента, тип работ."""

    region_id: int = Field(ge=1)
    date: date_type
    address: str = Field(min_length=1, max_length=300)
    start: time
    end: time
    work_type: str
    """Подключение / Дозаказ / Ремонт / Аварийные работы."""
    remake_level: RemakeLevel = RemakeLevel.FIX


class CreateTicketResult(UploadTicketsResult):
    number: str
    """Номер новой заявки."""


class TicketAssignmentFilter(StrEnum):
    ALL = "all"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    category: str
    reason: str | None = None
    reason_hint: str | None = None
    engineer: str | None = None
    assigned: bool = False
    window: str
    window_start: datetime
    window_end: datetime
    address: str
    status: str | None = None
    hd: str | None = None
    district: str | None = None


class TicketsQuery(BaseModel):
    region_id: int = Field(ge=1)
    date: date_type
    plan_id: int | None = Field(default=None, ge=1)
    assignment: TicketAssignmentFilter = TicketAssignmentFilter.ALL
    q: str | None = None
    work_type: list[str] = Field(default_factory=list)
    reason: list[str] = Field(default_factory=list)
    time_from: time | None = None
    time_to: time | None = None

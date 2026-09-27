from datetime import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    module: str
    status: str


class QualificationFilter(StrEnum):
    MASTER = "master"
    WORKER = "worker"
    NOVICE = "novice"


class BrigadeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    number: str
    region_id: int
    engineers_count: int = 0
    leader_name: str | None = None
    leader_short_name: str | None = None
    office_address: str | None = None
    office_lat: float | None = None
    office_lon: float | None = None
    start_work: time | None = None
    end_work: time | None = None
    work_days: list[int] = Field(default_factory=list)
    """ISO-номера рабочих дней недели: 1 — понедельник, 7 — воскресенье."""
    in_planning: bool = True
    area_ids: list[int] = Field(default_factory=list)


class AreaResponse(BaseModel):
    id: int
    name: str


class UpdateBrigadeRequest(BaseModel):
    """Карточка «Управление бригадой»: всё, что в ней есть, приходит целиком."""

    name: str = Field(min_length=1, max_length=100)
    office_address: str = Field(min_length=3, max_length=300)
    # Точка, поставленная на карте: тогда адрес — только подпись, геокодер не нужен
    office_lat: float | None = Field(default=None, ge=-90, le=90)
    office_lon: float | None = Field(default=None, ge=-180, le=180)
    area_ids: list[int] = Field(default_factory=list)
    work_days: list[int] = Field(min_length=1)
    start_work: time
    end_work: time
    in_planning: bool = True


class AddressSuggestionResponse(BaseModel):
    address: str
    lat: float
    lon: float
    has_house: bool
    """С номером дома — только такой адрес годится для офиса."""


class ReverseGeocodeResponse(BaseModel):
    address: str | None = None
    """Ближайший адрес; None — по точке ничего не нашлось."""
    has_house: bool = False
    """В адресе есть дом — только такой годится для офиса."""


class UpdateBrigadeResponse(BrigadeResponse):
    rescheduled_engineers: int = 0
    """Скольким инженерам рабочий день переставлен вслед за бригадой."""
    office_moved: bool = False
    """Офис переехал — у инженеров новая точка старта."""


class EngineerResponse(BaseModel):
    """Карточка инженера для обзора дня и страницы «Персонал»."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    brigade_id: int
    transport: str
    transport_label: str
    # Первый навык — для компактной карточки обзора дня.
    skill: str | None = None
    skills: list[str] = Field(default_factory=list)
    skill_labels: list[str] = Field(default_factory=list)
    qualification: str | None = None
    position: str | None = None
    qualification_hint: str | None = None
    is_lead: bool = False
    start_work: time | None = None
    end_work: time | None = None
    brigade_name: str | None = None


class EngineersQuery(BaseModel):
    region_id: int | None = Field(default=None, ge=1)
    brigade_id: int | None = Field(default=None, ge=1)
    q: str | None = None
    qualification: list[str] = Field(default_factory=list)
    skill: list[str] = Field(default_factory=list)
    transport: list[str] = Field(default_factory=list)


class CreateEngineerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brigade_id: int = Field(ge=1)
    transport: str = Field(min_length=1)
    # Пока не используется в планировании — опционально.
    qualification: QualificationFilter | None = None
    skills: list[str] = Field(min_length=1)
    start_work: time
    end_work: time
    is_lead: bool = False


class PersonnelFilterOptions(BaseModel):
    skills: list[str]
    transports: list[str]
    qualifications: list[str] = Field(default_factory=list)

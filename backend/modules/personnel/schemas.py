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


class LunchPlace(StrEnum):
    """Где обедают."""

    LAST_REQUEST = "last_request"
    """У последней заявки — там, где закончили работу, без лишней дороги."""
    OFFICE = "office"
    POINT = "point"
    """В своей точке: адрес или место на карте."""


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
    area_ids: list[int] = Field(default_factory=list)
    lunch_start: time | None = None
    lunch_end: time | None = None
    """Окно обеда: час внутри него, когда именно — решает планировщик."""
    lunch_place: LunchPlace = LunchPlace.LAST_REQUEST
    lunch_address: str | None = None
    lunch_lat: float | None = None
    lunch_lon: float | None = None
    """Место обеда «в своей точке»; для остальных мест пусто."""


class AreaResponse(BaseModel):
    id: int
    name: str


class UpdateBrigadeRequest(BaseModel):
    """Карточка «Управление бригадой»: всё, что в ней есть, приходит целиком.
    Название бригады не редактируется."""

    office_address: str = Field(min_length=3, max_length=300)
    # Точка, поставленная на карте: тогда адрес — только подпись, геокодер не нужен
    office_lat: float | None = Field(default=None, ge=-90, le=90)
    office_lon: float | None = Field(default=None, ge=-180, le=180)
    area_ids: list[int] = Field(default_factory=list)
    work_days: list[int] = Field(min_length=1)
    start_work: time
    end_work: time
    lunch_start: time = time(13, 0)
    lunch_end: time = time(14, 0)
    lunch_place: LunchPlace = LunchPlace.LAST_REQUEST
    # Для «в своей точке»: адрес из подсказок или точка на карте
    lunch_address: str | None = Field(default=None, max_length=300)
    lunch_lat: float | None = Field(default=None, ge=-90, le=90)
    lunch_lon: float | None = Field(default=None, ge=-180, le=180)


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
    """Скольким инженерам рабочий день переставлен вслед за бригадой (у кого нет своей смены)."""
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
    own_schedule: bool = False
    """Своя смена; без неё инженер работает по часам бригады."""
    work_days: list[int] = Field(default_factory=list)
    """Рабочие дни инженера (ISO): свои или бригады."""
    own_work_days: bool = False
    """Свой график; без него дни идут за бригадой."""
    lunch_start: time | None = None
    lunch_end: time | None = None
    own_lunch_time: bool = False
    """Своё окно обеда; без него — как у бригады."""
    lunch_place: LunchPlace = LunchPlace.LAST_REQUEST
    own_lunch_place: bool = False
    """Своё место обеда; без него — как у бригады."""
    lunch_address: str | None = None
    lunch_lat: float | None = None
    lunch_lon: float | None = None
    home_address: str | None = None
    brigade_name: str | None = None


class EngineersQuery(BaseModel):
    region_id: int | None = Field(default=None, ge=1)
    brigade_id: int | None = Field(default=None, ge=1)
    q: str | None = None
    qualification: list[str] = Field(default_factory=list)
    skill: list[str] = Field(default_factory=list)
    transport: list[str] = Field(default_factory=list)


class EngineerFields(BaseModel):
    """Поля формы инженера — одни и те же при добавлении и редактировании."""

    name: str = Field(min_length=1, max_length=200)
    brigade_id: int = Field(ge=1)
    transport: str = Field(min_length=1)
    # Пока не используется в планировании — опционально.
    qualification: QualificationFilter | None = None
    skills: list[str] = Field(min_length=1)
    home_address: str | None = Field(default=None, max_length=300)
    # Без часов — рабочий день бригады, и он дальше меняется вместе с бригадой
    start_work: time | None = None
    end_work: time | None = None
    # Без дней — рабочие дни бригады
    work_days: list[int] | None = None
    # Без окна обеда — окно бригады, без места — место бригады
    lunch_start: time | None = None
    lunch_end: time | None = None
    lunch_place: LunchPlace | None = None
    lunch_address: str | None = Field(default=None, max_length=300)
    lunch_lat: float | None = Field(default=None, ge=-90, le=90)
    lunch_lon: float | None = Field(default=None, ge=-180, le=180)


class CreateEngineerRequest(EngineerFields):
    is_lead: bool = False


class UpdateEngineerRequest(EngineerFields):
    """Карточка инженера целиком: не переданные часы и дни — как у бригады."""


class PersonnelFilterOptions(BaseModel):
    skills: list[str]
    transports: list[str]
    qualifications: list[str] = Field(default_factory=list)

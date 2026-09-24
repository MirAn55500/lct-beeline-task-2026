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
    is_lead: bool = False
    start_work: time | None = None
    end_work: time | None = None


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

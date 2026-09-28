from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.dictionary import Dictionary
    from modules.personnel.models.engineer import Engineer
    from modules.planning.models.plan import Plan
    from modules.planning.models.route import Route
    from modules.tickets.models.request import Request


class Assignment(BaseTable, table=True):
    """Назначение на заявку.

    Assigned: engineer_id заполнен, unassigned_reason_id пуст.
    Unassigned: engineer_id/transport_id пусты, unassigned_reason_id заполнен.
    """

    __tablename__ = "assignments"

    assignment_id: Optional[int] = Field(default=None, primary_key=True)
    request_id: int = Field(foreign_key="requests.request_id")
    engineer_id: Optional[int] = Field(default=None, foreign_key="engineers.engineer_id")
    plan_id: int = Field(foreign_key="plans.plan_id")
    transport_id: Optional[int] = Field(default=None, foreign_key="dicts.dict_id")
    unassigned_reason_id: Optional[int] = Field(
        default=None, foreign_key="dicts.dict_id"
    )
    actual_start_time: Optional[datetime] = Field(default=None)
    actual_end_time: Optional[datetime] = Field(default=None)

    # Расписание визита из плана (местное время региона). Пусто у неназначенных и у
    # планов, посчитанных до миграции 0010.
    position: Optional[int] = Field(default=None)
    planned_departure_at: Optional[datetime] = Field(default=None)
    planned_arrival_at: Optional[datetime] = Field(default=None)
    planned_start_at: Optional[datetime] = Field(default=None)
    planned_end_at: Optional[datetime] = Field(default=None)
    travel_minutes: Optional[float] = Field(default=None)
    distance_km: Optional[float] = Field(default=None)
    waiting_minutes: Optional[float] = Field(default=None)
    idle_minutes: Optional[float] = Field(default=None)
    explanation: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    # Окно клиента, с которым считалась версия (местное время). Окно заявки потом может
    # сдвинуться по согласованию, а старая версия плана должна остаться такой, какой была.
    # Пусто у планов до миграции 0015 — тогда берётся окно из заявки.
    window_start: Optional[datetime] = Field(default=None)
    window_end: Optional[datetime] = Field(default=None)

    request: Optional["Request"] = Relationship(back_populates="assignments")
    engineer: Optional["Engineer"] = Relationship(back_populates="assignments")
    plan: Optional["Plan"] = Relationship(back_populates="assignments")
    transport: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Assignment.transport_id]"}
    )
    unassigned_reason: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Assignment.unassigned_reason_id]"}
    )
    routes: list["Route"] = Relationship(back_populates="assignment")

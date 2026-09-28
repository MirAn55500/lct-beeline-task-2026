from datetime import date as date_type, datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Column, Date, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.region import Region
    from modules.planning.models.assignment import Assignment


class Plan(BaseTable, table=True):
    """План."""

    __tablename__ = "plans"

    plan_id: Optional[int] = Field(default=None, primary_key=True)
    version: int
    date: date_type = Field(
        sa_column=Column(Date, nullable=False, server_default=text("now()"))
    )
    region_id: int = Field(foreign_key="regions.region_id", index=True)
    created_at: datetime
    reference_plan_id: Optional[int] = Field(default=None, foreign_key="plans.plan_id")
    # even = равномерное (базовый), efficient = эффективное; пусто у старых версий.
    distribution: Optional[str] = Field(default=None, max_length=20)
    # Базовый расчёт (алгоритм ТЗ) при версии `baseline_of_id` — для сравнения планов.
    # Сам версией не считается: списки версий, последняя версия и даты с планом его не видят.
    baseline_of_id: Optional[int] = Field(default=None, foreign_key="plans.plan_id", index=True)
    # Версия так, как её показывали при сохранении (`PlanExportResponse`). Заявки и инженеры
    # потом меняются — переносятся на другой день, отменяются, правятся, — а старая версия
    # плана остаётся историей. Пусто у планов до миграции 0016: их собирают по текущим данным.
    snapshot: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB, nullable=True))
    # Обеды версии: по инженеру — когда, где и дорога к месту обеда (`service._lunch_rows`)
    lunches: Optional[list[dict[str, Any]]] = Field(default=None, sa_column=Column(JSONB, nullable=True))

    region: Optional["Region"] = Relationship(back_populates="plans")

    reference_plan: Optional["Plan"] = Relationship(
        back_populates="derived_plans",
        sa_relationship_kwargs={
            "remote_side": "[Plan.plan_id]",
            "foreign_keys": "[Plan.reference_plan_id]",
        },
    )
    derived_plans: list["Plan"] = Relationship(
        back_populates="reference_plan",
        sa_relationship_kwargs={"foreign_keys": "[Plan.reference_plan_id]"},
    )
    assignments: list["Assignment"] = Relationship(back_populates="plan")

from datetime import date as date_type, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Date, text
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

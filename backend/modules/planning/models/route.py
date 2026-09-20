from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.address import Address
    from modules.catalogs.models.dictionary import Dictionary
    from modules.planning.models.assignment import Assignment


class Route(BaseTable, table=True):
    """Маршрут."""

    __tablename__ = "routes"

    id: Optional[int] = Field(default=None, primary_key=True)
    assignment_id: int = Field(foreign_key="assignments.assignment_id")
    start_point_id: int = Field(foreign_key="addresses.address_id")
    end_point_id: int = Field(foreign_key="addresses.address_id")
    transport_id: int = Field(foreign_key="dicts.dict_id")
    start_time: datetime
    end_time: datetime
    path: Optional[Any] = Field(default=None, sa_column=Column(JSONB))
    is_active: bool = Field(default=False)

    assignment: Optional["Assignment"] = Relationship(back_populates="routes")
    start_point: Optional["Address"] = Relationship(
        back_populates="routes_as_start",
        sa_relationship_kwargs={"foreign_keys": "[Route.start_point_id]"},
    )
    end_point: Optional["Address"] = Relationship(
        back_populates="routes_as_end",
        sa_relationship_kwargs={"foreign_keys": "[Route.end_point_id]"},
    )
    transport: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Route.transport_id]"}
    )

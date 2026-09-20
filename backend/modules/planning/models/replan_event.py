from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.personnel.models.engineer import Engineer
    from modules.tickets.models.request import Request


class ReplanEvent(BaseTable, table=True):
    """Событие перепланирования."""

    __tablename__ = "replan_events"

    event_id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str
    event_time: datetime
    request_id: Optional[int] = Field(default=None, foreign_key="requests.request_id")
    engineer_id: Optional[int] = Field(default=None, foreign_key="engineers.engineer_id")

    request: Optional["Request"] = Relationship(back_populates="replan_events")
    engineer: Optional["Engineer"] = Relationship(back_populates="replan_events")

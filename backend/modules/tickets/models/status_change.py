from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.dictionary import Dictionary
    from modules.tickets.models.request import Request


class StatusChange(BaseTable, table=True):
    """Изменение статуса."""

    __tablename__ = "status_changes"

    id: Optional[int] = Field(default=None, primary_key=True)
    prev_status_id: int = Field(foreign_key="dicts.dict_id")
    new_status_id: int = Field(foreign_key="dicts.dict_id")
    request_id: int = Field(foreign_key="requests.request_id")
    status_change_dt: datetime

    prev_status: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[StatusChange.prev_status_id]"}
    )
    new_status: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[StatusChange.new_status_id]"}
    )
    request: Optional["Request"] = Relationship(back_populates="status_changes")

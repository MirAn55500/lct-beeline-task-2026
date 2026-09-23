from datetime import date as date_type, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Date, text
from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.address import Address
    from modules.catalogs.models.dictionary import Dictionary
    from modules.catalogs.models.region import Region
    from modules.planning.models.assignment import Assignment
    from modules.planning.models.replan_event import ReplanEvent
    from modules.tickets.models.status_change import StatusChange


class Request(BaseTable, table=True):
    """Заявки."""

    __tablename__ = "requests"

    request_id: Optional[int] = Field(default=None, primary_key=True)
    external_id: str
    address_id: int = Field(foreign_key="addresses.address_id")
    date: date_type = Field(
        sa_column=Column(Date, nullable=False, server_default=text("now()"))
    )
    plan_start_time: datetime
    plan_end_time: datetime
    priority_id: int = Field(foreign_key="dicts.dict_id")
    transport_id: Optional[int] = Field(default=None, foreign_key="dicts.dict_id")
    status_id: int = Field(foreign_key="dicts.dict_id")
    skill_id: int = Field(foreign_key="dicts.dict_id")
    region_id: int = Field(foreign_key="regions.region_id")
    request_type_vk_id: int = Field(foreign_key="dicts.dict_id")
    request_type_hd_id: int = Field(foreign_key="dicts.dict_id")

    address_ref: Optional["Address"] = Relationship(back_populates="requests")
    priority: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Request.priority_id]"}
    )
    transport: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Request.transport_id]"}
    )
    status: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Request.status_id]"}
    )
    skill: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Request.skill_id]"}
    )
    region: Optional["Region"] = Relationship(back_populates="requests")
    request_type_vk: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Request.request_type_vk_id]"}
    )
    request_type_hd: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Request.request_type_hd_id]"}
    )
    status_changes: list["StatusChange"] = Relationship(back_populates="request")
    assignments: list["Assignment"] = Relationship(back_populates="request")
    replan_events: list["ReplanEvent"] = Relationship(back_populates="request")

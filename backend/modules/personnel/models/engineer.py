from datetime import time
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.dictionary import Dictionary
    from modules.personnel.models.brigade import Brigade
    from modules.personnel.models.engineer_equipment import EngineerEquipment
    from modules.personnel.models.engineer_skill import EngineerSkill
    from modules.planning.models.assignment import Assignment
    from modules.planning.models.replan_event import ReplanEvent


class Engineer(BaseTable, table=True):
    """Инженер."""

    __tablename__ = "engineers"

    engineer_id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    start_work: time
    end_work: time
    transport_id: int = Field(foreign_key="dicts.dict_id")
    brigade_id: int = Field(foreign_key="brigades.brigade_id")

    transport: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Engineer.transport_id]"}
    )
    brigade: Optional["Brigade"] = Relationship(back_populates="engineers")
    skills: list["EngineerSkill"] = Relationship(back_populates="engineer")
    equipment: list["EngineerEquipment"] = Relationship(back_populates="engineer")
    assignments: list["Assignment"] = Relationship(back_populates="engineer")
    replan_events: list["ReplanEvent"] = Relationship(back_populates="engineer")

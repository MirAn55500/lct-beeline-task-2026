from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.dictionary import Dictionary
    from modules.personnel.models.engineer import Engineer


class EngineerSkill(BaseTable, table=True):
    """Навыки инженера."""

    __tablename__ = "engineer_skills"

    id: Optional[int] = Field(default=None, primary_key=True)
    engineer_id: int = Field(foreign_key="engineers.engineer_id")
    skill_id: int = Field(foreign_key="dicts.dict_id")

    engineer: Optional["Engineer"] = Relationship(back_populates="skills")
    skill: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[EngineerSkill.skill_id]"}
    )

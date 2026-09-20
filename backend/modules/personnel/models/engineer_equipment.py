from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.dictionary import Dictionary
    from modules.personnel.models.engineer import Engineer


class EngineerEquipment(BaseTable, table=True):
    """Снаряжение инженера."""

    __tablename__ = "engineer_equipment"

    id: Optional[int] = Field(default=None, primary_key=True)
    engineer_id: int = Field(foreign_key="engineers.engineer_id")
    item_id: int = Field(foreign_key="dicts.dict_id")

    engineer: Optional["Engineer"] = Relationship(back_populates="equipment")
    item: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[EngineerEquipment.item_id]"}
    )

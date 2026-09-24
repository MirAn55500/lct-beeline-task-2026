from datetime import time
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.address import Address
    from modules.catalogs.models.region import Region
    from modules.personnel.models.engineer import Engineer


class Brigade(BaseTable, table=True):
    """Бригада."""

    __tablename__ = "brigades"

    brigade_id: Optional[int] = Field(default=None, primary_key=True)
    region_id: int = Field(foreign_key="regions.region_id")
    name: str = Field(default="Бригада")
    number: str = Field(default="01")
    start_work: time
    end_work: time
    office_address_id: int = Field(foreign_key="addresses.address_id")

    region: Optional["Region"] = Relationship(back_populates="brigades")
    office_address: Optional["Address"] = Relationship(back_populates="brigades")
    engineers: list["Engineer"] = Relationship(back_populates="brigade")

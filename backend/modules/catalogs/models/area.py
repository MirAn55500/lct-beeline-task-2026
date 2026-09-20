from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.address import Address
    from modules.catalogs.models.region import Region


class Area(BaseTable, table=True):
    """Районы в регионе."""

    __tablename__ = "areas"

    id: Optional[int] = Field(default=None, primary_key=True)
    area: str
    region_id: int = Field(foreign_key="regions.region_id")

    region: Optional["Region"] = Relationship(back_populates="areas")
    addresses: list["Address"] = Relationship(back_populates="area_ref")

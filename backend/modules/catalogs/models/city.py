from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.region import Region


class City(BaseTable, table=True):
    """Город присутствия."""

    __tablename__ = "cities"

    city_id: Optional[int] = Field(default=None, primary_key=True)
    city_name: str
    timezone: str

    regions: list["Region"] = Relationship(back_populates="city")

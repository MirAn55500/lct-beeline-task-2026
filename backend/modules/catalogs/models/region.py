from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.area import Area
    from modules.catalogs.models.city import City
    from modules.personnel.models.brigade import Brigade
    from modules.tickets.models.request import Request
    from modules.tickets.models.upload_snapshot import UploadSnapshot


class Region(BaseTable, table=True):
    """Регион присутствия."""

    __tablename__ = "regions"

    region_id: Optional[int] = Field(default=None, primary_key=True)
    region_name: str
    city_id: int = Field(foreign_key="cities.city_id")

    city: Optional["City"] = Relationship(back_populates="regions")
    areas: list["Area"] = Relationship(back_populates="region")
    brigades: list["Brigade"] = Relationship(back_populates="region")
    requests: list["Request"] = Relationship(back_populates="region")
    upload_snapshots: list["UploadSnapshot"] = Relationship(back_populates="region")

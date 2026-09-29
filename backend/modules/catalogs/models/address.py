from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.area import Area
    from modules.personnel.models.brigade import Brigade
    from modules.planning.models.route import Route
    from modules.tickets.models.request import Request


class Address(BaseTable, table=True):
    """Адрес."""

    __tablename__ = "addresses"

    address_id: Optional[int] = Field(default=None, primary_key=True)
    area_id: int = Field(foreign_key="areas.id")
    address: str
    latitude: float
    longitude: float
    # Точность координаты («дом», «улица», «населённый пункт», «район») и её источник.
    # Пусто — записано до онлайн-геокодирования, перепроверяется при старте
    geo_precision: Optional[str] = None
    geo_source: Optional[str] = None

    area_ref: Optional["Area"] = Relationship(back_populates="addresses")
    brigades: list["Brigade"] = Relationship(
        back_populates="office_address",
        sa_relationship_kwargs={"foreign_keys": "Brigade.office_address_id"},
    )
    requests: list["Request"] = Relationship(back_populates="address_ref")
    routes_as_start: list["Route"] = Relationship(
        back_populates="start_point",
        sa_relationship_kwargs={"foreign_keys": "Route.start_point_id"},
    )
    routes_as_end: list["Route"] = Relationship(
        back_populates="end_point",
        sa_relationship_kwargs={"foreign_keys": "Route.end_point_id"},
    )

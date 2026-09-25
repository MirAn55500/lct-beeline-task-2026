from sqlmodel import Field

from core.base_model import BaseTable


class BrigadeArea(BaseTable, table=True):
    """Районы, которые обслуживает бригада."""

    __tablename__ = "brigade_areas"

    brigade_id: int = Field(foreign_key="brigades.brigade_id", primary_key=True)
    area_id: int = Field(foreign_key="areas.id", primary_key=True)

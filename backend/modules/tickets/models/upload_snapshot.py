from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.dictionary import Dictionary
    from modules.catalogs.models.region import Region
    from modules.tickets.models.snapshot_item import SnapshotItem


class UploadSnapshot(BaseTable, table=True):
    """Снэпшот загрузки."""

    __tablename__ = "upload_snapshots"

    snapshoot_id: Optional[int] = Field(default=None, primary_key=True)
    upload_dt: datetime
    upload_type_id: int = Field(foreign_key="dicts.dict_id")
    filename: str
    file_type_id: int = Field(foreign_key="dicts.dict_id")
    region_id: int = Field(foreign_key="regions.region_id")
    created: int
    updated: int
    skipped: int

    upload_type: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[UploadSnapshot.upload_type_id]"}
    )
    file_type: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[UploadSnapshot.file_type_id]"}
    )
    region: Optional["Region"] = Relationship(back_populates="upload_snapshots")
    items: list["SnapshotItem"] = Relationship(back_populates="snapshot")

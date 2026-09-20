from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.dictionary import Dictionary
    from modules.personnel.models.engineer import Engineer
    from modules.tickets.models.request import Request
    from modules.tickets.models.upload_snapshot import UploadSnapshot


class SnapshotItem(BaseTable, table=True):
    """Элемент снэпшота."""

    __tablename__ = "snapshot_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    snapshoot_id: int = Field(foreign_key="upload_snapshots.snapshoot_id")
    action_type_id: int = Field(foreign_key="dicts.dict_id")
    request_id: Optional[int] = Field(default=None, foreign_key="requests.request_id")
    engineer_id: Optional[int] = Field(default=None, foreign_key="engineers.engineer_id")

    snapshot: Optional["UploadSnapshot"] = Relationship(back_populates="items")
    action_type: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[SnapshotItem.action_type_id]"}
    )
    request: Optional["Request"] = Relationship()
    engineer: Optional["Engineer"] = Relationship()

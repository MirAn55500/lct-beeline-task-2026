from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.dictionary import Dictionary


class RequestTypeVkSkillMap(BaseTable, table=True):
    """Маппинг типа заявки ВК с навыком."""

    __tablename__ = "request_type_vk_skill_maps"

    id: Optional[int] = Field(default=None, primary_key=True)
    request_type_vk_id: int = Field(foreign_key="dicts.dict_id")
    skill_id: int = Field(foreign_key="dicts.dict_id")

    request_type_vk: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[RequestTypeVkSkillMap.request_type_vk_id]",
        }
    )
    skill: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[RequestTypeVkSkillMap.skill_id]",
        }
    )

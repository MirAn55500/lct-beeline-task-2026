from typing import Optional

from sqlmodel import Field

from core.base_model import BaseTable
from modules.catalogs.enums import DictGroup


class Dictionary(BaseTable, table=True):
    """Словари (общие справочные значения: статусы, навыки, транспорт и т.д.)."""

    __tablename__ = "dicts"

    dict_id: Optional[int] = Field(default=None, primary_key=True)
    value: str
    group: DictGroup = Field(index=True)

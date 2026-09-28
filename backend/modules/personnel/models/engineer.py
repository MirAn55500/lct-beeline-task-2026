from datetime import date, time
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship

from core.base_model import BaseTable

if TYPE_CHECKING:
    from modules.catalogs.models.address import Address
    from modules.catalogs.models.dictionary import Dictionary
    from modules.personnel.models.brigade import Brigade
    from modules.personnel.models.engineer_equipment import EngineerEquipment
    from modules.personnel.models.engineer_skill import EngineerSkill
    from modules.planning.models.assignment import Assignment
    from modules.planning.models.replan_event import ReplanEvent


class Engineer(BaseTable, table=True):
    """Инженер."""

    __tablename__ = "engineers"

    engineer_id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    # Смена инженера. Без own_schedule это рабочий день бригады, и он меняется вместе с ним
    start_work: time
    end_work: time
    own_schedule: bool = Field(default=False)
    # Свой график — ISO-номера дней недели подряд; None — рабочие дни бригады
    work_days: Optional[str] = Field(default=None, max_length=7)
    # Только для карточки: старт маршрутов — офис бригады
    home_address: Optional[str] = Field(default=None, max_length=300)
    transport_id: int = Field(foreign_key="dicts.dict_id")
    brigade_id: int = Field(foreign_key="brigades.brigade_id")
    # UI-квалификация страницы «Персонал»: master | worker | novice
    qualification: Optional[str] = Field(default=None)
    is_lead: bool = Field(default=False)
    # Свой обед. Пусто — как у бригады: окно и место меняются вместе с ней
    lunch_start: Optional[time] = Field(default=None)
    lunch_end: Optional[time] = Field(default=None)
    lunch_place: Optional[str] = Field(default=None, max_length=20)
    lunch_address_id: Optional[int] = Field(default=None, foreign_key="addresses.address_id")

    transport: Optional["Dictionary"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Engineer.transport_id]"}
    )
    lunch_address: Optional["Address"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Engineer.lunch_address_id]"}
    )
    brigade: Optional["Brigade"] = Relationship(back_populates="engineers")
    skills: list["EngineerSkill"] = Relationship(back_populates="engineer")
    equipment: list["EngineerEquipment"] = Relationship(back_populates="engineer")
    assignments: list["Assignment"] = Relationship(back_populates="engineer")
    replan_events: list["ReplanEvent"] = Relationship(back_populates="engineer")

    @property
    def weekdays(self) -> list[int]:
        """Рабочие дни инженера: свои или, если своих нет, бригады."""
        if self.work_days is None:
            return self.brigade.weekdays if self.brigade is not None else list(range(1, 8))
        return sorted({int(ch) for ch in self.work_days if ch in "1234567"})

    @property
    def own_lunch_time(self) -> bool:
        return self.lunch_start is not None and self.lunch_end is not None

    @property
    def own_lunch_place(self) -> bool:
        return self.lunch_place is not None

    def lunch_window(self) -> tuple[time, time] | None:
        """Окно обеда: своё или бригады. None — бригада не загружена."""
        if self.lunch_start is not None and self.lunch_end is not None:
            return self.lunch_start, self.lunch_end
        if self.brigade is None:
            return None
        return self.brigade.lunch_start, self.brigade.lunch_end

    def lunch_spot(self) -> tuple[str, "Address | None"]:
        """Где обедает: своё место или бригады, и адрес для места «point»."""
        if self.lunch_place is not None:
            return self.lunch_place, self.lunch_address
        if self.brigade is None:
            return "last_request", None
        return self.brigade.lunch_place, self.brigade.lunch_address

    def works_on(self, day: date) -> bool:
        """Инженер попадает в план на этот день."""
        return day.isoweekday() in self.weekdays

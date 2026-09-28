from __future__ import annotations

from sqlalchemy.orm import selectinload
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.catalogs.enums import DictGroup
from modules.catalogs.models.address import Address
from modules.catalogs.models.area import Area
from modules.catalogs.models.dictionary import Dictionary
from modules.catalogs.models.region import Region
from modules.personnel.models.brigade import Brigade
from modules.personnel.models.engineer import Engineer
from modules.personnel.models.engineer_skill import EngineerSkill
from modules.planning.models.route import Route
from modules.tickets.models.request import Request


OFFICE_AREA = "Офис"
"""Служебный район региона: в нём адрес офиса бригады (см. seed_east)."""


class PersonnelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_brigades(self, region_id: int | None = None) -> list[Brigade]:
        statement = (
            select(Brigade)
            .options(
                selectinload(Brigade.office_address),
                selectinload(Brigade.lunch_address),
                selectinload(Brigade.areas),
                selectinload(Brigade.engineers).selectinload(Engineer.transport),
                selectinload(Brigade.engineers)
                .selectinload(Engineer.skills)
                .selectinload(EngineerSkill.skill),
            )
            .order_by(Brigade.name, Brigade.number, Brigade.brigade_id)
        )
        if region_id is not None:
            statement = statement.where(Brigade.region_id == region_id)
        result = await self._session.exec(statement)
        return list(result.all())

    async def get_brigade(self, brigade_id: int) -> Brigade | None:
        """Бригада с офисом и местом обеда — от них считаются настройки инженера."""
        result = await self._session.exec(
            select(Brigade)
            .where(Brigade.brigade_id == brigade_id)
            .options(selectinload(Brigade.office_address), selectinload(Brigade.lunch_address))
        )
        return result.first()

    async def get_brigade_full(self, brigade_id: int) -> Brigade | None:
        """Бригада со всем, что показывает карточка: офис, районы, состав."""
        result = await self._session.exec(
            select(Brigade)
            .where(Brigade.brigade_id == brigade_id)
            .options(
                selectinload(Brigade.office_address).selectinload(Address.area_ref),
                selectinload(Brigade.lunch_address),
                selectinload(Brigade.areas),
                selectinload(Brigade.engineers),
            )
            .execution_options(populate_existing=True)
        )
        return result.first()

    async def list_areas(self, region_id: int) -> list[Area]:
        """Районы региона без служебного «Офис», в котором лежит адрес офиса."""
        result = await self._session.exec(
            select(Area)
            .where(Area.region_id == region_id, Area.area != OFFICE_AREA)
            .order_by(Area.area)
        )
        return list(result.all())

    async def get_region(self, region_id: int) -> Region | None:
        result = await self._session.exec(select(Region).where(Region.region_id == region_id))
        return result.first()

    async def get_or_create_office_area(self, region_id: int) -> Area:
        """Служебный район «Офис» региона — к нему привязывают адрес офиса бригады."""
        found = (
            await self._session.exec(
                select(Area).where(Area.region_id == region_id, Area.area == OFFICE_AREA)
            )
        ).first()
        if found is not None:
            return found
        area = Area(area=OFFICE_AREA, region_id=region_id)
        self._session.add(area)
        await self._session.flush()
        return area

    async def next_brigade_number(self, region_id: int) -> str:
        count = (
            await self._session.exec(
                select(func.count()).select_from(Brigade).where(Brigade.region_id == region_id)
            )
        ).one()
        return f"{int(count) + 1:02d}"

    async def add_brigade(self, brigade: Brigade) -> Brigade:
        self._session.add(brigade)
        await self._session.flush()
        return brigade

    async def find_address(
        self, area_id: int, address: str, lat: float, lon: float
    ) -> Address | None:
        """Уже записанный адрес с тем же текстом и точкой — чтобы не плодить строки."""
        result = await self._session.exec(
            select(Address).where(
                Address.area_id == area_id,
                Address.address == address,
                func.abs(Address.latitude - lat) < 1e-6,
                func.abs(Address.longitude - lon) < 1e-6,
            )
        )
        return result.first()

    async def address_in_use(self, address_id: int) -> bool:
        """На адрес ссылаются бригады (офис, обед), инженеры (обед), заявки или маршруты."""
        for statement in (
            select(func.count())
            .select_from(Brigade)
            .where(
                (Brigade.office_address_id == address_id)
                | (Brigade.lunch_address_id == address_id)
            ),
            select(func.count()).select_from(Engineer).where(Engineer.lunch_address_id == address_id),
            select(func.count()).select_from(Request).where(Request.address_id == address_id),
            select(func.count())
            .select_from(Route)
            .where((Route.start_point_id == address_id) | (Route.end_point_id == address_id)),
        ):
            if (await self._session.exec(statement)).one():
                return True
        return False

    async def delete_address(self, address: Address) -> None:
        await self._session.delete(address)

    async def add_address(self, address: Address) -> Address:
        self._session.add(address)
        await self._session.flush()
        return address

    async def list_engineers(
        self,
        *,
        region_id: int | None = None,
        brigade_id: int | None = None,
    ) -> list[Engineer]:
        statement = (
            select(Engineer)
            .join(Brigade, Engineer.brigade_id == Brigade.brigade_id)
            .options(
                selectinload(Engineer.transport),
                selectinload(Engineer.skills).selectinload(EngineerSkill.skill),
                selectinload(Engineer.brigade).selectinload(Brigade.lunch_address),
                selectinload(Engineer.lunch_address),
            )
            .order_by(col(Engineer.is_lead).desc(), Engineer.name)
        )
        if region_id is not None:
            statement = statement.where(Brigade.region_id == region_id)
        if brigade_id is not None:
            statement = statement.where(Engineer.brigade_id == brigade_id)
        result = await self._session.exec(statement)
        return list(result.all())

    async def list_engineers_by_region(self, region_id: int) -> list[Engineer]:
        return await self.list_engineers(region_id=region_id)

    async def get_engineer(self, engineer_id: int) -> Engineer | None:
        result = await self._session.exec(
            select(Engineer)
            .where(Engineer.engineer_id == engineer_id)
            .options(
                selectinload(Engineer.transport),
                selectinload(Engineer.skills).selectinload(EngineerSkill.skill),
                selectinload(Engineer.equipment),
                selectinload(Engineer.brigade).selectinload(Brigade.lunch_address),
                selectinload(Engineer.lunch_address),
            )
            # Сессия не сбрасывает объекты при коммите — иначе после правки старые навыки
            .execution_options(populate_existing=True)
        )
        return result.first()

    async def ensure_dict(self, group: DictGroup, value: str) -> int:
        label = value.strip() or "—"
        result = await self._session.exec(
            select(Dictionary).where(
                Dictionary.group == group,
                Dictionary.value == label,
            )
        )
        row = result.first()
        if row is not None and row.dict_id is not None:
            return row.dict_id
        row = Dictionary(value=label, group=group)
        self._session.add(row)
        await self._session.flush()
        return row.dict_id or 0

    async def add_engineer(self, engineer: Engineer) -> Engineer:
        self._session.add(engineer)
        await self._session.flush()
        await self._session.refresh(engineer)
        return engineer

    async def add_skill(self, engineer_id: int, skill_id: int) -> None:
        self._session.add(EngineerSkill(engineer_id=engineer_id, skill_id=skill_id))

    async def delete_skill(self, link: EngineerSkill) -> None:
        await self._session.delete(link)

    async def delete_engineer(self, engineer: Engineer) -> None:
        # FK без ON DELETE CASCADE — сначала связи.
        for link in list(engineer.skills or []):
            await self._session.delete(link)
        for link in list(engineer.equipment or []):
            await self._session.delete(link)
        await self._session.delete(engineer)

    async def commit(self) -> None:
        await self._session.commit()

    async def refresh_engineer(self, engineer_id: int) -> Engineer | None:
        await self._session.commit()
        return await self.get_engineer(engineer_id)

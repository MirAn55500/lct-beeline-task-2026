"""Синтетические инженеры «Востока» по колонке «Бригада» контрольной выгрузки.

Имена из файла, навыки и транспорт — те же доли, что в `planner.io_csv.engineers_from_control`.
Смена 09:00–22:00: в заявках есть окна до 22:00.
"""

from __future__ import annotations

import sys
from datetime import date, time
from pathlib import Path

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

_SOLUTION = Path(__file__).resolve().parents[3] / "solution"
if str(_SOLUTION) not in sys.path:
    sys.path.insert(0, str(_SOLUTION))

from planner.io_csv import engineers_from_control, load_requests  # noqa: E402

import modules.catalogs.models  # noqa: F401
import modules.personnel.models  # noqa: F401
import modules.planning.models  # noqa: F401
import modules.tickets.models  # noqa: F401
from core.database import async_session_factory
from modules.catalogs.enums import DictGroup
from modules.catalogs.models.address import Address
from modules.catalogs.models.area import Area
from modules.catalogs.models.dictionary import Dictionary
from modules.catalogs.models.region import Region
from modules.personnel.models.brigade import Brigade
from modules.personnel.models.engineer import Engineer
from modules.personnel.models.engineer_skill import EngineerSkill

CONTROL_CSV = Path(r"d:\Downloads\Обезличенные\Восток Контрольное распределение..csv")
SYNTHETIC_CSV = Path(
    r"d:\Downloads\Обезличенные\Обезличивание\Восток Синтетические данные.csv"
)
REGION_NAME = "Восток"
SHIFT_START = time(9, 0)
SHIFT_END = time(22, 0)

REASON_CODES = (
    "no_skill",
    "no_equipment",
    "no_work_time",
    "time_conflict",
    "no_region",
    "no_engineers",
    "no_transport",
    "not_found",
    "manual",
)


async def _dict_id(session: AsyncSession, group: DictGroup, value: str) -> int:
    found = (
        await session.exec(
            select(Dictionary).where(Dictionary.group == group, Dictionary.value == value)
        )
    ).first()
    if found is not None and found.dict_id is not None:
        return found.dict_id
    row = Dictionary(value=value, group=group)
    session.add(row)
    await session.flush()
    return row.dict_id or 0


async def seed_east_engineers() -> int:
    """Создаёт инженеров региона «Восток», если их ещё нет. Возвращает число новых."""
    async with async_session_factory() as session:
        for code in REASON_CODES:
            await _dict_id(session, DictGroup.UNASSIGNED_REASON, code)

        region = (
            await session.exec(select(Region).where(Region.region_name == REGION_NAME))
        ).first()
        if region is None or region.region_id is None:
            raise RuntimeError(f"Регион {REGION_NAME} не найден")

        existing = (
            await session.exec(
                select(Engineer)
                .join(Brigade, Engineer.brigade_id == Brigade.brigade_id)
                .where(Brigade.region_id == region.region_id)
            )
        ).first()
        if existing is not None:
            await session.commit()
            return 0

        synthetic = load_requests(SYNTHETIC_CSV, region_key=str(region.region_id))
        control = load_requests(CONTROL_CSV, region_key=str(region.region_id))
        office = synthetic.office_point or control.office_point
        if office is None or not synthetic.office_address:
            raise RuntimeError("В выгрузке нет адреса офиса")

        profiles = engineers_from_control(
            control.source_brigades.keys(),
            office,
            date(2026, 8, 17),
            region_key=str(region.region_id),
            shift=("09:00", "22:00"),
            lunch=None,
        )

        area = Area(area="Офис", region_id=region.region_id)
        session.add(area)
        await session.flush()
        address = Address(
            area_id=area.id or 0,
            address=synthetic.office_address,
            latitude=office.lat,
            longitude=office.lon,
        )
        session.add(address)
        await session.flush()
        brigade = Brigade(
            region_id=region.region_id,
            name=REGION_NAME,
            number="01",
            start_work=SHIFT_START,
            end_work=SHIFT_END,
            office_address_id=address.address_id or 0,
        )
        session.add(brigade)
        await session.flush()

        qualification_cycle = ("master", "worker", "novice")
        created = 0
        for index, profile in enumerate(profiles):
            transport_id = await _dict_id(
                session, DictGroup.TRANSPORT, profile.transport_mode.value
            )
            engineer = Engineer(
                name=profile.name,
                start_work=SHIFT_START,
                end_work=SHIFT_END,
                transport_id=transport_id,
                brigade_id=brigade.brigade_id or 0,
                qualification=qualification_cycle[index % 3],
                is_lead=index == 0,
            )
            session.add(engineer)
            await session.flush()
            for skill in sorted(profile.skills, key=lambda item: item.value):
                skill_id = await _dict_id(
                    session,
                    DictGroup.SKILL,
                    skill.value,
                )
                session.add(
                    EngineerSkill(engineer_id=engineer.engineer_id or 0, skill_id=skill_id)
                )
            created += 1

        await session.commit()
        return created


async def _main() -> None:
    created = await seed_east_engineers()
    print(created)


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())

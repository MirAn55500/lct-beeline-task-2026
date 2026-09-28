"""Засев инженеров «Юго-восток» из demo-scenarios/00-engineers-southeast.csv.

Запуск из каталога backend (с venv):

    python -m modules.personnel.seed_southeast

Создаёт бригаду и 12 инженеров, если в регионе ещё никого нет.
"""

from __future__ import annotations

import csv
import sys
from datetime import time
from pathlib import Path

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

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

REGION_NAME = "Юго-восток"
OFFICE = "г. Москва, ул Бирюлёвская, д 1с1"
OFFICE_LAT = 55.61
OFFICE_LON = 37.66
SHIFT_START = time(9, 0)
SHIFT_END = time(22, 0)
ENGINEERS_CSV = Path(__file__).resolve().parents[3] / "demo-scenarios" / "00-engineers-southeast.csv"

QUALIFICATION = {
    "мастер": "master",
    "бывалый": "worker",
    "новичок": "novice",
}
TRANSPORT = {
    "автомобиль": "car",
    "общ. транспорт": "public",
    "общественный транспорт": "public",
    "велосипед": "bike",
    "пешеход": "walking",
    "пешком": "walking",
}
SKILL = {
    "работы на подключение и дозаказы": "connection",
    "подключение": "connection",
    "локальные работы": "local",
    "аварийные работы": "emergency",
}


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


def _load_rows() -> list[dict[str, str]]:
    text = ENGINEERS_CSV.read_text(encoding="utf-8-sig")
    return [
        {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        for row in csv.DictReader(text.splitlines(), delimiter=";")
    ]


async def seed_southeast_engineers() -> int:
    if not ENGINEERS_CSV.exists():
        raise RuntimeError(f"Нет файла {ENGINEERS_CSV}. Сначала: python demo-scenarios/_generate.py")

    rows = _load_rows()
    async with async_session_factory() as session:
        region = (
            await session.exec(select(Region).where(Region.region_name == REGION_NAME))
        ).first()
        if region is None or region.region_id is None:
            raise RuntimeError(f"Регион {REGION_NAME} не найден — прогоните миграции")

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

        area = Area(area="Офис", region_id=region.region_id)
        session.add(area)
        await session.flush()
        address = Address(
            area_id=area.id or 0,
            address=OFFICE,
            latitude=OFFICE_LAT,
            longitude=OFFICE_LON,
        )
        session.add(address)
        await session.flush()

        brigade_name = rows[0].get("Бригада") or f"Бригада {REGION_NAME}"
        brigade = Brigade(
            region_id=region.region_id,
            name=brigade_name,
            number="01",
            start_work=SHIFT_START,
            end_work=SHIFT_END,
            office_address_id=address.address_id or 0,
        )
        session.add(brigade)
        await session.flush()

        created = 0
        for row in rows:
            name = row.get("ФИО", "").strip()
            if not name:
                continue
            transport_raw = row.get("Транспорт", "").strip().lower()
            transport_code = TRANSPORT.get(transport_raw, "walking")
            transport_id = await _dict_id(session, DictGroup.TRANSPORT, transport_code)
            qual = QUALIFICATION.get(row.get("Квалификация", "").strip().lower(), "worker")
            start = SHIFT_START
            end = SHIFT_END
            if row.get("Начало смены"):
                h, m = (int(x) for x in row["Начало смены"].split(":")[:2])
                start = time(h, m)
            if row.get("Конец смены"):
                h, m = (int(x) for x in row["Конец смены"].split(":")[:2])
                end = time(h, m)

            engineer = Engineer(
                name=name,
                start_work=start,
                end_work=end,
                transport_id=transport_id,
                brigade_id=brigade.brigade_id or 0,
                qualification=qual,
                is_lead=False,
            )
            session.add(engineer)
            await session.flush()

            for part in row.get("Навыки", "").split(","):
                code = SKILL.get(part.strip().lower())
                if not code:
                    continue
                skill_id = await _dict_id(session, DictGroup.SKILL, code)
                session.add(
                    EngineerSkill(engineer_id=engineer.engineer_id or 0, skill_id=skill_id)
                )
            created += 1

        await session.commit()
        return created


async def _main() -> None:
    created = await seed_southeast_engineers()
    print(created)


if __name__ == "__main__":
    import asyncio

    # Чтобы `python path/to/seed_southeast.py` находил core.*
    backend = Path(__file__).resolve().parents[2]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    asyncio.run(_main())

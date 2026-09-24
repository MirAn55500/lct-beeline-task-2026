"""Центры районов по уже сохранённым точкам — опора для проверки правдоподобия."""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.catalogs.models.address import Address
from modules.catalogs.models.area import Area

MIN_POINTS = 3
"""Меньше точек — медиана ненадёжна, район проверяется только по границам региона."""


async def district_anchors(session: AsyncSession, region_id: int) -> dict[str, tuple[float, float]]:
    rows = (
        await session.exec(
            select(Area.area, Address.latitude, Address.longitude)
            .join(Address, Address.area_id == Area.id)
            .where(Area.region_id == region_id)
        )
    ).all()
    points: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for area, lat, lon in rows:
        points[area].append((lat, lon))
    # Медиана устойчива к единичным выбросам вроде точки в соседнем городе
    return {
        area: (median(p[0] for p in pts), median(p[1] for p in pts))
        for area, pts in points.items()
        if len(pts) >= MIN_POINTS
    }

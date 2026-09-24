"""Перепроверка сохранённых адресов: при старте backend, в фоне.

Адреса, записанные до онлайн-геокодирования (точность не заполнена) или положенные
в центр района, геокодируются заново. Найденное точнее — записывается; для старых
точек, которые проходят проверку правдоподобия, а лучше не нашлось, ничего не меняется.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlmodel import or_, select

from core.config import get_settings
from core.database import async_session_factory
from modules.catalogs.models.address import Address
from modules.catalogs.models.area import Area
from modules.geocoding.anchors import district_anchors
from modules.geocoding.geocoder import DISTRICT, AddressGeocoder

logger = logging.getLogger(__name__)


async def recheck_addresses() -> None:
    try:
        await _recheck()
    except Exception:  # фоновая задача не должна ронять приложение
        logger.exception("Перепроверка адресов упала")


async def _recheck() -> None:
    async with async_session_factory() as session:
        rows = (
            await session.exec(
                select(Address, Area)
                .join(Area, Area.id == Address.area_id)
                .where(or_(Address.geo_precision.is_(None), Address.geo_precision == DISTRICT))
            )
        ).all()
        if not rows:
            return
        logger.info("Перепроверка координат: %d адресов", len(rows))

        by_region: dict[int, list[tuple[Address, Area]]] = defaultdict(list)
        for address, area in rows:
            by_region[area.region_id].append((address, area))

        fixed = 0
        for region_id, items in by_region.items():
            anchors = await district_anchors(session, region_id)
            async with AddressGeocoder(get_settings(), anchors) as geocoder:
                for address, area in items:
                    hit = await geocoder.locate(address.address, area.area)
                    legacy_ok = geocoder.plausible(
                        address.latitude, address.longitude, address.address, area.area
                    )
                    if hit.precision == DISTRICT and legacy_ok:
                        continue  # лучше не нашлось, старая точка правдоподобна
                    if (address.latitude, address.longitude) != (hit.lat, hit.lon):
                        fixed += 1
                    address.latitude, address.longitude = hit.lat, hit.lon
                    address.geo_precision, address.geo_source = hit.precision, hit.source
                    session.add(address)
            await session.commit()
        logger.info("Перепроверка координат: исправлено %d", fixed)

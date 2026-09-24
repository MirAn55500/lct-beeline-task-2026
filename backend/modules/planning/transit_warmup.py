"""Фоновый досчёт расписаний общественного транспорта для новых точек.

Матрица общественного транспорта собирается по одному участку за запрос (у матрицы ORS
нет времени отправления), поэтому считать её прямо в пересчёте плана нельзя: для новых
адресов это минуты. План сразу считается как обычно — новые точки на общественном
транспорте по координатам, — а сюда ставится задача: досчитать недостающие пары по
расписанию и, если что-то досчиталось, пересчитать план новой версией.

Досчёт идёт в раздел кэша того же дня недели и часа, из которого planner берёт
расписания для этой даты (кэш прогрет на неделю, см. tools/ors_prefetch.py). Пары,
по которым сервис ответил «вне фида» (Кашира с московским фидом не свяжется), пишутся
рядом с кэшем и больше не запрашиваются.

Задачи идут по одной, параллельных запросов к ORS — `TRANSIT_WORKERS`: 2, если ORS
делит с backend два ядра стенда, 6-8 на отдельной машине (solution/deploy/ors/REMOTE.md).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from pathlib import Path

from core.config import get_settings
from modules.planning.scenario_builder import routing_cache_lock  # и sys.path к planner

from planner.enums import TransportMode  # noqa: E402
from planner.models import Scenario  # noqa: E402
from planner.ors import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    OrsClient,
    RoutingCache,
    collect_points,
    fetch_transit_legs,
    point_key,
    scenario_departure,
    transit_profile,
    transit_reuse_section,
    transit_section_moment,
)

logger = logging.getLogger(__name__)

_queue: asyncio.Queue[tuple[int, date]] | None = None
_pending: set[tuple[int, date]] = set()


def schedule(region_id: int, day: date) -> None:
    """Поставить досчёт в очередь; повтор той же пары, пока она ждёт, игнорируется."""
    if _queue is None or (region_id, day) in _pending:
        return
    _pending.add((region_id, day))
    _queue.put_nowait((region_id, day))


async def worker() -> None:
    """Разбирает очередь до остановки приложения."""
    global _queue
    _queue = asyncio.Queue()
    while True:
        region_id, day = await _queue.get()
        _pending.discard((region_id, day))
        try:
            await _warm(region_id, day)
        except Exception:  # фоновая задача не должна ронять приложение
            logger.exception("Досчёт расписаний: регион %s, %s", region_id, day)


async def _warm(region_id: int, day: date) -> None:
    from core.database import async_session_factory
    from modules.planning.service import PlanningService

    async with async_session_factory() as session:
        scenario = await PlanningService(session).scenario_for(region_id, day)
    if scenario is None:
        return
    added = await asyncio.to_thread(warm_transit, scenario)
    if not added:
        return
    logger.info(
        "Досчёт расписаний: регион %s, %s — %d новых пар, пересчитываю план",
        region_id, day, added,
    )
    async with async_session_factory() as session:
        await PlanningService(session).recalculate(region_id, day, warm_transit=False)


def _ors_has_transit(client: OrsClient, profile: str, points, departure: str) -> bool:
    """Есть ли у инстанса расписания: одна пробная пара вместо тысяч отказов.

    `/v2/status` для этого не годится — список профилей он отдаёт не всем клиентам.
    Сервис лежит или профиль выключен (стенд без графа транспорта) — не досчитываем.
    """
    _, failures = fetch_transit_legs(client, profile, points[:2], departure, workers=1)
    return not (failures.outage or failures.rejected)


def warm_transit(scenario: Scenario) -> int:
    """Досчитать недостающие пары общественного транспорта. Возвращает число новых."""
    settings = get_settings()
    if not settings.ors_url:
        return 0
    if TransportMode.PUBLIC_TRANSPORT not in {e.transport_mode for e in scenario.engineers}:
        return 0

    cache_path = Path(settings.routing_cache_path or DEFAULT_CACHE_PATH)
    unroutable_path = cache_path.with_name("transit_unroutable.json")
    client = OrsClient(
        settings.ors_url,
        api_key=settings.ors_api_key or None,
        max_routes_per_request=25000,
        timeout=60,
    )
    profile = client.profile_of(TransportMode.PUBLIC_TRANSPORT)

    # Копия кэша: досчёт идёт минутами, держать общую блокировку всё это время нельзя
    with routing_cache_lock:
        snapshot = RoutingCache(cache_path)
    departure = scenario_departure(scenario)
    section = transit_profile(profile, departure)
    available = snapshot.sections_of(profile)
    if section not in available:
        spare = transit_reuse_section(
            available, departure, scenario.settings.timezone_offset_hours
        )
        if spare is not None:
            section, departure = spare, transit_section_moment(spare)

    points = collect_points(scenario)
    if len(points) < 2 or not _ors_has_transit(client, profile, points, departure):
        return 0

    unroutable = _load_unroutable(unroutable_path)
    skip = {tuple(key.split(">", 1)) for key in unroutable.get(section, [])}
    # Пара двух уже известных точек, которой нет в разделе, — прогрев её пробовал и
    # сервис не связал (граница фида): перезапрашивать её незачем. Досчитываются
    # только пары с новой точкой — так первый досчёт по Юго-востоку не повторяет
    # 3100 заведомо несвязных пар Каширы.
    known = snapshot.legs_of(section)
    seen = {k for pair in known for k in pair}
    keys = [point_key(p) for p in points]
    skip |= {(a, b) for a in keys for b in keys if a != b and a in seen and b in seen}
    outside: set[tuple[str, str]] = set()
    fetched, failures = fetch_transit_legs(
        client,
        profile,
        points,
        departure,
        workers=max(1, settings.transit_workers),
        known=known,
        skip=skip,
        outside=outside,
    )
    if failures.outage or failures.rejected:
        logger.warning(
            "Досчёт расписаний: сервис не ответил на %d пар, отклонил %d",
            failures.outage, failures.rejected,
        )

    index = {point_key(p): p for p in points}
    fresh = RoutingCache(None)
    for (ka, kb), (km, minutes) in fetched.items():
        a, b = index.get(ka), index.get(kb)
        if a is not None and b is not None:
            fresh.put_leg(section, a, b, km, minutes)

    with routing_cache_lock:
        cache = RoutingCache(cache_path)
        added = cache.merge(fresh)
        if added:
            cache.save()
        if outside:
            unroutable.setdefault(section, [])
            unroutable[section] = sorted(set(unroutable[section]) | {f"{a}>{b}" for a, b in outside})
            unroutable_path.write_text(json.dumps(unroutable), encoding="utf-8")
    return added


def _load_unroutable(path: Path) -> dict[str, list[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

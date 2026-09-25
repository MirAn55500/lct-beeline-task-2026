"""Общественный транспорт по расписанию GTFS — прямо в backend, без внешнего ORS.

Два источника времени в пути (`solution/docs/transit-raptor.md`):

* **известные пары** — профили rRAPTOR из Postgres (`transit_profile`): время на
  фактический момент выезда, посчитаны заранее (`solution/tools/raptor_prefetch.py`),
  на стенд приезжают файлом и грузятся при старте (`core/load_transit_profiles.py`);
* **новые адреса** — RAPTOR на 10:00 при расчёте плана (`fill_missing`): ~0.1 с на
  точку, плюс ~15 с один раз на загрузку расписания дня в процесс. Результат ложится
  в кэш маршрутов тем же разделом, что раньше писал ORS, и дальше берётся оттуда.

Фонового досчёта нет: новые пары сразу получают одно значение на 10:00. Пары вне фида
(Кашира и т. п.) запоминаются рядом с кэшем и больше не считаются.
"""

from __future__ import annotations

import json
import logging
from array import array
import threading
import time
from collections import defaultdict
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy import bindparam, text
from sqlmodel.ext.asyncio.session import AsyncSession

from core.config import get_settings
from modules.planning.scenario_builder import routing_cache_lock  # и sys.path к planner

from planner import raptor, transit_profiles  # noqa: E402
from planner.enums import TransportMode  # noqa: E402
from planner.models import Scenario  # noqa: E402
from planner.ors import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    DEFAULT_PROFILES,
    RoutingCache,
    collect_points,
    point_key,
    scenario_departure,
    transit_profile,
    transit_reuse_section,
)
from planner.raptor import Profile  # noqa: E402
from planner.travel import HaversineTravelModel  # noqa: E402

logger = logging.getLogger(__name__)

PT = TransportMode.PUBLIC_TRANSPORT
REFERENCE_SECONDS = 10 * 3600
"""Опорный выезд для новых адресов — тот же 10:00, что у кэша ORS (`PT_DEPARTURE_HOUR`)."""
DAY_FROM = 7 * 3600
DAY_MINUTES = (22 - 7) * 60 + 60 + raptor.HORIZON_MINUTES
"""Расписание в памяти — на весь рабочий день (выезды 07:00–22:00 и поездки после них):
по нему считается и 10:00 для новых адресов, и состав поездки на фактический выезд."""


def gtfs_path() -> Path:
    settings = get_settings()
    if settings.gtfs_path:
        return Path(settings.gtfs_path)
    return Path(raptor.__file__).resolve().parents[1] / "deploy" / "ors" / "files" / "gtfs.zip"


@lru_cache(maxsize=1)
def feed_version() -> str | None:
    path = gtfs_path()
    return transit_profiles.feed_version(path) if path.exists() else None


def uses_transit(scenario: Scenario) -> bool:
    return any(e.transport_mode is PT for e in scenario.engineers)


# ---------------------------------------------------------------- профили из Postgres


async def load_profiles(
    session: AsyncSession, scenario: Scenario
) -> tuple[dict[tuple[str, str], Profile], int, int] | None:
    """Профили пар сценария на его день недели: (профили, начало окна, конец окна)."""
    feed = feed_version()
    if feed is None or not uses_transit(scenario):
        return None
    window = (
        await session.execute(
            text("SELECT first_second, last_second FROM transit_feed WHERE feed_version = :f"),
            {"f": feed},
        )
    ).first()
    if window is None:
        return None
    keys = sorted({point_key(p) for p in collect_points(scenario)})
    query = text(
        "SELECT origin, dest, data FROM transit_profile "
        "WHERE feed_version = :f AND weekday = :w AND origin IN :keys AND dest IN :keys"
    ).bindparams(bindparam("keys", expanding=True))
    rows = (
        await session.execute(query, {"f": feed, "w": scenario.date.weekday(), "keys": keys})
    ).all()
    profiles = {(a, b): transit_profiles.decode(bytes(blob)) for a, b, blob in rows}
    return profiles, window[0], window[1]


# ---------------------------------------------------------------- RAPTOR на 10:00


_timetables: dict[str, raptor.TransitRouter] = {}
_timetable_lock = threading.Lock()
_rides: dict[tuple[str, str], array | None] = {}
"""(подпись дня, точка) → прибытие на все остановки при выходе в 10:00 (~56 КБ).

Один поиск из точки отвечает сразу на все цели. Запомнив его, следующий новый адрес
требует поиска только из себя: в обратную сторону («известная точка → новый адрес»)
хватает уже сохранённого прибытия на остановки у нового адреса.
"""


def _signature(day: date) -> str:
    return transit_profiles.service_signature(gtfs_path(), day)


def _router(day: date) -> raptor.TransitRouter:
    """Расписание дня в процессе. Дни с одинаковыми сервисами фида делят одно."""
    path = gtfs_path()
    signature = _signature(day)
    with _timetable_lock:
        router = _timetables.get(signature)
        if router is None:
            started = time.perf_counter()
            router = raptor.TransitRouter(
                raptor.load_timetable(path, day, DAY_FROM, horizon_minutes=DAY_MINUTES)
            )
            # Держим не больше двух дней: каждый ~300 МБ, а стенд маленький
            while len(_timetables) >= 2:
                old = next(iter(_timetables))
                _timetables.pop(old)
                for key in [k for k in _rides if k[0] == old]:
                    _rides.pop(key)
            _timetables[signature] = router
            logger.info(
                "RAPTOR: расписание на %s загружено за %.1f с", day, time.perf_counter() - started
            )
    return router


def _ride(router: raptor.TransitRouter, signature: str, key: str, point) -> array | None:
    cached = _rides.get((signature, key), False)
    if cached is not False:
        return cached
    access = router.access(point)
    ride = (
        array("i", router.arrivals(
            ((s, REFERENCE_SECONDS + w) for s, w in access), depart=REFERENCE_SECONDS
        ))
        if access else None
    )
    _rides[(signature, key)] = ride
    return ride


def _minutes(router, ride, origin, target, walk: float | None) -> float | None:
    """То же, что `TransitRouter.travel_minutes` для одной цели, по готовому поиску."""
    egress = router.access(target)
    if ride is None or not egress:
        return None
    arrival = min((ride[s] + w for s, w in egress if ride[s] < raptor.INF), default=raptor.INF)
    [walk_s] = router._walks(origin, [target], [walk])
    return min(arrival - REFERENCE_SECONDS, walk_s) / 60


def _unroutable_path(cache_path: Path) -> Path:
    return cache_path.with_name("transit_unroutable.json")


def _load_unroutable(path: Path) -> dict[str, list[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fill_missing(scenario: Scenario) -> int:
    """Досчитать RAPTOR на 10:00 пары общественного транспорта, которых нет в кэше.

    Пишет в тот раздел кэша, из которого planner возьмёт расписания для этой даты
    (своей даты или того же дня недели, см. `transit_reuse_section`). Возвращает число
    новых пар.
    """
    if not uses_transit(scenario) or not gtfs_path().exists():
        return 0
    settings = get_settings()
    cache_path = Path(settings.routing_cache_path or DEFAULT_CACHE_PATH)
    profile = DEFAULT_PROFILES[PT]
    departure = scenario_departure(scenario)

    with routing_cache_lock:
        snapshot = RoutingCache(cache_path)
    section = transit_profile(profile, departure)
    available = snapshot.sections_of(profile)
    if section not in available:
        spare = transit_reuse_section(available, departure, scenario.settings.timezone_offset_hours)
        if spare is not None:
            section = spare
    known = snapshot.legs_of(section)
    foot = snapshot.legs_of(DEFAULT_PROFILES[TransportMode.WALKING])
    unroutable = _load_unroutable(_unroutable_path(cache_path))
    skip = set(unroutable.get(section, []))

    points = {point_key(p): p for p in collect_points(scenario)}
    missing: dict[str, list[str]] = defaultdict(list)
    for a in points:
        for b in points:
            if a != b and (a, b) not in known and f"{a}>{b}" not in skip:
                missing[a].append(b)
    if not missing:
        return 0

    started = time.perf_counter()
    router = _router(scenario.date)
    signature = _signature(scenario.date)
    distance = HaversineTravelModel(scenario.settings)
    fresh = RoutingCache(None)
    outside: list[str] = []
    searched = sum((signature, a) not in _rides for a in missing)
    for a, targets in missing.items():
        ride = _ride(router, signature, a, points[a])
        for b in targets:
            minutes = _minutes(router, ride, points[a], points[b], (foot.get((a, b)) or (None, None))[1])
            if minutes is None:
                outside.append(f"{a}>{b}")
                continue
            km = distance.distance_km(points[a], points[b], PT)
            fresh.put_leg(section, points[a], points[b], round(km, 3), round(minutes, 3))

    with routing_cache_lock:
        cache = RoutingCache(cache_path)
        added = cache.merge(fresh)
        if added:
            cache.save()
        if outside:
            unroutable[section] = sorted(set(unroutable.get(section, [])) | set(outside))
            _unroutable_path(cache_path).write_text(json.dumps(unroutable), encoding="utf-8")
    logger.info(
        "RAPTOR: %d новых пар общественного транспорта на 10:00 за %.1f с "
        "(%d вне фида, поисков %d из %d точек)",
        added, time.perf_counter() - started, len(outside), searched, len(missing),
    )
    return added


def legs_source(scenario: Scenario):
    """Состав поездок на общественном транспорте для `Routing.attach` (RAPTOR), или None."""
    if not uses_transit(scenario) or not gtfs_path().exists():
        return None
    settings = get_settings()
    with routing_cache_lock:
        snapshot = RoutingCache(Path(settings.routing_cache_path or DEFAULT_CACHE_PATH))
    foot = snapshot.legs_of(DEFAULT_PROFILES[TransportMode.WALKING])

    def walk(a, b):
        return (foot.get((point_key(a), point_key(b))) or (None, None))[1]

    return raptor.transit_legs(_router(scenario.date), walk)

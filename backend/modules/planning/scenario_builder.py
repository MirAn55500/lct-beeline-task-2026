"""Сборка входа `planner.plan` из строк БД и разбор результата обратно в назначения."""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Collection
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

_SOLUTION = Path(__file__).resolve().parents[3] / "solution"
if str(_SOLUTION) not in sys.path:
    sys.path.insert(0, str(_SOLUTION))

from planner import (  # noqa: E402
    Engineer as PlannerEngineer,
)
from planner import (  # noqa: E402
    Algorithm,
    GeoPoint,
    Lunch,
    OrsTravelModel,
    Priority,
    Request as PlannerRequest,
    Scenario,
    Skill,
    TransportMode,
    WorkInterval,
    plan,
    setup_routing,
)
from planner.result import PlanResult  # noqa: E402
from planner.raptor import Profile  # noqa: E402
from planner.timed import TimedTransitModel  # noqa: E402
from planner.ors import (  # noqa: E402
    DEFAULT_PROFILES,
    NO_MATRIX_PROFILES,
    Routing,
    RoutingCache,
    collect_points,
    covers,
    scenario_modes,
)
from planner.travel import HaversineTravelModel, TravelModel  # noqa: E402

from core import ors_endpoint
from core.config import get_settings
from modules.personnel.models.engineer import Engineer
from modules.planning.models.assignment import Assignment
from modules.tickets.models.request import Request

_DURATION_BY_SKILL = {
    Skill.EMERGENCY: 80,
    Skill.CONNECTION: 70,
    Skill.LOCAL: 30,
}

_CLOSED_STATUS = {
    "completed",
    "cancelled",
    "выполнена",
    "отменена",
}

# Подписи для матчинга старых строк словаря; канон в БД — код (см. catalogs.seed_values).
_REASON_LABELS = {
    "no_engineers": "нет инженеров",
    "no_region": "нет инженера в регионе",
    "no_skill": "нет нужного навыка",
    "no_transport": "нет подходящего транспорта",
    "no_equipment": "нет нужного снаряжения",
    "no_work_time": "нет рабочего времени",
    "time_conflict": "конфликт времени",
    "not_found": "не найдено",
    "manual": "вручную",
}


def _skill(value: str | None) -> Skill:
    raw = (value or "").strip().lower()
    if raw in {"emergency", "авария"} or "авар" in raw:
        return Skill.EMERGENCY
    if raw in {"local", "локальная заявка"} or "локал" in raw or "ремонт" in raw:
        return Skill.LOCAL
    return Skill.CONNECTION


def _priority(value: str | None, skill: Skill) -> Priority:
    raw = (value or "").strip().lower()
    if raw in {"emergency", "авария"} or "авар" in raw:
        return Priority.EMERGENCY
    if raw in {"connection", "подключение"} or "подключ" in raw:
        return Priority.CONNECTION
    if raw in {"repair_or_addon", "ремонт", "дозаказ"} or "ремонт" in raw or "дозаказ" in raw:
        return Priority.REPAIR
    if skill is Skill.EMERGENCY:
        return Priority.EMERGENCY
    if skill is Skill.LOCAL:
        return Priority.REPAIR
    return Priority.CONNECTION


def _transport(value: str | None) -> TransportMode | None:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    if raw in {"car", "автомобиль", "машина"} or "авто" in raw or "машин" in raw:
        return TransportMode.CAR
    if raw in {"bicycle", "bike", "велосипед"} or "вел" in raw:
        return TransportMode.BICYCLE
    if raw in {"walking", "пешком"} or "пеш" in raw:
        return TransportMode.WALKING
    if raw in {"public_transport", "public", "общественный транспорт", "общ. транспорт"} or "общ" in raw:
        return TransportMode.PUBLIC_TRANSPORT
    return None


_MSK = timezone(timedelta(hours=3))


def _aware(moment: datetime) -> datetime:
    """Наивное местное время из БД — московское. Событие дня сравнивает моменты с поясом."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=_MSK)
    return moment.astimezone(_MSK)


def _at(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=_MSK)


LUNCH_MINUTES = 60


def _lunch(day: date, engineer: Engineer, office) -> Lunch | None:
    """Обед инженера на день: окно и место — свои или бригады (`Engineer.lunch_window`)."""
    window = engineer.lunch_window()
    if window is None or window[1] <= window[0]:
        return None
    start, end = _at(day, window[0]), _at(day, window[1])
    if (end - start).total_seconds() / 60 < LUNCH_MINUTES:
        return None
    place, spot = engineer.lunch_spot()
    if place == "office" and office is not None:
        point, address = GeoPoint(lat=office.latitude, lon=office.longitude), office.address
    elif place == "point" and spot is not None:
        point, address = GeoPoint(lat=spot.latitude, lon=spot.longitude), spot.address
    else:
        place, point, address = "last_request", None, ""
    return Lunch(
        window_start=start,
        window_end=end,
        minutes=LUNCH_MINUTES,
        point=point,
        place=place,
        address=address,
    )


def lunch_address_ids(engineers: list[Engineer]) -> dict[int, int]:
    """Адрес места обеда по инженеру — откуда начинается дорога после обеда (`routes`).

    Только для обеда в офисе или в своей точке: у последней заявки дорога идёт с её адреса.
    """
    out: dict[int, int] = {}
    for engineer in engineers:
        if engineer.engineer_id is None or engineer.brigade is None:
            continue
        place, spot = engineer.lunch_spot()
        if place == "office":
            out[engineer.engineer_id] = engineer.brigade.office_address_id
        elif place == "point" and spot is not None and spot.address_id is not None:
            out[engineer.engineer_id] = spot.address_id
    return out


def is_cancelled(request: Request) -> bool:
    """Заявку отменили: визит к ней, оставшийся в версии, — только состоявшаяся поездка."""
    status = request.status.value.strip().lower() if request.status else ""
    return status in {"cancelled", "отменена"}


def _is_closed(request: Request) -> bool:
    status = request.status.value.strip().lower() if request.status else ""
    return status in _CLOSED_STATUS


def build_scenario(
    *,
    day: date,
    region_id: int,
    region_name: str,
    requests: list[Request],
    engineers: list[Engineer],
    keep_closed: Collection[int] = (),
) -> tuple[Scenario, dict[int, int]]:
    """Возвращает сценарий и transport_id инженеров для записи назначений.

    `keep_closed` — id закрытых заявок, которые всё равно нужны: показ старой версии плана.
    """

    region_key = str(region_id)
    planner_requests: list[PlannerRequest] = []
    for index, request in enumerate(requests):
        if request.request_id is None or request.address_ref is None:
            continue
        if _is_closed(request) and request.request_id not in keep_closed:
            continue
        skill = _skill(request.skill.value if request.skill else None)
        category = request.request_type_vk.value if request.request_type_vk else ""
        if "дозаказ" in category.lower():
            duration = 20
        else:
            duration = _DURATION_BY_SKILL[skill]
        planner_requests.append(
            PlannerRequest(
                id=str(request.request_id),
                point=GeoPoint(
                    lat=request.address_ref.latitude,
                    lon=request.address_ref.longitude,
                ),
                window_start=_aware(request.plan_start_time),
                window_end=_aware(request.plan_end_time),
                duration_minutes=duration,
                required_skill=skill,
                region_key=region_key,
                priority=_priority(
                    request.priority.value if request.priority else None,
                    skill,
                ),
                required_transport=_transport(
                    request.transport.value if request.transport else None
                ),
                address=request.address_ref.address,
                input_order=index,
                request_type_bk=category,
            )
        )

    planner_engineers: list[PlannerEngineer] = []
    transport_by_engineer: dict[int, int] = {}
    for index, engineer in enumerate(engineers):
        if engineer.engineer_id is None or engineer.brigade is None:
            continue
        office = engineer.brigade.office_address
        if office is None:
            continue
        if engineer.end_work <= engineer.start_work:
            continue
        mode = _transport(engineer.transport.value if engineer.transport else None)
        if mode is None:
            mode = TransportMode.PUBLIC_TRANSPORT
        skills = frozenset(
            _skill(link.skill.value)
            for link in engineer.skills
            if link.skill is not None
        )
        equipment = frozenset(
            link.item.value
            for link in engineer.equipment
            if link.item is not None
        )
        planner_engineers.append(
            PlannerEngineer(
                id=str(engineer.engineer_id),
                name=engineer.name,
                start_point=GeoPoint(lat=office.latitude, lon=office.longitude),
                work_intervals=(
                    WorkInterval(
                        start=_at(day, engineer.start_work),
                        end=_at(day, engineer.end_work),
                    ),
                ),
                skills=skills or frozenset({Skill.CONNECTION}),
                transport_mode=mode,
                region_key=region_key,
                equipment=equipment,
                input_order=index,
                lunch=_lunch(day, engineer, office),
                active=engineer.planning_enabled,
            )
        )
        transport_by_engineer[engineer.engineer_id] = engineer.transport_id

    scenario = Scenario(
        date=day,
        requests=tuple(planner_requests),
        engineers=tuple(planner_engineers),
        name=region_name,
    )
    return scenario, transport_by_engineer


def restrict_availability(scenario: Scenario, cutoffs: dict[str, datetime]) -> Scenario:
    """Обрезает смену инженеров, которые в этот день стали недоступны с указанного момента."""
    if not cutoffs:
        return scenario
    engineers = []
    for engineer in scenario.engineers:
        raw = cutoffs.get(engineer.id)
        if raw is None:
            engineers.append(engineer)
            continue
        cutoff = _aware(raw)
        trimmed = tuple(
            WorkInterval(interval.start, min(interval.end, cutoff))
            for interval in engineer.work_intervals
            if interval.start < cutoff and min(interval.end, cutoff) > interval.start
        )
        engineers.append(
            replace(
                engineer,
                work_intervals=trimmed,
                active=engineer.active and bool(trimmed),
            )
        )
    return replace(scenario, engineers=tuple(engineers))


logger = logging.getLogger(__name__)

# Запросы матриц в ORS — по одному расчёту за раз: пешие и велосипедные поиски вдвоём
# роняли ORS по памяти (26.09). Расчёты по известным адресам этой очереди не ждут.
_fetch_lock = threading.Lock()


def _covered(scenario: Scenario, cache: RoutingCache) -> bool:
    """Все матрицы сценария уже в кэше — в ORS идти не за чем."""
    points = collect_points(scenario)
    for mode in scenario_modes(scenario):
        profile = DEFAULT_PROFILES.get(mode)
        if profile is None or profile in NO_MATRIX_PROFILES:
            continue
        if not covers(cache.legs_of(profile), points, profile):
            return False
    return True


def build_travel(
    scenario: Scenario,
    profiles: tuple[dict[tuple[str, str], Profile], int, int] | None = None,
) -> tuple[Routing, TravelModel | None]:
    """Модель поездок сценария: ORS или его кэш, общественный транспорт — rRAPTOR.

    `profiles` — профили rRAPTOR пар сценария (modules/planning/transit).
    """
    from modules.planning import routing_cache, transit

    # Общественный транспорт новых адресов — RAPTOR на 10:00 в кэш, до чтения кэша
    transit.fill_missing(scenario)
    # Без ORS_URL берутся сохранённые ответы сервиса, без кэша — расстояния по координатам
    url, api_key = ors_endpoint.pick(get_settings())  # основной или запасной ORS
    cache = routing_cache.shared()
    if url and not _covered(scenario, cache):
        with _fetch_lock:
            routing = setup_routing(scenario, url=url, api_key=api_key, cache=cache)
    else:
        routing = setup_routing(scenario, url=url, api_key=api_key, cache=cache)
    if cache.dirty:
        routing_cache.changed()
    travel = routing.travel
    if profiles is not None and profiles[0]:
        # Известные пары — время на фактический момент выезда (rRAPTOR)
        pairs, first, last = profiles
        travel = TimedTransitModel(
            travel or HaversineTravelModel(scenario.settings),
            pairs, scenario.settings, first=first, last=last,
        )
    return routing, travel


Lines = Literal["ors", "cache", "none"]


def finish_plan(
    scenario: Scenario, result: PlanResult, routing: Routing, travel, *, lines: Lines = "ors"
) -> PlanResult:
    """Линии по улицам и состав поездок в готовый план; новые участки — в кэш маршрутов.

    Авто/пешком/велосипед — ORS или кэш, общественный транспорт — RAPTOR на фактический
    выезд. Сбой здесь не должен ронять готовый план.

    `lines`: `"ors"` — недостающие линии из ORS; `"cache"` — только из кэша, остальные
    участки прямые (их достроит `fetch_lines` в фоне: на стенде ORS строит участок
    пешехода или велосипеда 3–14 с, и ход на Ганте ждал бы этого десятки секунд);
    `"none"` — без линий вовсе (базовый план: его показывают только в сравнении, без карты).
    """
    from modules.planning import routing_cache, transit

    if lines != "none":
        if lines == "cache":
            routing = Routing(routing.travel, None, routing.cache, routing.notes)
        try:
            result = routing.attach(result, transit_legs=transit.legs_source(scenario))
        except Exception:  # noqa: BLE001
            logger.exception("Геометрия маршрутов не построена — участки будут прямыми")
    notes = list(routing.notes)
    if isinstance(travel, (OrsTravelModel, TimedTransitModel)):
        notes += [n for n in travel.report() if n not in notes]
    for note in notes:
        logger.warning(note)
    # На диск — в фоне (`routing_cache`): запись 15 МБ JSON не должна держать ответ
    if routing.cache is not None and routing.cache.dirty:
        routing_cache.changed()
    return result


def run_plan(
    scenario: Scenario,
    algorithm: Algorithm = Algorithm.OPTIMIZED,
    profiles: tuple[dict[tuple[str, str], Profile], int, int] | None = None,
    *,
    lines: Lines = "ors",
) -> PlanResult:
    """Расчёт плана. `profiles` — профили rRAPTOR пар сценария (modules/planning/transit)."""
    return run_plan_routed(scenario, algorithm, profiles, lines=lines)[0]


def run_plan_routed(
    scenario: Scenario,
    algorithm: Algorithm = Algorithm.OPTIMIZED,
    profiles: tuple[dict[tuple[str, str], Profile], int, int] | None = None,
    *,
    lines: Lines = "cache",
) -> tuple[PlanResult, Routing]:
    """`run_plan` и маршрутизация, с которой он считался: по ней `fetch_lines` достроит
    в фоне линии, которых не было в кэше."""
    routing, travel = build_travel(scenario, profiles)
    result = plan(scenario, algorithm, travel=travel)
    return finish_plan(scenario, result, routing, travel, lines=lines), routing


def fetch_lines(routing: Routing, result: PlanResult) -> bool:
    """Линии участков плана, которых нет в кэше, — из ORS в кэш. True — кэш пополнился.

    Для плана, сохранённого с `lines="cache"`: выдача плана берёт эти линии из кэша
    (`street_path`). Общественный транспорт пропускается — его строит RAPTOR сразу.
    """
    from modules.planning import routing_cache

    cache = routing.cache
    routes = tuple(
        r for r in result.routes
        if r.visits and r.transport_mode is not TransportMode.PUBLIC_TRANSPORT
    )
    if cache is None or routing.client is None or not routes:
        return False
    before = cache.stats()["geometry"]
    routing.attach(replace(result, routes=routes))
    if cache.stats()["geometry"] == before:
        return False
    routing_cache.changed()
    return True


def street_path(path: dict, profile: str | None, cache: RoutingCache) -> dict:
    """Участок, сохранённый прямой, — по улицам, если его линия уже появилась в кэше.

    Прямой участок в строке плана — линия из двух точек: самих адресов. Линия ORS между
    двумя адресами всегда длиннее (точки привязаны к улицам), поэтому путаницы нет.
    """
    line = path.get("line") or []
    if len(line) != 2 or path.get("transit") or profile is None or profile in NO_MATRIX_PROFILES:
        return path
    a = GeoPoint(lat=line[0][1], lon=line[0][0])
    b = GeoPoint(lat=line[1][1], lon=line[1][0])
    found = cache.get_geometry(profile, a, b)
    if not found or len(found) < 2:
        return path
    return {**path, "line": found, "straight": False}


def route_legs(
    result: PlanResult,
    *,
    address_of: dict[int, int],
    office_of: dict[int, int],
    transport_of: dict[int, int],
    offset_hours: float = 3.0,
    lunch_address_of: dict[int, int] | None = None,
) -> dict[int, dict]:
    """Участок до каждого визита — для таблицы `routes`: откуда, когда, линия, состав поездки.

    Ключ — request_id. `path` — линия участка [[lon, lat], …] из общей геометрии маршрута
    (`Visit.geometry_range`) и состав поездки на общественном транспорте (`Visit.transit`).
    После обеда в офисе или своей точке визит едет от места обеда (`lunch_address_of`);
    дорога к самому обеду хранится в обедах плана (`lunch_rows`).
    """
    legs: dict[int, dict] = {}
    lunch_address_of = lunch_address_of or {}
    for route in result.routes:
        engineer_id = int(route.engineer_id)
        previous = office_of.get(engineer_id)
        line = [[p.lon, p.lat] for p in route.geometry]
        lunch = route.lunch
        for index, visit in enumerate(route.visits):
            if lunch is not None and lunch.is_detour and lunch.after_position == index:
                previous = lunch_address_of.get(engineer_id, previous)
            request_id = int(visit.request_id)
            here = address_of.get(request_id)
            if visit.geometry_range is not None and line:
                lo, hi = visit.geometry_range
                segment = line[lo : hi + 1]
            else:
                segment = [[visit.from_point.lon, visit.from_point.lat], [visit.to_point.lon, visit.to_point.lat]]
            if previous is not None and here is not None and engineer_id in transport_of:
                legs[request_id] = {
                    "start_point_id": previous,
                    "end_point_id": here,
                    "transport_id": transport_of[engineer_id],
                    "start_time": local_time(visit.departure_at, offset_hours),
                    "end_time": local_time(visit.arrival_at, offset_hours),
                    "path": {
                        "line": segment,
                        "straight": visit.geometry_range is None or route.geometry_source == "straight",
                        "transit": [leg.to_dict() for leg in visit.transit],
                    },
                }
            previous = here
    return legs


def lunch_rows(result: PlanResult, offset_hours: float = 3.0) -> list[dict]:
    """Обеды плана для `plans.lunches`: когда, где и дорога к месту обеда. Времена — местные."""

    def clock(moment: datetime | None) -> str | None:
        value = local_time(moment, offset_hours)
        return value.isoformat(timespec="seconds") if value is not None else None

    rows: list[dict] = []
    # Начатый обед инженера без заявок — без маршрута, дорога к обеду по прямой
    for engineer_id, lunch in result.idle_lunches:
        rows.append({
            "engineer_id": int(engineer_id),
            "after_position": 0,
            "departure_at": clock(lunch.departure_at),
            "arrival_at": clock(lunch.arrival_at),
            "start_at": clock(lunch.start_at),
            "end_at": clock(lunch.end_at),
            "travel_minutes": round(lunch.travel_minutes, 2),
            "distance_km": round(lunch.distance_km, 3),
            "place": lunch.place,
            "address": lunch.address,
            "point": [lunch.point.lon, lunch.point.lat],
            "detour": lunch.is_detour,
            "locked": True,
            "path": {
                "line": [[lunch.from_point.lon, lunch.from_point.lat], [lunch.point.lon, lunch.point.lat]],
                "straight": True,
                "transit": [],
            } if lunch.is_detour else None,
        })
    for route in result.routes:
        lunch = route.lunch
        if lunch is None:
            continue
        line = [[p.lon, p.lat] for p in route.geometry]
        path = None
        if lunch.is_detour:
            if lunch.geometry_range is not None and line:
                lo, hi = lunch.geometry_range
                segment = line[lo : hi + 1]
            else:
                segment = [[lunch.from_point.lon, lunch.from_point.lat], [lunch.point.lon, lunch.point.lat]]
            path = {
                "line": segment,
                "straight": lunch.geometry_range is None or route.geometry_source == "straight",
                "transit": [leg.to_dict() for leg in lunch.transit],
            }
        rows.append({
            "engineer_id": int(route.engineer_id),
            "after_position": lunch.after_position,
            "departure_at": clock(lunch.departure_at),
            "arrival_at": clock(lunch.arrival_at),
            "start_at": clock(lunch.start_at),
            "end_at": clock(lunch.end_at),
            "travel_minutes": round(lunch.travel_minutes, 2),
            "distance_km": round(lunch.distance_km, 3),
            "place": lunch.place,
            "address": lunch.address,
            "point": [lunch.point.lon, lunch.point.lat],
            "detour": lunch.is_detour,
            "locked": lunch.locked,
            "shifted": lunch.shifted,
            "path": path,
        })
    return rows


def reason_index(dicts: list) -> dict[str, int]:
    by_value = {
        item.value.strip().lower(): item.dict_id
        for item in dicts
        if item.dict_id is not None
    }
    indexed: dict[str, int] = {}
    for code, label in _REASON_LABELS.items():
        if code in by_value:
            indexed[code] = by_value[code]
        elif label in by_value:
            indexed[code] = by_value[label]
    return indexed


def local_time(moment: datetime | None, offset_hours: float = 3.0) -> datetime | None:
    """Момент плана → наивное местное время региона, как хранятся времена заявок в БД."""
    if moment is None or moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone(timedelta(hours=offset_hours))).replace(tzinfo=None)


def assignments_from_result(
    result: PlanResult,
    *,
    transport_by_engineer: dict[int, int],
    reason_by_code: dict[str, int],
    offset_hours: float = 3.0,
    scenario: Scenario | None = None,
    window_shift: dict[str, float] | None = None,
) -> tuple[list[Assignment], int, int]:
    """Строки назначений плана — вместе с расписанием визита (выезд, прибытие, работа).

    `scenario` — откуда взять окна клиентов, которые версия запоминает. `window_shift` —
    на сколько минут окно заявки сдвинуто согласованием в этом же ходе: в сценарии его
    ещё нет, а версия должна хранить уже новое.
    """
    visits = {v.request_id: v for route in result.routes for v in route.visits}
    by_id = scenario.request_by_id if scenario is not None else {}
    shifts = window_shift or {}
    rows: list[Assignment] = []
    assigned = 0
    unassigned = 0
    for item in result.assignments:
        request_id = int(item.request_id)
        window = {}
        source = by_id.get(item.request_id)
        if source is not None:
            shift = timedelta(minutes=shifts.get(item.request_id, 0.0))
            window = {
                "window_start": local_time(source.window_start + shift, offset_hours),
                "window_end": local_time(source.window_end + shift, offset_hours),
            }
        if item.is_assigned and item.engineer_id is not None:
            engineer_id = int(item.engineer_id)
            visit = visits.get(item.request_id)
            rows.append(
                Assignment(
                    request_id=request_id,
                    engineer_id=engineer_id,
                    plan_id=0,
                    transport_id=transport_by_engineer.get(engineer_id),
                    explanation=item.explanation or None,
                    **window,
                    **({} if visit is None else {
                        "position": visit.position,
                        "planned_departure_at": local_time(visit.departure_at, offset_hours),
                        "planned_arrival_at": local_time(visit.arrival_at, offset_hours),
                        "planned_start_at": local_time(visit.service_start_at, offset_hours),
                        "planned_end_at": local_time(visit.service_end_at, offset_hours),
                        "travel_minutes": round(visit.travel_minutes, 2),
                        "distance_km": round(visit.distance_km, 3),
                        "waiting_minutes": round(visit.waiting_minutes, 2),
                        "idle_minutes": round(visit.idle_before_minutes, 2),
                    }),
                )
            )
            assigned += 1
            continue
        reason_id = None
        if item.reason is not None:
            reason_id = reason_by_code.get(item.reason.value)
        rows.append(
            Assignment(
                request_id=request_id,
                engineer_id=None,
                plan_id=0,
                transport_id=None,
                unassigned_reason_id=reason_id,
                explanation=item.explanation or None,
                **window,
            )
        )
        unassigned += 1
    return rows, assigned, unassigned

"""Сборка входа `planner.plan` из строк БД и разбор результата обратно в назначения."""

from __future__ import annotations

import logging
import sys
import threading
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

_SOLUTION = Path(__file__).resolve().parents[3] / "solution"
if str(_SOLUTION) not in sys.path:
    sys.path.insert(0, str(_SOLUTION))

from planner import (  # noqa: E402
    Engineer as PlannerEngineer,
)
from planner import (  # noqa: E402
    Algorithm,
    GeoPoint,
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
from planner.travel import HaversineTravelModel  # noqa: E402

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


def _at(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock)


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
) -> tuple[Scenario, dict[int, int]]:
    """Возвращает сценарий и transport_id инженеров для записи назначений."""

    region_key = str(region_id)
    planner_requests: list[PlannerRequest] = []
    for index, request in enumerate(requests):
        if request.request_id is None or request.address_ref is None or _is_closed(request):
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
                window_start=request.plan_start_time,
                window_end=request.plan_end_time,
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


logger = logging.getLogger(__name__)

# Кэш маршрутов — один JSON-файл, запись не атомарная: чтение и запись по очереди
routing_cache_lock = threading.Lock()


def run_plan(
    scenario: Scenario,
    algorithm: Algorithm = Algorithm.OPTIMIZED,
    profiles: tuple[dict[tuple[str, str], Profile], int, int] | None = None,
) -> PlanResult:
    """Расчёт плана. `profiles` — профили rRAPTOR пар сценария (modules/planning/transit)."""
    from modules.planning import transit

    # Общественный транспорт новых адресов — RAPTOR на 10:00 в кэш, до чтения кэша
    transit.fill_missing(scenario)
    # Без ORS_URL берутся сохранённые ответы сервиса, без кэша — расстояния по координатам
    settings = get_settings()
    options = {"cache_path": settings.routing_cache_path} if settings.routing_cache_path else {}
    url, api_key = ors_endpoint.pick(settings)  # основной или запасной ORS
    with routing_cache_lock:
        routing = setup_routing(scenario, url=url, api_key=api_key, **options)
    travel = routing.travel
    if profiles is not None and profiles[0]:
        # Известные пары — время на фактический момент выезда (rRAPTOR)
        pairs, first, last = profiles
        travel = TimedTransitModel(
            travel or HaversineTravelModel(scenario.settings),
            pairs, scenario.settings, first=first, last=last,
        )
    result = plan(scenario, algorithm, travel=travel)
    # Линии по улицам и состав поездок: авто/пешком/велосипед — ORS или кэш, общественный
    # транспорт — RAPTOR на фактический выезд. Сбой здесь не должен ронять готовый план.
    try:
        result = routing.attach(result, transit_legs=transit.legs_source(scenario))
    except Exception:  # noqa: BLE001
        logger.exception("Геометрия маршрутов не построена — участки будут прямыми")
    notes = list(routing.notes)
    if isinstance(travel, (OrsTravelModel, TimedTransitModel)):
        notes += [n for n in travel.report() if n not in notes]
    for note in notes:
        logger.warning(note)
    with routing_cache_lock:
        routing.save()
    return result


def route_legs(
    result: PlanResult,
    *,
    address_of: dict[int, int],
    office_of: dict[int, int],
    transport_of: dict[int, int],
    offset_hours: float = 3.0,
) -> dict[int, dict]:
    """Участок до каждого визита — для таблицы `routes`: откуда, когда, линия, состав поездки.

    Ключ — request_id. `path` — линия участка [[lon, lat], …] из общей геометрии маршрута
    (`Visit.geometry_range`) и состав поездки на общественном транспорте (`Visit.transit`).
    """
    legs: dict[int, dict] = {}
    for route in result.routes:
        engineer_id = int(route.engineer_id)
        previous = office_of.get(engineer_id)
        line = [[p.lon, p.lat] for p in route.geometry]
        for visit in route.visits:
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
) -> tuple[list[Assignment], int, int]:
    """Строки назначений плана — вместе с расписанием визита (выезд, прибытие, работа)."""
    visits = {v.request_id: v for route in result.routes for v in route.visits}
    rows: list[Assignment] = []
    assigned = 0
    unassigned = 0
    for item in result.assignments:
        request_id = int(item.request_id)
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
            )
        )
        unassigned += 1
    return rows, assigned, unassigned

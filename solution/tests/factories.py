# -*- coding: utf-8 -*-
"""Короткие билдеры входных данных и независимые «оракулы» расчётов.

Модуль решает три задачи:

1. Аккуратно подтягивает публичные имена пакета ``planner`` (SPEC §1, §2, §8).
   Если пакет ещё не реализован или неполон — весь тест-модуль скипается с
   внятным сообщением, а не разваливает коллекцию.
2. Даёт максимально короткую запись сценария::

       eng("E1", skills=["connection"], shift=("09:00", "18:00"))
       req("R1", window=("10:00", "12:00"), dur=70, skill="connection")
       sc([r1, r2], [e1])

3. Содержит НЕЗАВИСИМЫЕ от реализации формулы (гаверсинус, время в пути,
   рабочий календарь). Они нужны, чтобы тесты проверяли контракт, а не
   повторяли вычисления планировщика.
"""
from __future__ import annotations

import importlib
import math
import random
import types
from dataclasses import replace
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

import pytest

# --------------------------------------------------------------------------
# Константы времени (SPEC §0: Europe/Moscow = фиксированный UTC+3)
# --------------------------------------------------------------------------

TZ = timezone(timedelta(hours=3))
DATE = _date(2026, 8, 17)  # понедельник, дата из примеров базы знаний


def _skip(message: str) -> None:
    """Скипнуть текущий тест-модуль целиком с понятной причиной."""
    pytest.skip(message, allow_module_level=True)


# --------------------------------------------------------------------------
# Разрешение публичных имён пакета planner
# --------------------------------------------------------------------------

try:
    import planner as _planner  # noqa: F401
except Exception as exc:  # pragma: no cover - ветка для незавершённой реализации
    _skip(f"пакет planner недоступен для импорта: {exc!r}")

# Функции верхнего уровня резолвим ДО импорта подмодулей: `import planner.replan`
# перезапишет атрибут `planner.replan` модулем и «съест» одноимённую функцию.
_API_RAW: dict[str, Any] = {
    name: getattr(_planner, name, None)
    for name in ("plan", "replan", "apply_event", "compare", "validate_plan", "solve")
}

_MODULE_NAMES = (
    "planner",
    "planner.enums",
    "planner.models",
    "planner.result",
    "planner.cost",
    "planner.calendar",
    "planner.travel",
    "planner.feasibility",
)
_MODULES: dict[str, types.ModuleType] = {}
for _name in _MODULE_NAMES:
    try:
        _MODULES[_name] = importlib.import_module(_name)
    except Exception:  # подмодуля может не быть — это не повод падать целиком
        continue


def sym(name: str, required: bool = True):
    """Найти публичное имя в любом из модулей пакета planner.

    SPEC описывает выходные модели то как ``planner.models``, то как
    ``planner.result``, поэтому поиск идёт по нескольким модулям.
    """
    for mod_name in _MODULE_NAMES:
        mod = _MODULES.get(mod_name)
        if mod is not None and hasattr(mod, name):
            return getattr(mod, name)
    if required:
        _skip(f"в пакете planner не найдено публичное имя {name!r} (см. SPEC)")
    return None


def _api(name: str):
    """Достать функцию публичного API, обойдя затенение подмодулем."""
    value = _API_RAW.get(name)
    if callable(value) and not isinstance(value, types.ModuleType):
        return value
    mod = _MODULES.get(f"planner.{name}")
    if mod is not None and callable(getattr(mod, name, None)):
        return getattr(mod, name)
    value = getattr(_planner, name, None)
    if callable(value) and not isinstance(value, types.ModuleType):
        return value
    _skip(f"в planner нет функции публичного API {name}() (SPEC §8)")


# Перечисления (SPEC §1)
Skill = sym("Skill")
TransportMode = sym("TransportMode")
Priority = sym("Priority")
AssignmentStatus = sym("AssignmentStatus")
Algorithm = sym("Algorithm")
EventType = sym("EventType")
ReasonCode = sym("ReasonCode")

# Входные модели (SPEC §2)
GeoPoint = sym("GeoPoint")
WorkInterval = sym("WorkInterval")
Engineer = sym("Engineer")
Request = sym("Request")
Settings = sym("Settings")
Scenario = sym("Scenario")
ReplanEvent = sym("ReplanEvent")

# Публичный API (SPEC §8)
plan = _api("plan")
replan = _api("replan")
apply_event = _api("apply_event")
compare = _api("compare")
validate_plan = _api("validate_plan")
solve = _api("solve")


def scenario_after(scenario, previous, ev):
    """Действующий сценарий после события — единственный корректный вход validate_plan.

    После события состав заявок меняется (срочная добавилась, отменённая исчезла, у
    заявки с отказом клиента обнулилась работа), поэтому результат ``replan()`` описывает
    именно этот сценарий, а не исходный.
    """
    updated, _notes = apply_event(scenario, previous, ev)
    return updated


# --------------------------------------------------------------------------
# Время
# --------------------------------------------------------------------------


def t(hhmm: str, day: _date | None = None) -> datetime:
    """Момент "HH:MM" на дате сценария в московском времени."""
    hours, minutes = hhmm.split(":")
    base = day or DATE
    return datetime(base.year, base.month, base.day, int(hours), int(minutes), tzinfo=TZ)


def hhmm(moment: datetime | None) -> str:
    """Читаемое представление момента для сообщений об ошибках."""
    if moment is None:
        return "None"
    return moment.astimezone(TZ).strftime("%d.%m %H:%M:%S")


def minutes_between(a: datetime, b: datetime) -> float:
    """Календарные (не рабочие) минуты между двумя моментами."""
    return (b - a).total_seconds() / 60.0


def dt_close(a: datetime | None, b: datetime | None, tol_seconds: float = 1.0) -> bool:
    """Сравнение моментов с допуском — расчёты ведутся в float-минутах."""
    if a is None or b is None:
        return a is b
    return abs((a - b).total_seconds()) <= tol_seconds


def assert_dt(actual: datetime | None, expected: datetime | None, what: str = "", tol: float = 1.0) -> None:
    """Assert на момент времени с человекочитаемым сообщением."""
    assert dt_close(actual, expected, tol), (
        f"{what}: ожидалось {hhmm(expected)}, получено {hhmm(actual)}"
    )


# --------------------------------------------------------------------------
# Билдеры входных моделей
# --------------------------------------------------------------------------

_DEFAULT_ENG_POINT = (55.70, 37.60)
_DEFAULT_REQ_POINT = (55.71, 37.61)


def gp(point) -> Any:
    """GeoPoint из пары (lat, lon) либо готового GeoPoint."""
    if isinstance(point, GeoPoint):
        return point
    lat, lon = point
    return GeoPoint(float(lat), float(lon))


def _normalize_shift(shift, day: _date | None) -> tuple:
    """Привести разные записи графика к кортежу WorkInterval.

    Поддерживаются: ``("09:00", "18:00")``, ``[("09:00","13:00"), ("14:00","18:00")]``,
    ``None``/``()`` (выходной), готовые WorkInterval.
    """
    if not shift:
        return ()
    if isinstance(shift[0], str):
        shift = [shift]
    intervals = []
    for item in shift:
        if isinstance(item, WorkInterval):
            intervals.append(item)
            continue
        start, end = item
        start_dt = t(start, day) if isinstance(start, str) else start
        end_dt = t(end, day) if isinstance(end, str) else end
        intervals.append(WorkInterval(start_dt, end_dt))
    return tuple(intervals)


def _skills(values: Iterable[str]) -> frozenset:
    return frozenset(v if isinstance(v, Skill) else Skill(v) for v in values)


def eng(
    id: str,
    *,
    skills: Sequence[str] = ("connection",),
    shift=("09:00", "18:00"),
    at=_DEFAULT_ENG_POINT,
    transport: str = "car",
    region: str = "default",
    equipment: Iterable[str] = (),
    active: bool = True,
    order: int = 0,
    name: str | None = None,
    day: _date | None = None,
) -> Any:
    """Инженер с разумными дефолтами (SPEC §2.3)."""
    return Engineer(
        id=id,
        name=name if name is not None else f"Инженер {id}",
        start_point=gp(at),
        work_intervals=_normalize_shift(shift, day),
        skills=_skills(skills),
        transport_mode=transport if isinstance(transport, TransportMode) else TransportMode(transport),
        region_key=region,
        equipment=frozenset(equipment),
        active=active,
        input_order=order,
    )


def req(
    id: str,
    *,
    window=("10:00", "12:00"),
    dur: int = 70,
    skill: str = "connection",
    at=_DEFAULT_REQ_POINT,
    priority: str = "normal",
    region: str = "default",
    transport: str | None = None,
    equipment: Iterable[str] = (),
    order: int = 0,
    address: str = "",
    district: str = "",
    day: _date | None = None,
) -> Any:
    """Заявка с разумными дефолтами (SPEC §2.4)."""
    start, end = window
    return Request(
        id=id,
        point=gp(at),
        window_start=t(start, day) if isinstance(start, str) else start,
        window_end=t(end, day) if isinstance(end, str) else end,
        duration_minutes=dur,
        required_skill=skill if isinstance(skill, Skill) else Skill(skill),
        region_key=region,
        priority=priority if isinstance(priority, Priority) else Priority(priority),
        required_transport=(
            None
            if transport is None
            else (transport if isinstance(transport, TransportMode) else TransportMode(transport))
        ),
        required_equipment=frozenset(equipment),
        address=address,
        district=district,
        input_order=order,
    )


def settings(**overrides) -> Any:
    """Settings с проверкой имён полей — опечатка в тесте должна падать сразу."""
    s = Settings()
    for key, value in overrides.items():
        if not hasattr(s, key):
            raise AttributeError(f"в Settings нет поля {key!r} (см. SPEC §2.5)")
        setattr(s, key, value)
    return s


def sc(
    requests: Sequence[Any],
    engineers: Sequence[Any],
    *,
    date: _date | None = None,
    name: str = "",
    renumber: bool = True,
    **settings_overrides,
) -> Any:
    """Сценарий (SPEC §2.6).

    По умолчанию ``input_order`` проставляется по позиции в списке — именно от
    него зависит поведение baseline и все tie-break'и. ``renumber=False``
    сохраняет явно заданные порядки.
    """
    reqs = tuple(requests)
    engs = tuple(engineers)
    if renumber:
        reqs = tuple(replace(r, input_order=i) for i, r in enumerate(reqs))
        engs = tuple(replace(e, input_order=i) for i, e in enumerate(engs))
    return Scenario(
        date=date or DATE,
        requests=reqs,
        engineers=engs,
        settings=settings(**settings_overrides),
        name=name,
    )


def event(
    type_: str,
    at: str | datetime,
    *,
    request=None,
    request_id: str | None = None,
    engineer_id: str | None = None,
    comment: str = "",
    day: _date | None = None,
) -> Any:
    """Событие перепланирования (SPEC §2.7)."""
    return ReplanEvent(
        type=type_ if isinstance(type_, EventType) else EventType(type_),
        at=t(at, day) if isinstance(at, str) else at,
        request=request,
        request_id=request_id,
        engineer_id=engineer_id,
        comment=comment,
    )


# --------------------------------------------------------------------------
# Независимые «оракулы» — формулы SPEC, реализованные отдельно от planner
# --------------------------------------------------------------------------

EARTH_R_KM = 6371.0088


def oracle_haversine_km(a, b) -> float:
    """Гаверсинус по формуле SPEC §3.2 (независимая реализация)."""
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(h))


def _same_point(a, b) -> bool:
    return a.lat == b.lat and a.lon == b.lon


def oracle_distance_km(a, b, mode, cfg) -> float:
    """distance_km = haversine * detour_factor[mode]; 0.0 для совпадающих точек."""
    if _same_point(a, b):
        return 0.0
    return oracle_haversine_km(a, b) * cfg.detour_factor[mode]


def oracle_travel_minutes(a, b, mode, cfg) -> float:
    """travel = distance/speed*60 + overhead; 0.0 для совпадающих точек."""
    if _same_point(a, b):
        return 0.0
    return oracle_distance_km(a, b, mode, cfg) / cfg.speed_kmh[mode] * 60.0 + cfg.overhead_minutes[mode]


class OracleCalendar:
    """Независимая реализация рабочего календаря (SPEC §3.1).

    Используется тестами как эталон, чтобы не проверять planner его же кодом.
    """

    def __init__(self, intervals: Iterable[Any]):
        self.intervals = tuple(sorted(intervals, key=lambda iv: iv.start))

    @property
    def capacity_minutes(self) -> float:
        return sum(minutes_between(iv.start, iv.end) for iv in self.intervals)

    def contains(self, moment: datetime) -> bool:
        return any(iv.start <= moment <= iv.end for iv in self.intervals)

    def first_moment_at_or_after(self, moment: datetime) -> datetime | None:
        for iv in self.intervals:
            if moment <= iv.start:
                return iv.start
            if moment <= iv.end:
                return moment
        return None

    def add(self, moment: datetime, minutes: float) -> datetime | None:
        cur = self.first_moment_at_or_after(moment)
        if cur is None:
            return None
        left = float(minutes)
        for iv in self.intervals:
            if iv.end <= cur:
                continue
            start = max(cur, iv.start)
            available = minutes_between(start, iv.end)
            if left <= available:
                return start + timedelta(minutes=left)
            left -= available
            cur = iv.end
        return None

    def sub(self, moment: datetime, minutes: float) -> datetime | None:
        left = float(minutes)
        cur = moment
        for iv in reversed(self.intervals):
            if iv.start >= cur:
                continue
            end = min(cur, iv.end)
            available = minutes_between(iv.start, end)
            if left <= available:
                return end - timedelta(minutes=left)
            left -= available
            cur = iv.start
        return None

    def working_between(self, a: datetime, b: datetime) -> float:
        if b <= a:
            return 0.0
        total = 0.0
        for iv in self.intervals:
            lo, hi = max(a, iv.start), min(b, iv.end)
            if hi > lo:
                total += minutes_between(lo, hi)
        return total


def oracle_calendar(engineer) -> OracleCalendar:
    """Эталонный календарь инженера."""
    return OracleCalendar(engineer.work_intervals)


# --------------------------------------------------------------------------
# Удобные обёртки над результатом планирования
# --------------------------------------------------------------------------


def plan_baseline(scenario):
    """Базовый план (SPEC §6.1)."""
    return plan(scenario, Algorithm.BASELINE)


def plan_optimized(scenario):
    """Оптимизированный план (SPEC §6.2)."""
    return plan(scenario, Algorithm.OPTIMIZED)


def plan_both(scenario):
    """Пара (baseline, optimized) для сравнительных проверок."""
    return plan_baseline(scenario), plan_optimized(scenario)


def assignments_by_id(result) -> dict[str, Any]:
    """Отображение request_id -> Assignment."""
    return {a.request_id: a for a in result.assignments}


def routes_by_engineer(result) -> dict[str, Any]:
    """Отображение engineer_id -> RouteResult."""
    return {r.engineer_id: r for r in result.routes}


def assigned_ids(result) -> set[str]:
    """Идентификаторы назначенных заявок."""
    return {a.request_id for a in result.assignments if a.status == AssignmentStatus.ASSIGNED}


def unassigned_ids(result) -> set[str]:
    """Идентификаторы неназначенных заявок."""
    return {a.request_id for a in result.assignments if a.status == AssignmentStatus.UNASSIGNED}


def route_request_ids(result, engineer_id: str) -> list[str]:
    """Порядок посещения заявок конкретным инженером."""
    route = routes_by_engineer(result).get(engineer_id)
    if route is None:
        return []
    return [v.request_id for v in route.visits]


def has_cyrillic(text: str) -> bool:
    """Строка содержит кириллицу — объяснения обязаны быть на русском."""
    return any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in text or "")


VOLATILE_KEYS = {"computation_ms", "plan_id", "previous_plan_id", "generated_at", "created_at"}


def normalized_dict(result) -> Any:
    """``to_dict()`` без нестабильных полей (время расчёта, сгенерированные id).

    Нужен для сравнения прогонов: побайтовое равенство SPEC требует от
    содержательной части плана, а не от ``computation_ms``.
    """

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in VOLATILE_KEYS}
        if isinstance(node, (list, tuple)):
            return [strip(v) for v in node]
        return node

    return strip(result.to_dict())


# --------------------------------------------------------------------------
# Псевдослучайные сценарии (детерминированные по seed)
# --------------------------------------------------------------------------

_SKILL_POOL = ("local", "connection", "emergency")
_DURATIONS = (20, 30, 70, 80)  # нормативы БЗ без дорожных 20 минут


def random_scenario(
    seed: int,
    n_engineers: int = 4,
    n_requests: int = 20,
    *,
    urgent_share: float = 0.15,
    transport_pool: Sequence[str] = ("car", "walking", "bicycle", "public_transport"),
    box: tuple[float, float, float, float] = (55.60, 55.85, 37.40, 37.80),
    **settings_overrides,
):
    """Детерминированный псевдослучайный сценарий по seed.

    Генерация зависит только от seed, поэтому property-тесты воспроизводимы.
    """
    rnd = random.Random(seed)
    lat_lo, lat_hi, lon_lo, lon_hi = box

    def point():
        return (round(rnd.uniform(lat_lo, lat_hi), 5), round(rnd.uniform(lon_lo, lon_hi), 5))

    engineers = []
    for i in range(n_engineers):
        skills = [s for s in _SKILL_POOL if rnd.random() < 0.6] or [rnd.choice(_SKILL_POOL)]
        if rnd.random() < 0.3:
            shift = [("09:00", "13:00"), ("14:00", "18:00")]
        else:
            shift = ("09:00", "18:00")
        engineers.append(
            eng(
                f"E{i + 1}",
                skills=skills,
                shift=shift,
                at=point(),
                transport=rnd.choice(transport_pool),
                order=i,
            )
        )

    requests = []
    for i in range(n_requests):
        start_minute = rnd.randrange(9 * 60, 16 * 60, 30)
        width = rnd.choice((60, 90, 120, 180))
        ws = datetime(DATE.year, DATE.month, DATE.day, tzinfo=TZ) + timedelta(minutes=start_minute)
        requests.append(
            req(
                f"R{i + 1}",
                window=(ws, ws + timedelta(minutes=width)),
                dur=rnd.choice(_DURATIONS),
                skill=rnd.choice(_SKILL_POOL),
                at=point(),
                priority="urgent" if rnd.random() < urgent_share else "normal",
                order=i,
            )
        )

    return sc(requests, engineers, name=f"random-{seed}", **settings_overrides)

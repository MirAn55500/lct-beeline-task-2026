"""Входные модели планировщика.

Все входные объекты неизменяемы (`frozen=True`): планировщик никогда не мутирует
переданный сценарий, а строит собственное рабочее состояние. Это даёт воспроизводимость
и позволяет безопасно переиспользовать один сценарий для baseline и optimized.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from .enums import EventType, ExecutionStatus, Priority, ReplanScope, Skill, TransportMode

__all__ = [
    "MSK",
    "GeoPoint",
    "WorkInterval",
    "Lunch",
    "Engineer",
    "Request",
    "Settings",
    "Scenario",
    "ReplanEvent",
]

MSK = timezone(timedelta(hours=3))
"""Москва, UTC+3. Предоставленный набор данных целиком в этом поясе."""


def _parse_dt(value: Any) -> datetime:
    """Принимает datetime или ISO-строку, всегда возвращает aware-datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=MSK)
    if isinstance(value, str):
        return _parse_dt(datetime.fromisoformat(value))
    raise TypeError(f"Ожидалась дата и время, получено {type(value).__name__}")


# --------------------------------------------------------------------------------------
# География
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """Координата WGS84. В GeoJSON порядок пар — (lon, lat), см. `as_geojson`."""

    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.lat <= 90.0:
            raise ValueError(f"Широта вне диапазона [-90, 90]: {self.lat}")
        if not -180.0 <= self.lon <= 180.0:
            raise ValueError(f"Долгота вне диапазона [-180, 180]: {self.lon}")

    def as_geojson(self) -> list[float]:
        return [self.lon, self.lat]

    def to_dict(self) -> dict[str, float]:
        return {"lat": self.lat, "lon": self.lon}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "GeoPoint":
        return cls(lat=float(raw["lat"]), lon=float(raw["lon"]))

    def is_same_as(self, other: "GeoPoint", eps: float = 1e-9) -> bool:
        return math.isclose(self.lat, other.lat, abs_tol=eps) and math.isclose(
            self.lon, other.lon, abs_tol=eps
        )


# --------------------------------------------------------------------------------------
# Рабочее время
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkInterval:
    """Непрерывный рабочий интервал. Разрывы между интервалами = перерывы."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        # Нормализуем tz-aware: смешение naive и aware роняет любое сравнение,
        # поэтому недостающая зона достраивается здесь же, как у других полей.
        object.__setattr__(self, "start", _parse_dt(self.start))
        object.__setattr__(self, "end", _parse_dt(self.end))
        if self.end <= self.start:
            raise ValueError(f"Рабочий интервал пуст или вывернут: {self.start} .. {self.end}")

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "WorkInterval":
        return cls(start=_parse_dt(raw["start"]), end=_parse_dt(raw["end"]))


def _normalize_intervals(intervals: Iterable[WorkInterval]) -> tuple[WorkInterval, ...]:
    """Сортирует интервалы и запрещает пересечения (перерыв — это разрыв, а не наложение)."""
    ordered = tuple(sorted(intervals, key=lambda i: (i.start, i.end)))
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.start < prev.end:
            raise ValueError(f"Рабочие интервалы пересекаются: {prev.end} > {nxt.start}")
    return ordered


@dataclass(frozen=True, slots=True)
class Lunch:
    """Обед инженера: `minutes` подряд где-то внутри окна [`window_start`, `window_end`].

    Когда именно обедать, решает планировщик: обед стоит в маршруте между заявками там,
    где он меньше всего мешает. Работу обед не прерывает — это отдельная остановка.

    `point` — где обедать. `None` — там, где инженер окажется: у последней заявки
    (до первой — в точке старта), без лишней дороги. Точка (офис, кафе) — к ней
    нужно доехать и от неё ехать дальше, и эту дорогу планировщик тоже учитывает.
    `place` и `address` — только подписи для интерфейса.
    """

    window_start: datetime
    window_end: datetime
    minutes: int = 60
    point: GeoPoint | None = None
    place: str = "last_request"
    """`last_request` — у последней заявки, `office` — в офисе, `point` — в своей точке."""
    address: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_start", _parse_dt(self.window_start))
        object.__setattr__(self, "window_end", _parse_dt(self.window_end))
        if self.minutes <= 0:
            raise ValueError("Обед должен длиться больше нуля минут")
        if self.window_end <= self.window_start:
            raise ValueError(f"Окно обеда пусто или вывернуто: {self.window_start} .. {self.window_end}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "minutes": self.minutes,
            "point": self.point.to_dict() if self.point is not None else None,
            "place": self.place,
            "address": self.address,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Lunch":
        point = raw.get("point")
        return cls(
            window_start=_parse_dt(raw["window_start"]),
            window_end=_parse_dt(raw["window_end"]),
            minutes=int(raw.get("minutes", 60)),
            point=GeoPoint.from_dict(point) if point else None,
            place=str(raw.get("place", "last_request")),
            address=str(raw.get("address", "")),
        )


# --------------------------------------------------------------------------------------
# Исполнитель
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Engineer:
    """Один выездной инженер.

    Стартовая точка — офис бригады своего региона либо условный домашний адрес
    в удалённом городе Подмосковья (`home_start=True`). Возврат после последней
    заявки моделью не предусмотрен (ТЗ п. 2.4, открытый маршрут).
    """

    id: str
    name: str
    start_point: GeoPoint
    work_intervals: tuple[WorkInterval, ...] = ()
    skills: frozenset[Skill] = frozenset()
    skill_levels: tuple[tuple[Skill, str], ...] = ()
    """Уровень владения по каждому навыку — пары (навык, уровень).

    Хранится и показывается, но в отборе исполнителя НЕ участвует: шкала квалификации
    и правило её влияния на назначение в базе знаний остаются открытым вопросом.
    Придумывать это правило за заказчика нельзя, а терять данные — тем более.
    """
    transport_mode: TransportMode = TransportMode.CAR
    region_key: str = "default"
    equipment: frozenset[str] = frozenset()
    active: bool = True
    input_order: int = 0
    home_start: bool = False
    """True, если `start_point` — условный домашний адрес, а не офис бригады.

    Комплект оборудования к моменту такого старта считается уже выданным;
    логистика выдачи в маршрут не включается.
    """
    lunch: Lunch | None = None
    """Обед в течение смены; `None` — обед не планируется."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "work_intervals", _normalize_intervals(self.work_intervals))
        object.__setattr__(self, "skills", frozenset(Skill(s) for s in self.skills))
        object.__setattr__(
            self, "skill_levels", tuple((Skill(k), str(v)) for k, v in self.skill_levels)
        )
        object.__setattr__(self, "equipment", frozenset(self.equipment))
        object.__setattr__(self, "transport_mode", TransportMode(self.transport_mode))

    @property
    def capacity_minutes(self) -> float:
        return sum(i.minutes for i in self.work_intervals)

    def level_of(self, skill: Skill) -> str | None:
        """Уровень владения навыком; `None`, если он не задан."""
        for code, level in self.skill_levels:
            if code == skill:
                return level
        return None

    @property
    def shift_start(self) -> datetime | None:
        return self.work_intervals[0].start if self.work_intervals else None

    @property
    def shift_end(self) -> datetime | None:
        return self.work_intervals[-1].end if self.work_intervals else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "start_point": self.start_point.to_dict(),
            "work_intervals": [i.to_dict() for i in self.work_intervals],
            "skills": sorted(s.value for s in self.skills),
            "skill_levels": [[k.value, v] for k, v in self.skill_levels],
            "transport_mode": self.transport_mode.value,
            "region_key": self.region_key,
            "equipment": sorted(self.equipment),
            "active": self.active,
            "input_order": self.input_order,
            "home_start": self.home_start,
            "lunch": self.lunch.to_dict() if self.lunch is not None else None,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Engineer":
        return cls(
            id=str(raw["id"]),
            name=str(raw.get("name", raw["id"])),
            start_point=GeoPoint.from_dict(raw["start_point"]),
            work_intervals=tuple(WorkInterval.from_dict(i) for i in raw.get("work_intervals", ())),
            skills=frozenset(Skill(s) for s in raw.get("skills", ())),
            skill_levels=tuple((Skill(k), str(v)) for k, v in raw.get("skill_levels", ())),
            transport_mode=TransportMode(raw.get("transport_mode", TransportMode.CAR)),
            region_key=str(raw.get("region_key", "default")),
            equipment=frozenset(raw.get("equipment", ())),
            active=bool(raw.get("active", True)),
            input_order=int(raw.get("input_order", 0)),
            home_start=bool(raw.get("home_start", False)),
            lunch=Lunch.from_dict(raw["lunch"]) if raw.get("lunch") else None,
        )


# --------------------------------------------------------------------------------------
# Заявка
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Request:
    """Выездная работа для одного инженера.

    `window_start`/`window_end` — окно **прибытия** (БЗ «Правила модели»): раньше окна
    начинать работу нельзя, раннее прибытие означает ожидание; прибытие позже
    `window_end` не считается попаданием в окно. Алгоритм окна сам не сдвигает:
    расчёт берёт актуальное окно из сценария; старый план сохраняет своё.

    `duration_minutes` — длительность выполнения без дороги: технические работы
    и документы. Для всех видов (подключение 70, авария 80, дозаказ 20, локальная 30)
    дорожные 20 минут из Excel не входят: перемещение считается отдельно.

    `received_at` — момент поступления. Работа не начинается раньше поступления
    и прибытия; заявка, поступившая после `Scenario.as_of`, в этот снимок не входит.
    """

    id: str
    point: GeoPoint
    window_start: datetime
    window_end: datetime
    duration_minutes: int
    required_skill: Skill
    region_key: str = "default"
    priority: Priority = Priority.CONNECTION
    required_transport: TransportMode | None = None
    required_equipment: frozenset[str] = frozenset()
    address: str = ""
    district: str = ""
    input_order: int = 0
    received_at: datetime | None = None
    execution_status: ExecutionStatus = ExecutionStatus.PENDING
    request_type_bk: str = ""

    def __post_init__(self) -> None:
        # Нормализуем tz-aware: смешение naive и aware роняет любое сравнение,
        # поэтому недостающая зона достраивается здесь же, как у других полей.
        object.__setattr__(self, "window_start", _parse_dt(self.window_start))
        object.__setattr__(self, "window_end", _parse_dt(self.window_end))
        object.__setattr__(self, "required_skill", Skill(self.required_skill))
        object.__setattr__(self, "priority", Priority(self.priority))
        object.__setattr__(self, "execution_status", ExecutionStatus(self.execution_status))
        object.__setattr__(self, "required_equipment", frozenset(self.required_equipment))
        if self.required_transport is not None:
            object.__setattr__(self, "required_transport", TransportMode(self.required_transport))
        if self.received_at is not None:
            object.__setattr__(self, "received_at", _parse_dt(self.received_at))
        # `bool` — подкласс `int`, и `True` тихо становится длительностью в одну минуту,
        # а `False` — нулевой. Обе величины проходят и проверку на конечность, и проверку
        # знака, поэтому отсекать их приходится по типу и раньше всех.
        if isinstance(self.duration_minutes, bool):
            raise ValueError(
                f"Заявка {self.id}: длительность должна быть числом минут, "
                f"а не логическим значением ({self.duration_minutes})"
            )
        # Порядок важен: `nan < 0` ложно, поэтому проверка на конечность идёт первой.
        # Иначе `NaN` доходит до `int(timing.duration)` в объяснении отказа, а `inf` —
        # до `timedelta`, и вместо внятного отказа получается ошибка из глубины расчёта.
        if not math.isfinite(self.duration_minutes):
            raise ValueError(
                f"Заявка {self.id}: длительность должна быть конечным числом, "
                f"задано {self.duration_minutes}"
            )
        if self.duration_minutes < 0:
            raise ValueError(
                f"Заявка {self.id}: длительность не может быть отрицательной ({self.duration_minutes})"
            )

    @property
    def window_width_minutes(self) -> float:
        return (self.window_end - self.window_start).total_seconds() / 60.0

    @property
    def is_emergency(self) -> bool:
        return self.priority is Priority.EMERGENCY

    @property
    def is_closed(self) -> bool:
        return self.execution_status.is_closed

    @property
    def service_not_before(self) -> datetime:
        """Самый ранний момент начала работ: max(окно, поступление)."""
        if self.received_at is None:
            return self.window_start
        return self.window_start if self.window_start >= self.received_at else self.received_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "point": self.point.to_dict(),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "duration_minutes": self.duration_minutes,
            "required_skill": self.required_skill.value,
            "region_key": self.region_key,
            "priority": self.priority.value,
            "required_transport": (
                self.required_transport.value if self.required_transport else None
            ),
            "required_equipment": sorted(self.required_equipment),
            "address": self.address,
            "district": self.district,
            "input_order": self.input_order,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "execution_status": self.execution_status.value,
            "request_type_bk": self.request_type_bk,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Request":
        transport = raw.get("required_transport")
        received = raw.get("received_at")
        return cls(
            id=str(raw["id"]),
            point=GeoPoint.from_dict(raw["point"]),
            window_start=_parse_dt(raw["window_start"]),
            window_end=_parse_dt(raw["window_end"]),
            duration_minutes=int(raw["duration_minutes"]),
            required_skill=Skill(raw["required_skill"]),
            region_key=str(raw.get("region_key", "default")),
            priority=Priority(raw.get("priority", Priority.CONNECTION)),
            required_transport=TransportMode(transport) if transport else None,
            required_equipment=frozenset(raw.get("required_equipment", ())),
            address=str(raw.get("address", "")),
            district=str(raw.get("district", "")),
            input_order=int(raw.get("input_order", 0)),
            received_at=_parse_dt(received) if received else None,
            execution_status=ExecutionStatus(raw.get("execution_status", ExecutionStatus.PENDING)),
            request_type_bk=str(raw.get("request_type_bk", "")),
        )


# --------------------------------------------------------------------------------------
# Параметры расчёта
# --------------------------------------------------------------------------------------


def _default_speed() -> dict[TransportMode, float]:
    return {
        TransportMode.CAR: 28.0,
        TransportMode.WALKING: 4.5,
        TransportMode.BICYCLE: 13.0,
        TransportMode.PUBLIC_TRANSPORT: 18.0,
    }


def _default_overhead() -> dict[TransportMode, float]:
    """Парковка, подъезд/подход, вход в подъезд — «сопутствующие затраты» из БЗ."""
    return {
        TransportMode.CAR: 8.0,
        TransportMode.WALKING: 3.0,
        TransportMode.BICYCLE: 4.0,
        TransportMode.PUBLIC_TRANSPORT: 10.0,
    }


def _default_detour() -> dict[TransportMode, float]:
    """Коэффициент извилистости: перевод расстояния по прямой в пробег по улицам."""
    return {
        TransportMode.CAR: 1.35,
        TransportMode.WALKING: 1.25,
        TransportMode.BICYCLE: 1.30,
        TransportMode.PUBLIC_TRANSPORT: 1.40,
    }


@dataclass(slots=True)
class Settings:
    """Параметры модели и поиска.

    Все допущения вынесены сюда, чтобы их можно было назвать в README и заменить
    (например, подставив реальную маршрутизацию вместо расчёта по координатам).
    """

    # --- модель перемещения ---
    speed_kmh: dict[TransportMode, float] = field(default_factory=_default_speed)
    overhead_minutes: dict[TransportMode, float] = field(default_factory=_default_overhead)
    detour_factor: dict[TransportMode, float] = field(default_factory=_default_detour)
    suburban_speed_kmh: float = 45.0
    """Общественный транспорт за городом — электричка: средняя скорость, км/ч.

    Расписание (GTFS) есть только по городу, и поездка вне него (Кашира, Ступино)
    считается по координатам. По городской скорости 100 км выходили в 7–8 часов, хотя
    электричкой это 2,5–3 часа, и далёкие аварии не вставали ни к кому. Для поездки по
    координатам берётся меньшее из городского и пригородного времени: короткие поездки
    считаются как раньше, длинные — как электричкой.
    """
    suburban_detour_factor: float = 1.2
    """Извилистость пригородной поездки: железная дорога прямее улиц."""
    suburban_overhead_minutes: float = 30.0
    """Дорога до станции и от неё, ожидание электрички, минуты."""

    # --- жёсткие ограничения ---
    check_region: bool = True
    check_equipment: bool = False
    service_must_start_within_window: bool = True

    # --- поиск ---
    regret_k: int = 3
    time_limit_seconds: float = 5.0
    enable_local_search: bool = True
    enable_fleet_minimization: bool = True
    max_local_search_rounds: int = 30
    or_opt_max_segment: int = 3
    ejection_depth: int = 3
    emergency_lunch_shift_minutes: int = 120
    """На сколько авария может сдвинуть обед за его окно — раньше или позже, в пределах
    смены. Обед 13–14 при аварии с окном 12–14 на 80 минут иначе не даёт её взять никому:
    до обеда работа не успевает, а после обеда окно клиента уже закрыто. 0 — не сдвигать.
    """

    # --- перепланирование ---
    stabilize_after_replan: bool = True
    replan_scope: ReplanScope = ReplanScope.HIGH
    """Степень изменения плана при событии: `low` / `medium` / `high`.

    Ремонт всегда идёт снизу вверх — сначала вставка в свободное окно, потом
    перестроение затронутого маршрута, потом пересчёт остатка дня. Этот параметр
    задаёт только **потолок**: до какой ступени разрешено дойти, если дешёвые не
    справились. По умолчанию доступны все три ступени: сохранённая заявка важнее
    неподвижности картинки, а тай-брейк на число изменённых маршрутов и так не даёт
    трогать лишнее.
    """
    global_replan_time_share: float = 0.4
    """Доля `time_limit_seconds`, зарезервированная под пересчёт остатка дня.

    Без собственного бюджета дешёвые ступени успевают съесть весь лимит, и страховка
    не запускается вовсе.
    """

    timezone_offset_hours: int = 3

    def copy(self) -> "Settings":
        return Settings(
            speed_kmh=dict(self.speed_kmh),
            overhead_minutes=dict(self.overhead_minutes),
            detour_factor=dict(self.detour_factor),
            suburban_speed_kmh=self.suburban_speed_kmh,
            suburban_detour_factor=self.suburban_detour_factor,
            suburban_overhead_minutes=self.suburban_overhead_minutes,
            check_region=self.check_region,
            check_equipment=self.check_equipment,
            service_must_start_within_window=self.service_must_start_within_window,
            regret_k=self.regret_k,
            time_limit_seconds=self.time_limit_seconds,
            enable_local_search=self.enable_local_search,
            enable_fleet_minimization=self.enable_fleet_minimization,
            max_local_search_rounds=self.max_local_search_rounds,
            or_opt_max_segment=self.or_opt_max_segment,
            ejection_depth=self.ejection_depth,
            emergency_lunch_shift_minutes=self.emergency_lunch_shift_minutes,
            stabilize_after_replan=self.stabilize_after_replan,
            replan_scope=ReplanScope(self.replan_scope),
            global_replan_time_share=self.global_replan_time_share,
            timezone_offset_hours=self.timezone_offset_hours,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "speed_kmh": {k.value: v for k, v in self.speed_kmh.items()},
            "overhead_minutes": {k.value: v for k, v in self.overhead_minutes.items()},
            "detour_factor": {k.value: v for k, v in self.detour_factor.items()},
            "suburban_speed_kmh": self.suburban_speed_kmh,
            "suburban_detour_factor": self.suburban_detour_factor,
            "suburban_overhead_minutes": self.suburban_overhead_minutes,
            "check_region": self.check_region,
            "check_equipment": self.check_equipment,
            "service_must_start_within_window": self.service_must_start_within_window,
            "regret_k": self.regret_k,
            "time_limit_seconds": self.time_limit_seconds,
            "enable_local_search": self.enable_local_search,
            "enable_fleet_minimization": self.enable_fleet_minimization,
            "max_local_search_rounds": self.max_local_search_rounds,
            "or_opt_max_segment": self.or_opt_max_segment,
            "ejection_depth": self.ejection_depth,
            "emergency_lunch_shift_minutes": self.emergency_lunch_shift_minutes,
            "stabilize_after_replan": self.stabilize_after_replan,
            "replan_scope": ReplanScope(self.replan_scope).value,
            "global_replan_time_share": self.global_replan_time_share,
            "timezone_offset_hours": self.timezone_offset_hours,
        }


# --------------------------------------------------------------------------------------
# Сценарий
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scenario:
    """Полный вход одного расчёта: день, заявки, инженеры, параметры."""

    date: Date
    requests: tuple[Request, ...] = ()
    engineers: tuple[Engineer, ...] = ()
    settings: Settings = field(default_factory=Settings)
    name: str = ""
    as_of: datetime | None = None
    """Граница снимка плана. Заявки с `received_at` позже этого момента
    в расчёт не входят (авария в 13:00 не появляется в плане на 09:00).
    `None` — учитывать все незакрытые заявки входа.
    """

    def __post_init__(self) -> None:
        object.__setattr__(self, "requests", tuple(self.requests))
        object.__setattr__(self, "engineers", tuple(self.engineers))
        # Нормализуем tz-aware: смешение naive и aware роняет любое сравнение,
        # поэтому недостающая зона достраивается здесь же, как у других полей.
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _parse_dt(self.as_of))
        _require_unique("заявок", (r.id for r in self.requests))
        _require_unique("инженеров", (e.id for e in self.engineers))

    # -- индексы --

    @property
    def request_by_id(self) -> dict[str, Request]:
        return {r.id: r for r in self.requests}

    @property
    def engineer_by_id(self) -> dict[str, Engineer]:
        return {e.id: e for e in self.engineers}

    def active_engineers(self) -> tuple[Engineer, ...]:
        return tuple(e for e in self.engineers if e.active)

    def planning_requests(self) -> tuple[Request, ...]:
        """Заявки, которые этот расчёт имеет право назначать.

        Закрытые исключаются. Если задан `as_of`, ещё не поступившие тоже.
        """
        selected: list[Request] = []
        for request in self.requests:
            if request.is_closed:
                continue
            if (
                self.as_of is not None
                and request.received_at is not None
                and request.received_at > self.as_of
            ):
                continue
            selected.append(request)
        return tuple(selected)

    # -- проверки --

    def validate(self) -> list[str]:
        """Мягкие проверки входа. Возвращает список предупреждений (пустой = всё чисто).

        Жёсткие ошибки (дубли идентификаторов) поднимаются ещё в конструкторе:
        с ними расчёт не имеет смысла, а молчаливое переопределение исказило бы метрики.
        """
        warnings: list[str] = []
        for r in self.requests:
            if r.window_end < r.window_start:
                warnings.append(
                    f"Заявка {r.id}: конец окна раньше начала "
                    f"({r.window_end:%H:%M} < {r.window_start:%H:%M})"
                )
            if r.duration_minutes <= 0:
                warnings.append(f"Заявка {r.id}: неположительная длительность {r.duration_minutes}")
            if r.window_start.date() != self.date:
                warnings.append(
                    f"Заявка {r.id}: окно относится к {r.window_start.date()}, "
                    f"а план строится на {self.date}"
                )
            if r.is_closed:
                warnings.append(
                    f"Заявка {r.id}: статус {r.execution_status.value} — "
                    f"закрытые исключаются из планирования"
                )
            if (
                self.as_of is not None
                and r.received_at is not None
                and r.received_at > self.as_of
            ):
                warnings.append(
                    f"Заявка {r.id}: поступила в {r.received_at:%H:%M}, "
                    f"позже снимка плана {self.as_of:%H:%M} — в этот расчёт не входит"
                )
        for e in self.engineers:
            if e.active and not e.work_intervals:
                warnings.append(f"Инженер {e.id} ({e.name}): нет рабочих интервалов на дату плана")
            if e.active and not e.skills:
                warnings.append(f"Инженер {e.id} ({e.name}): не задан ни один навык")
            for interval in e.work_intervals:
                if interval.start.date() != self.date and interval.end.date() != self.date:
                    warnings.append(
                        f"Инженер {e.id}: рабочий интервал {interval.start:%d.%m %H:%M} "
                        f"вне даты плана {self.date}"
                    )
        warnings += self._warn_about_requests_longer_than_any_shift()
        if not self.engineers:
            warnings.append("В сценарии нет ни одного инженера — все заявки останутся без исполнителя")
        if not self.requests:
            warnings.append("В сценарии нет заявок")
        return warnings

    def _warn_about_requests_longer_than_any_shift(self) -> list[str]:
        """Заявки, которые не выполнить ни при каком распределении.

        Работа не начинается раньше окна и поступления. Если после этого момента ни у
        одного инженера не остаётся `duration_minutes` рабочих минут до конца смены,
        заявка не поместится даже в пустой день. Это не результат расчёта, а свойство
        входных данных: чаще всего окна выгрузки просто выходят за границы заданной
        смены. Без явного предупреждения такие заявки молча оседают в «не назначено»,
        и причину ищут в алгоритме, а не в параметрах дня.
        """
        available = [e for e in self.engineers if e.active and e.work_intervals]
        if not available:
            return []
        hopeless: list[str] = []
        for request in self.planning_requests():
            if request.duration_minutes <= 0:
                continue
            start = request.service_not_before
            if any(
                _working_minutes_from(e.work_intervals, start) >= request.duration_minutes
                for e in available
            ):
                continue
            hopeless.append(request.id)
        if not hopeless:
            return []
        shown = ", ".join(hopeless[:5])
        if len(hopeless) > 5:
            shown += f" и ещё {len(hopeless) - 5}"
        return [
            f"Заявок, не помещающихся в смену ни одного инженера: {len(hopeless)} ({shown}). "
            f"Работа не может начаться раньше окна, а смена заканчивается раньше, чем она "
            f"успеет закончиться — их не выполнить ни при каком распределении. "
            f"Проверьте границы смены: в выгрузке есть окна, выходящие за неё"
        ]

    # -- производные сценарии (используются при перепланировании) --

    def with_requests(self, requests: Sequence[Request]) -> "Scenario":
        return replace(self, requests=tuple(requests))

    def with_engineers(self, engineers: Sequence[Engineer]) -> "Scenario":
        return replace(self, engineers=tuple(engineers))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "date": self.date.isoformat(),
            "requests": [r.to_dict() for r in self.requests],
            "engineers": [e.to_dict() for e in self.engineers],
            "settings": self.settings.to_dict(),
            "as_of": self.as_of.isoformat() if self.as_of else None,
        }


def _working_minutes_from(intervals: Iterable[WorkInterval], moment: datetime) -> float:
    """Сколько рабочих минут остаётся в графике начиная с `moment`."""
    total = 0.0
    for interval in intervals:
        start = moment if moment > interval.start else interval.start
        if interval.end > start:
            total += (interval.end - start).total_seconds() / 60.0
    return total


def _require_unique(what: str, ids: Iterable[str]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in ids:
        if item in seen and item not in duplicates:
            duplicates.append(item)
        seen.add(item)
    if duplicates:
        raise ValueError(f"Дублирующиеся идентификаторы {what}: {', '.join(duplicates)}")


# --------------------------------------------------------------------------------------
# Событие перепланирования
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplanEvent:
    """Одно событие, меняющее план в течение дня (ТЗ п. 2.4, строка «Событие»)."""

    type: EventType
    at: datetime
    request: Request | None = None
    request_id: str | None = None
    engineer_id: str | None = None
    comment: str = ""

    def __post_init__(self) -> None:
        # Нормализуем tz-aware: смешение naive и aware роняет любое сравнение,
        # поэтому недостающая зона достраивается здесь же, как у других полей.
        object.__setattr__(self, "at", _parse_dt(self.at))
        object.__setattr__(self, "type", EventType(self.type))
        if not self.type.is_event:
            # `MANUAL_REASSIGN` — метка diff, а не событие: ручной ход делает `reassign()`,
            # у которого нет ни момента события, ни заморозки по нему.
            raise ValueError(
                "Ручное переназначение не является событием перепланирования: "
                "используйте reassign()"
            )
        if self.type is EventType.URGENT_REQUEST and self.request is None:
            raise ValueError("Для аварийной заявки нужен полный набор полей заявки (поле request)")
        if self.type in (EventType.CANCEL_REQUEST, EventType.CLIENT_REFUSAL):
            if not (self.request_id or (self.request and self.request.id)):
                raise ValueError("Для отмены или отказа клиента нужен request_id")
        if self.type is EventType.ENGINEER_UNAVAILABLE and not self.engineer_id:
            raise ValueError("Для недоступности инженера нужен engineer_id")
        if self.type.is_status and not (self.request_id or (self.request and self.request.id)):
            raise ValueError("Для статуса исполнения нужен request_id визита")

    @property
    def target_request_id(self) -> str | None:
        if self.request_id:
            return self.request_id
        return self.request.id if self.request else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "at": self.at.isoformat(),
            "request": self.request.to_dict() if self.request else None,
            "request_id": self.request_id,
            "engineer_id": self.engineer_id,
            "comment": self.comment,
        }

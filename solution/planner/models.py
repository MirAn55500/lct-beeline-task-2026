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

from .enums import EventType, Priority, Skill, TransportMode

__all__ = [
    "MSK",
    "GeoPoint",
    "WorkInterval",
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


# --------------------------------------------------------------------------------------
# Исполнитель
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Engineer:
    """Один выездной инженер.

    Стартовая точка — офис бригады своего региона (БЗ «Бригада»). Возврат в офис
    после последней заявки моделью не предусмотрен (ТЗ п. 2.4, открытый маршрут).
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
        )


# --------------------------------------------------------------------------------------
# Заявка
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Request:
    """Выездная работа для одного инженера.

    `window_start`/`window_end` — окно **прибытия** (БЗ «Правила модели»): раньше окна
    начинать работу нельзя, раннее прибытие означает ожидание; прибытие позже
    `window_end` не считается попаданием в окно. Окна никогда не сдвигаются.

    `duration_minutes` — только технические работы и документы, **без** дорожной
    составляющей норматива (БЗ «Нормативы работ»): дорога считается отдельно.
    """

    id: str
    point: GeoPoint
    window_start: datetime
    window_end: datetime
    duration_minutes: int
    required_skill: Skill
    region_key: str = "default"
    priority: Priority = Priority.NORMAL
    required_transport: TransportMode | None = None
    required_equipment: frozenset[str] = frozenset()
    address: str = ""
    district: str = ""
    input_order: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_skill", Skill(self.required_skill))
        object.__setattr__(self, "priority", Priority(self.priority))
        object.__setattr__(self, "required_equipment", frozenset(self.required_equipment))
        if self.required_transport is not None:
            object.__setattr__(self, "required_transport", TransportMode(self.required_transport))

    @property
    def window_width_minutes(self) -> float:
        return (self.window_end - self.window_start).total_seconds() / 60.0

    @property
    def is_urgent(self) -> bool:
        return self.priority is Priority.URGENT

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
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Request":
        transport = raw.get("required_transport")
        return cls(
            id=str(raw["id"]),
            point=GeoPoint.from_dict(raw["point"]),
            window_start=_parse_dt(raw["window_start"]),
            window_end=_parse_dt(raw["window_end"]),
            duration_minutes=int(raw["duration_minutes"]),
            required_skill=Skill(raw["required_skill"]),
            region_key=str(raw.get("region_key", "default")),
            priority=Priority(raw.get("priority", Priority.NORMAL)),
            required_transport=TransportMode(transport) if transport else None,
            required_equipment=frozenset(raw.get("required_equipment", ())),
            address=str(raw.get("address", "")),
            district=str(raw.get("district", "")),
            input_order=int(raw.get("input_order", 0)),
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
    ejection_depth: int = 1

    # --- перепланирование ---
    stabilize_after_replan: bool = True

    timezone_offset_hours: int = 3

    def copy(self) -> "Settings":
        return Settings(
            speed_kmh=dict(self.speed_kmh),
            overhead_minutes=dict(self.overhead_minutes),
            detour_factor=dict(self.detour_factor),
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
            stabilize_after_replan=self.stabilize_after_replan,
            timezone_offset_hours=self.timezone_offset_hours,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "speed_kmh": {k.value: v for k, v in self.speed_kmh.items()},
            "overhead_minutes": {k.value: v for k, v in self.overhead_minutes.items()},
            "detour_factor": {k.value: v for k, v in self.detour_factor.items()},
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
            "stabilize_after_replan": self.stabilize_after_replan,
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "requests", tuple(self.requests))
        object.__setattr__(self, "engineers", tuple(self.engineers))
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
        if not self.engineers:
            warnings.append("В сценарии нет ни одного инженера — все заявки останутся без исполнителя")
        if not self.requests:
            warnings.append("В сценарии нет заявок")
        return warnings

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
        }


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
        object.__setattr__(self, "type", EventType(self.type))
        if self.type is EventType.URGENT_REQUEST and self.request is None:
            raise ValueError("Для срочной заявки нужен полный набор полей заявки (поле request)")
        if self.type in (EventType.CANCEL_REQUEST, EventType.CLIENT_REFUSAL):
            if not (self.request_id or (self.request and self.request.id)):
                raise ValueError("Для отмены или отказа клиента нужен request_id")
        if self.type is EventType.ENGINEER_UNAVAILABLE and not self.engineer_id:
            raise ValueError("Для недоступности инженера нужен engineer_id")

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

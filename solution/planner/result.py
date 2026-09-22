"""Выходные структуры: то, что видит интерфейс и диспетчер.

Всё неизменяемо и полностью сериализуется в JSON без кастомного энкодера: результат
расчёта должен без обработки уезжать в REST-ответ, в файл плана и в карту.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime
from typing import Any

from .enums import Algorithm, AssignmentStatus, EventType, ReasonCode, Skill, TransportMode
from .models import GeoPoint

__all__ = [
    "TransitLeg",
    "Visit",
    "RouteResult",
    "Assignment",
    "EngineerMetrics",
    "PlanMetrics",
    "PlanDiff",
    "PlanResult",
]


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def _r(value: float, digits: int = 3) -> float:
    return round(value, digits)


# --------------------------------------------------------------------------------------

TRANSIT_KIND_TITLES: dict[str, str] = {
    "walk": "пешком",
    "tram": "трамвай",
    "subway": "метро",
    "rail": "электричка",
    "bus": "автобус",
    "ferry": "паром",
    "cable": "кабельный трамвай",
    "gondola": "канатная дорога",
    "funicular": "фуникулёр",
    "trolleybus": "троллейбус",
    "monorail": "монорельс",
}
"""Коды `route_type` GTFS словами. Названия нужны диспетчеру: «сесть на 903» без
«автобус» читается хуже, а «Калужско-Рижская линия» без «метро» — непонятно вовсе."""

_NAMED_BY_LINE = frozenset({"subway", "rail", "monorail"})
"""Виды транспорта, которые называют линией, а не номером маршрута."""


@dataclass(frozen=True, slots=True)
class TransitLeg:
    """Участок поездки на общественном транспорте: пешком до остановки или в вагоне.

    Заполняется только для маршрутов с режимом `public_transport` и только тогда, когда
    подключён маршрутный сервис с GTFS-фидом: расчёт по координатам знает лишь время в
    пути, а на чём именно человек едет — не знает и придумывать не должен.

    Зачем это в плане. Время в пути на общественном транспорте — не свойство пары точек,
    а свойство конкретной поездки: 40 минут складываются из «6 минут до остановки,
    ждать 4, ехать 18 на 903-м, пересесть, ещё 12 на метро». Диспетчер, который видит
    только «40 минут», не может ни проверить расчёт, ни объяснить инженеру, куда идти.

    Почему сумма участков не обязана совпадать с `Visit.travel_minutes`. Расписание
    планирования одно на день и считается на опорный час (`ors.PT_DEPARTURE_HOUR`), а
    поездка показывается на фактическое время выезда — в девять утра рейсы ходят чаще,
    чем в восемь вечера, и ждать приходится по-разному. Расхождение — минуты, и оно
    заложено в модель, а не ошибка: иначе время в пути зависело бы от расписания,
    которое само от него и строится. Плюс `travel_minutes` включает сопутствующие
    затраты (`Settings.overhead_minutes`), которых маршрутный сервис не знает.
    """

    kind: str
    """`walk` — пешком, иначе вид транспорта: `bus`, `tram`, `subway`, `rail`…"""
    route: str = ""
    """Номер маршрута: «903», «м2», «6», «D3»."""
    line: str = ""
    """Полное название маршрута: «Метро «Озёрная» — Метро «Ясенево»», «Калужско-Рижская
    линия». У метро и электрички в подписи идёт оно, а не номер: «метро 6» понятно не
    всякому, «Калужско-Рижская линия» — всякому."""
    headsign: str = ""
    """Куда идёт этот рейс — то, что написано на лобовом стекле."""
    from_stop: str = ""
    """Остановка посадки. Для пешего участка пусто."""
    to_stop: str = ""
    """Остановка высадки."""
    departure_at: datetime | None = None
    arrival_at: datetime | None = None
    minutes: float = 0.0
    distance_km: float = 0.0
    stops: int = 0
    """Сколько остановок ехать. Ноль для пешего участка."""

    @property
    def title(self) -> str:
        """Человекочитаемое описание участка — то, что показывается диспетчеру."""
        if self.kind == "walk":
            return f"пешком {round(self.minutes)} мин"
        what = TRANSIT_KIND_TITLES.get(self.kind, self.kind)
        # У наземного маршрута опознавательный знак — номер на борту, у рельсового —
        # название линии: «метро 6» не читается, «Калужско-Рижская линия» читается.
        mark = self.line if self.kind in _NAMED_BY_LINE and self.line else self.route
        where = f" от «{self.from_stop}»" if self.from_stop else ""
        return f"{what} {mark}{where}, {self.stops} ост., {round(self.minutes)} мин"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "route": self.route,
            "line": self.line,
            "headsign": self.headsign,
            "from_stop": self.from_stop,
            "to_stop": self.to_stop,
            "departure_at": _iso(self.departure_at),
            "arrival_at": _iso(self.arrival_at),
            "minutes": _r(self.minutes, 1),
            "distance_km": _r(self.distance_km),
            "stops": self.stops,
            "title": self.title,
        }


@dataclass(frozen=True, slots=True)
class Visit:
    """Один визит в маршруте: когда выехал, когда приехал, когда начал и закончил."""

    request_id: str
    position: int
    engineer_id: str
    departure_at: datetime
    arrival_at: datetime
    service_start_at: datetime
    service_end_at: datetime
    travel_minutes: float
    distance_km: float
    waiting_minutes: float
    from_point: GeoPoint
    to_point: GeoPoint
    latest_departure_at: datetime | None = None
    slack_minutes: float = 0.0
    """Запас до срыва: на сколько минут можно задержать начало этой работы, не сломав
    ни её окно, ни ни одну из последующих заявок маршрута. Ноль означает, что любая
    задержка в пути роняет остаток дня — это и есть прогноз опозданий."""
    service_minutes: float = 0.0
    """Чистая длительность работ. Отдельным полем, потому что разность
    `service_end_at - service_start_at` включает перерыв, если работа его пересекла."""
    idle_before_minutes: float = 0.0
    """Свободные рабочие минуты перед выездом к этому визиту: инженер уже закончил
    прошлую работу, но ехать ещё рано. Выезд откладывается, чтобы не стоять у клиента,
    и это время — честный резерв дня, а не занятость."""
    locked: bool = False
    address: str = ""
    priority: str = "connection"
    required_skill: Skill = Skill.CONNECTION
    geometry_range: tuple[int, int] | None = None
    """Границы участка внутри `RouteResult.geometry`: от предыдущей точки маршрута сюда.

    Индексы, а не копия координат: линия по улицам — это сотни точек на маршрут, и
    хранить её дважды (целиком и по участкам) значит удвоить JSON плана без пользы.
    `None` — реальной геометрии нет, участок рисуется прямой.
    """
    transit: tuple["TransitLeg", ...] = ()
    """Из чего сложилась дорога сюда на общественном транспорте: пешие подходы,
    поездки, пересадки. Пусто для остальных способов передвижения и тогда, когда
    маршрутный сервис недоступен — см. `TransitLeg`."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "position": self.position,
            "engineer_id": self.engineer_id,
            "departure_at": _iso(self.departure_at),
            "arrival_at": _iso(self.arrival_at),
            "service_start_at": _iso(self.service_start_at),
            "service_end_at": _iso(self.service_end_at),
            "latest_departure_at": _iso(self.latest_departure_at),
            "service_minutes": _r(self.service_minutes, 1),
            "idle_before_minutes": _r(self.idle_before_minutes, 1),
            "slack_minutes": _r(self.slack_minutes, 1),
            "travel_minutes": _r(self.travel_minutes, 1),
            "distance_km": _r(self.distance_km),
            "waiting_minutes": _r(self.waiting_minutes, 1),
            "from_point": self.from_point.to_dict(),
            "to_point": self.to_point.to_dict(),
            "locked": self.locked,
            "address": self.address,
            "priority": self.priority,
            "required_skill": self.required_skill.value,
            "geometry_range": list(self.geometry_range) if self.geometry_range else None,
            "transit": [leg.to_dict() for leg in self.transit],
        }


@dataclass(frozen=True, slots=True)
class RouteResult:
    """Маршрут одного инженера за день."""

    engineer_id: str
    engineer_name: str
    transport_mode: TransportMode
    start_point: GeoPoint
    visits: tuple[Visit, ...]
    start_at: datetime | None
    end_at: datetime | None
    distance_km: float
    travel_minutes: float
    service_minutes: float
    waiting_minutes: float
    capacity_minutes: float
    region_key: str = "default"
    explanation: str = ""
    geometry: tuple[GeoPoint, ...] = ()
    """Линия маршрута по улицам, полученная из маршрутного сервиса (`planner.ors`).

    Пустая, пока план считался по координатам: тогда карта рисует `polyline` —
    прямые между точками. Заполняется постобработкой `attach_route_geometry`,
    расписание и назначения от неё не зависят.
    """
    geometry_source: str = "straight"
    """`"ors"` — линия по улицам, `"straight"` — соединение точек по прямой.

    Поле существует, чтобы интерфейс не выдавал прямую за реальный маршрут.
    """

    @property
    def busy_minutes(self) -> float:
        return self.service_minutes + self.travel_minutes + self.waiting_minutes

    @property
    def free_minutes(self) -> float:
        return self.capacity_minutes - self.busy_minutes

    @property
    def utilization(self) -> float:
        return self.busy_minutes / self.capacity_minutes if self.capacity_minutes else 0.0

    @property
    def polyline(self) -> tuple[GeoPoint, ...]:
        """Точки для отрисовки на карте: старт и далее адреса в порядке посещения."""
        return (self.start_point,) + tuple(v.to_point for v in self.visits)

    @property
    def request_ids(self) -> tuple[str, ...]:
        return tuple(v.request_id for v in self.visits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engineer_id": self.engineer_id,
            "engineer_name": self.engineer_name,
            "transport_mode": self.transport_mode.value,
            "region_key": self.region_key,
            "start_point": self.start_point.to_dict(),
            "visits": [v.to_dict() for v in self.visits],
            "start_at": _iso(self.start_at),
            "end_at": _iso(self.end_at),
            "distance_km": _r(self.distance_km),
            "travel_minutes": _r(self.travel_minutes, 1),
            "service_minutes": _r(self.service_minutes, 1),
            "waiting_minutes": _r(self.waiting_minutes, 1),
            "capacity_minutes": _r(self.capacity_minutes, 1),
            "explanation": self.explanation,
            "busy_minutes": _r(self.busy_minutes, 1),
            "free_minutes": _r(self.free_minutes, 1),
            "utilization": _r(self.utilization, 4),
            "polyline": [p.as_geojson() for p in self.polyline],
            "geometry": [p.as_geojson() for p in self.geometry],
            "geometry_source": self.geometry_source,
        }


@dataclass(frozen=True, slots=True)
class Assignment:
    """Результат распределения одной заявки: исполнитель либо причина отказа."""

    request_id: str
    status: AssignmentStatus
    engineer_id: str | None = None
    engineer_name: str | None = None
    position: int | None = None
    arrival_at: datetime | None = None
    service_start_at: datetime | None = None
    service_end_at: datetime | None = None
    reason: ReasonCode | None = None
    explanation: str = ""
    checked_skill: Skill | None = None
    checked_transport: TransportMode | None = None
    checked_equipment: tuple[str, ...] = ()
    checked_qualification_level: str | None = None
    incremental_distance_km: float | None = None

    @property
    def is_assigned(self) -> bool:
        return self.status is AssignmentStatus.ASSIGNED

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "engineer_id": self.engineer_id,
            "engineer_name": self.engineer_name,
            "position": self.position,
            "arrival_at": _iso(self.arrival_at),
            "service_start_at": _iso(self.service_start_at),
            "service_end_at": _iso(self.service_end_at),
            "reason": self.reason.value if self.reason else None,
            "explanation": self.explanation,
            "checked_skill": self.checked_skill.value if self.checked_skill else None,
            "checked_transport": self.checked_transport.value if self.checked_transport else None,
            "checked_equipment": list(self.checked_equipment),
            "checked_qualification_level": self.checked_qualification_level,
            "incremental_distance_km": (
                _r(self.incremental_distance_km) if self.incremental_distance_km is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class EngineerMetrics:
    engineer_id: str
    engineer_name: str
    assigned_count: int
    distance_km: float
    travel_minutes: float
    service_minutes: float
    waiting_minutes: float
    capacity_minutes: float
    utilization: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "engineer_id": self.engineer_id,
            "engineer_name": self.engineer_name,
            "assigned_count": self.assigned_count,
            "distance_km": _r(self.distance_km),
            "travel_minutes": _r(self.travel_minutes, 1),
            "service_minutes": _r(self.service_minutes, 1),
            "waiting_minutes": _r(self.waiting_minutes, 1),
            "capacity_minutes": _r(self.capacity_minutes, 1),
            "utilization": _r(self.utilization, 4),
        }


@dataclass(frozen=True, slots=True)
class PlanMetrics:
    """Обязательные метрики ТЗ п. 2.3 плюс то, что нужно диспетчеру для решения."""

    assigned_count: int = 0
    feasible_count: int = 0
    """Прогноз выполнимых заявок. Совпадает с `assigned_count`, потому что план строится
    только из допустимых назначений; выделен отдельно, так как «назначено» и «выполнено»
    в модели разные величины, и при появлении фактов они разойдутся."""
    tight_visit_count: int = 0
    """Сколько визитов идут без запаса (менее 10 минут до срыва окна)."""
    unassigned_count: int = 0
    emergency_unassigned_count: int = 0
    connection_unassigned_count: int = 0
    used_engineer_count: int = 0
    available_engineer_count: int = 0
    total_distance_km: float = 0.0
    total_travel_minutes: float = 0.0
    total_service_minutes: float = 0.0
    total_waiting_minutes: float = 0.0
    avg_utilization: float = 0.0
    computation_ms: float = 0.0
    constraints_valid: bool = True
    per_engineer: tuple[EngineerMetrics, ...] = ()

    def quality_key(self) -> tuple[int, int, int, int, float, float]:
        """Лексикографический ключ сравнения планов: меньше — лучше.

        Авария важнее подключения, подключение важнее общего объёма, затем люди,
        время в пути и пробег.
        """
        return (
            self.emergency_unassigned_count,
            self.connection_unassigned_count,
            self.unassigned_count,
            self.used_engineer_count,
            round(self.total_travel_minutes, 6),
            round(self.total_distance_km, 6),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assigned_count": self.assigned_count,
            "feasible_count": self.feasible_count,
            "tight_visit_count": self.tight_visit_count,
            "unassigned_count": self.unassigned_count,
            "emergency_unassigned_count": self.emergency_unassigned_count,
            "connection_unassigned_count": self.connection_unassigned_count,
            "used_engineer_count": self.used_engineer_count,
            "available_engineer_count": self.available_engineer_count,
            "total_distance_km": _r(self.total_distance_km),
            "total_travel_minutes": _r(self.total_travel_minutes, 1),
            "total_service_minutes": _r(self.total_service_minutes, 1),
            "total_waiting_minutes": _r(self.total_waiting_minutes, 1),
            "avg_utilization": _r(self.avg_utilization, 4),
            "computation_ms": _r(self.computation_ms, 1),
            "constraints_valid": self.constraints_valid,
            "per_engineer": [m.to_dict() for m in self.per_engineer],
        }


@dataclass(frozen=True, slots=True)
class PlanDiff:
    """Что именно изменилось после перепланирования (ТЗ п. 2.4.2)."""

    previous_plan_id: str
    event_type: EventType
    changed_request_ids: tuple[str, ...] = ()
    changed_route_engineer_ids: tuple[str, ...] = ()
    removed_route_engineer_ids: tuple[str, ...] = ()
    newly_assigned_request_ids: tuple[str, ...] = ()
    newly_unassigned_request_ids: tuple[str, ...] = ()
    unchanged_route_engineer_ids: tuple[str, ...] = ()
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_plan_id": self.previous_plan_id,
            "event_type": self.event_type.value,
            "changed_request_ids": list(self.changed_request_ids),
            "changed_route_engineer_ids": list(self.changed_route_engineer_ids),
            "removed_route_engineer_ids": list(self.removed_route_engineer_ids),
            "newly_assigned_request_ids": list(self.newly_assigned_request_ids),
            "newly_unassigned_request_ids": list(self.newly_unassigned_request_ids),
            "unchanged_route_engineer_ids": list(self.unchanged_route_engineer_ids),
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class PlanResult:
    """Итог одного расчёта. Самодостаточен: для отображения ничего больше не нужно."""

    plan_id: str
    algorithm: Algorithm
    date: Date
    routes: tuple[RouteResult, ...] = ()
    assignments: tuple[Assignment, ...] = ()
    metrics: PlanMetrics = field(default_factory=PlanMetrics)
    warnings: tuple[str, ...] = ()
    diff: PlanDiff | None = None
    name: str = ""
    created_at: datetime | None = None
    not_before: datetime | None = None
    """Момент «сейчас», от которого считался ремонт по событию.

    Работа, которая к этому моменту не началась, не может быть назначена раньше него:
    план после события — расписание остатка дня, а не задним числом переписанное утро.
    У расчёта с нуля этого ограничения нет, там `None`.
    """

    @property
    def unassigned(self) -> tuple[Assignment, ...]:
        return tuple(a for a in self.assignments if not a.is_assigned)

    @property
    def assigned(self) -> tuple[Assignment, ...]:
        return tuple(a for a in self.assignments if a.is_assigned)

    def assignment_of(self, request_id: str) -> Assignment | None:
        for a in self.assignments:
            if a.request_id == request_id:
                return a
        return None

    def route_of(self, engineer_id: str) -> RouteResult | None:
        for r in self.routes:
            if r.engineer_id == engineer_id:
                return r
        return None

    def visit_of(self, request_id: str) -> Visit | None:
        """Визит заявки в маршрутах. `None`, если заявка не назначена.

        Отдельно от `assignment_of`, потому что `Assignment` не хранит `departure_at`:
        решение «инженер уже выехал» строится именно на нём, а живёт оно только в визите.
        """
        for r in self.routes:
            for v in r.visits:
                if v.request_id == request_id:
                    return v
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "algorithm": self.algorithm.value,
            "date": self.date.isoformat(),
            "created_at": _iso(self.created_at),
            "not_before": _iso(self.not_before),
            "routes": [r.to_dict() for r in self.routes],
            "assignments": [a.to_dict() for a in self.assignments],
            "unassigned": [a.to_dict() for a in self.unassigned],
            "metrics": self.metrics.to_dict(),
            "warnings": list(self.warnings),
            "diff": self.diff.to_dict() if self.diff else None,
        }

"""Рабочее решение: набор маршрутов + пул неназначенных заявок.

Отделено от `PlanResult` намеренно. `Solution` — изменяемая структура, с которой работают
фазы алгоритма; `PlanResult` — неизменяемый отчёт для интерфейса. Смешение этих двух ролей
в одном объекте обычно заканчивается тем, что UI показывает промежуточное состояние поиска.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from .context import PlanContext
from .enums import Priority, ReasonCode
from .models import Engineer, Request
from .route import RouteState

__all__ = ["Solution", "QualityKey"]

QualityKey = tuple[int, int, int, int, float, float]
_ROUND = 6


class Solution:
    """Состояние поиска: кто что везёт и что осталось без исполнителя."""

    __slots__ = ("ctx", "routes", "_order", "unassigned", "reasons")

    def __init__(self, ctx: PlanContext, engineers: Iterable[Engineer] | None = None) -> None:
        self.ctx = ctx
        pool = list(engineers if engineers is not None else ctx.scenario.active_engineers())
        pool.sort(key=lambda e: (e.input_order, e.id))
        self.routes: dict[str, RouteState] = {e.id: RouteState(ctx, e) for e in pool}
        self._order: list[str] = [e.id for e in pool]
        self.unassigned: dict[str, Request] = {}
        self.reasons: dict[str, tuple[ReasonCode, list[str]]] = {}

    # ------------------------------------------------------------------ обход

    @property
    def order(self) -> list[str]:
        return list(self._order)

    def __iter__(self) -> Iterator[RouteState]:
        for engineer_id in self._order:
            yield self.routes[engineer_id]

    def used_routes(self) -> list[RouteState]:
        return [self.routes[i] for i in self._order if self.routes[i].stops]

    def empty_routes(self) -> list[RouteState]:
        return [self.routes[i] for i in self._order if not self.routes[i].stops]

    def drop_engineer(self, engineer_id: str) -> None:
        """Полностью убирает инженера из решения (недоступность на весь день)."""
        self.routes.pop(engineer_id, None)
        if engineer_id in self._order:
            self._order.remove(engineer_id)

    # ------------------------------------------------------------------ назначения

    def assigned_ids(self) -> set[str]:
        return {r.id for route in self for r in route.stops}

    def assigned_count(self) -> int:
        return sum(route.size for route in self)

    def route_of(self, request_id: str) -> RouteState | None:
        for route in self:
            if route.index_of(request_id) >= 0:
                return route
        return None

    def mark_unassigned(
        self, request: Request, reason: ReasonCode, details: Iterable[str] = ()
    ) -> None:
        self.unassigned[request.id] = request
        self.reasons[request.id] = (reason, list(details))

    def clear_unassigned(self, request_id: str) -> None:
        self.unassigned.pop(request_id, None)
        self.reasons.pop(request_id, None)

    # ------------------------------------------------------------------ показатели

    @property
    def total_distance_km(self) -> float:
        return sum(route.distance_km for route in self)

    @property
    def total_travel_minutes(self) -> float:
        return sum(route.travel_minutes for route in self)

    @property
    def total_service_minutes(self) -> float:
        return sum(route.service_minutes for route in self)

    @property
    def total_waiting_minutes(self) -> float:
        return sum(route.waiting_minutes for route in self)

    @property
    def used_engineer_count(self) -> int:
        return sum(1 for route in self if route.stops)

    def unassigned_of(self, priority: Priority) -> int:
        return sum(1 for r in self.unassigned.values() if r.priority is priority)

    def quality_key(self) -> QualityKey:
        """Лексикографический ключ качества плана: меньше — лучше.

        Порядок: авария → подключение → общий объём → число людей → время в пути → пробег.
        Ремонт и дозаказ входят в общий объём; отдельный ключ для них не нужен.
        """
        return (
            self.unassigned_of(Priority.EMERGENCY),
            self.unassigned_of(Priority.CONNECTION),
            len(self.unassigned),
            self.used_engineer_count,
            round(self.total_travel_minutes, _ROUND),
            round(self.total_distance_km, _ROUND),
        )

    def routing_key(self) -> tuple[float, float]:
        """Ключ сравнения при перестановках внутри неизменного состава назначений."""
        return (round(self.total_travel_minutes, _ROUND), round(self.total_distance_km, _ROUND))

    # ------------------------------------------------------------------ копирование

    def clone(self) -> "Solution":
        copy = Solution.__new__(Solution)
        copy.ctx = self.ctx
        copy.routes = {key: route.clone() for key, route in self.routes.items()}
        copy._order = list(self._order)
        copy.unassigned = dict(self.unassigned)
        copy.reasons = {k: (v[0], list(v[1])) for k, v in self.reasons.items()}
        return copy

    def restore_from(self, other: "Solution") -> None:
        """Откат к сохранённому состоянию без пересоздания объекта."""
        self.routes = {key: route.clone() for key, route in other.routes.items()}
        self._order = list(other._order)
        self.unassigned = dict(other.unassigned)
        self.reasons = {k: (v[0], list(v[1])) for k, v in other.reasons.items()}

    def __repr__(self) -> str:  # pragma: no cover - диагностика
        return (
            f"Solution(назначено={self.assigned_count()}, "
            f"без исполнителя={len(self.unassigned)}, "
            f"инженеров={self.used_engineer_count})"
        )

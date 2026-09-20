"""Конструктивные фазы: базовый вариант из ТЗ и regret-вставка.

**Базовый** (`build_baseline`) — дословная реализация правила ТЗ п. 2.3. Он нужен не как
запасной вариант, а как точка отсчёта: без него нельзя показать, что оптимизация что-то дала.

**Regret-вставка** (`insert_regret`) — основной конструктивный алгоритм. Отличие от жадного
«первый подходящий» в одном: на каждом шаге размещается не первая попавшаяся заявка,
а та, которую **опаснее всего откладывать** — у которой разрыв между лучшим и k-м по
качеству вариантом наибольший. Заявка с единственным исполнителем получает бесконечное
сожаление и размещается первой. Это ровно то место, где жадный алгоритм теряет заявки:
он занимает единственного подходящего инженера чем-то другим.

Объяснение диспетчеру формулируется так же коротко: «эту заявку поставили раньше остальных,
потому что запасных вариантов у неё почти не было».
"""

from __future__ import annotations

import time as _time
from typing import Iterable, Sequence

from .context import PlanContext
from .cost import WORST_POSSIBLE, InsertionCost
from .enums import Priority, ReasonCode
from .feasibility import ReasonAccumulator, check_static
from .models import Request
from .route import RouteState
from .solution import Solution

__all__ = [
    "build_baseline",
    "insert_regret",
    "place_single",
    "place_with_ejection",
    "reclaim_emergencies",
]


def _ordered_requests(requests: Iterable[Request]) -> list[Request]:
    return sorted(requests, key=lambda r: (r.input_order, r.id))


# --------------------------------------------------------------------------------------
# Базовый алгоритм (ТЗ п. 2.3)
# --------------------------------------------------------------------------------------


def build_baseline(ctx: PlanContext) -> Solution:
    """Заявки в порядке поступления → первому подходящему инженеру по порядку входа.

    Порядок посещения совпадает с порядком назначения: заявка всегда дописывается
    в конец маршрута. Никакой оптимизации — это осознанно «плохой» эталон.
    """
    solution = Solution(ctx)
    # Перебираются все инженеры входа, а не только активные: исключённый из планирования
    # сотрудник должен попасть в диагностику с причиной «нет рабочего времени»,
    # иначе диспетчер получит бессодержательное «нет ни одного исполнителя».
    engineers = sorted(ctx.scenario.engineers, key=lambda e: (e.input_order, e.id))

    for request in _ordered_requests(ctx.scenario.planning_requests()):
        accumulator = ReasonAccumulator()
        placed = False
        for engineer in engineers:
            static = check_static(engineer, request, ctx.settings)
            if not static.ok:
                accumulator.add(static)
                continue
            route = solution.routes.get(engineer.id)
            if route is None:
                continue
            if route.insert_checked(request, len(route.stops)):
                placed = True
                break
            accumulator.add(route.reject_reason(request))
        if not placed:
            reason, details = accumulator.resolve(bool(ctx.scenario.engineers))
            solution.mark_unassigned(request, reason, details)

    return solution


# --------------------------------------------------------------------------------------
# Regret-вставка
# --------------------------------------------------------------------------------------


class _InsertionCache:
    """Лучшая позиция каждой заявки в каждом маршруте.

    Пересчитывается не целиком: после вставки меняется ровно один маршрут, поэтому
    обновляется только его столбец. Без этого конструктивная фаза на 100 заявках
    и 15 инженерах делает миллионы лишних проверок.
    """

    __slots__ = ("ctx", "solution", "allowed", "best", "static_reasons")

    def __init__(self, ctx: PlanContext, solution: Solution, pool: Sequence[Request]) -> None:
        self.ctx = ctx
        self.solution = solution
        self.allowed: dict[str, list[str]] = {}
        self.static_reasons: dict[str, ReasonAccumulator] = {}
        self.best: dict[str, dict[str, tuple[InsertionCost, int]]] = {}

        with_route = set(solution.order)
        for request in pool:
            accumulator = ReasonAccumulator()
            allowed: list[str] = []
            for engineer in sorted(ctx.scenario.engineers, key=lambda e: (e.input_order, e.id)):
                static = check_static(engineer, request, ctx.settings)
                if static.ok and engineer.id in with_route:
                    allowed.append(engineer.id)
                elif not static.ok:
                    accumulator.add(static)
            self.allowed[request.id] = allowed
            self.static_reasons[request.id] = accumulator
            self.best[request.id] = {}

    def refresh(self, request: Request, engineer_ids: Iterable[str], allow_new: bool) -> None:
        column = self.best[request.id]
        for engineer_id in engineer_ids:
            column.pop(engineer_id, None)
            route = self.solution.routes.get(engineer_id)
            if route is None:
                continue
            if route.is_empty and not allow_new:
                continue
            found = route.best_insertion(request)
            if found is not None:
                column[engineer_id] = found

    def refresh_all(self, requests: Iterable[Request], allow_new: bool) -> None:
        for request in requests:
            self.refresh(request, self.allowed[request.id], allow_new)

    def options(self, request: Request) -> list[tuple[InsertionCost, int, str]]:
        column = self.best[request.id]
        items = [(cost, position, engineer_id) for engineer_id, (cost, position) in column.items()]
        items.sort(key=lambda item: (item[0].key, item[2]))
        return items

    def forget(self, request_id: str) -> None:
        self.best.pop(request_id, None)
        self.allowed.pop(request_id, None)
        self.static_reasons.pop(request_id, None)


def _regret_of(options: Sequence[tuple[InsertionCost, int, str]], k: int) -> InsertionCost:
    """Насколько дороже обойдётся заявка, если не поставить её на лучшее место сейчас."""
    if len(options) <= 1:
        return WORST_POSSIBLE
    index = min(k, len(options)) - 1
    return options[index][0] - options[0][0]


def insert_regret(
    ctx: PlanContext,
    solution: Solution,
    pool: Sequence[Request],
    *,
    allow_new_engineers: bool = True,
    deadline: float | None = None,
    record_failures: bool = True,
) -> list[Request]:
    """Размещает заявки из `pool`. Возвращает список тех, кому места не нашлось.

    `allow_new_engineers=False` запрещает задействовать инженера, у которого сейчас пустой
    маршрут — этот режим использует минимизация числа исполнителей.
    """
    if not pool:
        return []

    remaining = {r.id: r for r in _ordered_requests(pool)}
    cache = _InsertionCache(ctx, solution, list(remaining.values()))
    cache.refresh_all(remaining.values(), allow_new_engineers)
    rejected: list[Request] = []
    k = max(2, ctx.settings.regret_k)

    while remaining:
        if deadline is not None and _time.monotonic() > deadline:
            break

        chosen_id: str | None = None
        chosen_key: tuple | None = None
        chosen_options: list[tuple[InsertionCost, int, str]] = []
        hopeless: list[str] = []

        for request_id, request in remaining.items():
            options = cache.options(request)
            if not options:
                hopeless.append(request_id)
                continue
            regret = _regret_of(options, k)
            key = (
                request.priority.rank,
                regret.key,
                -request.window_width_minutes,
                -request.input_order,
            )
            if chosen_key is None or key > chosen_key:
                chosen_key = key
                chosen_id = request_id
                chosen_options = options

        for request_id in hopeless:
            request = remaining.pop(request_id)
            rejected.append(request)
            if record_failures:
                _record_failure(ctx, solution, cache, request)
            cache.forget(request_id)

        if chosen_id is None:
            continue

        request = remaining.pop(chosen_id)
        placed_engineer: str | None = None
        for cost, position, engineer_id in chosen_options:
            route = solution.routes[engineer_id]
            if route.insert_checked(request, position):
                placed_engineer = engineer_id
                break
            # Быстрая оценка оказалась оптимистичной — пересчитываем этот маршрут честно.
            cache.refresh(request, (engineer_id,), allow_new_engineers)

        if placed_engineer is None:
            rejected.append(request)
            if record_failures:
                _record_failure(ctx, solution, cache, request)
            cache.forget(chosen_id)
            continue

        solution.clear_unassigned(chosen_id)
        cache.forget(chosen_id)
        for other in remaining.values():
            if placed_engineer in cache.allowed[other.id]:
                cache.refresh(other, (placed_engineer,), allow_new_engineers)

    for request in remaining.values():
        rejected.append(request)
        if record_failures:
            _record_failure(ctx, solution, cache, request, timed_out=True)

    rejected.sort(key=lambda r: (r.input_order, r.id))
    return rejected


def _record_failure(
    ctx: PlanContext,
    solution: Solution,
    cache: _InsertionCache,
    request: Request,
    *,
    timed_out: bool = False,
) -> None:
    """Формирует причину неназначения: самая содержательная из всех проверок."""
    accumulator = cache.static_reasons.get(request.id) or ReasonAccumulator()
    if timed_out:
        solution.mark_unassigned(
            request,
            ReasonCode.NOT_FOUND,
            ["исчерпан лимит времени поиска; невозможность размещения не доказана"],
        )
        return
    for engineer_id in cache.allowed.get(request.id, ()):
        route = solution.routes.get(engineer_id)
        if route is not None:
            accumulator.add(route.reject_reason(request))
    reason, details = accumulator.resolve(bool(ctx.scenario.engineers))
    solution.mark_unassigned(request, reason, details)


# --------------------------------------------------------------------------------------
# Точечная вставка (перепланирование)
# --------------------------------------------------------------------------------------


def place_single(
    ctx: PlanContext,
    solution: Solution,
    request: Request,
    *,
    allowed_engineers: Sequence[str] | None = None,
) -> tuple[RouteState, int] | None:
    """Ставит одну заявку в лучшую допустимую позицию по всем маршрутам.

    Используется при перепланировании: существующие маршруты не пересобираются,
    меняется ровно один из них.
    """
    candidates = allowed_engineers if allowed_engineers is not None else solution.order
    best: tuple[InsertionCost, int, str] | None = None
    for engineer_id in candidates:
        route = solution.routes.get(engineer_id)
        if route is None:
            continue
        if not check_static(route.engineer, request, ctx.settings).ok:
            continue
        found = route.best_insertion(request)
        if found is None:
            continue
        cost, position = found
        if best is None or (cost.key, engineer_id) < (best[0].key, best[2]):
            best = (cost, position, engineer_id)

    if best is None:
        return None
    route = solution.routes[best[2]]
    if not route.insert_checked(request, best[1]):
        return None
    solution.clear_unassigned(request.id)
    return route, best[1]


def place_with_ejection(
    ctx: PlanContext,
    solution: Solution,
    request: Request,
    *,
    allowed_engineers: Sequence[str] | None = None,
    touched: set[str] | None = None,
) -> tuple[RouteState, int] | None:
    """Ставит заявку, вытесняя до `ejection_depth` менее приоритетных, если прямой вставки нет.

    Авария важнее любой другой работы: она сдвигает хвост маршрута, а если окна
    остальных не держат сдвиг — вытесняет их. Одной вытесненной заявки хватает не
    всегда: длинная авария в плотной смене освобождает себе место только через
    несколько работ подряд, поэтому вытеснение идёт по нарастающей, но не глубже
    заданного предела — иначе ради одной заявки можно развалить весь день.

    Сначала ищется вытеснение, после которого **все** потеснённые заявки находят новое
    место. Только если такого нет, принимается честная потеря работ меньшего приоритета.
    """
    depth = max(0, ctx.settings.ejection_depth)
    if depth <= 0:
        return None

    candidates = allowed_engineers if allowed_engineers is not None else solution.order
    fallback: tuple[str, int, list[str], Solution] | None = None
    for engineer_id in candidates:
        probe = solution.routes.get(engineer_id)
        if probe is None or probe.is_empty or not probe.accepts(request):
            continue
        victims = [
            r.id
            for r in probe.stops[probe.locked_count :]
            if r.priority.rank < request.priority.rank
        ]

        for first in range(len(victims)):
            snapshot = solution.clone()
            route = solution.routes[engineer_id]
            removed: list[Request] = []
            position = -1

            # Освобождаем места по одному, начиная с выбранной заявки: так при
            # `ejection_depth=1` поведение остаётся прежним — перебор одиночных жертв.
            for victim_id in victims[first:]:
                index = route.index_of(victim_id)
                if index < 0 or index < route.locked_count:
                    continue
                removed.append(route.remove_at(index))
                placed = route.best_insertion(request)
                if placed is not None and route.insert_checked(request, placed[1]):
                    position = placed[1]
                    break
                if len(removed) >= depth:
                    break

            if position < 0:
                solution.restore_from(snapshot)
                continue

            solution.clear_unassigned(request.id)
            homeless: list[str] = []
            for victim in removed:
                rehomed = place_single(ctx, solution, victim)
                if rehomed is None:
                    homeless.append(victim.id)
                elif touched is not None:
                    touched.add(rehomed[0].engineer.id)

            if not homeless:
                if touched is not None:
                    touched.add(engineer_id)
                return solution.routes[engineer_id], position
            # Вытеснение с потерей — запасной вариант: берём тот, где теряется меньше.
            if fallback is None or len(homeless) < len(fallback[2]):
                fallback = (engineer_id, position, homeless, solution.clone())
            solution.restore_from(snapshot)

    if fallback is not None:
        engineer_id, position, homeless, state = fallback
        solution.restore_from(state)
        for victim_id in homeless:
            victim = ctx.scenario.request_by_id.get(victim_id)
            if victim is not None:
                solution.mark_unassigned(
                    victim,
                    ReasonCode.TIME_CONFLICT,
                    [f"место освобождено под аварийную заявку {request.id}"],
                )
        if touched is not None:
            touched.add(engineer_id)
        return solution.routes[engineer_id], position

    return None


def reclaim_emergencies(
    ctx: PlanContext,
    solution: Solution,
    *,
    allowed_engineers: Sequence[str] | None = None,
    touched: set[str] | None = None,
) -> int:
    """Доразмещает неназначенные аварии, сдвигая или вытесняя менее приоритетные."""
    pending = [
        request
        for request in sorted(
            solution.unassigned.values(),
            key=lambda r: (-r.priority.rank, r.input_order, r.id),
        )
        if request.priority is Priority.EMERGENCY
    ]
    placed = 0
    for request in pending:
        if request.id not in solution.unassigned:
            continue
        if place_single(ctx, solution, request, allowed_engineers=allowed_engineers) is not None:
            placed += 1
            continue
        found = place_with_ejection(
            ctx,
            solution,
            request,
            allowed_engineers=allowed_engineers,
            touched=touched,
        )
        if found is not None:
            placed += 1
    return placed

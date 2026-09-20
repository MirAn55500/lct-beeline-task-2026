"""Улучшающая фаза: классический локальный поиск поверх готового решения.

Четыре оператора, проверенные на бенчмарках Соломона для VRPTW:

* `or-opt` — перенос подряд идущих 1..3 заявок в другое место того же маршрута;
* `2-opt` — разворот участка маршрута;
* `relocate` — перенос участка в маршрут другого инженера;
* `exchange` — обмен двумя заявками между маршрутами.

Ход принимается, только если он уменьшает (время в пути, пробег) и **не ухудшает** ничего
более важного: не теряет заявок и не добавляет задействованных инженеров. Допустимость
каждого хода проверяет тот же `RouteState`, что и первичную вставку, — отдельной
«упрощённой» проверки для локального поиска нет принципиально, иначе оптимизатор рано или
поздно начнёт выдавать планы, которые проходят его собственную проверку и не проходят общую.

Структура прохода: каждый оператор делает **один** проход и применяет лучший найденный ход.
Повторение обеспечивает внешний цикл раундов. Вложенные циклы «улучшай, пока улучшается»
внутри каждого оператора давали ту же точку сходимости, но на порядок дороже.

После каждого раунда делается попытка пристроить неназначенные заявки: перестановки
освобождают время, и заявка, не помещавшаяся после конструктивной фазы, часто влезает.
"""

from __future__ import annotations

import time as _time

from .context import PlanContext
from .route import RouteState
from .solution import Solution

__all__ = ["local_search"]

_EPS = 1e-7


def _route_key(route: RouteState) -> tuple[float, float]:
    return (route.travel_minutes, route.distance_km)


def _pair_key(a: RouteState, b: RouteState) -> tuple[float, float]:
    return (a.travel_minutes + b.travel_minutes, a.distance_km + b.distance_km)


def _better(new: tuple[float, float], old: tuple[float, float], eps: float = _EPS) -> bool:
    """Строгое улучшение: сначала время в пути, затем пробег.

    Сравнение с допуском обязательно: без него ход, улучшающий результат на 1e-15,
    принимается, тут же откатывается обратным ходом, и поиск зацикливается.
    """
    if new[0] < old[0] - eps:
        return True
    if new[0] > old[0] + eps:
        return False
    return new[1] < old[1] - eps


def _move_better(
    new: tuple[int, float, float], old: tuple[int, float, float], eps: float = _EPS
) -> bool:
    """То же сравнение с ведущим признаком «ход освобождает инженера»."""
    if new[0] != old[0]:
        return new[0] < old[0]
    return _better((new[1], new[2]), (old[1], old[2]), eps)


def local_search(
    ctx: PlanContext,
    solution: Solution,
    *,
    deadline: float | None = None,
    routes_filter: set[str] | None = None,
) -> int:
    """Гоняет операторы до сходимости или лимита времени. Возвращает число улучшений.

    `routes_filter` ограничивает поиск конкретными инженерами — так перепланирование
    не переворачивает весь день ради пары минут, и диспетчер видит точечное изменение.
    """
    settings = ctx.settings
    improvements = 0
    max_segment = max(1, settings.or_opt_max_segment)

    for _ in range(max(1, settings.max_local_search_rounds)):
        if deadline is not None and _time.monotonic() > deadline:
            break
        gain = _intra_route_pass(solution, max_segment, deadline, routes_filter)
        gain += _inter_route_pass(solution, max_segment, deadline, routes_filter)
        gain += _retry_unassigned(ctx, solution, routes_filter)
        improvements += gain
        if gain == 0:
            break

    return improvements


# --------------------------------------------------------------------------------------
# Внутри маршрута
# --------------------------------------------------------------------------------------


def _intra_route_pass(
    solution: Solution,
    max_segment: int,
    deadline: float | None,
    routes_filter: set[str] | None,
) -> int:
    gains = 0
    for route in solution:
        if routes_filter is not None and route.engineer.id not in routes_filter:
            continue
        if route.size < 2:
            continue
        if deadline is not None and _time.monotonic() > deadline:
            break
        gains += _or_opt(route, max_segment)
        gains += _two_opt(route)
    return gains


def _or_opt(route: RouteState, max_segment: int) -> int:
    """Перенос сегмента из 1..max_segment заявок в другое место того же маршрута."""
    base_key = _route_key(route)
    n = route.size
    best: tuple[tuple[float, float], list] | None = None

    for length in range(1, min(max_segment, n) + 1):
        for start in range(route.locked_count, n - length + 1):
            segment = route.stops[start : start + length]
            rest = route.stops[:start] + route.stops[start + length :]
            for target in range(route.locked_count, len(rest) + 1):
                if target == start:
                    continue
                candidate = rest[:target] + segment + rest[target:]
                snapshot = route.stops[:]
                if not route.try_sequence(candidate):
                    continue
                key = _route_key(route)
                if _better(key, base_key) and (best is None or _better(key, best[0])):
                    best = (key, candidate)
                route.try_sequence(snapshot)

    if best is not None and route.try_sequence(best[1]):
        return 1
    return 0


def _two_opt(route: RouteState) -> int:
    """Разворот участка. На маршрутах с окнами срабатывает редко, но стоит копейки."""
    base_key = _route_key(route)
    n = route.size
    best: tuple[tuple[float, float], list] | None = None

    for i in range(route.locked_count, n - 1):
        for j in range(i + 2, n + 1):
            candidate = route.stops[:i] + route.stops[i:j][::-1] + route.stops[j:]
            snapshot = route.stops[:]
            if not route.try_sequence(candidate):
                continue
            key = _route_key(route)
            if _better(key, base_key) and (best is None or _better(key, best[0])):
                best = (key, candidate)
            route.try_sequence(snapshot)

    if best is not None and route.try_sequence(best[1]):
        return 1
    return 0


# --------------------------------------------------------------------------------------
# Между маршрутами
# --------------------------------------------------------------------------------------


def _inter_route_pass(
    solution: Solution,
    max_segment: int,
    deadline: float | None,
    routes_filter: set[str] | None,
) -> int:
    gains = 0
    routes = [r for r in solution if routes_filter is None or r.engineer.id in routes_filter]
    for source in routes:
        if source.is_empty:
            continue
        for target in routes:
            if target is source:
                continue
            if deadline is not None and _time.monotonic() > deadline:
                return gains
            # Отсечение: если целевой инженер не имеет права взять ни одну заявку
            # донора (навык, регион, транспорт), перебирать пару бессмысленно.
            if not any(target.accepts(r) for r in source.stops[source.locked_count :]):
                continue
            gains += _relocate(source, target, max_segment)
            gains += _exchange(source, target)
    return gains


def _relocate(source: RouteState, target: RouteState, max_segment: int) -> int:
    """Перенос сегмента из одного маршрута в другой.

    Открывать нового инженера ради экономии километров нельзя: число задействованных
    исполнителей — критерий более высокого порядка. Исключение одно — если маршрут-донор
    при этом опустошается, то есть людей становится не больше, а меньше. Такой ход
    принимается, даже если километры немного выросли.
    """
    if source.is_empty:
        return 0

    base_travel, base_distance = _pair_key(source, target)
    base_key = (1, base_travel, base_distance)
    target_was_empty = target.is_empty
    n = source.size
    best: tuple[tuple[int, float, float], list, list] | None = None

    for length in range(1, min(max_segment, n) + 1):
        for start in range(source.locked_count, n - length + 1):
            segment = source.stops[start : start + length]
            if any(not target.accepts(r) for r in segment):
                continue
            remainder = source.stops[:start] + source.stops[start + length :]
            if target_was_empty and remainder:
                continue  # новый инженер появился бы, а старый не освободился
            for position in range(target.locked_count, target.size + 1):
                candidate = target.stops[:position] + segment + target.stops[position:]
                src_snapshot = source.stops[:]
                tgt_snapshot = target.stops[:]
                if not source.try_sequence(remainder):
                    continue
                if not target.try_sequence(candidate):
                    source.try_sequence(src_snapshot)
                    continue
                travel, distance = _pair_key(source, target)
                frees_engineer = not remainder and not target_was_empty
                key = (0 if frees_engineer else 1, travel, distance)
                if _move_better(key, base_key) and (best is None or _move_better(key, best[0])):
                    best = (key, remainder, candidate)
                source.try_sequence(src_snapshot)
                target.try_sequence(tgt_snapshot)

    if best is not None:
        src_snapshot = source.stops[:]
        if source.try_sequence(best[1]) and target.try_sequence(best[2]):
            return 1
        source.try_sequence(src_snapshot)
    return 0


def _exchange(source: RouteState, target: RouteState) -> int:
    """Обмен одной заявкой между двумя маршрутами. Состав инженеров не меняется."""
    if source.is_empty or target.is_empty:
        return 0

    base_key = _pair_key(source, target)
    best: tuple[tuple[float, float], list, list] | None = None

    for i in range(source.locked_count, source.size):
        moved_out = source.stops[i]
        if not target.accepts(moved_out):
            continue
        for j in range(target.locked_count, target.size):
            moved_in = target.stops[j]
            if not source.accepts(moved_in):
                continue
            new_source = source.stops[:]
            new_target = target.stops[:]
            new_source[i], new_target[j] = moved_in, moved_out
            src_snapshot = source.stops[:]
            tgt_snapshot = target.stops[:]
            if not source.try_sequence(new_source):
                continue
            if not target.try_sequence(new_target):
                source.try_sequence(src_snapshot)
                continue
            key = _pair_key(source, target)
            if _better(key, base_key) and (best is None or _better(key, best[0])):
                best = (key, new_source, new_target)
            source.try_sequence(src_snapshot)
            target.try_sequence(tgt_snapshot)

    if best is not None:
        src_snapshot = source.stops[:]
        if source.try_sequence(best[1]) and target.try_sequence(best[2]):
            return 1
        source.try_sequence(src_snapshot)
    return 0


# --------------------------------------------------------------------------------------
# Повторная попытка для неназначенных
# --------------------------------------------------------------------------------------


def _retry_unassigned(
    ctx: PlanContext, solution: Solution, routes_filter: set[str] | None
) -> int:
    """После перестановок часть заявок начинает помещаться — пробуем снова.

    Это не косметика: именно здесь добираются заявки, которые конструктивная фаза
    отвергла из-за неудачного порядка визитов, а не из-за реальной нехватки ресурса.
    """
    if not solution.unassigned:
        return 0
    from .construct import place_single, place_with_ejection

    placed = 0
    candidates = sorted(
        solution.unassigned.values(), key=lambda r: (-r.priority.rank, r.input_order, r.id)
    )
    allowed = None if routes_filter is None else [i for i in solution.order if i in routes_filter]
    for request in candidates:
        if place_single(ctx, solution, request, allowed_engineers=allowed) is not None:
            placed += 1
        elif request.is_emergency and place_with_ejection(
            ctx, solution, request, allowed_engineers=allowed
        ) is not None:
            placed += 1
    return placed

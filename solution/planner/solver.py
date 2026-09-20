"""Сборка результата и главная точка входа расчёта.

`plan(scenario)` — единственная функция, которая нужна снаружи: на вход весь сценарий
(заявки, инженеры, параметры), на выходе всё для маршрутов, расписаний, карты, метрик
и объяснений.

Порядок фаз оптимизированного расчёта:

    1. regret-вставка            — построить допустимое решение, не теряя заявок
    2. локальный поиск           — сократить время в пути и пробег
    3. минимизация исполнителей  — освободить людей, не потеряв ни одной заявки
    4. локальный поиск повторно  — прибрать маршруты после переносов

Общий лимит времени делится между фазами; любая из них может завершиться досрочно,
и решение останется корректным — каждая фаза поддерживает допустимость как инвариант.
"""

from __future__ import annotations

import time as _time
from dataclasses import replace as _replace
from datetime import datetime
from typing import Sequence

from .construct import build_baseline, insert_regret, reclaim_emergencies
from .context import PlanContext
from .enums import Algorithm, AssignmentStatus, Priority, ReasonCode
from .explain import explain_assignment, explain_route, explain_unassigned
from .feasibility import check_static
from .fleet import minimize_fleet
from .improve import local_search
from .models import Request, Scenario
from .result import (
    Assignment,
    EngineerMetrics,
    PlanDiff,
    PlanMetrics,
    PlanResult,
    RouteResult,
    Visit,
)
from .route import RouteState
from .solution import Solution
from .travel import TravelModel

__all__ = ["plan", "solve", "build_result"]

_PLAN_COUNTER = {"value": 0}


def _next_plan_id(prefix: str) -> str:
    _PLAN_COUNTER["value"] += 1
    return f"{prefix}-{_PLAN_COUNTER['value']:04d}"


# --------------------------------------------------------------------------------------
# Поиск
# --------------------------------------------------------------------------------------


def solve(
    ctx: PlanContext,
    algorithm: Algorithm = Algorithm.OPTIMIZED,
    *,
    deadline: float | None = None,
) -> Solution:
    """Строит решение выбранным алгоритмом. Результат — внутреннее состояние, не отчёт."""
    if algorithm is Algorithm.BASELINE:
        return build_baseline(ctx)

    settings = ctx.settings
    if deadline is None:
        deadline = _time.monotonic() + max(0.1, settings.time_limit_seconds)

    solution = Solution(ctx)
    pool: Sequence[Request] = sorted(
        ctx.scenario.planning_requests(), key=lambda r: (r.input_order, r.id)
    )
    # Конструктивная фаза идёт без урезания: без допустимого решения оптимизировать нечего.
    insert_regret(ctx, solution, pool, deadline=deadline)
    reclaim_emergencies(ctx, solution)

    # Оставшийся бюджет делится между фазами заранее. Иначе локальный поиск на трудном
    # наборе съедает всё время и минимизация числа исполнителей — первая обязательная
    # метрика ТЗ — просто не успевает запуститься.
    remaining = max(0.0, deadline - _time.monotonic())
    improve_first = _time.monotonic() + remaining * 0.35
    fleet_until = _time.monotonic() + remaining * 0.75

    if settings.enable_local_search:
        local_search(ctx, solution, deadline=improve_first)

    if settings.enable_fleet_minimization:
        minimize_fleet(ctx, solution, deadline=fleet_until)

    if settings.enable_local_search:
        local_search(ctx, solution, deadline=deadline)

    return solution


def plan(
    scenario: Scenario,
    algorithm: Algorithm = Algorithm.OPTIMIZED,
    *,
    travel: TravelModel | None = None,
    plan_id: str | None = None,
) -> PlanResult:
    """Главная точка входа: сценарий → полный план дня."""
    started = _time.monotonic()
    warnings = scenario.validate()
    ctx = PlanContext(scenario, travel)
    deadline = started + max(0.1, scenario.settings.time_limit_seconds)
    solution = solve(ctx, algorithm, deadline=deadline)
    elapsed_ms = (_time.monotonic() - started) * 1000.0
    return build_result(
        ctx,
        solution,
        algorithm,
        warnings=warnings,
        elapsed_ms=elapsed_ms,
        plan_id=plan_id,
    )


# --------------------------------------------------------------------------------------
# Сборка отчёта
# --------------------------------------------------------------------------------------


def build_result(
    ctx: PlanContext,
    solution: Solution,
    algorithm: Algorithm,
    *,
    warnings: Sequence[str] = (),
    elapsed_ms: float = 0.0,
    diff: PlanDiff | None = None,
    plan_id: str | None = None,
    created_at: datetime | None = None,
) -> PlanResult:
    """Превращает состояние поиска в неизменяемый отчёт с метриками и объяснениями."""
    scenario = ctx.scenario
    alternatives = _count_alternatives(ctx)
    _refresh_reasons(ctx, solution)

    routes: list[RouteResult] = []
    assignments: dict[str, Assignment] = {}

    for state in solution:
        if state.is_empty:
            continue
        route, route_assignments = _build_route(ctx, state, alternatives)
        routes.append(route)
        assignments.update(route_assignments)

    for request in scenario.planning_requests():
        if request.id in assignments:
            continue
        reason, details = solution.reasons.get(request.id, (ReasonCode.NOT_FOUND, []))
        assignments[request.id] = Assignment(
            request_id=request.id,
            status=AssignmentStatus.UNASSIGNED,
            reason=reason,
            explanation=explain_unassigned(request, reason, details),
            checked_skill=request.required_skill,
            checked_transport=request.required_transport,
            checked_equipment=tuple(sorted(request.required_equipment)),
        )

    ordered_assignments = tuple(
        assignments[r.id]
        for r in sorted(scenario.planning_requests(), key=lambda r: (r.input_order, r.id))
        if r.id in assignments
    )

    metrics = _build_metrics(ctx, solution, routes, ordered_assignments, elapsed_ms)

    return PlanResult(
        plan_id=plan_id or _next_plan_id(algorithm.value),
        algorithm=algorithm,
        date=scenario.date,
        routes=tuple(routes),
        assignments=ordered_assignments,
        metrics=metrics,
        warnings=tuple(warnings),
        diff=diff,
        name=scenario.name,
        created_at=created_at,
    )


def _refresh_reasons(ctx: PlanContext, solution: Solution) -> None:
    """Пересобирает причины отказа по ИТОГОВОМУ состоянию маршрутов.

    Причина, записанная в момент неудачной вставки, к концу расчёта устаревает: тогда
    маршруты были пустыми, и диспетчеру досталось бы «не помещается в смену» про инженера,
    который на самом деле к вечеру занят под завязку. Объяснение должно описывать тот план,
    который человек видит на экране, а не промежуточное состояние поиска.
    """
    from .feasibility import ReasonAccumulator

    if not solution.unassigned:
        return
    has_engineers = bool(ctx.scenario.engineers)
    engineers = sorted(ctx.scenario.engineers, key=lambda e: (e.input_order, e.id))
    for request_id, request in solution.unassigned.items():
        existing = solution.reasons.get(request_id)
        if existing is not None and existing[0] is ReasonCode.MANUAL:
            continue  # решение диспетчера машинной догадкой не переписывается
        accumulator = ReasonAccumulator()
        for engineer in engineers:
            static = check_static(engineer, request, ctx.settings)
            if not static.ok:
                accumulator.add(static)
                continue
            route = solution.routes.get(engineer.id)
            if route is not None and route.best_insertion(request) is None:
                accumulator.add(route.reject_reason(request))
        reason, details = accumulator.resolve(has_engineers)
        if reason is ReasonCode.NOT_FOUND and request_id in solution.reasons:
            continue  # заявка отсеяна по лимиту времени — исходная формулировка точнее
        solution.reasons[request_id] = (reason, details)


def _count_alternatives(ctx: PlanContext) -> dict[str, int]:
    """Сколько инженеров вообще имели право взять заявку — нужно для объяснений."""
    counts: dict[str, int] = {}
    engineers = ctx.scenario.active_engineers()
    for request in ctx.scenario.planning_requests():
        counts[request.id] = sum(
            1 for e in engineers if check_static(e, request, ctx.settings).ok
        )
    return counts


def _build_route(
    ctx: PlanContext, state: RouteState, alternatives: dict[str, int]
) -> tuple[RouteResult, dict[str, Assignment]]:
    engineer = state.engineer
    travel = ctx.travel
    mode = state.mode
    visits: list[Visit] = []
    assignments: dict[str, Assignment] = {}

    for index, request in enumerate(state.stops):
        dep, arr, start, end, wait, idle, leg_minutes, leg_km = state.schedule_at(index)
        from_point = engineer.start_point if index == 0 else state.stops[index - 1].point

        visit = Visit(
            request_id=request.id,
            position=index + 1,
            engineer_id=engineer.id,
            departure_at=ctx.to_datetime(dep),
            arrival_at=ctx.to_datetime(arr),
            service_start_at=ctx.to_datetime(start),
            service_end_at=ctx.to_datetime(end),
            travel_minutes=leg_minutes,
            distance_km=leg_km,
            waiting_minutes=wait,
            from_point=from_point,
            to_point=request.point,
            latest_departure_at=ctx.to_datetime(state.latest_departure_m(index)),
            service_minutes=float(request.duration_minutes),
            idle_before_minutes=idle,
            slack_minutes=state.slack_m(index),
            locked=index < state.locked_count,
            address=request.address,
            priority=request.priority.value,
            required_skill=request.required_skill,
        )
        visits.append(visit)

        added = _incremental_distance(ctx, state, index)
        assignments[request.id] = Assignment(
            request_id=request.id,
            status=AssignmentStatus.ASSIGNED,
            engineer_id=engineer.id,
            engineer_name=engineer.name,
            position=index + 1,
            arrival_at=visit.arrival_at,
            service_start_at=visit.service_start_at,
            service_end_at=visit.service_end_at,
            explanation=explain_assignment(
                request,
                engineer.name,
                visit,
                engineer.shift_end,
                alternatives=alternatives.get(request.id, 0),
                added_distance_km=added,
            ),
            checked_skill=request.required_skill,
            checked_transport=request.required_transport,
            checked_equipment=tuple(sorted(request.required_equipment)),
            checked_qualification_level=engineer.level_of(request.required_skill),
            incremental_distance_km=added,
        )

    route = RouteResult(
        engineer_id=engineer.id,
        engineer_name=engineer.name,
        transport_mode=mode,
        start_point=engineer.start_point,
        visits=tuple(visits),
        start_at=ctx.to_datetime(state.start_m),
        end_at=ctx.to_datetime(state.end_m),
        distance_km=state.distance_km,
        travel_minutes=state.travel_minutes,
        service_minutes=state.service_minutes,
        waiting_minutes=state.waiting_minutes,
        capacity_minutes=state.cal.capacity_minutes,
        region_key=engineer.region_key,
    )
    return _replace(route, explanation=explain_route(route)), assignments


def _incremental_distance(ctx: PlanContext, state: RouteState, index: int) -> float:
    """Насколько длиннее стал маршрут из-за этой заявки — «цена» её вставки в км."""
    travel = ctx.travel
    mode = state.mode
    prev = state.engineer.start_point if index == 0 else state.stops[index - 1].point
    current = state.stops[index].point
    if index + 1 < len(state.stops):
        nxt = state.stops[index + 1].point
        return (
            travel.distance_km(prev, current, mode)
            + travel.distance_km(current, nxt, mode)
            - travel.distance_km(prev, nxt, mode)
        )
    return travel.distance_km(prev, current, mode)


def _build_metrics(
    ctx: PlanContext,
    solution: Solution,
    routes: Sequence[RouteResult],
    assignments: Sequence[Assignment],
    elapsed_ms: float,
) -> PlanMetrics:
    per_engineer = tuple(
        EngineerMetrics(
            engineer_id=r.engineer_id,
            engineer_name=r.engineer_name,
            assigned_count=len(r.visits),
            distance_km=r.distance_km,
            travel_minutes=r.travel_minutes,
            service_minutes=r.service_minutes,
            waiting_minutes=r.waiting_minutes,
            capacity_minutes=r.capacity_minutes,
            utilization=r.utilization,
        )
        for r in routes
    )
    assigned = sum(1 for a in assignments if a.is_assigned)
    unassigned_list = [a for a in assignments if not a.is_assigned]
    tight = sum(1 for r in routes for v in r.visits if v.slack_minutes < 10.0)
    by_id = {r.id: r for r in ctx.scenario.planning_requests()}
    emergency_ids = {rid for rid, r in by_id.items() if r.priority is Priority.EMERGENCY}
    connection_ids = {rid for rid, r in by_id.items() if r.priority is Priority.CONNECTION}
    utilizations = [m.utilization for m in per_engineer]

    return PlanMetrics(
        assigned_count=assigned,
        feasible_count=assigned,
        tight_visit_count=tight,
        unassigned_count=len(unassigned_list),
        emergency_unassigned_count=sum(1 for a in unassigned_list if a.request_id in emergency_ids),
        connection_unassigned_count=sum(
            1 for a in unassigned_list if a.request_id in connection_ids
        ),
        used_engineer_count=len(routes),
        available_engineer_count=len(ctx.scenario.active_engineers()),
        total_distance_km=sum(r.distance_km for r in routes),
        total_travel_minutes=sum(r.travel_minutes for r in routes),
        total_service_minutes=sum(r.service_minutes for r in routes),
        total_waiting_minutes=sum(r.waiting_minutes for r in routes),
        avg_utilization=(sum(utilizations) / len(utilizations)) if utilizations else 0.0,
        computation_ms=elapsed_ms,
        constraints_valid=all(state.feasible for state in solution),
        per_engineer=per_engineer,
    )

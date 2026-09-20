"""Событийное перепланирование: инкрементальный ремонт вместо пересчёта с нуля.

Требование ТЗ — новый план за считанные минуты и наглядный показ того, **что именно
изменилось**. Пересчёт «с чистого листа» формально удовлетворяет первому и полностью
проваливает второе: диспетчер видит, что перетасовался весь день, и не может понять,
это следствие события или случайность эвристики.

Поэтому все четыре сценария работают по общему каркасу:

    заморозить прошлое → применить событие → починить только затронутое → показать разницу

**Заморозка** — ключевой инвариант: назначение, работа по которому началась до момента
события, не меняется ни по исполнителю, ни по времени. Такие визиты остаются в начале
маршрута как `locked`, и ни один оператор поиска не имеет права их тронуть.
"""

from __future__ import annotations

import time as _time
from dataclasses import replace as _replace
from datetime import datetime
from typing import Sequence

from .construct import insert_regret, place_single, place_with_ejection
from .context import PlanContext
from .enums import Algorithm, EventType, Priority, ReasonCode
from .explain import explain_replan
from .improve import local_search
from .models import Engineer, Request, Scenario, WorkInterval
from .result import PlanDiff, PlanResult
from .solution import Solution
from .solver import build_result
from .travel import TravelModel

__all__ = ["replan", "apply_event", "seed_from_previous", "build_diff"]


def replan(
    previous: PlanResult,
    scenario: Scenario,
    event,
    *,
    travel: TravelModel | None = None,
    plan_id: str | None = None,
) -> PlanResult:
    """Перестраивает план после одного события. Возвращает новый план с `diff`."""
    started = _time.monotonic()

    new_scenario, extra_warnings = apply_event(scenario, previous, event)
    ctx = PlanContext(new_scenario, travel)
    deadline = started + max(0.1, new_scenario.settings.time_limit_seconds)

    solution, orphans, touched = seed_from_previous(ctx, previous, event.at)

    pool: list[Request] = list(orphans)
    for assignment in previous.unassigned:
        request = new_scenario.request_by_id.get(assignment.request_id)
        if request is not None and request.id not in solution.assigned_ids():
            pool.append(request)

    urgent_request = None
    if event.type is EventType.URGENT_REQUEST:
        urgent_request = new_scenario.request_by_id.get(event.request.id)

    if urgent_request is not None:
        placed = place_single(ctx, solution, urgent_request)
        if placed is None:
            placed = place_with_ejection(
                ctx, solution, urgent_request, touched=touched
            )
        if placed is None:
            solution.mark_unassigned(
                urgent_request,
                ReasonCode.TIME_CONFLICT,
                ["аварийную заявку не удалось вставить ни в один маршрут, даже вытесняя менее приоритетные"],
            )
        else:
            touched.add(placed[0].engineer.id)

    if pool:
        pool.sort(key=lambda r: (-r.priority.rank, r.input_order, r.id))
        insert_regret(ctx, solution, pool, deadline=deadline)
        for request in pool:
            route = solution.route_of(request.id)
            if route is not None:
                touched.add(route.engineer.id)

    if new_scenario.settings.stabilize_after_replan and touched:
        local_search(ctx, solution, deadline=deadline, routes_filter=set(touched))

    elapsed_ms = (_time.monotonic() - started) * 1000.0
    result = build_result(
        ctx,
        solution,
        Algorithm.OPTIMIZED,
        warnings=tuple(new_scenario.validate()) + tuple(extra_warnings),
        elapsed_ms=elapsed_ms,
        plan_id=plan_id,
    )
    diff = build_diff(previous, result, event)
    return _replace(result, diff=diff)


# --------------------------------------------------------------------------------------
# Применение события к входным данным
# --------------------------------------------------------------------------------------


def apply_event(scenario: Scenario, previous: PlanResult, event) -> tuple[Scenario, list[str]]:
    """Вносит событие во входные данные и возвращает ДЕЙСТВУЮЩИЙ сценарий и примечания.

    Функция публичная не для красоты: после события состав заявок меняется (срочная
    добавилась, отменённая исчезла, у заявки с отказом клиента обнулилась работа), и
    результат `replan()` описывает именно этот сценарий. Проверять его через
    `validate_plan(result, scenario)` с ИСХОДНЫМ сценарием некорректно — нужен тот,
    что вернула эта функция.
    """
    warnings: list[str] = []
    requests = list(scenario.requests)
    engineers = list(scenario.engineers)

    if event.type is EventType.URGENT_REQUEST:
        new_request = event.request
        if new_request.id in {r.id for r in requests}:
            requests = [r for r in requests if r.id != new_request.id]
        order = max((r.input_order for r in requests), default=0) + 1
        requests.append(
            _replace(
                new_request,
                input_order=order,
                priority=Priority.EMERGENCY,
                received_at=new_request.received_at or event.at,
            )
        )

    elif event.type is EventType.CANCEL_REQUEST:
        target = event.target_request_id
        if target not in {r.id for r in requests}:
            warnings.append(f"Отменяемая заявка {target} отсутствует во входных данных")
        requests = [r for r in requests if r.id != target]

    elif event.type is EventType.CLIENT_REFUSAL:
        target = event.target_request_id
        updated: list[Request] = []
        for request in requests:
            if request.id != target:
                updated.append(request)
                continue
            spent = _minutes_spent(previous, request.id, event.at)
            updated.append(_replace(request, duration_minutes=max(0, int(round(spent)))))
            warnings.append(
                f"Заявка {target}: отказ клиента на адресе — поездка сохранена, "
                f"работа не засчитана, освободилось время в маршруте"
            )
        requests = updated

    elif event.type is EventType.ENGINEER_UNAVAILABLE:
        cutoff = _unavailable_cutoff(previous, event)
        updated_engineers: list[Engineer] = []
        for engineer in engineers:
            if engineer.id != event.engineer_id:
                updated_engineers.append(engineer)
                continue
            trimmed = _trim_intervals(engineer.work_intervals, cutoff)
            updated_engineers.append(
                _replace(engineer, work_intervals=trimmed, active=bool(trimmed))
            )
            warnings.append(
                f"Инженер {engineer.name} недоступен с {event.at:%H:%M}; "
                f"уже начатые работы сохранены"
            )
        engineers = updated_engineers

    # Событие происходит «сейчас», поэтому граница снимка сдвигается на его момент:
    # иначе аварийная заявка, поступившая позже прежнего `as_of`, попадала бы в маршрут,
    # но выпадала из `planning_requests()` — и, значит, из назначений и метрик.
    as_of = scenario.as_of
    if as_of is not None and event.at > as_of:
        as_of = event.at

    return (
        _replace(
            scenario, requests=tuple(requests), engineers=tuple(engineers), as_of=as_of
        ),
        warnings,
    )


def _minutes_spent(previous: PlanResult, request_id: str, moment: datetime) -> float:
    assignment = previous.assignment_of(request_id)
    if assignment is None or assignment.service_start_at is None:
        return 0.0
    return max(0.0, (moment - assignment.service_start_at).total_seconds() / 60.0)


def _unavailable_cutoff(previous: PlanResult, event) -> datetime:
    """Смена обрезается моментом события, но не раньше конца уже начатых работ."""
    cutoff = event.at
    route = previous.route_of(event.engineer_id)
    if route is not None:
        for visit in route.visits:
            if visit.service_start_at < event.at and visit.service_end_at > cutoff:
                cutoff = visit.service_end_at
    return cutoff


def _trim_intervals(
    intervals: Sequence[WorkInterval], cutoff: datetime
) -> tuple[WorkInterval, ...]:
    trimmed: list[WorkInterval] = []
    for interval in intervals:
        if interval.start >= cutoff:
            continue
        end = min(interval.end, cutoff)
        if end > interval.start:
            trimmed.append(WorkInterval(interval.start, end))
    return tuple(trimmed)


# --------------------------------------------------------------------------------------
# Перенос предыдущего плана в рабочее состояние
# --------------------------------------------------------------------------------------


def seed_from_previous(
    ctx: PlanContext, previous: PlanResult, frozen_before: datetime | None
) -> tuple[Solution, list[Request], set[str]]:
    """Восстанавливает маршруты прошлого плана и помечает начатые визиты как замороженные.

    `frozen_before` — момент события: визиты, работа по которым началась раньше, трогать
    нельзя. `None` означает, что замораживать нечего (ручное вмешательство диспетчера
    вне контекста события).
    """
    solution = Solution(ctx)
    by_id = ctx.scenario.request_by_id
    orphans: list[Request] = []
    touched: set[str] = set()

    for route in previous.routes:
        state = solution.routes.get(route.engineer_id)
        if state is None:
            # Инженер выбыл из расчёта целиком: все его заявки ищут нового исполнителя.
            orphans.extend(
                by_id[v.request_id] for v in route.visits if v.request_id in by_id
            )
            touched.add(route.engineer_id)
            continue

        kept: list[Request] = []
        schedule: list[tuple[float, float, float, float, float, float, float]] = []
        locked_count = 0
        for visit in route.visits:
            request = by_id.get(visit.request_id)
            if request is None:
                touched.add(route.engineer_id)
                continue  # заявка снята событием
            # Признак `locked` уже проставлен в предыдущем плане и обязан переживать любое
            # восстановление: работа, которая началась, не перестаёт быть начатой оттого,
            # что вызывающий не передал момент времени. Без этого ручное переназначение
            # уводило визит, по которому инженер уже работает.
            frozen = visit.locked or (
                frozen_before is not None and visit.service_start_at < frozen_before
            )
            if frozen and len(kept) == locked_count:
                locked_count += 1
                schedule.append(_visit_schedule(ctx, visit))
            kept.append(request)

        if not state.adopt(kept, locked_count, schedule):
            # Обрезанная смена или изменившаяся длительность: факты по начатым работам
            # остаются на месте, остальное честно отправляем на перераспределение.
            touched.add(route.engineer_id)
            head = kept[:locked_count]
            tail = kept[locked_count:]
            if not state.adopt(head, locked_count, schedule):
                # Недостижимо, пока префикс состоит из фактов, но молча терять заявки нельзя.
                state.adopt([], 0, ())
                orphans.extend(head)
                tail = kept
            for request in tail:
                if not state.insert_checked(request, len(state.stops)):
                    orphans.append(request)

    orphans.sort(key=lambda r: (-r.priority.rank, r.input_order, r.id))
    return solution, orphans, touched


def _visit_schedule(
    ctx: PlanContext, visit
) -> tuple[float, float, float, float, float, float, float]:
    """Фактическое расписание начатого визита в минутах от точки отсчёта расчёта."""
    m = ctx.to_minutes
    return (
        m(visit.departure_at),
        m(visit.arrival_at),
        m(visit.service_start_at),
        m(visit.service_end_at),
        visit.waiting_minutes,
        visit.travel_minutes,
        visit.distance_km,
    )


# --------------------------------------------------------------------------------------
# Разница планов
# --------------------------------------------------------------------------------------


def _route_signature(route) -> tuple:
    """Отпечаток маршрута для сравнения планов.

    Включает и окончание работ: при отказе клиента на адресе визит остаётся на месте
    с тем же началом, но занимает меньше времени. Без `service_end_at` такой маршрут
    попал бы в «не изменились», хотя расписание у инженера изменилось.
    """
    return tuple(
        (v.request_id, v.position, v.service_start_at.isoformat(), v.service_end_at.isoformat())
        for v in route.visits
    )


def build_diff(previous: PlanResult, current: PlanResult, event) -> PlanDiff:
    before = {r.engineer_id: _route_signature(r) for r in previous.routes}
    after = {r.engineer_id: _route_signature(r) for r in current.routes}

    changed = sorted(
        engineer_id
        for engineer_id in set(before) | set(after)
        if before.get(engineer_id) != after.get(engineer_id) and engineer_id in after
    )
    removed = sorted(engineer_id for engineer_id in before if engineer_id not in after)
    unchanged = sorted(
        engineer_id
        for engineer_id in before
        if engineer_id in after and before[engineer_id] == after[engineer_id]
    )

    prev_assignment = {a.request_id: a for a in previous.assignments}
    changed_requests: list[str] = []
    newly_assigned: list[str] = []
    newly_unassigned: list[str] = []

    for assignment in current.assignments:
        old = prev_assignment.get(assignment.request_id)
        if old is None:
            if assignment.is_assigned:
                newly_assigned.append(assignment.request_id)
            else:
                newly_unassigned.append(assignment.request_id)
            changed_requests.append(assignment.request_id)
            continue
        if old.engineer_id != assignment.engineer_id or old.status is not assignment.status:
            changed_requests.append(assignment.request_id)
            if assignment.is_assigned and not old.is_assigned:
                newly_assigned.append(assignment.request_id)
            if not assignment.is_assigned and old.is_assigned:
                newly_unassigned.append(assignment.request_id)
        elif old.service_start_at != assignment.service_start_at:
            changed_requests.append(assignment.request_id)

    diff = PlanDiff(
        previous_plan_id=previous.plan_id,
        event_type=event.type,
        changed_request_ids=tuple(sorted(set(changed_requests))),
        changed_route_engineer_ids=tuple(changed),
        removed_route_engineer_ids=tuple(removed),
        newly_assigned_request_ids=tuple(sorted(set(newly_assigned))),
        newly_unassigned_request_ids=tuple(sorted(set(newly_unassigned))),
        unchanged_route_engineer_ids=tuple(unchanged),
    )
    summary = explain_replan(event.type, diff, len(previous.routes))
    return _replace(diff, summary=summary)

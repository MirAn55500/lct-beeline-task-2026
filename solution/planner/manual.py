"""Ручное вмешательство диспетчера в готовый план.

Требование базы знаний (Should have): «вручную переназначать заявку другому инженеру —
чтобы учесть обстоятельства, отсутствующие в системе». Алгоритм видит навыки, окна и
километры; он не знает, что на этом адресе злая собака, а с этим клиентом умеет
разговаривать только Петров.

Принцип: ручное решение **не обходит жёсткие ограничения**. Диспетчер вправе выбрать
исполнителя, но не вправе назначить работу тому, у кого нет навыка, или воткнуть визит
так, что развалится остаток дня. Если ход недопустим, план остаётся прежним, а диспетчер
получает внятное объяснение, почему — это честнее, чем принять ход и молча выдать
невыполнимое расписание.
"""

from __future__ import annotations

import time as _time
from dataclasses import replace as _replace

from .context import PlanContext
from .enums import Algorithm, AssignmentStatus, EventType, ReasonCode
from .feasibility import check_static
from .models import Scenario
from .replan import build_diff, seed_from_previous
from .result import PlanDiff, PlanResult
from .solver import build_result
from .travel import TravelModel

__all__ = ["reassign"]


class _ManualEvent:
    """Минимальная заглушка события: `build_diff` берёт из него только тип."""

    type = EventType.URGENT_REQUEST
    at = None


def reassign(
    previous: PlanResult,
    scenario: Scenario,
    request_id: str,
    engineer_id: str | None,
    position: int | None = None,
    *,
    travel: TravelModel | None = None,
    plan_id: str | None = None,
) -> PlanResult:
    """Переносит заявку к выбранному исполнителю либо снимает её с исполнителя.

    `engineer_id=None` снимает заявку с маршрута и оставляет неназначенной.
    `position` — желаемое место в маршруте, нумерация с 1; `None` означает «поставить
    туда, где это обойдётся дешевле всего».

    Если перенос недопустим, возвращается **прежний план** с добавленным предупреждением:
    состав назначений не меняется, `diff` пустой.
    """
    started = _time.monotonic()
    request = scenario.request_by_id.get(request_id)
    if request is None:
        return _refuse(previous, f"Заявки {request_id} нет во входных данных")

    ctx = PlanContext(scenario, travel)
    solution, orphans, touched = seed_from_previous(ctx, previous, None)

    current = solution.route_of(request_id)
    if current is not None:
        if current.index_of(request_id) < current.locked_count:
            return _refuse(
                previous, f"Заявка {request_id} уже начата в работу и не может быть перенесена"
            )
        current.remove_request(request_id)
        touched.add(current.engineer.id)

    # --- снятие с исполнителя ---
    if engineer_id is None:
        solution.mark_unassigned(request, ReasonCode.NOT_FOUND, [])
        result = _finish(ctx, solution, previous, started, plan_id)
        return _override_explanation(
            result,
            request_id,
            f"Заявка {request_id} снята с исполнителя вручную диспетчером "
            f"и ожидает нового назначения.",
        )

    # --- перенос к выбранному исполнителю ---
    target = solution.routes.get(engineer_id)
    if target is None:
        return _refuse(previous, f"Инженер {engineer_id} не участвует в расчёте")

    static = check_static(target.engineer, request, ctx.settings)
    if not static.ok:
        return _refuse(
            previous,
            f"Заявку {request_id} нельзя назначить на {target.engineer.name}: {static.detail}",
        )

    placed = False
    if position is not None:
        placed = target.insert_checked(request, max(0, position - 1))
        if not placed:
            return _refuse(
                previous,
                f"Заявка {request_id} не помещается на позицию {position} в маршруте "
                f"{target.engineer.name}: нарушаются окна или смена",
            )
    else:
        best = target.best_insertion(request)
        placed = best is not None and target.insert_checked(request, best[1])
        if not placed:
            return _refuse(
                previous,
                f"У {target.engineer.name} нет ни одного места, куда заявка {request_id} "
                f"помещается без нарушения окон и смены",
            )

    solution.clear_unassigned(request_id)
    touched.add(engineer_id)

    # Заявки, осиротевшие при восстановлении плана, не должны потеряться из-за ручного хода.
    if orphans:
        from .construct import insert_regret

        insert_regret(ctx, solution, orphans)

    return _finish(ctx, solution, previous, started, plan_id)


# --------------------------------------------------------------------------------------


def _finish(
    ctx: PlanContext,
    solution,
    previous: PlanResult,
    started: float,
    plan_id: str | None,
) -> PlanResult:
    result = build_result(
        ctx,
        solution,
        Algorithm.OPTIMIZED,
        warnings=tuple(ctx.scenario.validate()),
        elapsed_ms=(_time.monotonic() - started) * 1000.0,
        plan_id=plan_id,
    )
    diff = build_diff(previous, result, _ManualEvent())
    diff = _replace(
        diff,
        summary="Ручное переназначение диспетчером. "
        + (diff.summary.split(". ", 1)[1] if ". " in diff.summary else diff.summary),
    )
    return _replace(result, diff=diff)


def _refuse(previous: PlanResult, reason: str) -> PlanResult:
    """План остаётся прежним; отказ виден диспетчеру в предупреждениях."""
    return _replace(
        previous,
        warnings=previous.warnings + (f"Ручное переназначение отклонено: {reason}",),
        diff=PlanDiff(
            previous_plan_id=previous.plan_id,
            event_type=EventType.URGENT_REQUEST,
            unchanged_route_engineer_ids=tuple(r.engineer_id for r in previous.routes),
            summary=f"Ручное переназначение отклонено: {reason}. План не изменён.",
        ),
    )


def _override_explanation(result: PlanResult, request_id: str, text: str) -> PlanResult:
    assignments = tuple(
        _replace(a, explanation=text)
        if a.request_id == request_id and a.status is AssignmentStatus.UNASSIGNED
        else a
        for a in result.assignments
    )
    return _replace(result, assignments=assignments)

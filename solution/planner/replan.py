"""Событийное перепланирование: инкрементальный ремонт вместо пересчёта с нуля.

Требование ТЗ — новый план за считанные минуты и наглядный показ того, **что именно
изменилось**. Пересчёт «с чистого листа» формально удовлетворяет первому и полностью
проваливает второе: диспетчер видит, что перетасовался весь день, и не может понять,
это следствие события или случайность эвристики.

Поэтому все четыре сценария работают по общему каркасу:

    заморозить прошлое → применить событие → починить только затронутое → показать разницу

**Заморозка** — ключевой инвариант: назначение, работа по которому началась до момента
события, не меняется ни по исполнителю, ни по времени. Такие визиты остаются в начале
маршрута как `locked`, и ни один оператор поиска не имеет права их тронуть. Замораживается
и визит, к которому инженер **уже выехал**: развернуть человека на середине дороги можно
только на бумаге.

Ремонт идёт по трём ступеням, от самой дешёвой к самой дорогой, и каждая следующая
включается, только если предыдущая не справилась:

    1. точечная вставка          свободное окно существующих маршрутов, никого не двигая
    2. локальное вытеснение      маршрут одного инженера: до `ejection_depth` заявок меньшего приоритета
    3. пересчёт остатка дня      все маршруты: начатое заморожено, остальное раскладывается заново

`Settings.replan_scope` задаёт **потолок** этой лестницы — «степень изменения плана»
низкая / средняя / высокая. Снизу она начинается всегда: даже при высокой степени
сначала пробуется вставка в свободное окно, и только потом всё остальное.

Третья ступень применяется **только если она лучше** по `quality_key()`, а при равном
качестве выигрывает вариант, который меняет меньше маршрутов. Иначе страховка, задуманная
как последний шанс для аварии, перетряхивала бы день там, где хватило одной вставки.

**Статусы исполнения** (`VISIT_ARRIVED`, `VISIT_COMPLETED`) состав заявок не меняют — они
приносят факт: инженер на месте в 10:05, работы закончены в 11:40. Факт подставляется в
замороженный префикс маршрута вместо планового расписания, и остаток дня считается уже от
него. Отсутствие статуса — не новость: по договорённости с диспетчером «нет сообщения»
значит «идёт по плану», поэтому молчание ничего не двигает.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass as _dataclass
from dataclasses import replace as _replace
from datetime import datetime
from typing import Mapping, Sequence

from .construct import (
    insert_regret,
    place_single,
    place_with_ejection,
    reclaim_emergencies,
)
from .context import PlanContext
from .enums import Algorithm, EventType, Priority, ReasonCode, ReplanScope
from .explain import explain_replan
from .improve import local_search
from .models import Engineer, Request, Scenario, WorkInterval
from .result import PlanDiff, PlanResult
from .solution import Solution
from .solver import build_result
from .travel import TravelModel

__all__ = ["replan", "rebuild_unstarted", "apply_event", "seed_from_previous", "build_diff"]

_EPS_MINUTES = 1e-6
_SECOND_MINUTES = 1 / 60
"""Времена в БД хранятся с разной точностью (обеды — до секунды): расхождение в секунду — не противоречие."""


def replan(
    previous: PlanResult,
    scenario: Scenario,
    event,
    *,
    travel: TravelModel | None = None,
    plan_id: str | None = None,
    scope: ReplanScope | str | None = None,
) -> PlanResult:
    """Перестраивает план после одного события. Возвращает новый план с `diff`.

    `scope` — степень изменения плана на этот конкретный вызов; `None` означает значение
    из настроек сценария. Это и есть кнопка «перестроить сильнее»: первый прогон с низкой
    степенью, и если заявку сохранить не удалось — повторный с высокой, уже осознанно
    соглашаясь на переставленный день.
    """
    started = _time.monotonic()

    new_scenario, extra_warnings = apply_event(scenario, previous, event)
    ctx = PlanContext(new_scenario, travel)
    settings = new_scenario.settings
    allowed = ReplanScope(scope if scope is not None else settings.replan_scope)
    limit = max(0.1, settings.time_limit_seconds)
    deadline = started + limit
    # Пересчёт остатка дня — полноценный расчёт, а не точечная вставка, поэтому его доля
    # лимита резервируется заранее: иначе дешёвые ступени успевают съесть весь бюджет,
    # и страховка не запускается вовсе.
    reserve = min(0.9, max(0.0, settings.global_replan_time_share))
    cheap_deadline = started + limit * (1.0 - reserve)

    # Инженер, выбывший «на ходу», единственный, кого можно развернуть с дороги: он
    # недоступен, и ехать ему больше некуда. У остальных выезд — такой же факт, как работа.
    aborted = (
        event.engineer_id if event.type is EventType.ENGINEER_UNAVAILABLE else None
    )
    # Заявка, переобъявленная аварией: её прежний визит восстанавливать нельзя, иначе
    # рядом с ним встанет второй, уже по новым координатам и нормативу.
    redeclared = (
        frozenset({event.request.id})
        if event.type is EventType.URGENT_REQUEST
        else frozenset()
    )
    facts = _facts_from_event(event, previous)
    # Факт исполнения подставляется в замороженный префикс: с этого момента остаток дня
    # считается от того, что произошло, а не от того, что планировалось.
    solution, orphans, touched = seed_from_previous(
        ctx,
        previous,
        event.at,
        aborted_engineer_id=aborted,
        facts=facts,
        not_before=event.at,
        drop_ids=redeclared,
    )

    urgent_request = None
    if event.type is EventType.URGENT_REQUEST:
        urgent_request = new_scenario.request_by_id.get(event.request.id)
        if urgent_request is not None and urgent_request.id in solution.assigned_ids():
            # Визит остался в маршруте, значит он заморожен, а событие отклонено
            # (`apply_event` уже сказал об этом диспетчеру). Ставить второй раз нечего.
            urgent_request = None

    if urgent_request is not None:
        # Ступень 1 — точечная вставка, ступень 2 — локальное вытеснение.
        placed = place_single(ctx, solution, urgent_request)
        if placed is None and allowed.allows_ejection:
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

    # Пул собирается ПОСЛЕ размещения аварии: вытеснение второй ступени само добавляет
    # в него заявки, и собранный заранее список прошёл бы мимо них.
    pool = _pending_pool(ctx, solution, orphans, previous)
    if pool:
        insert_regret(ctx, solution, pool, deadline=cheap_deadline)
        for request in pool:
            route = solution.route_of(request.id)
            if route is not None:
                touched.add(route.engineer.id)

    # Ступень 2 для всех, кого событие выбило из плана: затянувшаяся работа или выбывший
    # инженер оставляют без исполнителя обычные заявки, а не только аварии.
    if allowed.allows_ejection:
        _reclaim_displaced(ctx, solution, previous, touched)

    # Перестановки внутри затронутых маршрутов — тоже часть второй ступени: при низкой
    # степени изменения план остаётся как был, даже ценой чуть более длинной дороги.
    if settings.stabilize_after_replan and touched and allowed.allows_ejection:
        local_search(ctx, solution, deadline=cheap_deadline, routes_filter=set(touched))

    # Ступень 3 — пересчёт остатка дня. Дорогая и заметная диспетчеру, поэтому только
    # после провала двух дешёвых ступеней и только если результат действительно лучше.
    if (
        allowed.allows_rebuild
        and _global_rebuild_applies(event)
        and _cheap_repair_failed(solution, previous, urgent_request)
    ):
        rebuilt = _rebuild_remainder(
            ctx,
            previous,
            event,
            extra=[r for r in (urgent_request,) if r is not None],
            deadline=deadline,
            aborted_engineer_id=aborted,
            drop_ids=redeclared,
        )
        if _prefer_rebuilt(rebuilt, solution, previous):
            solution = rebuilt

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
    return _replace(result, diff=diff, not_before=event.at)


# --------------------------------------------------------------------------------------
# Ступень 3: пересчёт остатка дня
# --------------------------------------------------------------------------------------


@_dataclass(frozen=True, slots=True)
class _VisitFact:
    """Что известно о визите по статусам: когда приехали и когда закончили."""

    arrived_at: datetime | None = None
    completed_at: datetime | None = None


def _facts_from_event(event, previous: PlanResult) -> dict[str, _VisitFact]:
    """Факты исполнения, которые принесло событие. Для остальных событий — пусто."""
    target = getattr(event, "target_request_id", None)
    if target is None:
        return {}
    if event.type is EventType.VISIT_ARRIVED:
        return {target: _VisitFact(arrived_at=event.at)}
    if event.type is EventType.VISIT_COMPLETED:
        return {target: _VisitFact(completed_at=event.at)}
    if event.type in (EventType.CLIENT_REFUSAL, EventType.CANCEL_REQUEST):
        # Снятие работы по визиту, который уже свершился, — тоже факт окончания: работа на
        # этом адресе закончена, сколько бы ни было записано в нормативе. Без него
        # замороженный визит держал плановое `service_end_at`, и освободившийся хвост дня
        # не двигался. Отмена и отказ здесь неразличимы: оба снимают работу с уже
        # состоявшегося визита, и оба обязаны сохранить адрес, с которого ехать дальше.
        if not _is_committed(previous, target, event.at):
            # Инженер ещё не выехал: при отказе визит не заморожен и пересчитывается
            # обычным путём с нулевым нормативом, при отмене заявки в сценарии уже нет.
            return {}
        visit = previous.visit_of(target)
        # Посреди работы окончание — момент события. В дороге работа не начиналась вовсе,
        # поэтому заканчивается там же, где по плану начиналась: поездку событие не
        # отменяет. После планового окончания визит засчитан целиком.
        return {target: _VisitFact(completed_at=_removal_moment(visit, event.at))}
    return {}


def _pending_pool(
    ctx: PlanContext,
    solution: Solution,
    orphans: Sequence[Request],
    previous: PlanResult,
) -> list[Request]:
    """Всё, что сейчас без исполнителя: осиротевшие, вытесненные и ранее неназначенные."""
    assigned = solution.assigned_ids()
    pool: list[Request] = []
    seen: set[str] = set()
    for source in (list(orphans), list(solution.unassigned.values())):
        for request in source:
            if request.id in assigned or request.id in seen:
                continue
            pool.append(request)
            seen.add(request.id)
    for assignment in previous.unassigned:
        request = ctx.scenario.request_by_id.get(assignment.request_id)
        if request is None or request.id in assigned or request.id in seen:
            continue
        pool.append(request)
        seen.add(request.id)
    pool.sort(key=lambda r: (-r.priority.rank, r.input_order, r.id))
    return pool


def _global_rebuild_applies(event) -> bool:
    """Где ступень вообще уместна.

    Авария конкурирует за место со всем остатком дня; выбывший инженер заставляет этот
    остаток пересобрать по той же причине; затянувшаяся работа — тоже: сдвинутый хвост
    выбивает заявки из окон, и им нужен новый исполнитель, а не отказ. Отмена и отказ
    клиента только освобождают время — пересчитывать там нечего.
    """
    return event.type in (
        EventType.URGENT_REQUEST,
        EventType.ENGINEER_UNAVAILABLE,
        EventType.VISIT_ARRIVED,
        EventType.VISIT_COMPLETED,
    )


def _was_assigned(previous: PlanResult, request_id: str) -> bool:
    """Была ли заявка назначена в предыдущем плане."""
    assignment = previous.assignment_of(request_id)
    return assignment is not None and assignment.is_assigned


def _cheap_repair_failed(
    solution: Solution, previous: PlanResult, urgent: Request | None
) -> bool:
    """Осталось ли после дешёвых ступеней то, что раньше исполнялось, а теперь нет."""
    if urgent is not None and urgent.id in solution.unassigned:
        return True
    return any(_was_assigned(previous, request_id) for request_id in solution.unassigned)


def _reclaim_displaced(
    ctx: PlanContext, solution: Solution, previous: PlanResult, touched: set[str]
) -> None:
    """Вторая ступень для заявок, которые событие выбило из плана.

    Свободного окна для них не нашлось (это уже пробовала первая ступень), поэтому
    пробуем подвинуть работы внутри одного маршрута: вытеснить менее приоритетную и
    пристроить её заново. Аварии обрабатываются здесь же — им место важнее всего.

    Заявки, которые были без исполнителя и **до** события, не трогаются: событие их
    положение не ухудшило, а перетряхивать из-за них чужие маршруты — не его дело.
    """
    pending = [
        request
        for request in sorted(
            solution.unassigned.values(),
            key=lambda r: (-r.priority.rank, r.input_order, r.id),
        )
        if request.priority is Priority.EMERGENCY or _was_assigned(previous, request.id)
    ]
    for request in pending:
        if request.id not in solution.unassigned:
            continue
        found = place_with_ejection(ctx, solution, request, touched=touched)
        if found is not None:
            touched.add(found[0].engineer.id)


def _rebuild_remainder(
    ctx: PlanContext,
    previous: PlanResult,
    event,
    *,
    extra: Sequence[Request],
    deadline: float,
    aborted_engineer_id: str | None,
    drop_ids: frozenset[str] | set[str] = frozenset(),
) -> Solution:
    """Снимает у всех инженеров всё неначатое и раскладывает заново вместе с событием.

    Замороженные префиксы остаются на месте: позиции ниже `locked_count` недоступны ни
    вставке, ни локальному поиску. Пул — снятые хвосты, ранее неназначенные и новая
    авария; `insert_regret` сортирует по приоритету, поэтому авария рассматривается
    первой и получает бесконечное сожаление, если исполнитель у неё один.
    """
    solution, pool, _ = seed_from_previous(
        ctx,
        previous,
        event.at,
        keep_tail=False,
        aborted_engineer_id=aborted_engineer_id,
        facts=_facts_from_event(event, previous),
        not_before=event.at,
        drop_ids=drop_ids,
    )
    known = solution.assigned_ids() | {r.id for r in pool}
    for source in (
        [ctx.scenario.request_by_id.get(a.request_id) for a in previous.unassigned],
        list(extra),
    ):
        for request in source:
            if request is None or request.id in known:
                continue
            pool.append(request)
            known.add(request.id)

    pool.sort(key=lambda r: (-r.priority.rank, r.input_order, r.id))
    insert_regret(ctx, solution, pool, deadline=deadline)
    reclaim_emergencies(ctx, solution)
    if ctx.settings.enable_local_search:
        local_search(ctx, solution, deadline=deadline)
    return solution


def _changed_route_count(previous: PlanResult, solution: Solution) -> int:
    """Сколько маршрутов решение переписывает относительно прошлого плана."""
    before = {
        route.engineer_id: tuple(v.request_id for v in route.visits)
        for route in previous.routes
    }
    after = {
        engineer_id: route.request_ids
        for engineer_id, route in solution.routes.items()
        if route.stops
    }
    return sum(
        1
        for engineer_id in set(before) | set(after)
        if before.get(engineer_id, ()) != after.get(engineer_id, ())
    )


def _prefer_rebuilt(
    rebuilt: Solution, incremental: Solution, previous: PlanResult
) -> bool:
    """Правило приёмки: пересчёт применяется, только если он лучше.

    Сравнение идёт по `quality_key()` — тому же порядку, что и везде в планировщике
    (авария → подключение → объём → люди → время в пути → пробег). При равном качестве
    побеждает стабильность: вариант, который меняет меньше маршрутов. Без этого ступень,
    задуманная как страховка, переставляла бы день ради нулевого выигрыша.
    """
    left, right = rebuilt.quality_key(), incremental.quality_key()
    if left != right:
        return left < right
    return _changed_route_count(previous, rebuilt) < _changed_route_count(
        previous, incremental
    )


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
        known = new_request.id in {r.id for r in requests}
        if known and _is_committed(previous, new_request.id, event.at):
            # Работа по этой заявке уже идёт (или инженер к ней выехал). Подменить её
            # новым объектом нельзя: замороженный визит хранит расписание и пробег до
            # СТАРОГО адреса, и после подмены карта разошлась бы с фактом поездки.
            # Переобъявление отклоняется целиком — это честнее молчаливой рассинхронизации.
            warnings.append(
                f"Аварийная заявка {new_request.id} совпала по номеру с уже начатой "
                f"заявкой: работа по ней идёт, событие не применено. "
                f"Подайте аварию под новым номером"
            )
        else:
            if known:
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
        visit = previous.visit_of(target)
        if visit is not None and _is_committed(previous, target, event.at):
            # Отмена не отменяет ни дорогу, ни уже потраченное время. Убрать такую
            # заявку из сценария — значит стереть точку, в которой инженер сейчас
            # стоит: остаток дня поедет из офиса, накрутив пробег, которого не будет.
            # Верификатор это пропускает, потому что считает по тому же усечённому
            # сценарию. Поэтому визит остаётся фактом — ровно как при отказе клиента, —
            # а норматив урезается до отработанного.
            spent = _minutes_worked(
                scenario, previous, target, _removal_moment(visit, event.at)
            )
            requests = [
                _replace(r, duration_minutes=max(0, int(round(spent)))) if r.id == target else r
                for r in requests
            ]
            if visit.service_end_at <= event.at:
                what = "работа уже выполнена, отменять нечего"
            elif visit.service_start_at < event.at:
                what = f"работа уже шла, засчитано {int(round(spent))} мин"
            else:
                what = "инженер уже в пути, поездка сохранена, работа не засчитана"
            warnings.append(
                f"Отмена заявки {target}: {what}; визит остаётся в маршруте "
                f"как состоявшийся, дальше маршрут идёт с её адреса"
            )
        else:
            requests = [r for r in requests if r.id != target]

    elif event.type is EventType.CLIENT_REFUSAL:
        target = event.target_request_id
        if target not in {r.id for r in requests}:
            # Молчать нельзя ровно по той же причине, что и при отмене: диспетчер думает,
            # что снял работу, а событие не нашло к чему примениться.
            warnings.append(
                f"Отказ клиента по заявке {target}: её нет во входных данных"
            )
        updated: list[Request] = []
        for request in requests:
            if request.id != target:
                updated.append(request)
                continue
            visit = previous.visit_of(request.id)
            moment = event.at if visit is None else _removal_moment(visit, event.at)
            spent = _minutes_worked(scenario, previous, request.id, moment)
            updated.append(_replace(request, duration_minutes=max(0, int(round(spent)))))
            warnings.append(
                f"Заявка {target}: отказ клиента на адресе — поездка сохранена, "
                f"работа не засчитана, освободилось время в маршруте"
            )
        requests = updated

    elif event.type is EventType.VISIT_ARRIVED:
        target = event.target_request_id
        assignment = previous.assignment_of(target)
        if assignment is None or not assignment.is_assigned:
            warnings.append(
                f"Статус «инженер на месте» по заявке {target}: её нет ни в одном маршруте"
            )
        else:
            planned = assignment.arrival_at
            delta = 0.0 if planned is None else (event.at - planned).total_seconds() / 60.0
            if abs(delta) >= 1.0:
                warnings.append(
                    f"Заявка {target}: инженер на месте в {event.at:%H:%M}, "
                    f"на {abs(delta):.0f} мин {'позже' if delta > 0 else 'раньше'} плана — "
                    f"остаток маршрута пересчитан от факта"
                )
            warnings += _out_of_shift_note(
                scenario, assignment, event.at, "инженер на месте"
            )

    elif event.type is EventType.VISIT_COMPLETED:
        target = event.target_request_id
        assignment = previous.assignment_of(target)
        if assignment is None or not assignment.is_assigned:
            warnings.append(
                f"Статус «работы завершены» по заявке {target}: её нет ни в одном маршруте"
            )
        else:
            actual = _minutes_worked(scenario, previous, target, event.at)
            updated = []
            for request in requests:
                if request.id != target:
                    updated.append(request)
                    continue
                delta = actual - request.duration_minutes
                updated.append(_replace(request, duration_minutes=max(0, int(round(actual)))))
                if delta >= 1.0:
                    warnings.append(
                        f"Заявка {target}: работа заняла на {delta:.0f} мин больше норматива "
                        f"({request.duration_minutes} мин) — остаток маршрута сдвинут вперёд"
                    )
                elif delta <= -1.0:
                    warnings.append(
                        f"Заявка {target}: работа закончена на {abs(delta):.0f} мин раньше "
                        f"норматива — в маршруте освободилось время"
                    )
            requests = updated
            if assignment.arrival_at is not None and event.at < assignment.arrival_at:
                # Работы не могли завершиться раньше, чем инженер доехал. Расписание
                # сохраняет поездку (её отменять не за что), но противоречие в журнале
                # молчать не должно — это либо опечатка в статусе, либо чужой визит.
                warnings.append(
                    f"Заявка {target}: работы завершены в {event.at:%H:%M}, "
                    f"до планового прибытия в {assignment.arrival_at:%H:%M} — "
                    f"поездка сохранена, работа не засчитана"
                )
            warnings += _out_of_shift_note(
                scenario, assignment, event.at, "работы завершены"
            )

    elif event.type is EventType.ENGINEER_UNAVAILABLE:
        if event.engineer_id not in {e.id for e in engineers}:
            # Иначе смена никого не задевает, а `diff.summary` всё равно рапортует
            # «Инженер стал недоступен» — журнал расходится с тем, что произошло.
            warnings.append(
                f"Выбытие инженера {event.engineer_id}: его нет во входных данных"
            )
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


def _out_of_shift_note(
    scenario: Scenario, assignment, moment: datetime, what: str
) -> list[str]:
    """Предупреждение, если сообщённый факт пришёлся на нерабочее время исполнителя.

    Факт не подделывают: если инженер доложил о приезде в 19:00 при смене до 18:00,
    в плане так и будет — работа за границей графика. Но `validate_plan` на locked-визитах
    расписание не пересчитывает и об этом промолчит, поэтому сказать диспетчеру должно
    само событие: иначе ночная работа обнаруживается только глазами по карте.

    Три случая различаются, потому что означают разное. До смены и после смены — работа
    вне графика. Перерыв — не то же самое: смена не кончилась, работа просто начнётся
    после обеда, и говорить здесь про «выходит за пределы смены» значило бы пугать
    диспетчера там, где всё в порядке.
    """
    engineer = scenario.engineer_by_id.get(assignment.engineer_id or "")
    if engineer is None or not engineer.work_intervals:
        return []
    intervals = sorted(engineer.work_intervals, key=lambda i: i.start)
    if any(i.start <= moment <= i.end for i in intervals):
        return []

    head = f"Заявка {assignment.request_id}: статус «{what}» в {moment:%H:%M} — "
    shift_start, shift_end = intervals[0].start, intervals[-1].end
    if moment < shift_start:
        tail = (
            f"{engineer.name} ещё не вышел на смену (смена с {shift_start:%H:%M}); "
            f"работа выходит за пределы смены"
        )
    elif moment > shift_end:
        tail = (
            f"вне графика {engineer.name} (смена до {shift_end:%H:%M}); "
            f"работа выходит за пределы смены"
        )
    else:
        resumes = min(i.start for i in intervals if i.start > moment)
        tail = (
            f"{engineer.name} в перерыве; работа продолжится в {resumes:%H:%M}"
        )
    return [head + tail]


def _minutes_worked(
    scenario: Scenario, previous: PlanResult, request_id: str, moment: datetime
) -> float:
    """Сколько РАБОЧИХ минут заняла работа к указанному моменту.

    Считается по графику исполнителя, а не по часам на стене: обед посреди работы —
    не работа. Иначе заявка, которую прервал перерыв, получала бы длительность на час
    больше фактической, и остаток дня уезжал бы вправо без всякой причины.
    """
    assignment = previous.assignment_of(request_id)
    if assignment is None or assignment.service_start_at is None:
        return 0.0
    start = assignment.service_start_at
    if moment <= start:
        return 0.0
    engineer = scenario.engineer_by_id.get(assignment.engineer_id or "")
    if engineer is None:
        return (moment - start).total_seconds() / 60.0
    return _working_minutes(engineer.work_intervals, start, moment)


def _working_minutes(
    intervals: Sequence[WorkInterval], start: datetime, end: datetime
) -> float:
    """Пересечение отрезка [start, end] с рабочими интервалами, в минутах."""
    total = 0.0
    for interval in intervals:
        low = max(interval.start, start)
        high = min(interval.end, end)
        if high > low:
            total += (high - low).total_seconds() / 60.0
    return total


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


def rebuild_unstarted(
    previous: PlanResult,
    scenario: Scenario,
    at: datetime,
    *,
    travel: TravelModel | None = None,
    plan_id: str | None = None,
) -> PlanResult:
    """Пересчёт дня, который не трогает начатое: «Свободный» пересчёт посреди смены.

    Визиты, к которым инженер выехал до `at`, остаются на своих местах и со своим
    расписанием. Всё неначатое снимается и вместе с заявками без исполнителя (и новыми,
    которых в прошлом плане не было) раскладывается заново, не раньше `at`. Это та же
    третья ступень, что и при событии, только без самого события.
    """
    started = _time.monotonic()
    ctx = PlanContext(scenario, travel)
    deadline = started + max(0.1, scenario.settings.time_limit_seconds)
    solution, pool, _ = seed_from_previous(
        ctx, previous, at, keep_tail=False, not_before=at
    )
    known = solution.assigned_ids() | {r.id for r in pool}
    for request in scenario.planning_requests():
        if request.id not in known:
            pool.append(request)
            known.add(request.id)
    pool.sort(key=lambda r: (-r.priority.rank, r.input_order, r.id))
    insert_regret(ctx, solution, pool, deadline=deadline)
    reclaim_emergencies(ctx, solution)
    if scenario.settings.enable_local_search:
        local_search(ctx, solution, deadline=deadline)
    result = build_result(
        ctx,
        solution,
        Algorithm.OPTIMIZED,
        warnings=tuple(scenario.validate()),
        elapsed_ms=(_time.monotonic() - started) * 1000.0,
        plan_id=plan_id,
    )
    return _replace(result, not_before=at)


def seed_from_previous(
    ctx: PlanContext,
    previous: PlanResult,
    frozen_before: datetime | None,
    *,
    keep_tail: bool = True,
    aborted_engineer_id: str | None = None,
    facts: Mapping[str, "_VisitFact"] | None = None,
    not_before: datetime | None = None,
    drop_ids: frozenset[str] | set[str] = frozenset(),
) -> tuple[Solution, list[Request], set[str]]:
    """Восстанавливает маршруты прошлого плана и помечает начатые визиты как замороженные.

    `frozen_before` — момент события: визиты, к которым инженер уже выехал, трогать
    нельзя. `None` означает, что замораживать нечего (ручное вмешательство диспетчера
    вне контекста события).

    `keep_tail=False` оставляет от каждого маршрута только замороженный префикс, а весь
    неначатый хвост возвращает в пул — это вход третьей ступени перепланирования.

    `aborted_engineer_id` — инженер, выбывший по событию: его поездка прервана, поэтому
    визит, до которого он не доехал, замораживать нельзя, иначе план оставит работу
    человеку, которого в смене уже нет.

    `facts` — статусы исполнения по визитам. Факт всегда сильнее плана: визит с фактом
    замораживается вместе со всем, что стоит в маршруте до него, и в расписание идут
    фактические времена, а не те, что насчитал предыдущий прогон.

    `not_before` — «сейчас»: ни одна работа, которая ещё не началась, не может быть
    назначена раньше этого момента. Без этого ремонт спокойно отправлял вытесненную
    заявку в утро инженера, у которого день начинался позже события, — расписание
    получалось задним числом и при этом формально корректным.

    `drop_ids` — заявки, которые событие переобъявило заново. Их незамороженный визит
    не восстанавливается и в осиротевшие не попадает: вызывающий ставит новую версию
    сам. Без этого старый визит оставался в маршруте, а новая версия вставлялась рядом,
    и одна заявка получала два выезда.
    """
    solution = Solution(ctx)
    if not_before is not None:
        floor = ctx.to_minutes(not_before)
        for state in solution.routes.values():
            state.floor_m = floor
    by_id = ctx.scenario.request_by_id
    orphans: list[Request] = []
    touched: set[str] = set()

    # Начатый обед инженера без заявок — факт и в новом плане
    for engineer_id, idle in previous.idle_lunches:
        state = solution.routes.get(engineer_id)
        fact = _lunch_fact(ctx, idle, frozen_before)
        if state is not None and state.lunch is not None and fact is not None:
            state.adopt([], 0, (), fact)

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
        # Всё, что стоит в маршруте до визита с фактом, тоже стало прошлым: инженер не
        # мог доложить о третьей заявке, не сделав первые две.
        confirmed_upto = -1
        if facts:
            for index, visit in enumerate(route.visits):
                if visit.request_id in facts:
                    confirmed_upto = max(confirmed_upto, index)
        # Момент, когда инженер освободился по последнему замороженному визиту. Факт может
        # оказаться позже плана, и тогда «следующая работа началась в 11:00» — уже не факт,
        # а опровергнутое допущение: в 11:00 человек ещё работал на предыдущем адресе.
        frozen_cursor: float | None = None
        for index, visit in enumerate(route.visits):
            request = by_id.get(visit.request_id)
            if request is None:
                touched.add(route.engineer_id)
                continue  # заявка снята событием
            # Признак `locked` уже проставлен в предыдущем плане и обязан переживать любое
            # восстановление: работа, которая началась, не перестаёт быть начатой оттого,
            # что вызывающий не передал момент времени. Без этого ручное переназначение
            # уводило визит, по которому инженер уже работает.
            frozen = (
                visit.locked
                or index <= confirmed_upto
                or (
                    frozen_before is not None
                    and _already_committed(
                        visit, frozen_before, route.engineer_id, aborted_engineer_id
                    )
                )
            )
            if frozen and len(kept) == locked_count:
                fact = facts.get(visit.request_id) if facts else None
                actual = _visit_schedule(ctx, visit, state.engineer, request, fact)
                started_lunch = _lunch_fact(ctx, route.lunch, frozen_before)
                if (
                    fact is None
                    and started_lunch is not None
                    and actual[2] >= started_lunch[2]
                    and actual[0] < started_lunch[3] - _SECOND_MINUTES
                ):
                    # Визит после начатого обеда, а выезд к нему — раньше конца обеда: пока
                    # инженер обедает, к нему не выехать. Работа не начата, её место — после обеда.
                    touched.add(route.engineer_id)
                elif frozen_cursor is not None and actual[2] < frozen_cursor - _EPS_MINUTES:
                    # Противоречие с фактом: эту работу нельзя считать начатой. Она и всё,
                    # что за ней, возвращаются в расчёт и поедут от фактического времени.
                    touched.add(route.engineer_id)
                else:
                    locked_count += 1
                    if fact is not None:
                        touched.add(route.engineer_id)
                    schedule.append(actual)
                    frozen_cursor = actual[3]
                    kept.append(request)
                    continue
            if request.id in drop_ids:
                # Заявку переобъявило событие, а начаться она не успела: старый визит
                # снимается, новую версию поставит вызывающий.
                touched.add(route.engineer_id)
                continue
            if not keep_tail:
                orphans.append(request)
                touched.add(route.engineer_id)
                continue
            kept.append(request)

        # Начатый обед — такой же факт, как начатая работа: переставлять его нельзя.
        lunch = _lunch_fact(ctx, route.lunch, frozen_before)
        if lunch is not None:
            # По факту инженер уехал на заявку раньше планового конца обеда: обед кончился тогда
            early = [leg[0] for leg in schedule if leg[2] >= lunch[2] and leg[0] < lunch[3]]
            if early:
                end = max(lunch[2], min(early))
                lunch = (lunch[0], lunch[1], lunch[2], end, *lunch[4:])
        if not state.adopt(kept, locked_count, schedule, lunch):
            # Обрезанная смена или изменившаяся длительность: факты по начатым работам
            # остаются на месте, остальное честно отправляем на перераспределение.
            touched.add(route.engineer_id)
            head = kept[:locked_count]
            tail = kept[locked_count:]
            if not state.adopt(head, locked_count, schedule, lunch):
                # Недостижимо, пока префикс состоит из фактов, но молча терять заявки нельзя.
                state.adopt([], 0, ())
                orphans.extend(head)
                tail = kept
            for request in tail:
                if not state.insert_checked(request, len(state.stops)):
                    orphans.append(request)

    orphans.sort(key=lambda r: (-r.priority.rank, r.input_order, r.id))
    return solution, orphans, touched


def _lunch_fact(
    ctx: PlanContext, lunch, frozen_before: datetime | None
) -> tuple[float, float, float, float, float, float, float] | None:
    """Расписание обеда прошлого плана в минутах, если обед уже начался (или выехали на него)."""
    if lunch is None:
        return None
    if not lunch.locked and (frozen_before is None or lunch.departure_at >= frozen_before):
        return None
    m = ctx.to_minutes
    return (
        m(lunch.departure_at),
        m(lunch.arrival_at),
        m(lunch.start_at),
        m(lunch.end_at),
        0.0,
        lunch.travel_minutes,
        lunch.distance_km,
    )


def _already_committed(
    visit, moment: datetime, engineer_id: str, aborted_engineer_id: str | None
) -> bool:
    """Начата ли работа или уже начата поездка к ней на момент события.

    Заморозка только по началу работ оставляла инженера, который выехал, но не доехал,
    «свободным»: точечная вставка ещё могла этого не заметить, а пересчёт остатка дня
    спокойно развернёт человека на другой адрес. Выезд — такой же свершившийся факт,
    как и начатая работа.

    Исключение — инженер, выбывший по событию: его поездка прервана вместе со сменой.
    """
    if visit.service_start_at < moment:
        return True
    if engineer_id == aborted_engineer_id:
        return False
    return visit.departure_at < moment


def _removal_moment(visit, moment: datetime) -> datetime:
    """Момент, которым снятие работы (отмена, отказ) обрезает визит.

    Событие ограничено границами самого визита. Сверху: если работа по плану уже
    закончилась, пришедшая позже отмена засчитывает визит целиком, а не тянет окончание
    к себе — иначе час между окончанием работы и звонком диспетчера превращался в час
    работы, и замороженный хвост дня уезжал вправо. Снизу: до начала работ засчитывать
    нечего, поездка при этом сохраняется.

    К `VISIT_COMPLETED` это не относится: там момент — донесение исполнителя, и он
    вправе разойтись с планом в любую сторону.
    """
    if moment < visit.service_start_at:
        return visit.service_start_at
    if moment > visit.service_end_at:
        return visit.service_end_at
    return moment


def _is_committed(previous: PlanResult, request_id: str, moment: datetime) -> bool:
    """Свершилось ли что-то по заявке к моменту события — по прошлому плану.

    Тонкая обёртка над `_already_committed`, чтобы `apply_event` судил о «прошлом»
    ровно тем же правилом, что и заморозка в `seed_from_previous`: одно расхождение
    здесь — и событие меняет то, что менять уже поздно.
    """
    visit = previous.visit_of(request_id)
    if visit is None:
        return False
    return _already_committed(visit, moment, visit.engineer_id, None)


def _visit_schedule(
    ctx: PlanContext,
    visit,
    engineer: Engineer | None = None,
    request: Request | None = None,
    fact: "_VisitFact | None" = None,
) -> tuple[float, float, float, float, float, float, float]:
    """Расписание замороженного визита в минутах от точки отсчёта расчёта.

    Без факта берётся расписание предыдущего плана — начатая работа не пересчитывается.
    С фактом плановые времена заменяются сообщёнными: приезд и окончание работ известны
    точно, а то, что ещё не произошло, достраивается от них по обычным правилам —
    работа не начинается раньше открытия окна и не идёт в перерыв.
    """
    m = ctx.to_minutes
    departure = m(visit.departure_at)
    arrival = m(visit.arrival_at)
    start = m(visit.service_start_at)
    end = m(visit.service_end_at)
    waiting = visit.waiting_minutes

    if fact is not None and engineer is not None and request is not None:
        cal = ctx.calendar(engineer)
        timing = ctx.timing(request)
        if fact.arrived_at is not None:
            arrival = m(fact.arrived_at)
            departure = min(departure, arrival)
            target = arrival if arrival > timing.service_not_before else timing.service_not_before
            start = cal.first_m(target)
            if start is None:
                start = target
            waiting = cal.working_between_m(arrival, start)
            finished = cal.add_m(start, timing.duration)
            end = finished if finished is not None else start + timing.duration
        if fact.completed_at is not None:
            end = max(start, m(fact.completed_at))

    return (
        departure,
        arrival,
        start,
        end,
        waiting,
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

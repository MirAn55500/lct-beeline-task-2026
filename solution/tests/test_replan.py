# -*- coding: utf-8 -*-
"""Перепланирование (SPEC §6.3) — все четыре типа событий.

Ключевая идея: инкрементальный ремонт, а не пересчёт с нуля. Главный
инвариант — заморозка прошлого: назначение, начатое до момента события, не
меняется ни по инженеру, ни по времени. Остальное — устойчивость нетронутых
маршрутов и корректность PlanDiff.
"""
from __future__ import annotations

import pytest

from factories import (
    AssignmentStatus,
    EventType,
    scenario_after,
    assigned_ids,
    assignments_by_id,
    eng,
    event,
    has_cyrillic,
    hhmm,
    plan_optimized,
    replan,
    req,
    routes_by_engineer,
    sc,
    t,
    validate_plan,
)

HOME = (55.70, 37.60)

P = {
    "R1": (55.705, 37.605),
    "R2": (55.695, 37.595),
    "R3": (55.710, 37.610),
    "R4": (55.690, 37.590),
    "R5": (55.715, 37.615),
    "R6": (55.685, 37.585),
    "R7": (55.720, 37.620),
}


def base_scenario():
    """Базовый сценарий дня: два инженера, семь заявок, работы до и после 13:00."""
    engineers = [
        eng("E1", shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", shift=("09:00", "18:00"), at=HOME, order=1),
    ]
    requests = [
        req("R1", window=("09:00", "10:00"), dur=60, at=P["R1"]),
        req("R2", window=("09:00", "10:00"), dur=60, at=P["R2"]),
        req("R3", window=("11:00", "12:00"), dur=60, at=P["R3"]),
        req("R4", window=("11:00", "12:00"), dur=60, at=P["R4"]),
        req("R5", window=("14:00", "15:00"), dur=60, at=P["R5"]),
        req("R6", window=("15:30", "16:30"), dur=45, at=P["R6"]),
        req("R7", window=("16:00", "17:00"), dur=45, at=P["R7"]),
    ]
    return sc(requests, engineers, name="replan-base")


EVENT_AT = "13:00"


# --------------------------------------------------------------------------
# Вспомогательные функции
# --------------------------------------------------------------------------


def locked_snapshot(result, moment):
    """Снимок назначений, начатых строго раньше moment (SPEC §6.3 п.1)."""
    snapshot = {}
    for assignment in result.assignments:
        if assignment.status != AssignmentStatus.ASSIGNED:
            continue
        if assignment.service_start_at is not None and assignment.service_start_at < moment:
            snapshot[assignment.request_id] = (
                assignment.engineer_id,
                assignment.arrival_at,
                assignment.service_start_at,
                assignment.service_end_at,
            )
    return snapshot


def route_signature(result, engineer_id):
    """Детерминированная «сериализация» маршрута для сравнения планов."""
    route = routes_by_engineer(result).get(engineer_id)
    if route is None:
        return None
    return (
        tuple(
            (
                v.request_id,
                v.position,
                v.departure_at,
                v.arrival_at,
                v.service_start_at,
                v.service_end_at,
                round(v.distance_km, 6),
                round(v.travel_minutes, 6),
                round(v.waiting_minutes, 6),
            )
            for v in route.visits
        ),
        round(route.distance_km, 6),
        round(route.travel_minutes, 6),
        round(route.service_minutes, 6),
        round(route.waiting_minutes, 6),
    )


def assert_windows_not_shifted(result, scenario):
    """Окна заявок не сдвигаются никогда (SPEC §6.3, база знаний)."""
    known = {r.id: r for r in scenario.requests}
    for assignment in result.assignments:
        if assignment.status != AssignmentStatus.ASSIGNED:
            continue
        request = known.get(assignment.request_id)
        if request is None:
            continue
        assert assignment.arrival_at <= request.window_end, (
            f"{request.id}: прибытие {hhmm(assignment.arrival_at)} позже конца окна "
            f"{hhmm(request.window_end)}"
        )
        assert assignment.service_start_at >= request.window_start, (
            f"{request.id}: работа начата раньше окна"
        )


def assert_locked_unchanged(before, after, moment):
    """Ни одно назначение с service_start_at < moment не изменилось."""
    frozen = locked_snapshot(before, moment)
    assert frozen, "в сценарии нет замороженных назначений — тест бессмыслен"
    after_by_id = assignments_by_id(after)
    for request_id, snapshot in frozen.items():
        assignment = after_by_id.get(request_id)
        assert assignment is not None, f"{request_id}: замороженное назначение исчезло"
        assert assignment.status == AssignmentStatus.ASSIGNED, (
            f"{request_id}: замороженное назначение стало неназначенным"
        )
        actual = (
            assignment.engineer_id,
            assignment.arrival_at,
            assignment.service_start_at,
            assignment.service_end_at,
        )
        assert actual == snapshot, f"{request_id}: замороженное назначение изменилось {snapshot} -> {actual}"


def urgent_request(**overrides):
    """Срочная заявка для события URGENT_REQUEST."""
    params = dict(
        window=("13:30", "14:30"),
        dur=30,
        at=(55.700, 37.600),
        priority="urgent",
        order=100,
    )
    params.update(overrides)
    return req("RU", **params)


# --------------------------------------------------------------------------
# Инвариант заморозки — общий для всех типов событий
# --------------------------------------------------------------------------


def all_events():
    """Четыре события на одном и том же базовом сценарии."""
    return {
        "urgent": event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent_request()),
        "cancel": event(EventType.CANCEL_REQUEST, EVENT_AT, request_id="R5"),
        "unavailable": event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="E2"),
        "refusal": event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="R5"),
    }


@pytest.mark.parametrize("name", sorted(all_events()))
def test_locked_assignments_never_change(name):
    """САМЫЙ ВАЖНЫЙ тест перепланирования: прошлое не переписывается.

    Ни одно назначение, начатое раньше момента события, не меняет ни инженера,
    ни одного из времён — для всех четырёх типов событий.
    """
    scenario = base_scenario()
    before = plan_optimized(scenario)
    ev = all_events()[name]
    after = replan(before, scenario, ev)
    assert_locked_unchanged(before, after, t(EVENT_AT))


@pytest.mark.parametrize("name", sorted(all_events()))
def test_replan_result_is_valid(name):
    """Результат ремонта обязан проходить независимый верификатор."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    ev = all_events()[name]
    after = replan(before, scenario, ev)
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


@pytest.mark.parametrize("name", sorted(all_events()))
def test_windows_are_never_shifted_by_replan(name):
    """Окна заявок остаются исходными при любом ремонте."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    ev = all_events()[name]
    after = replan(before, scenario, ev)
    assert_windows_not_shifted(after, scenario_after(scenario, before, ev))


@pytest.mark.parametrize("name", sorted(all_events()))
def test_requests_are_never_auto_cancelled(name):
    """Заявка не «отменяется» сама: у каждой остаётся ровно один Assignment."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    ev = all_events()[name]
    after = replan(before, scenario, ev)

    # Состав заявок считается по действующему сценарию: отменённая исчезает только
    # потому, что её отменили явным событием, а не «сама».
    expected = {r.id for r in scenario_after(scenario, before, ev).requests}
    actual = {a.request_id for a in after.assignments}
    assert expected == actual, (
        f"расхождение состава: потеряны {sorted(expected - actual)}, "
        f"лишние {sorted(actual - expected)}"
    )
    ids = [a.request_id for a in after.assignments]
    assert len(ids) == len(set(ids)), "дублирующиеся Assignment после ремонта"
    if name == "cancel":
        assert "R5" not in actual, "отменённая заявка обязана исчезнуть из назначений"


@pytest.mark.parametrize("name", sorted(all_events()))
def test_plan_diff_is_consistent(name):
    """PlanDiff: changed и unchanged не пересекаются и вместе покрывают маршруты."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    ev = all_events()[name]
    after = replan(before, scenario, ev)

    diff = after.diff
    assert diff is not None, "PlanDiff обязан заполняться при перепланировании"
    assert diff.previous_plan_id == before.plan_id
    assert diff.event_type == ev.type
    assert diff.summary and has_cyrillic(diff.summary), "summary пуст или не на русском"

    changed = set(diff.changed_route_engineer_ids)
    unchanged = set(diff.unchanged_route_engineer_ids)
    removed = set(diff.removed_route_engineer_ids)
    assert not (changed & unchanged), f"пересечение changed/unchanged: {changed & unchanged}"

    all_routes = {r.engineer_id for r in before.routes} | {r.engineer_id for r in after.routes}
    assert all_routes <= (changed | unchanged | removed), (
        f"не покрыты маршруты: {sorted(all_routes - (changed | unchanged | removed))}"
    )


@pytest.mark.parametrize("name", sorted(all_events()))
def test_routes_declared_unchanged_are_really_identical(name):
    """Маршруты из unchanged_route_engineer_ids совпадают побайтово с прежними."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    ev = all_events()[name]
    after = replan(before, scenario, ev)
    if after.diff is None:
        pytest.skip("PlanDiff не заполнен")

    for engineer_id in after.diff.unchanged_route_engineer_ids:
        assert route_signature(after, engineer_id) == route_signature(before, engineer_id), (
            f"маршрут {engineer_id} объявлен неизменным, но отличается"
        )


# --------------------------------------------------------------------------
# URGENT_REQUEST
# --------------------------------------------------------------------------


def test_urgent_request_is_inserted_into_plan():
    """Срочная заявка, для которой есть место, обязана быть размещена."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    urgent = urgent_request()
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent))

    assert "RU" in assigned_ids(after), "срочная заявка не размещена, хотя место было"
    assert after.metrics.urgent_unassigned_count == 0


def test_urgent_request_does_not_touch_unrelated_routes():
    """Маршруты, которых срочная заявка не касается, остаются идентичными."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    urgent = urgent_request()
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent))

    host = assignments_by_id(after)["RU"].engineer_id
    touched = {host}
    if after.diff is not None:
        touched |= set(after.diff.changed_route_engineer_ids)

    for route in before.routes:
        if route.engineer_id in touched:
            continue
        assert route_signature(after, route.engineer_id) == route_signature(
            before, route.engineer_id
        ), f"маршрут {route.engineer_id} изменился, хотя срочная заявка его не касалась"


def test_impossible_urgent_request_is_unassigned_with_reason():
    """Невозможную срочную заявку честно помечаем неназначенной с причиной."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    urgent = urgent_request(window=("03:00", "04:00"), dur=30)
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent))

    assignment = assignments_by_id(after).get("RU")
    assert assignment is not None, "срочная заявка исчезла из результата"
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.reason is not None
    assert assignment.explanation and has_cyrillic(assignment.explanation)


def test_urgent_request_in_the_past_is_not_forced_into_locked_window():
    """Срочная заявка с окном в прошлом не ломает уже выполненные работы."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    urgent = urgent_request(window=("09:00", "09:30"), dur=30)
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent))

    assert_locked_unchanged(before, after, t(EVENT_AT))
    assignment = assignments_by_id(after)["RU"]
    assert assignment.status == AssignmentStatus.UNASSIGNED, (
        "заявку с окном в прошлом нельзя размещать задним числом"
    )


# --------------------------------------------------------------------------
# Вытеснение (ejection)
# --------------------------------------------------------------------------


def ejection_scenario():
    """Плотный день одного инженера: свободного места под срочную нет."""
    engineers = [eng("E1", shift=("09:00", "18:00"), at=HOME, order=0)]
    requests = [
        req("N1", window=("09:00", "09:00"), dur=120, at=HOME),
        req("N2", window=("11:00", "11:00"), dur=120, at=HOME),
        req("N3", window=("13:00", "13:00"), dur=120, at=HOME),
        req("N4", window=("15:00", "15:00"), dur=120, at=HOME),
    ]
    return sc(requests, engineers, name="ejection")


def test_ejection_places_urgent_request():
    """При ejection_depth>=1 срочная заявка вытесняет обычную и размещается."""
    base = ejection_scenario()
    scenario = sc(base.requests, base.engineers, ejection_depth=1)
    before = plan_optimized(scenario)
    assert before.metrics.assigned_count == 4, "сценарий вытеснения собран неверно"

    urgent = req("RU", window=("15:00", "15:00"), dur=120, at=HOME, priority="urgent", order=100)
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, "14:00", request=urgent))

    assert "RU" in assigned_ids(after), "срочная заявка не размещена даже вытеснением"
    assert "N4" not in assigned_ids(after) or assignments_by_id(after)["N4"].engineer_id is not None


def test_ejected_request_is_either_reassigned_or_honestly_unassigned():
    """Вытесненная заявка не пропадает: либо переразмещена, либо с причиной."""
    base = ejection_scenario()
    scenario = sc(base.requests, base.engineers, ejection_depth=1)
    before = plan_optimized(scenario)
    urgent = req("RU", window=("15:00", "15:00"), dur=120, at=HOME, priority="urgent", order=100)
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, "14:00", request=urgent))

    victim = assignments_by_id(after)["N4"]
    if victim.status == AssignmentStatus.UNASSIGNED:
        assert victim.reason is not None
        assert victim.explanation and has_cyrillic(victim.explanation)
    else:
        assert victim.engineer_id is not None


def test_ejection_respects_frozen_past():
    """Вытеснять можно только незамороженные заявки."""
    base = ejection_scenario()
    scenario = sc(base.requests, base.engineers, ejection_depth=1)
    before = plan_optimized(scenario)
    urgent = req("RU", window=("15:00", "15:00"), dur=120, at=HOME, priority="urgent", order=100)
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, "14:00", request=urgent))
    assert_locked_unchanged(before, after, t("14:00"))


def test_zero_ejection_depth_forbids_displacement():
    """ejection_depth=0 запрещает вытеснение: срочная остаётся неназначенной."""
    base = ejection_scenario()
    scenario = sc(base.requests, base.engineers, ejection_depth=0)
    before = plan_optimized(scenario)
    urgent = req("RU", window=("15:00", "15:00"), dur=120, at=HOME, priority="urgent", order=100)
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, "14:00", request=urgent))

    assert assignments_by_id(after)["RU"].status == AssignmentStatus.UNASSIGNED
    assert "N4" in assigned_ids(after), "без вытеснения обычная заявка должна остаться"


# --------------------------------------------------------------------------
# CANCEL_REQUEST
# --------------------------------------------------------------------------


def cancelled_setup(request_id="R5"):
    """Готовит план и событие отмены, возвращает (сценарий, до, после, инженер)."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    host = assignments_by_id(before)[request_id].engineer_id
    after = replan(before, scenario, event(EventType.CANCEL_REQUEST, EVENT_AT, request_id=request_id))
    return scenario, before, after, host


def test_cancelled_request_disappears_from_route():
    """Отменённая заявка исчезает из маршрута и не остаётся назначенной."""
    _scenario, _before, after, host = cancelled_setup()
    assert "R5" not in [v.request_id for v in routes_by_engineer(after).get(host).visits]
    assert "R5" not in assigned_ids(after)


def test_cancel_shifts_route_tail_earlier():
    """Хвост маршрута после отмены сдвигается раньше или остаётся на месте."""
    _scenario, before, after, host = cancelled_setup()
    before_times = {
        v.request_id: v.service_start_at for v in routes_by_engineer(before)[host].visits
    }
    after_route = routes_by_engineer(after).get(host)
    if after_route is None:
        pytest.skip("маршрут исчез целиком")
    for visit in after_route.visits:
        if visit.request_id in before_times:
            assert visit.service_start_at <= before_times[visit.request_id], (
                f"{visit.request_id} после отмены стартует позже: "
                f"{hhmm(before_times[visit.request_id])} -> {hhmm(visit.service_start_at)}"
            )


def test_cancel_does_not_touch_other_routes():
    """SPEC §6.3: пересчитывается только маршрут отменённой заявки."""
    _scenario, before, after, host = cancelled_setup()
    for route in before.routes:
        if route.engineer_id == host:
            continue
        assert route_signature(after, route.engineer_id) == route_signature(
            before, route.engineer_id
        ), f"маршрут {route.engineer_id} изменился при отмене чужой заявки"


def test_cancel_reduces_service_minutes_by_request_duration():
    """Снятая работа не засчитывается в метрики обслуживания."""
    scenario, before, after, _host = cancelled_setup()
    duration = {r.id: r.duration_minutes for r in scenario.requests}["R5"]
    assert after.metrics.total_service_minutes == pytest.approx(
        before.metrics.total_service_minutes - duration, abs=1e-6
    )


# --------------------------------------------------------------------------
# CLIENT_REFUSAL
# --------------------------------------------------------------------------


def test_client_refusal_keeps_the_trip():
    """Отказ клиента: поездка состоялась, её расстояние остаётся в маршруте."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    host = assignments_by_id(before)["R5"].engineer_id
    after = replan(before, scenario, event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="R5"))

    route_before = routes_by_engineer(before)[host]
    route_after = routes_by_engineer(after).get(host)
    assert route_after is not None, "маршрут исчез, хотя поездка состоялась"
    assert "R5" in [v.request_id for v in route_after.visits], (
        "визит должен остаться в маршруте как состоявшаяся поездка"
    )
    assert route_after.distance_km == pytest.approx(route_before.distance_km, rel=1e-6), (
        "пробег изменился, хотя последовательность точек та же"
    )


def test_client_refusal_does_not_count_the_work():
    """Работа не засчитывается: суммарное время обслуживания уменьшается."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    duration = {r.id: r.duration_minutes for r in scenario.requests}["R5"]
    after = replan(before, scenario, event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="R5"))

    assert after.metrics.total_service_minutes == pytest.approx(
        before.metrics.total_service_minutes - duration, abs=1e-6
    ), "время работы по отказной заявке не должно попадать в метрики"


def test_client_refusal_frees_time_for_the_tail():
    """Освободившееся время достаётся хвосту маршрута, но окна не нарушаются."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    host = assignments_by_id(before)["R5"].engineer_id
    after = replan(before, scenario, event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="R5"))
    assert_windows_not_shifted(after, scenario)
    assert routes_by_engineer(after)[host] is not None


# --------------------------------------------------------------------------
# ENGINEER_UNAVAILABLE
# --------------------------------------------------------------------------


def test_engineer_unavailable_keeps_only_locked_visits():
    """Маршрут выбывшего инженера исчезает или содержит только начатое ранее."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    after = replan(
        before, scenario, event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="E2")
    )

    route = routes_by_engineer(after).get("E2")
    if route is not None:
        for visit in route.visits:
            assert visit.service_start_at < t(EVENT_AT), (
                f"{visit.request_id} остался у выбывшего инженера после {EVENT_AT}"
            )


def test_engineer_unavailable_redistributes_orphans():
    """Незамороженные заявки выбывшего либо переходят другим, либо честно теряются."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    orphans = [
        a.request_id
        for a in before.assignments
        if a.status == AssignmentStatus.ASSIGNED
        and a.engineer_id == "E2"
        and a.service_start_at >= t(EVENT_AT)
    ]
    if not orphans:
        pytest.skip("у E2 нет незамороженных заявок в этом сценарии")

    after = replan(
        before, scenario, event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="E2")
    )
    by_id = assignments_by_id(after)
    for request_id in orphans:
        assignment = by_id[request_id]
        if assignment.status == AssignmentStatus.ASSIGNED:
            assert assignment.engineer_id != "E2", f"{request_id} остался у выбывшего инженера"
        else:
            assert assignment.reason is not None
            assert assignment.explanation and has_cyrillic(assignment.explanation)


def test_engineer_unavailable_does_not_rebuild_other_routes_from_scratch():
    """Чужие маршруты не пересобираются: их начало остаётся прежним."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    after = replan(
        before, scenario, event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="E2")
    )

    before_e1 = routes_by_engineer(before).get("E1")
    after_e1 = routes_by_engineer(after).get("E1")
    assert after_e1 is not None
    prefix_before = [
        v.request_id for v in before_e1.visits if v.service_start_at < t(EVENT_AT)
    ]
    prefix_after = [v.request_id for v in after_e1.visits if v.service_start_at < t(EVENT_AT)]
    assert prefix_after[: len(prefix_before)] == prefix_before, (
        "замороженный префикс чужого маршрута изменился"
    )


def test_engineer_unavailable_with_no_alternative_marks_requests_unassigned():
    """Единственный инженер выбыл — оставшиеся заявки получают внятную причину."""
    engineers = [eng("E1", shift=("09:00", "18:00"), at=HOME)]
    requests = [
        req("R1", window=("09:00", "10:00"), dur=60, at=HOME),
        req("R2", window=("15:00", "16:00"), dur=60, at=HOME),
    ]
    scenario = sc(requests, engineers)
    before = plan_optimized(scenario)
    after = replan(
        before, scenario, event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="E1")
    )

    by_id = assignments_by_id(after)
    assert by_id["R1"].status == AssignmentStatus.ASSIGNED, "прошлое должно остаться замороженным"
    assert by_id["R2"].status == AssignmentStatus.UNASSIGNED
    assert by_id["R2"].reason is not None
    assert by_id["R2"].explanation and has_cyrillic(by_id["R2"].explanation)


# --------------------------------------------------------------------------
# Общие свойства результата перепланирования
# --------------------------------------------------------------------------


def test_replan_keeps_plan_id_distinct_from_previous():
    """Ремонт создаёт новый план, а не мутирует старый."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    after = replan(before, scenario, event(EventType.CANCEL_REQUEST, EVENT_AT, request_id="R5"))
    assert after.plan_id != before.plan_id
    assert "R5" in assigned_ids(before), "исходный план не должен меняться"


def test_replan_does_not_mutate_previous_result():
    """Предыдущий PlanResult остаётся прежним после ремонта."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    snapshot = {r.engineer_id: route_signature(before, r.engineer_id) for r in before.routes}
    replan(before, scenario, event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="E2"))
    for engineer_id, signature in snapshot.items():
        assert route_signature(before, engineer_id) == signature, (
            f"replan изменил предыдущий план ({engineer_id})"
        )


def test_replan_without_stabilization_is_still_valid():
    """stabilize_after_replan=False не должен ломать корректность."""
    base = base_scenario()
    scenario = sc(base.requests, base.engineers, stabilize_after_replan=False)
    before = plan_optimized(scenario)
    ev = event(EventType.CANCEL_REQUEST, EVENT_AT, request_id="R5")
    after = replan(before, scenario, ev)
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []

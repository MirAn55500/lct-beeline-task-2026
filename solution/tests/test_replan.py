# -*- coding: utf-8 -*-
"""Перепланирование (SPEC §6.3) — все четыре типа событий.

Ключевая идея: инкрементальный ремонт, а не пересчёт с нуля. Главный
инвариант — заморозка прошлого: назначение, начатое до момента события, не
меняется ни по инженеру, ни по времени. Остальное — устойчивость нетронутых
маршрутов и корректность PlanDiff.
"""
from __future__ import annotations

from datetime import timedelta

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
    normalized_dict,
    plan_optimized,
    replan,
    req,
    routes_by_engineer,
    sc,
    t,
    unassigned_ids,
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
        eng("E1", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME, order=1),
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
    """Алгоритм окна сам не сдвигает: визиты сверяются с актуальным окном сценария."""
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


def route_ids(result, engineer_id):
    """Порядок заявок в маршруте инженера (пустой список, если маршрута нет)."""
    route = routes_by_engineer(result).get(engineer_id)
    return [] if route is None else [v.request_id for v in route.visits]


def first_free_visit(result, engineer_id="E1"):
    """Первый визит маршрута, который ещё не стал фактом."""
    route = routes_by_engineer(result).get(engineer_id)
    assert route is not None, f"маршрута {engineer_id} нет в плане"
    for visit in route.visits:
        if not visit.locked:
            return visit
    raise AssertionError(f"в маршруте {engineer_id} все визиты заморожены")


def visit_of(result, request_id):
    """Визит по заявке — нужен там, где важны выезд и признак заморозки."""
    for route in result.routes:
        for visit in route.visits:
            if visit.request_id == request_id:
                return visit
    raise AssertionError(f"визита {request_id} нет в плане")


def urgent_request(**overrides):
    """Аварийная заявка для события URGENT_REQUEST (имя события не менялось)."""
    params = dict(
        window=("13:30", "14:30"),
        dur=30,
        at=(55.700, 37.600),
        skill="emergency",
        priority="emergency",
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
    """Алгоритм окна сам не мутирует: визиты укладываются в окно действующего сценария."""
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
    expected = {r.id for r in scenario_after(scenario, before, ev).planning_requests()}
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
    """Аварийная заявка, для которой есть место, обязана быть размещена."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    urgent = urgent_request()
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent))

    assert "RU" in assigned_ids(after), "аварийная заявка не размещена, хотя место было"
    assert after.metrics.emergency_unassigned_count == 0


def test_urgent_request_does_not_touch_unrelated_routes():
    """Маршруты, которых аварийная заявка не касается, остаются идентичными."""
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
        ), f"маршрут {route.engineer_id} изменился, хотя аварийная заявка его не касалась"


def test_impossible_urgent_request_is_unassigned_with_reason():
    """Невозможную аварийную заявку честно помечаем неназначенной с причиной."""
    scenario = base_scenario()
    before = plan_optimized(scenario)
    urgent = urgent_request(window=("03:00", "04:00"), dur=30)
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent))

    assignment = assignments_by_id(after).get("RU")
    assert assignment is not None, "аварийная заявка исчезла из результата"
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
    """Плотный день одного инженера: свободного места под аварию нет."""
    engineers = [eng("E1", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME, order=0)]
    requests = [
        req("N1", window=("09:00", "09:00"), dur=120, at=HOME),
        req("N2", window=("11:00", "11:00"), dur=120, at=HOME),
        req("N3", window=("13:00", "13:00"), dur=120, at=HOME),
        req("N4", window=("15:00", "15:00"), dur=120, at=HOME),
    ]
    return sc(requests, engineers, name="ejection")


def test_ejection_places_urgent_request():
    """При ejection_depth>=1 авария вытесняет заявку меньшего приоритета и размещается."""
    base = ejection_scenario()
    scenario = sc(base.requests, base.engineers, ejection_depth=1)
    before = plan_optimized(scenario)
    assert before.metrics.assigned_count == 4, "сценарий вытеснения собран неверно"

    urgent = req(
        "RU",
        window=("15:00", "15:00"),
        dur=120,
        at=HOME,
        skill="emergency",
        priority="emergency",
        order=100,
    )
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, "14:00", request=urgent))

    assert "RU" in assigned_ids(after), "аварийная заявка не размещена даже вытеснением"
    assert "N4" not in assigned_ids(after) or assignments_by_id(after)["N4"].engineer_id is not None


def test_ejected_request_is_either_reassigned_or_honestly_unassigned():
    """Вытесненная заявка не пропадает: либо переразмещена, либо с причиной."""
    base = ejection_scenario()
    scenario = sc(base.requests, base.engineers, ejection_depth=1)
    before = plan_optimized(scenario)
    urgent = req(
        "RU",
        window=("15:00", "15:00"),
        dur=120,
        at=HOME,
        skill="emergency",
        priority="emergency",
        order=100,
    )
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
    urgent = req(
        "RU",
        window=("15:00", "15:00"),
        dur=120,
        at=HOME,
        skill="emergency",
        priority="emergency",
        order=100,
    )
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, "14:00", request=urgent))
    assert_locked_unchanged(before, after, t("14:00"))


def test_zero_ejection_depth_forbids_displacement():
    """ejection_depth=0 запрещает вытеснение: авария остаётся неназначенной.

    Степень изменения плана — средняя: третья ступень (пересчёт остатка дня) в тест
    не входит, она разместила бы аварию и без вытеснения. Про неё — отдельные тесты ниже.
    """
    base = ejection_scenario()
    scenario = sc(
        base.requests, base.engineers, ejection_depth=0, replan_scope="medium"
    )
    before = plan_optimized(scenario)
    urgent = req(
        "RU",
        window=("15:00", "15:00"),
        dur=120,
        at=HOME,
        skill="emergency",
        priority="emergency",
        order=100,
    )
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, "14:00", request=urgent))

    assert assignments_by_id(after)["RU"].status == AssignmentStatus.UNASSIGNED
    assert "N4" in assigned_ids(after), "без вытеснения заявка меньшего приоритета должна остаться"


def test_ejection_cannot_displace_another_emergency():
    """Входящая авария не вытесняет другую аварию: rank входящей не выше."""
    engineers = [eng("E1", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME)]
    requests = [
        req("N1", window=("09:00", "09:00"), dur=120, at=HOME),
        req("N2", window=("11:00", "11:00"), dur=120, at=HOME),
        req("N3", window=("13:00", "13:00"), dur=120, at=HOME),
        req(
            "N4",
            window=("15:00", "15:00"),
            dur=120,
            at=HOME,
            skill="emergency",
            priority="emergency",
        ),
    ]
    scenario = sc(requests, engineers, ejection_depth=1)
    before = plan_optimized(scenario)
    assert "N4" in assigned_ids(before)

    incoming = req(
        "RU",
        window=("15:00", "15:00"),
        dur=120,
        at=HOME,
        skill="emergency",
        priority="emergency",
        order=100,
    )
    after = replan(before, scenario, event(EventType.URGENT_REQUEST, "14:00", request=incoming))

    assert "N4" in assigned_ids(after), "другую аварию нельзя вытеснить"
    assert assignments_by_id(after)["RU"].status == AssignmentStatus.UNASSIGNED


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


# --------------------------------------------------------------------------
# Регрессии: заморозка при исчезновении более раннего визита и глубина вытеснения
# --------------------------------------------------------------------------


def _chain_scenario(**overrides):
    """Один инженер и цепочка из трёх заявок подряд — без конкуренции за исполнителя."""
    here = (55.750, 37.610)
    there = (55.760, 37.630)
    engineers = [eng("E1", skills=["connection"], shift=("09:00", "20:00"), at=here, order=0)]
    requests = [
        req("R1", window=("09:00", "18:00"), dur=60, at=here, order=0),
        req("R2", window=("09:00", "18:00"), dur=60, at=there, order=1),
        req("R3", window=("09:00", "18:00"), dur=60, at=there, order=2),
    ]
    return sc(requests, engineers, name="replan-chain", **overrides)


def test_started_work_keeps_its_time_when_earlier_visit_disappears():
    """Отмена уже отработанного визита не двигает начатые работы назад во времени.

    Регрессия: расписание пересчитывалось от начала смены целиком, поэтому исчезновение
    более раннего визита сдвигало замороженный хвост в прошлое — план утверждал, что
    работа шла не тогда, когда она шла на самом деле.
    """
    scenario = _chain_scenario()
    before = plan_optimized(scenario)
    first = before.routes[0].visits[0]

    # Момент события — когда все три визита уже начаты: всё, что было, стало фактом.
    moment = before.routes[0].visits[-1].service_start_at + timedelta(minutes=1)
    after = replan(before, scenario, event(EventType.CANCEL_REQUEST, moment, request_id=first.request_id))

    was = {v.request_id: v for v in before.routes[0].visits}
    for visit in after.routes[0].visits:
        assert visit.locked, f"визит {visit.request_id} обязан остаться замороженным"
        old = was[visit.request_id]
        assert visit.service_start_at == old.service_start_at, visit.request_id
        assert visit.service_end_at == old.service_end_at, visit.request_id
        assert visit.arrival_at == old.arrival_at, visit.request_id
    assert validate_plan(after, scenario_after(scenario, before, event(
        EventType.CANCEL_REQUEST, moment, request_id=first.request_id))) == []


def test_urgent_request_gets_assignment_when_scenario_has_snapshot():
    """Со снимком `as_of` авария после события попадает и в маршрут, и в назначения.

    Регрессия: `apply_event` не сдвигал границу снимка на момент события, поэтому
    заявка стояла в маршруте, но выпадала из `planning_requests()` — а значит из
    назначений и из метрик, и план при этом выглядел корректным.
    """
    engineers = [eng("E1", skills=["connection", "emergency"], shift=("09:00", "18:00"), order=0)]
    requests = [req("R1", window=("10:00", "12:00"), dur=60, order=0)]
    scenario = sc(requests, engineers, as_of="09:00", name="replan-snapshot")
    before = plan_optimized(scenario)

    urgent = req(
        "U1",
        window=("13:00", "15:00"),
        dur=80,
        skill="emergency",
        priority="emergency",
        received_at="13:00",
        order=99,
    )
    ev = event(EventType.URGENT_REQUEST, "13:00", request=urgent)
    after = replan(before, scenario, ev)

    placed = assignments_by_id(after).get("U1")
    assert placed is not None, "аварийная заявка обязана иметь Assignment"
    assert placed.status == AssignmentStatus.ASSIGNED
    assert "U1" in assigned_ids(after)
    assert after.metrics.assigned_count == 2
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_ejection_depth_allows_displacing_several_requests():
    """`ejection_depth` — это глубина: при 2 авария вытесняет две заявки, при 1 — нет.

    Регрессия: вытеснялась ровно одна заявка при любом значении настройки, поэтому
    авария, которой нужно освободить два слота подряд, терялась.

    Степень изменения — средняя: измеряется именно глубина вытеснения, а не страховка,
    которая разложит остаток дня заново при любой глубине.
    """
    here = (55.750, 37.610)
    engineers = [eng("E1", skills=["connection", "emergency"], shift=("09:00", "13:00"), at=here, order=0)]
    requests = [
        req("C1", window=("09:00", "12:00"), dur=100, at=here, priority="connection", order=0),
        req("C2", window=("09:00", "12:00"), dur=100, at=here, priority="connection", order=1),
    ]
    urgent = req(
        "A1",
        window=("09:00", "10:00"),
        dur=180,
        at=here,
        skill="emergency",
        priority="emergency",
        received_at="09:00",
        order=9,
    )

    outcome = {}
    for depth in (1, 2):
        scenario = sc(
            requests,
            engineers,
            ejection_depth=depth,
            replan_scope="medium",
            name=f"eject-{depth}",
        )
        before = plan_optimized(scenario)
        ev = event(EventType.URGENT_REQUEST, "09:00", request=urgent)
        after = replan(before, scenario, ev)
        outcome[depth] = "A1" in assigned_ids(after)
        assert validate_plan(after, scenario_after(scenario, before, ev)) == []

    assert outcome[1] is False, "одной вытесненной заявки не хватает — авария не помещается"
    assert outcome[2] is True, "при глубине 2 авария обязана вытеснить обе заявки и встать"


# --------------------------------------------------------------------------
# Ступень 3: пересчёт остатка дня (SPEC §6.3)
# --------------------------------------------------------------------------


def rebuild_scenario(**overrides):
    """День, где авария помещается только после пересчёта по всем инженерам.

    E1 — единственный с навыком `emergency` — везёт весь день; E2 свободен, но
    аварию взять не может. Освободить у E1 место можно, только сняв все пять работ
    сразу: вытеснение ограничено `ejection_depth`, поэтому одним маршрутом задача
    не решается.
    """
    engineers = [
        eng("E1", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", skills=["connection"], shift=("09:00", "18:00"), at=HOME, order=1),
    ]
    requests = [
        req("C1", window=("09:00", "09:30"), dur=120, at=HOME, order=0),
        req("C2", window=("09:00", "17:00"), dur=90, at=HOME, order=1),
        req("C3", window=("09:00", "17:00"), dur=90, at=HOME, order=2),
        req("C4", window=("09:00", "17:00"), dur=90, at=HOME, order=3),
        req("C5", window=("09:00", "17:00"), dur=90, at=HOME, order=4),
    ]
    return sc(requests, engineers, name="rebuild", **overrides)


def rebuild_event():
    """Авария на 10:00: работа C1 уже идёт, остаток дня ещё не начат."""
    urgent = req(
        "A1",
        window=("10:00", "11:00"),
        dur=400,
        at=HOME,
        skill="emergency",
        priority="emergency",
        received_at="10:00",
        order=90,
    )
    return event(EventType.URGENT_REQUEST, "10:00", request=urgent)


def test_urgent_request_fits_only_after_freeing_several_slots():
    """Глубина вытеснения по умолчанию — 3: авария, которой нужно три слота, встаёт.

    Регрессия на `ejection_depth`: со значением 1 средняя ступень вырождалась в
    «сними ровно одну заявку и сдайся», и авария на несколько часов не размещалась
    никогда, хотя один маршрут её вмещал.
    """
    engineers = [
        eng("E1", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", skills=["connection"], shift=("09:00", "18:00"), at=HOME, order=1),
    ]
    requests = [req(f"C{i}", window=("09:00", "16:00"), dur=100, at=HOME, order=i) for i in range(4)]
    urgent = req(
        "A1",
        window=("09:00", "09:30"),
        dur=400,
        at=HOME,
        skill="emergency",
        priority="emergency",
        received_at="09:00",
        order=90,
    )
    ev = event(EventType.URGENT_REQUEST, "09:00", request=urgent)

    placed = {}
    for depth in (2, 3):
        scenario = sc(
            requests, engineers, ejection_depth=depth, replan_scope="medium"
        )
        before = plan_optimized(scenario)
        assert sorted(route_ids(before, "E1")) == ["C0", "C1", "C2", "C3"], "сценарий собран неверно"
        after = replan(before, scenario, ev)
        placed[depth] = "A1" in assigned_ids(after)
        assert validate_plan(after, scenario_after(scenario, before, ev)) == []

    assert placed[2] is False, "двух освобождённых слотов авария не переживает"
    assert placed[3] is True, "трёх слотов достаточно — при глубине по умолчанию авария обязана встать"


def test_urgent_request_fits_only_after_rebuilding_the_whole_day():
    """Авария конкурирует за место со всем остатком дня, а не с одним слотом.

    Одним маршрутом задача не решается: у единственного подходящего инженера
    нужно снять все пять работ, а вытеснение ограничено глубиной. Пересчёт
    остатка дня раскладывает их по свободному инженеру и освобождает день целиком.
    """
    scenario = rebuild_scenario()
    before = plan_optimized(scenario)
    assert route_ids(before, "E2") == [], "сценарий собран неверно: второй инженер должен быть свободен"

    ev = rebuild_event()
    after = replan(before, scenario, ev)

    assert "A1" in assigned_ids(after), "авария не размещена даже пересчётом остатка дня"
    assert assignments_by_id(after)["A1"].engineer_id == "E1", "аварию может взять только E1"
    assert unassigned_ids(after) == set(), "пересчёт обязан сохранить все прежние работы"
    assert set(after.diff.changed_route_engineer_ids) == {"E1", "E2"}, (
        "пересчёт остатка дня по определению трогает больше одного маршрута"
    )
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_single_route_repair_cannot_place_that_urgent_request():
    """Контроль сценария: при средней степени изменения та же авария теряется.

    Без него предыдущий тест ничего не доказывал бы — авария могла бы помещаться
    и точечной вставкой.
    """
    scenario = rebuild_scenario(replan_scope="medium")
    before = plan_optimized(scenario)
    ev = rebuild_event()
    after = replan(before, scenario, ev)

    assert "A1" in unassigned_ids(after)
    assert after.metrics.emergency_unassigned_count == 1


def test_global_rebuild_does_not_move_started_visits():
    """Начатая работа не меняется ни по исполнителю, ни по времени.

    Пересчёт трогает все маршруты, поэтому инвариант заморозки проверяется именно
    на нём: замороженный префикс обязан пережить полное перераспределение.
    """
    scenario = rebuild_scenario()
    before = plan_optimized(scenario)
    ev = rebuild_event()
    after = replan(before, scenario, ev)

    assert_locked_unchanged(before, after, t("10:00"))
    first = assignments_by_id(after)["C1"]
    assert first.engineer_id == "E1"
    assert first.position == 1, "начатая работа обязана остаться в начале маршрута"


def test_global_rebuild_is_applied_only_when_it_is_better():
    """Правило приёмки: пересчёт берётся, только если он лучше по `quality_key()`.

    Ступень задумана как страховка; без сравнения с инкрементальным ремонтом она
    могла бы ухудшить план — например, растащить день ради худшего распределения.
    """
    for build in (rebuild_scenario, unavailable_rebuild_scenario):
        with_stage = build()
        without_stage = build(replan_scope="medium")
        ev = rebuild_event() if build is rebuild_scenario else unavailable_rebuild_event()

        best = replan(plan_optimized(with_stage), with_stage, ev)
        incremental = replan(plan_optimized(without_stage), without_stage, ev)

        assert best.metrics.quality_key() <= incremental.metrics.quality_key(), (
            f"{build.__name__}: пересчёт ухудшил план вместо того, чтобы его спасти"
        )


def test_global_rebuild_does_not_disturb_a_day_that_needs_one_insertion():
    """Тай-брейк на стабильность: дешёвая вставка не подменяется пересчётом.

    Смысл событийного перепланирования — показать диспетчеру, что именно
    изменилось. Пока хватает одной вставки, план обязан совпадать с тем, который
    получается при выключенной третьей ступени, до последнего поля.
    """
    scenario = base_scenario()
    quiet = sc(
        scenario.requests,
        scenario.engineers,
        replan_scope="medium",
        name=scenario.name,
    )
    ev = event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent_request())

    with_stage = replan(plan_optimized(scenario), scenario, ev)
    without_stage = replan(plan_optimized(quiet), quiet, ev)

    assert normalized_dict(with_stage) == normalized_dict(without_stage)
    assert len(with_stage.diff.changed_route_engineer_ids) == 1, (
        "хватило одной вставки — переставлять остальные маршруты нечем оправдать"
    )


def test_global_rebuild_is_deterministic():
    """Два прогона одного события дают побайтово одинаковый план."""
    scenario = rebuild_scenario()
    before = plan_optimized(scenario)
    first = replan(before, scenario, rebuild_event())
    second = replan(before, scenario, rebuild_event())
    assert normalized_dict(first) == normalized_dict(second)


# --------------------------------------------------------------------------
# Ступень 3 при недоступности инженера
# --------------------------------------------------------------------------


def unavailable_rebuild_scenario(**overrides):
    """Выбывает E1, и его работу можно пристроить, только подвинув чужую.

    X требует навыка `emergency` (взять её могут только E1 и E2), C2 — обычная.
    Обе начинаются в одно и то же узкое окно, поэтому E2 вмещает ровно одну из них:
    точечный ремонт бессилен, а пересчёт остатка дня отдаёт C2 свободному E3.
    """
    engineers = [
        eng("E1", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME, order=1),
        eng("E3", skills=["connection"], shift=("09:00", "18:00"), at=HOME, order=2),
    ]
    requests = [
        req("X", window=("14:00", "14:30"), dur=120, at=HOME, skill="emergency",
            priority="connection", order=0),
        req("C2", window=("14:00", "14:30"), dur=120, at=HOME, order=1),
    ]
    return sc(requests, engineers, name="unavailable-rebuild", **overrides)


def unavailable_rebuild_event():
    return event(EventType.ENGINEER_UNAVAILABLE, "13:00", engineer_id="E1")


def test_engineer_unavailable_triggers_the_same_rebuild():
    """Выбыл человек — остаток дня пересобирается по той же логике, что и для аварии."""
    scenario = unavailable_rebuild_scenario()
    before = plan_optimized(scenario)
    assert route_ids(before, "E1") == ["X"], "сценарий собран неверно"

    ev = unavailable_rebuild_event()
    after = replan(before, scenario, ev)

    assert unassigned_ids(after) == set(), "работу выбывшего инженера удалось сохранить только пересчётом"
    assert assignments_by_id(after)["X"].engineer_id == "E2"
    assert assignments_by_id(after)["C2"].engineer_id == "E3"
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_engineer_unavailable_without_rebuild_loses_the_request():
    """Контроль: точечный ремонт ту же заявку теряет."""
    scenario = unavailable_rebuild_scenario(replan_scope="medium")
    before = plan_optimized(scenario)
    after = replan(before, scenario, unavailable_rebuild_event())
    assert "X" in unassigned_ids(after)


# --------------------------------------------------------------------------
# Заморозка «в пути»
# --------------------------------------------------------------------------

FAR = (55.95, 37.60)


def transit_scenario(**overrides):
    """F1 — работа за городом: инженер выезжает в 09:0x и едет до 10:30."""
    engineers = [
        eng("E1", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", skills=["connection"], shift=("09:00", "18:00"), at=HOME, order=1),
    ]
    requests = [
        req("F1", window=("10:30", "11:00"), dur=120, at=FAR, skill="emergency",
            priority="connection", order=0),
        req("C2", window=("09:00", "17:00"), dur=90, at=HOME, order=1),
        req("C3", window=("09:00", "17:00"), dur=90, at=HOME, order=2),
        req("C4", window=("09:00", "17:00"), dur=90, at=HOME, order=3),
        req("C5", window=("09:00", "17:00"), dur=90, at=HOME, order=4),
    ]
    return sc(requests, engineers, name="transit", **overrides)


def test_visit_the_engineer_already_left_for_is_frozen():
    """Инженер, который выехал, но не доехал, не считается свободным.

    Заморозка только по началу работ оставляла такой визит «мягким»: пересчёт
    остатка дня разворачивал человека на середине дороги на другой адрес.
    Выезд — такой же свершившийся факт, как и начатая работа.
    """
    scenario = transit_scenario()
    before = plan_optimized(scenario)
    visit = visit_of(before, "F1")
    assert visit.departure_at < t("10:00") < visit.service_start_at, (
        "сценарий собран неверно: на момент события инженер обязан быть в пути"
    )

    ev = event(EventType.ENGINEER_UNAVAILABLE, "10:00", engineer_id="E2")
    after = replan(before, scenario, ev)

    moved = visit_of(after, "F1")
    assert moved.engineer_id == visit.engineer_id, "инженера развернули с дороги"
    assert moved.departure_at == visit.departure_at
    assert moved.service_start_at == visit.service_start_at
    assert moved.locked is True, "визит «в пути» обязан быть помечен как замороженный"
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_aborted_engineer_releases_the_visit_he_did_not_reach():
    """Исключение: выбывшего инженера поездка не держит.

    Его смена обрезана моментом события, ехать ему больше некуда, поэтому
    недоеханный визит освобождается, а не остаётся в маршруте человека,
    которого в смене уже нет.
    """
    engineers = [
        eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME, order=1),
    ]
    requests = [
        req("F2", window=("10:30", "11:00"), dur=60, at=FAR, skill="emergency",
            priority="connection", order=0),
        req("C1", window=("09:00", "16:00"), dur=90, at=HOME, order=1),
    ]
    scenario = sc(requests, engineers, name="aborted-transit")
    before = plan_optimized(scenario)
    visit = visit_of(before, "F2")
    assert visit.engineer_id == "E2"
    assert visit.departure_at < t("10:00") < visit.service_start_at, "сценарий собран неверно"

    ev = event(EventType.ENGINEER_UNAVAILABLE, "10:00", engineer_id="E2")
    after = replan(before, scenario, ev)

    placed = assignments_by_id(after)["F2"]
    assert placed.engineer_id != "E2", "выбывшему инженеру оставили поездку, которую он не завершит"
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


# --------------------------------------------------------------------------
# Пул неразмещённых
# --------------------------------------------------------------------------


def test_displaced_request_is_moved_to_another_engineer():
    """Вытесненная ради аварии заявка уезжает к свободному инженеру, а не в отказ."""
    engineers = [
        eng("E1", skills=["connection", "emergency"], shift=("09:00", "13:00"), at=HOME, order=0),
        eng("E2", skills=["connection"], shift=("13:00", "18:00"), at=HOME, order=1),
    ]
    requests = [
        req("C1", window=("09:00", "16:00"), dur=120, at=HOME, order=0),
        req("C2", window=("09:00", "16:00"), dur=120, at=HOME, order=1),
    ]
    scenario = sc(requests, engineers, replan_scope="medium", name="displaced")
    before = plan_optimized(scenario)
    assert sorted(route_ids(before, "E1")) == ["C1", "C2"], "сценарий собран неверно"

    urgent = req(
        "A1",
        window=("09:00", "09:30"),
        dur=180,
        at=HOME,
        skill="emergency",
        priority="emergency",
        received_at="09:00",
        order=90,
    )
    ev = event(EventType.URGENT_REQUEST, "09:00", request=urgent)
    after = replan(before, scenario, ev)

    assert "A1" in assigned_ids(after), "авария обязана встать вытеснением"
    assert unassigned_ids(after) == set(), "вытесненные заявки должны были уехать к E2"
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_urgent_request_is_not_inserted_twice():
    """Заявка, которая была неназначенной и пришла событием, попадает в план один раз.

    Пул неразмещённых собирается ПОСЛЕ размещения аварии. Собранный раньше, он
    содержал саму аварию — её ставила точечная вставка, а следом regret-вставка
    ставила её же второй раз, и в маршруте появлялся визит-двойник.
    """
    engineers = [
        eng("E1", skills=["connection", "emergency"], shift=("09:00", "13:00"), at=HOME, order=0)
    ]
    requests = [
        req("C1", window=("09:00", "09:30"), dur=240, at=HOME, order=0),
        req("R9", window=("09:00", "13:00"), dur=60, at=HOME, order=1),
    ]
    scenario = sc(requests, engineers, replan_scope="medium", name="twice")
    before = plan_optimized(scenario)
    assert "R9" in unassigned_ids(before), "сценарий собран неверно: R9 обязана не поместиться"

    ev = event(EventType.URGENT_REQUEST, "09:00", request=requests[1])
    after = replan(before, scenario, ev)

    visits = [v.request_id for route in after.routes for v in route.visits]
    assert visits.count("R9") == 1, f"заявка попала в план дважды: {visits}"
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


# --------------------------------------------------------------------------
# Статусы исполнения (SPEC §6.3): «инженер на месте», «работы завершены»
# --------------------------------------------------------------------------


def status_scenario(**overrides):
    """Один инженер, три работы подряд; окна вторых двух открыты заранее."""
    engineers = [eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=HOME, order=0)]
    requests = [
        req("S1", window=("09:00", "09:30"), dur=120, at=HOME, order=0),   # 09:00–11:00
        req("S2", window=("09:00", "17:00"), dur=120, at=HOME, order=1),
        req("S3", window=("09:00", "17:00"), dur=120, at=HOME, order=2),
    ]
    return sc(requests, engineers, name="status", **overrides)


def test_completed_status_records_the_actual_duration():
    """Работа закончилась раньше норматива — в плане остаётся фактическая длительность."""
    scenario = status_scenario()
    before = plan_optimized(scenario)
    visit = visit_of(before, "S1")
    assert visit.service_start_at == t("09:00") and visit.service_end_at == t("11:00")

    ev = event(EventType.VISIT_COMPLETED, "10:00", request_id="S1")
    after = replan(before, scenario, ev)

    done = visit_of(after, "S1")
    assert done.service_start_at == t("09:00"), "начало начатой работы — факт, оно не двигается"
    assert done.service_end_at == t("10:00"), "окончание обязано быть взято из статуса"
    assert done.locked is True
    assert any("раньше норматива" in w for w in after.warnings)
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_early_completion_pulls_the_rest_of_the_day_earlier():
    """Освободившееся время достаётся остатку маршрута, если окна уже открыты."""
    scenario = status_scenario()
    before = plan_optimized(scenario)
    planned = routes_by_engineer(before)["E1"].visits[1].service_start_at

    ev = event(EventType.VISIT_COMPLETED, "10:00", request_id="S1")
    after = replan(before, scenario, ev)

    resumed = first_free_visit(after)
    assert resumed.service_start_at == t("10:00"), (
        "следующая работа обязана начаться с фактического освобождения инженера"
    )
    assert resumed.service_start_at < planned
    assert set(assigned_ids(after)) == {"S1", "S2", "S3"}
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_late_completion_does_not_overlap_the_next_visit():
    """Затянувшаяся работа опровергает допущение «следующая уже идёт по плану».

    Регрессия: визит, чьё плановое начало было в прошлом, замораживался как факт —
    и оставался в маршруте поверх работы, которая на самом деле ещё шла.
    """
    scenario = status_scenario()
    before = plan_optimized(scenario)
    assert routes_by_engineer(before)["E1"].visits[1].service_start_at == t("11:00"), (
        "сценарий собран неверно"
    )

    # В 12:00 по плану следующая работа уже час как идёт, но инженер всё это время был на S1.
    ev = event(EventType.VISIT_COMPLETED, "12:00", request_id="S1")
    after = replan(before, scenario, ev)

    assert visit_of(after, "S1").service_end_at == t("12:00")
    for visit in after.routes[0].visits:
        if visit.locked:
            continue
        assert visit.service_start_at >= t("12:00"), (
            f"{visit.request_id}: работа не может начаться раньше, чем инженер освободился"
        )
    assert any("больше норматива" in w for w in after.warnings)
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_late_completion_moves_what_no_longer_fits():
    """Выбитая из окна заявка ищет нового исполнителя, а не остаётся с нарушением."""
    engineers = [
        eng("E1", skills=["connection"], shift=("09:00", "13:30"), at=HOME, order=0),
        eng("E2", skills=["connection"], shift=("09:00", "18:00"), at=HOME, order=1),
    ]
    requests = [
        req("S1", window=("09:00", "09:30"), dur=120, at=HOME, order=0),   # 09:00–11:00
        req("S2", window=("11:00", "13:00"), dur=120, at=HOME, order=1),   # 11:00–13:00
    ]
    scenario = sc(requests, engineers, name="status-late")
    before = plan_optimized(scenario)
    assert route_ids(before, "E1") == ["S1", "S2"], "сценарий собран неверно"

    # Работа затянулась на час: в смену E1 (до 13:30) вторая заявка больше не помещается.
    ev = event(EventType.VISIT_COMPLETED, "12:00", request_id="S1")
    after = replan(before, scenario, ev)

    moved = assignments_by_id(after)["S2"]
    assert moved.status == AssignmentStatus.ASSIGNED, "заявку можно было сохранить у другого инженера"
    assert moved.engineer_id == "E2"
    assert moved.service_start_at == t("12:00"), "второй инженер свободен и окно ещё открыто"
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_arrival_status_fixes_the_visit_by_fact():
    """Приезд позже плана сдвигает начало работ и замораживает визит по факту."""
    scenario = status_scenario()
    before = plan_optimized(scenario)

    ev = event(EventType.VISIT_ARRIVED, "09:40", request_id="S1")
    after = replan(before, scenario, ev)

    arrived = visit_of(after, "S1")
    assert arrived.arrival_at == t("09:40"), "прибытие обязано быть взято из статуса"
    assert arrived.service_start_at == t("09:40"), "окно открыто — работа начинается сразу"
    assert arrived.service_end_at == t("11:40"), "норматив от фактического начала"
    assert arrived.locked is True
    assert arrived.engineer_id == "E1"
    assert any("на месте" in w for w in after.warnings)
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_unreported_visit_is_assumed_done_as_planned():
    """Молчание — не новость: визит без статуса остаётся с плановым расписанием."""
    scenario = status_scenario()
    before = plan_optimized(scenario)
    planned = visit_of(before, "S1")

    ev = event(EventType.VISIT_COMPLETED, "13:00", request_id="S2")
    after = replan(before, scenario, ev)

    kept = visit_of(after, "S1")
    assert (kept.engineer_id, kept.service_start_at, kept.service_end_at) == (
        planned.engineer_id,
        planned.service_start_at,
        planned.service_end_at,
    ), "визит, по которому статуса не было, трогать нечем и незачем"


def test_status_replan_never_schedules_work_in_the_past():
    """Ремонт по событию — расписание остатка дня, а не переписанное задним числом утро.

    Регрессия: вытесненная заявка уезжала к инженеру, у которого день начинался позже
    события, и вставала ему на 09:00 — при событии в 11:40.
    """
    engineers = [
        eng("E1", skills=["local", "connection"], shift=("09:00", "13:30"), at=HOME, order=0),
        eng("E2", skills=["connection"], shift=("09:00", "17:00"), at=HOME, order=1),
    ]
    requests = [
        req("S1", window=("09:00", "09:30"), dur=120, at=HOME, skill="local", order=0),
        req("D", window=("09:00", "16:00"), dur=120, at=HOME, order=1),
        req("L", window=("15:00", "15:00"), dur=120, at=HOME, order=2),
    ]
    scenario = sc(requests, engineers, name="status-past")
    before = plan_optimized(scenario)
    assert route_ids(before, "E1") == ["S1", "D"], "сценарий собран неверно"

    ev = event(EventType.VISIT_COMPLETED, "11:40", request_id="S1")
    after = replan(before, scenario, ev)

    assert after.not_before == t("11:40"), "план обязан помнить момент, от которого он собран"
    for route in after.routes:
        for visit in route.visits:
            if visit.locked:
                continue
            assert visit.departure_at >= t("11:40"), (
                f"заявка {visit.request_id} назначена задним числом: выезд {hhmm(visit.departure_at)}"
            )
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_status_replan_is_deterministic():
    """Два прогона одного статуса дают побайтово одинаковый план."""
    scenario = status_scenario()
    before = plan_optimized(scenario)
    ev = event(EventType.VISIT_COMPLETED, "10:00", request_id="S1")
    assert normalized_dict(replan(before, scenario, ev)) == normalized_dict(
        replan(before, scenario, ev)
    )


# --------------------------------------------------------------------------
# Степень изменения плана (SPEC §2.5, §6.3)
# --------------------------------------------------------------------------


def ladder_scenario(**overrides):
    """Затянувшаяся работа выбивает D; место для неё есть только вместо дозаказа.

    E1 не успевает D до конца смены, у E2 свободного окна нужной длины нет: до R1
    остаётся 80 минут, после R2 смена кончается. Освободить место можно только
    вытеснением — то есть начиная со средней степени изменения.
    """
    engineers = [
        eng("E1", skills=["local", "connection"], shift=("09:00", "13:30"), at=HOME, order=0),
        eng("E2", skills=["connection"], shift=("09:00", "17:00"), at=HOME, order=1),
    ]
    requests = [
        req("S1", window=("09:00", "09:30"), dur=120, at=HOME, skill="local", order=0),
        req("D", window=("09:00", "16:00"), dur=120, at=HOME, priority="connection", order=1),
        req("R1", window=("13:00", "13:00"), dur=120, at=HOME, priority="repair_or_addon", order=2),
        req("R2", window=("15:00", "15:00"), dur=120, at=HOME, priority="repair_or_addon", order=3),
    ]
    return sc(requests, engineers, name="ladder", **overrides)


def ladder_event():
    return event(EventType.VISIT_COMPLETED, "11:40", request_id="S1")


def test_replan_scope_low_leaves_the_rest_of_the_day_untouched():
    """Низкая степень: только свободные окна — не влезло, значит честный отказ."""
    scenario = ladder_scenario(replan_scope="low")
    before = plan_optimized(scenario)
    assert route_ids(before, "E1") == ["S1", "D"], "сценарий собран неверно"

    after = replan(before, scenario, ladder_event())

    assert "D" in unassigned_ids(after), "низкая степень не вправе никого двигать ради D"
    assert route_ids(after, "E2") == route_ids(before, "E2"), "чужой маршрут обязан остаться как был"
    assert assignments_by_id(after)["D"].explanation, "отказ обязан быть объяснён"


def test_replan_scope_medium_displaces_a_lower_priority_request():
    """Средняя степень: подключение вытесняет дозаказ в пределах одного маршрута."""
    scenario = ladder_scenario(replan_scope="medium")
    before = plan_optimized(scenario)
    after = replan(before, scenario, ladder_event())

    assert "D" in assigned_ids(after), "вытеснение обязано найти место подключению"
    assert assignments_by_id(after)["D"].engineer_id == "E2"
    assert after.metrics.connection_unassigned_count == 0
    assert after.metrics.unassigned_count == 1, "вместо подключения без исполнителя остался дозаказ"
    assert validate_plan(after, scenario_after(scenario, before, ladder_event())) == []


def test_replan_scope_orders_the_ladder_from_cheap_to_expensive():
    """Каждая следующая степень не хуже предыдущей — лестница именно возрастающая."""
    keys = []
    for scope in ("low", "medium", "high"):
        scenario = ladder_scenario(replan_scope=scope)
        before = plan_optimized(scenario)
        after = replan(before, scenario, ladder_event())
        keys.append(after.metrics.quality_key())
        assert validate_plan(after, scenario_after(scenario, before, ladder_event())) == []

    assert keys[1] <= keys[0], "средняя степень обязана быть не хуже низкой"
    assert keys[2] <= keys[1], "высокая степень обязана быть не хуже средней"


def test_replan_scope_defaults_to_high():
    """По умолчанию доступны все три ступени."""
    from planner import ReplanScope

    assert ReplanScope(sc([], []).settings.replan_scope) is ReplanScope.HIGH


def test_replan_scope_can_be_overridden_per_call():
    """Степень можно задать на один вызов — не трогая настройки сценария."""
    scenario = ladder_scenario()          # по умолчанию высокая
    before = plan_optimized(scenario)

    restrained = replan(before, scenario, ladder_event(), scope="low")
    assert "D" in unassigned_ids(restrained), "вызов с низкой степенью обязан вести себя как низкая"

    as_configured = replan(before, scenario, ladder_event())
    assert "D" in assigned_ids(as_configured), "настройка сценария осталась высокой"


def test_low_scope_still_uses_free_slots():
    """Низкая степень — не «ничего не делать»: свободное окно используется всегда."""
    engineers = [
        eng("E1", skills=["connection"], shift=("09:00", "13:30"), at=HOME, order=0),
        eng("E2", skills=["connection"], shift=("09:00", "18:00"), at=HOME, order=1),
    ]
    requests = [
        req("S1", window=("09:00", "09:30"), dur=120, at=HOME, order=0),
        req("S2", window=("11:00", "13:00"), dur=120, at=HOME, order=1),
    ]
    scenario = sc(requests, engineers, replan_scope="low", name="low-free")
    before = plan_optimized(scenario)
    ev = event(EventType.VISIT_COMPLETED, "12:00", request_id="S1")
    after = replan(before, scenario, ev)

    assert assignments_by_id(after)["S2"].engineer_id == "E2", (
        "свободное окно у второго инженера — самая дешёвая ступень, она доступна всегда"
    )
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


# ======================================================================================
# Переобъявление заявки аварией: инвариант «одна заявка — один выезд»
# ======================================================================================


def redeclare_scenario():
    """Один инженер, утренняя работа и дальний вечерний визит."""
    engineers = [eng("E1", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME)]
    requests = [
        req("R1", window=("09:00", "12:00"), dur=60, at=P["R1"], order=0),
        req("R2", window=("14:00", "18:00"), dur=60, at=(55.90, 37.90), order=1),
    ]
    return sc(requests, engineers, name="redeclare")


def test_urgent_request_replacing_a_pending_visit_does_not_duplicate_it():
    """Авария под номером ещё не начатой заявки заменяет её визит, а не добавляет второй."""
    scenario = redeclare_scenario()
    before = plan_optimized(scenario)
    assert "R2" in assigned_ids(before), "предусловие: R2 назначена"

    urgent = req(
        "R2",
        window=("11:00", "18:00"),
        dur=30,
        at=P["R3"],
        skill="emergency",
        priority="emergency",
        received_at="10:30",
    )
    ev = event(EventType.URGENT_REQUEST, "10:30", request=urgent)
    after = replan(before, scenario, ev)

    visits = [v.request_id for route in after.routes for v in route.visits]
    assert visits.count("R2") == 1, f"R2 обязана быть ровно в одном визите: {visits}"
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_urgent_request_replacing_a_pending_visit_uses_the_new_address():
    """Переобъявленный визит переезжает на новые координаты и новый норматив."""
    scenario = redeclare_scenario()
    before = plan_optimized(scenario)

    urgent = req(
        "R2",
        window=("11:00", "18:00"),
        dur=30,
        at=P["R3"],
        skill="emergency",
        priority="emergency",
        received_at="10:30",
    )
    ev = event(EventType.URGENT_REQUEST, "10:30", request=urgent)
    after = replan(before, scenario, ev)

    visit = next(v for route in after.routes for v in route.visits if v.request_id == "R2")
    assert visit.to_point.lat == pytest.approx(P["R3"][0])
    assert visit.service_minutes == pytest.approx(30.0)


def test_urgent_request_for_an_already_started_visit_is_refused():
    """Авария под номером начатой работы не применяется: развернуть её уже нельзя."""
    engineers = [eng("E1", skills=["connection", "emergency"], shift=("09:00", "18:00"), at=HOME)]
    requests = [req("R1", window=("09:00", "12:00"), dur=180, at=P["R1"], order=0)]
    scenario = sc(requests, engineers, name="redeclare-started")
    before = plan_optimized(scenario)
    start = before.assignment_of("R1").service_start_at

    urgent = req(
        "R1",
        window=("11:00", "18:00"),
        dur=30,
        at=P["R5"],
        skill="emergency",
        priority="emergency",
    )
    moment = start + timedelta(minutes=30)
    ev = event(EventType.URGENT_REQUEST, moment, request=urgent)
    after = replan(before, scenario, ev)

    visits = [v.request_id for route in after.routes for v in route.visits]
    assert visits.count("R1") == 1, f"дубля быть не должно: {visits}"
    visit = next(v for route in after.routes for v in route.visits if v.request_id == "R1")
    assert visit.service_minutes == pytest.approx(180.0), (
        "начатая работа считается по прежнему нормативу — событие отклонено"
    )
    assert any("R1" in w and has_cyrillic(w) for w in after.warnings), after.warnings
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


# ======================================================================================
# Отказ клиента: освобождение хвоста дня
# ======================================================================================


def test_refusal_mid_work_releases_the_rest_of_the_route():
    """Отказ посреди работы обрезает визит фактом и сдвигает хвост маршрута влево."""
    engineers = [eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=HOME)]
    requests = [
        req("A", window=("09:00", "12:00"), dur=120, at=P["R1"], order=0),
        req("B", window=("09:00", "17:00"), dur=60, at=P["R2"], order=1),
    ]
    scenario = sc(requests, engineers, name="refusal-tail")
    before = plan_optimized(scenario)
    planned_b = before.assignment_of("B").service_start_at
    moment = before.assignment_of("A").service_start_at + timedelta(minutes=16)

    ev = event(EventType.CLIENT_REFUSAL, moment, request_id="A")
    after = replan(before, scenario, ev)

    visit_a = next(v for route in after.routes for v in route.visits if v.request_id == "A")
    assert visit_a.locked is True
    assert visit_a.service_end_at == moment, (
        f"работа обязана закончиться в момент отказа, а не в {hhmm(visit_a.service_end_at)}"
    )
    assert after.assignment_of("B").service_start_at < planned_b, (
        "освободившееся время должно достаться следующей работе"
    )
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_refusal_on_the_way_keeps_the_trip_and_zeroes_the_work():
    """Отказ, когда инженер уже в пути: поездка состоялась, работа — нет."""
    engineers = [eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=HOME)]
    requests = [req("C", window=("11:00", "16:00"), dur=90, at=(56.20, 38.20), order=0)]
    scenario = sc(requests, engineers, name="refusal-enroute")
    before = plan_optimized(scenario)
    visit_before = next(v for route in before.routes for v in route.visits)
    moment = visit_before.departure_at + timedelta(minutes=30)
    assert moment < visit_before.service_start_at, "предусловие: выехал, но ещё не доехал"

    ev = event(EventType.CLIENT_REFUSAL, moment, request_id="C")
    after = replan(before, scenario, ev)

    visit = next(v for route in after.routes for v in route.visits if v.request_id == "C")
    assert visit.departure_at == visit_before.departure_at, "поездка сохраняется"
    assert visit.distance_km == pytest.approx(visit_before.distance_km)
    assert visit.service_end_at == visit.service_start_at, "работы не было"
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_status_outside_the_shift_is_reported_to_the_dispatcher():
    """Приезд после конца смены — факт, но диспетчер обязан о нём услышать."""
    engineers = [eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=HOME)]
    requests = [req("A", window=("09:00", "18:00"), dur=60, at=P["R1"], order=0)]
    scenario = sc(requests, engineers, name="late-arrival")
    before = plan_optimized(scenario)

    ev = event(EventType.VISIT_ARRIVED, "19:00", request_id="A")
    after = replan(before, scenario, ev)

    assert any("вне графика" in w for w in after.warnings), after.warnings


def test_verifier_honours_now_after_a_frozen_visit():
    """Верификатор считает «сейчас» по тому же правилу, что и планировщик.

    Пол `not_before` действует на **каждую** незамороженную работу, а не только на начало
    маршрута. Раньше после начатого визита курсор верификатора вставал в его окончание и
    про пол забывал: план, корректно поставивший работу на момент события, получал четыре
    расхождения подряд — по выезду, прибытию, началу и концу.
    """
    engineers = [eng("E1", skills=["connection"], shift=("09:00", "20:00"), at=HOME)]
    # Точки выстроены цепочкой от офиса, чтобы порядок объезда был очевиден и
    # оптимизатору нечего было переставлять: весь смысл теста — во временах.
    requests = [
        req("R1", window=("09:00", "10:00"), dur=60, at=P["R1"], order=0),
        req("R2", window=("14:00", "15:00"), dur=60, at=P["R3"], order=1),
        req("R3", window=("09:00", "19:00"), dur=60, at=P["R5"], order=2),
    ]
    scenario = sc(requests, engineers, name="floor-after-frozen")
    before = plan_optimized(scenario)
    assert [v.request_id for v in before.routes[0].visits] == ["R1", "R2", "R3"]

    ev = event(EventType.CANCEL_REQUEST, "12:00", request_id="R2")
    after = replan(before, scenario, ev)

    frozen = next(v for v in after.routes[0].visits if v.request_id == "R1")
    moved = next(v for v in after.routes[0].visits if v.request_id == "R3")
    assert frozen.locked is True, "стенд сломан: R1 обязана быть замороженной"
    assert moved.departure_at >= after.not_before, "работа не может начаться в прошлом"
    assert moved.departure_at > frozen.service_end_at, (
        "стенд сломан: R3 должна была подняться к моменту события, а не встать сразу за R1"
    )
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_status_during_a_break_is_not_reported_as_overtime():
    """Перерыв — не конец смены: работа продолжится после обеда, пугать нечем."""
    engineers = [eng("E1", skills=["connection"], shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME)]
    requests = [req("A", window=("09:00", "18:00"), dur=60, at=P["R1"], order=0)]
    scenario = sc(requests, engineers, name="break-status")
    before = plan_optimized(scenario)

    after = replan(before, scenario, event(EventType.VISIT_ARRIVED, "13:30", request_id="A"))

    notes = [w for w in after.warnings if "перерыв" in w]
    assert notes, after.warnings
    assert not any("за пределы смены" in w for w in after.warnings), after.warnings


def _distant_chain():
    """Инженер из офиса едет далеко и там работает две заявки подряд.

    Расстояние между офисом и рабочей точкой намеренно велико: если ремонт потеряет
    адрес, с которого инженер продолжает день, это видно по пробегу, а не по третьему
    знаку после запятой.
    """
    office = (55.75, 37.60)
    far = (56.30, 38.40)
    near_far = (56.31, 38.41)
    engineers = [eng("E1", skills=["connection"], shift=("09:00", "20:00"), at=office)]
    requests = [
        req("R1", window=("09:00", "18:00"), dur=120, at=far, order=0),
        req("R2", window=("09:00", "20:00"), dur=60, at=near_far, order=1),
    ]
    return sc(requests, engineers, name="distant-chain")


def test_cancelling_started_work_keeps_the_address_to_continue_from():
    """Отмена начатой работы не телепортирует инженера в офис.

    Регрессия: `CANCEL_REQUEST` убирал заявку из сценария целиком, и вместе с ней из
    маршрута пропадала точка, в которой инженер физически стоит. Остаток дня строился
    от офиса — сто километров пробега, которых не будет. Верификатор молчал: он считает
    по тому же усечённому сценарию. Отказ клиента в той же ситуации визит сохраняет.
    """
    scenario = _distant_chain()
    before = plan_optimized(scenario)
    started = before.visit_of("R1")
    moment = started.service_start_at + timedelta(minutes=60)
    assert moment < started.service_end_at, "стенд сломан: работа обязана идти"

    ev = event(EventType.CANCEL_REQUEST, moment, request_id="R1")
    after = replan(before, scenario, ev)

    cancelled = after.visit_of("R1")
    assert cancelled is not None, "начатая работа не может исчезнуть из маршрута"
    assert cancelled.locked is True
    assert cancelled.service_end_at == moment, "работа обрывается моментом отмены"

    tail = after.visit_of("R2")
    assert tail.departure_at == cancelled.service_end_at
    assert tail.distance_km < 10.0, (
        f"хвост дня едет от адреса R1, а не из офиса: {tail.distance_km:.1f} км"
    )
    assert any("R1" in w for w in after.warnings), after.warnings
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_cancelling_work_before_departure_still_removes_it():
    """Граница обратная: пока инженер не выехал, отмена снимает заявку целиком."""
    scenario = _distant_chain()
    before = plan_optimized(scenario)
    ev = event(EventType.CANCEL_REQUEST, "09:00", request_id="R2")
    after = replan(before, scenario, ev)

    assert after.visit_of("R2") is None
    assert "R2" not in assigned_ids(after)
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_cancelling_en_route_keeps_the_trip_and_counts_no_work():
    """Отмена в пути: развернуть выехавшего нельзя, но работать он не начинал."""
    scenario = _distant_chain()
    before = plan_optimized(scenario)
    started = before.visit_of("R1")
    moment = started.departure_at + timedelta(minutes=10)
    assert moment < started.service_start_at, "стенд сломан: инженер обязан быть в пути"

    ev = event(EventType.CANCEL_REQUEST, moment, request_id="R1")
    after = replan(before, scenario, ev)

    visit = after.visit_of("R1")
    assert visit is not None and visit.locked is True
    assert visit.departure_at == started.departure_at, "поездка уже состоялась"
    assert visit.service_end_at == visit.service_start_at, "работа не начиналась"
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []


def test_cancelling_finished_work_changes_nothing():
    """Отмена после планового окончания не удлиняет работу до момента звонка.

    `service_end_at` обрезается границами самого визита: иначе час между окончанием
    работы и отменой засчитывался как работа, и замороженный хвост дня уезжал вправо.
    """
    scenario = _distant_chain()
    before = plan_optimized(scenario)
    done = before.visit_of("R1")
    moment = done.service_end_at + timedelta(minutes=30)

    ev = event(EventType.CANCEL_REQUEST, moment, request_id="R1")
    after = replan(before, scenario, ev)

    visit = after.visit_of("R1")
    assert visit is not None
    assert visit.service_end_at == done.service_end_at
    assert visit.service_minutes == done.service_minutes
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []

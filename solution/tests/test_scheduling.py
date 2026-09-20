# -*- coding: utf-8 -*-
"""Расписание визита и временные окна (SPEC §3.3).

Самая тонкая часть контракта: алгоритм окна сам не сдвигает, раннее
прибытие превращается в ожидание, позднее — в отказ. Проверяем каждую границу
по отдельности, включая распространение времени по цепочке визитов.
"""
from __future__ import annotations

import pytest

from factories import (
    AssignmentStatus,
    ReasonCode,
    TransportMode,
    assert_dt,
    assignments_by_id,
    eng,
    hhmm,
    oracle_calendar,
    oracle_travel_minutes,
    plan_optimized,
    req,
    route_request_ids,
    routes_by_engineer,
    sc,
    t,
    validate_plan,
)

HOME = (55.70, 37.60)
NEAR = (55.705, 37.605)


def only_visit(result, engineer_id="E1"):
    """Единственный визит маршрута — для точечных проверок расписания."""
    route = routes_by_engineer(result)[engineer_id]
    assert len(route.visits) == 1, f"ожидался один визит, получено {len(route.visits)}"
    return route.visits[0]


# --------------------------------------------------------------------------
# Отложенный выезд: ждём до выезда, а не у клиента
# --------------------------------------------------------------------------


def test_departure_is_delayed_so_engineer_does_not_wait_at_the_client():
    """Выезд откладывается до окна: инженер не стоит у подъезда два часа.

    Свободное время остаётся простоем ПЕРЕД выездом (`idle_before_minutes`), а не
    попадает в занятость: иначе маршрут из одной заявки показывал бы полную загрузку.
    """
    scenario = sc(
        [req("R1", window=("11:00", "12:00"), dur=60, at=HOME)],
        [eng("E1", shift=("09:00", "18:00"), at=HOME)],
    )
    result = plan_optimized(scenario)
    visit = only_visit(result)

    assert_dt(visit.service_start_at, t("11:00"), "начало работы = начало окна")
    assert_dt(visit.arrival_at, t("11:00"), "приезжает ровно к началу работ")
    assert visit.waiting_minutes == pytest.approx(0.0, abs=1e-6), "у клиента ждать нечего"
    assert visit.idle_before_minutes == pytest.approx(120.0, abs=1e-6), (
        "два свободных часа до выезда должны быть видны как простой"
    )

    # Смена 540 минут, работы 60, дороги нет: свободны ровно 480 минут. Пока ожидание
    # считалось занятостью, те же 120 минут простоя списывались в busy и «съедали» запас.
    route = routes_by_engineer(result)["E1"]
    assert route.busy_minutes == pytest.approx(60.0, abs=1e-6)
    assert route.free_minutes == pytest.approx(480.0, abs=1e-6), (
        "свободное время дня обязано быть честным, а не съеденным ожиданием"
    )
    assert validate_plan(result, scenario) == []


def test_delayed_departure_never_misses_the_arrival_window():
    """Откладывая выезд, алгоритм не имеет права опоздать в окно прибытия.

    Окно закрывается раньше, чем работа может начаться (заявка поступает позже окна),
    поэтому откат выезда упирается в `window_end`, а не в начало работ.
    """
    scenario = sc(
        [
            req(
                "R1",
                window=("10:00", "11:00"),
                dur=30,
                at=HOME,
                received_at="12:00",
            )
        ],
        [eng("E1", shift=("09:00", "18:00"), at=HOME)],
        service_must_start_within_window=False,
    )
    result = plan_optimized(scenario)
    visit = only_visit(result)

    assert visit.arrival_at <= t("11:00"), "прибытие обязано попасть в окно"
    assert_dt(visit.service_start_at, t("12:00"), "работа не начинается раньше поступления")
    assert visit.waiting_minutes > 0, "остаточное ожидание у клиента здесь неизбежно"
    assert validate_plan(result, scenario) == []


def test_waiting_minutes_equal_working_minutes_between_arrival_and_start():
    """waiting_minutes считается в РАБОЧЕМ времени (перерыв не ожидание)."""
    engineer = eng("E1", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME)
    scenario = sc([req("R1", window=("15:00", "16:00"), dur=30, at=HOME)], [engineer])
    result = plan_optimized(scenario)
    visit = only_visit(result)

    calendar = oracle_calendar(engineer)
    expected = calendar.working_between(visit.arrival_at, visit.service_start_at)
    assert visit.waiting_minutes == pytest.approx(expected, abs=1e-6), (
        f"ожидание {visit.waiting_minutes} != рабочих минут {expected}"
    )
    # Час обеда не должен попасть в ожидание.
    assert visit.waiting_minutes <= 300


def test_no_waiting_when_arrival_is_inside_window():
    """Прибытие внутри окна — работа начинается сразу, ожидание нулевое."""
    scenario = sc(
        [req("R1", window=("09:00", "12:00"), dur=60, at=NEAR)],
        [eng("E1", shift=("09:00", "18:00"), at=HOME)],
    )
    result = plan_optimized(scenario)
    visit = only_visit(result)
    assert visit.waiting_minutes == pytest.approx(0.0, abs=1e-6)
    assert_dt(visit.service_start_at, visit.arrival_at, "старт работы = прибытие")


# --------------------------------------------------------------------------
# Границы окна прибытия
# --------------------------------------------------------------------------


def test_arrival_exactly_at_window_start_is_allowed():
    """Прибытие ровно в начало окна — допустимо (граница включительна)."""
    scenario = sc(
        [req("R1", window=("09:00", "09:00"), dur=60, at=HOME)],
        [eng("E1", shift=("09:00", "18:00"), at=HOME)],
    )
    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]
    assert assignment.status == AssignmentStatus.ASSIGNED
    assert_dt(assignment.service_start_at, t("09:00"), "старт в начале окна")
    assert validate_plan(result, scenario) == []


def test_arrival_exactly_at_window_end_is_allowed():
    """Прибытие ровно в конец окна допустимо: условие arrival <= window_end."""
    engineer = eng("E1", shift=("09:00", "18:00"), at=HOME)
    # Инженер занят первой заявкой ровно до 10:00, ко второй приходит точно в 10:00.
    filler = req("R0", window=("09:00", "09:00"), dur=60, at=HOME)
    second = req("R1", window=("10:00", "10:00"), dur=60, at=HOME)
    scenario = sc([filler, second], [engineer])

    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]
    assert assignment.status == AssignmentStatus.ASSIGNED, "граница window_end отвергнута"
    assert_dt(assignment.arrival_at, t("10:00"), "прибытие ровно в конец окна")
    assert validate_plan(result, scenario) == []


def test_arrival_one_minute_after_window_end_is_rejected():
    """Опоздание даже на минуту — заявка не назначается, окна не сдвигаются."""
    scenario = sc(
        [req("R1", window=("09:00", "09:30"), dur=60, at=HOME)],
        [eng("E1", shift=("10:00", "18:00"), at=HOME)],
    )
    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.reason == ReasonCode.TIME_CONFLICT
    assert validate_plan(result, scenario) == []


def test_window_entirely_before_shift_is_unassigned():
    """Окно целиком до начала смены — назначения быть не может."""
    scenario = sc(
        [req("R1", window=("06:00", "08:00"), dur=30, at=HOME)],
        [eng("E1", shift=("09:00", "18:00"), at=HOME)],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.reason == ReasonCode.TIME_CONFLICT


def test_window_entirely_after_shift_is_unassigned():
    """Окно целиком после конца смены — назначения быть не может."""
    scenario = sc(
        [req("R1", window=("19:00", "21:00"), dur=30, at=HOME)],
        [eng("E1", shift=("09:00", "18:00"), at=HOME)],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.reason == ReasonCode.TIME_CONFLICT


# --------------------------------------------------------------------------
# Границы смены
# --------------------------------------------------------------------------


def test_service_must_fit_inside_shift():
    """Работа, вылезающая за конец смены, недопустима (SPEC §3.3 п.3)."""
    scenario = sc(
        [req("R1", window=("17:30", "17:45"), dur=60, at=HOME)],
        [eng("E1", shift=("09:00", "18:00"), at=HOME)],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.reason == ReasonCode.TIME_CONFLICT


def test_service_ending_exactly_at_shift_end_is_allowed():
    """Работа, заканчивающаяся ровно в 18:00, укладывается в смену."""
    scenario = sc(
        [req("R1", window=("17:00", "17:00"), dur=60, at=HOME)],
        [eng("E1", shift=("09:00", "18:00"), at=HOME)],
    )
    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]
    assert assignment.status == AssignmentStatus.ASSIGNED
    assert_dt(assignment.service_end_at, t("18:00"), "окончание ровно в конце смены")
    assert validate_plan(result, scenario) == []


def test_request_longer_than_whole_shift_is_unassigned():
    """Заявка длиннее всей смены не помещается ни при каком расписании."""
    scenario = sc(
        [req("R1", window=("09:00", "17:00"), dur=600, at=HOME)],
        [eng("E1", shift=("09:00", "18:00"), at=HOME)],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED


def test_request_longer_than_remaining_capacity_across_break_is_unassigned():
    """Суммарной ёмкости двух интервалов не хватает — отказ, а не переработка."""
    scenario = sc(
        [req("R1", window=("09:00", "12:00"), dur=481, at=HOME)],
        [eng("E1", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME)],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED


# --------------------------------------------------------------------------
# Перерыв внутри смены
# --------------------------------------------------------------------------


def test_service_spanning_break_does_not_consume_break_time():
    """Работа, попавшая на обед, растягивается по календарю, но не «съедает» его."""
    engineer = eng("E1", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME)
    scenario = sc([req("R1", window=("12:30", "12:30"), dur=60, at=HOME)], [engineer])
    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]

    assert assignment.status == AssignmentStatus.ASSIGNED
    assert_dt(assignment.service_start_at, t("12:30"), "старт работы")
    assert_dt(assignment.service_end_at, t("14:30"), "окончание после обеда")
    assert validate_plan(result, scenario) == []


def test_service_start_never_moves_past_window_end_when_flag_enabled():
    """При service_must_start_within_window=True старт не переносится за конец окна.

    Окно 12:30-13:10 частично накрыто перерывом 13:00-14:00: перенос старта на
    14:00 был бы выходом за окно, значит такая заявка не назначается.
    """
    engineer = eng("E1", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME)
    request = req("R1", window=("13:05", "13:40"), dur=30, at=HOME)
    scenario = sc([request], [engineer], service_must_start_within_window=True)

    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]
    if assignment.status == AssignmentStatus.ASSIGNED:
        assert assignment.service_start_at <= request.window_end, (
            f"старт {hhmm(assignment.service_start_at)} вышел за конец окна "
            f"{hhmm(request.window_end)} при включённом флаге"
        )
    else:
        assert assignment.reason == ReasonCode.TIME_CONFLICT
    assert validate_plan(result, scenario) == []


def test_request_exactly_inside_break_is_not_served_during_break():
    """Заявка с окном строго внутри перерыва не может обслуживаться в перерыв."""
    engineer = eng("E1", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME)
    scenario = sc([req("R1", window=("13:10", "13:50"), dur=20, at=HOME)], [engineer])
    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]

    if assignment.status == AssignmentStatus.ASSIGNED:
        calendar = oracle_calendar(engineer)
        assert calendar.contains(assignment.service_start_at), (
            f"работа начата в перерыв: {hhmm(assignment.service_start_at)}"
        )
    assert validate_plan(result, scenario) == []


# --------------------------------------------------------------------------
# Внутренняя согласованность визита
# --------------------------------------------------------------------------


def test_visit_fields_are_mutually_consistent():
    """departure <= arrival <= service_start <= service_end и travel/distance согласованы."""
    engineer = eng("E1", shift=("09:00", "18:00"), at=HOME, transport="car")
    scenario = sc(
        [
            req("R1", window=("09:30", "12:00"), dur=70, at=(55.72, 37.62)),
            req("R2", window=("12:00", "16:00"), dur=30, at=(55.74, 37.65)),
        ],
        [engineer],
    )
    result = plan_optimized(scenario)
    route = routes_by_engineer(result)["E1"]
    cfg = scenario.settings

    prev_point = engineer.start_point
    for visit in route.visits:
        assert visit.departure_at <= visit.arrival_at, "отправление позже прибытия"
        assert visit.arrival_at <= visit.service_start_at, "работа раньше прибытия"
        assert visit.service_start_at < visit.service_end_at, "нулевая или отрицательная работа"
        assert visit.from_point == prev_point, "участок начинается не там, где закончился предыдущий"
        expected_travel = oracle_travel_minutes(
            prev_point, visit.to_point, engineer.transport_mode, cfg
        )
        assert visit.travel_minutes == pytest.approx(expected_travel, rel=1e-6), (
            f"{visit.request_id}: время в пути не совпало с формулой"
        )
        prev_point = visit.to_point


def test_latest_departure_at_is_consistent_with_travel_time():
    """latest_departure_at = sub(service_start, travel) — справочное, но обязано сходиться."""
    engineer = eng("E1", shift=("09:00", "18:00"), at=HOME, transport="car")
    scenario = sc([req("R1", window=("14:00", "15:00"), dur=30, at=(55.75, 37.66))], [engineer])
    result = plan_optimized(scenario)
    visit = only_visit(result)

    if visit.latest_departure_at is None:
        pytest.skip("latest_departure_at не заполнен — поле справочное")
    calendar = oracle_calendar(engineer)
    expected = calendar.sub(visit.service_start_at, visit.travel_minutes)
    assert expected is not None
    assert abs((visit.latest_departure_at - expected).total_seconds()) <= 1, (
        f"latest_departure_at {hhmm(visit.latest_departure_at)} != {hhmm(expected)}"
    )
    assert visit.latest_departure_at >= visit.departure_at, "выехать позже крайнего срока нельзя"


# --------------------------------------------------------------------------
# Распространение времени по цепочке (time propagation)
# --------------------------------------------------------------------------


def test_insertion_never_breaks_window_of_later_visits():
    """Вставка второй заявки не имеет права сломать окно третьей.

    Цепочка R1(09:00) -> R2(широкое окно) -> R3(жёсткое окно 12:00-12:10):
    если планировщик вставит R2 между ними «жадно», R3 опоздает. План обязан
    либо переставить порядок, либо отказаться от R2 — но не нарушить окно.
    """
    engineer = eng("E1", shift=("09:00", "18:00"), at=HOME)
    scenario = sc(
        [
            req("R1", window=("09:00", "09:30"), dur=60, at=HOME),
            req("R2", window=("09:00", "17:00"), dur=180, at=HOME),
            req("R3", window=("12:00", "12:10"), dur=60, at=HOME),
        ],
        [engineer],
    )
    result = plan_optimized(scenario)

    assert validate_plan(result, scenario) == [], "план нарушил ограничения при распространении времени"
    by_id = assignments_by_id(result)
    if by_id["R3"].status == AssignmentStatus.ASSIGNED:
        assert by_id["R3"].arrival_at <= scenario.requests[2].window_end


def test_chain_of_three_keeps_all_windows():
    """Три заявки с раздельными окнами — все назначены и все окна соблюдены."""
    engineer = eng("E1", shift=("09:00", "18:00"), at=HOME)
    requests = [
        req("R1", window=("09:00", "10:00"), dur=60, at=HOME),
        req("R2", window=("11:00", "12:00"), dur=60, at=HOME),
        req("R3", window=("14:00", "15:00"), dur=60, at=HOME),
    ]
    scenario = sc(requests, [engineer])
    result = plan_optimized(scenario)

    assert validate_plan(result, scenario) == []
    assert route_request_ids(result, "E1") == ["R1", "R2", "R3"]
    by_id = assignments_by_id(result)
    for request in requests:
        assignment = by_id[request.id]
        assert assignment.status == AssignmentStatus.ASSIGNED
        assert request.window_start <= assignment.service_start_at
        assert assignment.arrival_at <= request.window_end


def test_no_overlap_between_consecutive_services():
    """Работы одного инженера не пересекаются: service_end[i] <= departure[i+1]."""
    engineer = eng("E1", shift=("09:00", "18:00"), at=HOME, transport="car")
    scenario = sc(
        [
            req("R1", window=("09:00", "11:00"), dur=70, at=(55.71, 37.61)),
            req("R2", window=("09:00", "14:00"), dur=80, at=(55.73, 37.64)),
            req("R3", window=("09:00", "17:00"), dur=30, at=(55.69, 37.58)),
        ],
        [engineer],
    )
    result = plan_optimized(scenario)
    route = routes_by_engineer(result)["E1"]
    for prev, nxt in zip(route.visits, route.visits[1:]):
        assert prev.service_end_at <= nxt.departure_at, (
            f"пересечение работ: {prev.request_id} до {hhmm(prev.service_end_at)}, "
            f"{nxt.request_id} выехал в {hhmm(nxt.departure_at)}"
        )


def test_travel_consumes_working_time_only():
    """Перемещение через перерыв растягивается: инженер не едет в обед."""
    engineer = eng(
        "E1", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME, transport="walking"
    )
    scenario = sc([req("R1", window=("09:00", "18:00"), dur=30, at=(55.78, 37.70))], [engineer])
    result = plan_optimized(scenario)
    route = routes_by_engineer(result).get("E1")
    if route is None or not route.visits:
        pytest.skip("заявка не назначена — проверять распространение нечего")

    visit = route.visits[0]
    calendar = oracle_calendar(engineer)
    consumed = calendar.working_between(visit.departure_at, visit.arrival_at)
    assert consumed == pytest.approx(visit.travel_minutes, abs=1e-6), (
        f"перемещение потребило {consumed} рабочих минут вместо {visit.travel_minutes}"
    )


def test_emergency_does_not_start_before_received_at():
    """Работа не начинается раньше поступления: авария в 13:00 при окне с 09:00."""
    request = req(
        "RE",
        window=("09:00", "21:00"),
        dur=100,
        skill="emergency",
        priority="emergency",
        at=HOME,
        received_at="13:00",
    )
    assert request.service_not_before == t("13:00")
    scenario = sc([request], [eng("E1", skills=["emergency"], shift=("09:00", "18:00"), at=HOME)])
    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["RE"]
    assert assignment.status == AssignmentStatus.ASSIGNED
    assert assignment.service_start_at >= t("13:00"), (
        f"авария начата в {hhmm(assignment.service_start_at)}, раньше поступления 13:00"
    )
    assert validate_plan(result, scenario) == []

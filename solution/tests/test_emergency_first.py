# -*- coding: utf-8 -*-
"""Авария — как можно раньше: первой в маршруте, обычная работа её не отодвигает."""
from __future__ import annotations

from planner import replan
from planner.enums import EventType

from factories import (
    assigned_ids,
    eng,
    event,
    plan_optimized,
    req,
    sc,
    scenario_after,
    t,
    validate_plan,
)

HOME = (55.70, 37.60)
NEAR = (55.71, 37.60)
FAR = (55.73, 37.60)
AWAY = (55.90, 37.90)


def visit(result, request_id):
    return next(v for r in result.routes for v in r.visits if v.request_id == request_id)


def route_of(result, request_id):
    return next(r for r in result.routes if any(v.request_id == request_id for v in r.visits))


def test_all_day_emergency_goes_first():
    """Окно на весь день не повод ставить аварию в конец: по дороге выгоднее было бы
    заехать к ближней заявке, но авария — первой."""
    scenario = sc(
        [
            req("R1", window=("09:00", "18:00"), dur=60, at=NEAR),
            req("EM", window=("00:01", "23:59"), dur=80, at=FAR, skill="emergency", priority="emergency"),
        ],
        [eng("E1", skills=["connection", "emergency"], at=HOME)],
    )
    result = plan_optimized(scenario)
    assert assigned_ids(result) == {"R1", "EM"}
    assert [v.request_id for v in result.routes[0].visits] == ["EM", "R1"]
    assert validate_plan(result, scenario) == []


def test_ordinary_request_does_not_delay_an_emergency():
    """Обычная работа не встаёт перед аварией, если та из-за неё начнётся позже."""
    scenario = sc(
        [
            req("R1", window=("09:00", "12:00"), dur=60, at=NEAR),
            req("EM", window=("10:00", "10:30"), dur=60, at=FAR, skill="emergency", priority="emergency"),
        ],
        [eng("E1", skills=["connection", "emergency"], at=HOME)],
    )
    result = plan_optimized(scenario)
    assert assigned_ids(result) == {"R1", "EM"}
    assert visit(result, "EM").service_start_at == t("10:00")
    assert visit(result, "R1").service_start_at >= visit(result, "EM").service_end_at
    assert validate_plan(result, scenario) == []


def test_idle_engineer_takes_the_emergency_if_sooner():
    """Лишний инженер ради более раннего начала аварии — не расточительство: E1 занят
    начатой работой до 14:00, свободный E2 начнёт аварию сразу."""
    scenario = sc(
        [req("R1", window=("12:00", "12:30"), dur=120, at=NEAR)],
        [
            eng("E1", skills=["connection", "emergency"], at=HOME),
            eng("E2", skills=["emergency"], at=HOME),
        ],
    )
    before = plan_optimized(scenario)
    urgent = req(
        "EM", window=("09:00", "18:00"), dur=60, at=NEAR, skill="emergency", priority="emergency", order=100
    )
    ev = event(EventType.URGENT_REQUEST, "12:30", request=urgent)
    after = replan(before, scenario, ev)
    assert route_of(after, "EM").engineer_id == "E2"
    assert visit(after, "EM").service_start_at < t("13:00")
    assert assigned_ids(after) == {"R1", "EM"}


def midday_scenario():
    """У E1 плотный день обычных работ с узкими окнами, E2 далеко и аварии не берёт."""
    return sc(
        [
            req("R1", window=("12:30", "13:00"), dur=60, at=NEAR),
            req("R2", window=("14:00", "14:30"), dur=60, at=NEAR),
            req("R3", window=("15:30", "16:00"), dur=60, at=NEAR),
        ],
        [
            eng("E1", skills=["connection", "emergency"], at=HOME),
            eng("E2", skills=["connection"], at=AWAY),
        ],
    )


def test_midday_emergency_starts_right_away():
    """Авария пришла в 12:00. Свободное место у бригады только в конце дня, но авария
    не ждёт: обычные работы уступают ей место и уходят другим или остаются без исполнителя."""
    scenario = midday_scenario()
    before = plan_optimized(scenario)
    assert {v.request_id for v in route_of(before, "R1").visits} == {"R1", "R2", "R3"}
    urgent = req(
        "EM", window=("12:00", "18:00"), dur=80, at=NEAR, skill="emergency", priority="emergency", order=100
    )
    ev = event(EventType.URGENT_REQUEST, "12:00", request=urgent)
    after = replan(before, scenario, ev)
    assert "EM" in assigned_ids(after)
    assert visit(after, "EM").service_start_at < t("12:30")
    assert validate_plan(after, scenario_after(scenario, before, ev)) == []
    for u in after.unassigned:
        assert "EM" in u.explanation or "авари" in u.explanation.lower(), u.explanation


def test_midday_emergency_without_ejection_waits_for_a_free_slot():
    """Низкая степень изменения плана работы не снимает: авария — в первое свободное место."""
    scenario = midday_scenario()
    before = plan_optimized(scenario)
    urgent = req(
        "EM", window=("12:00", "18:00"), dur=80, at=NEAR, skill="emergency", priority="emergency", order=100
    )
    ev = event(EventType.URGENT_REQUEST, "12:00", request=urgent)
    after = replan(before, scenario, ev, scope="low")
    assert assigned_ids(after) >= {"R1", "R2", "R3", "EM"}
    assert visit(after, "EM").service_start_at > t("16:00")


def test_board_engineer_mode_puts_a_new_emergency_first():
    """«Инженерный» на доске (новая заявка в готовый план посреди дня): авария встаёт
    сразу, а не после всех работ бригады."""
    from planner.dispatch import Board

    from test_dispatch import stored

    scenario = midday_scenario()
    before = plan_optimized(scenario)
    urgent = req(
        "EM", window=("12:00", "18:00"), dur=80, at=NEAR, skill="emergency", priority="emergency", order=100
    )
    board = Board(sc([*scenario.requests, urgent], scenario.engineers, renumber=False), stored(before), now=t("12:00"))
    assert board.place_new(["EM"], scope="medium") == ["EM"]
    result = board.result()
    assert visit(result, "EM").service_start_at < t("12:30")

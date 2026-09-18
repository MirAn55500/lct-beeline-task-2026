# -*- coding: utf-8 -*-
"""Базовый алгоритм (SPEC §6.1, ТЗ п. 2.3).

Baseline — обязательная точка отсчёта для демонстрации выигрыша. Его правило
описано однозначно, поэтому здесь проверяется ТОЧНОЕ поведение: порядок обхода
заявок, выбор первого подходящего инженера и посчитанные вручную времена.
"""
from __future__ import annotations

import pytest

from factories import (
    Algorithm,
    AssignmentStatus,
    ReasonCode,
    assert_dt,
    assignments_by_id,
    eng,
    normalized_dict,
    plan_baseline,
    req,
    route_request_ids,
    routes_by_engineer,
    sc,
    t,
    validate_plan,
)

HOME = (55.70, 37.60)


def manual_scenario():
    """Сценарий с нулевыми перемещениями — расписание считается вручную.

    Все точки совпадают со стартовой точкой инженеров, поэтому travel == 0
    и времена определяются только окнами и длительностями.
    """
    engineers = [
        eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=HOME),
        eng("E2", skills=["connection", "local"], shift=("09:00", "18:00"), at=HOME),
    ]
    requests = [
        req("R1", window=("09:00", "12:00"), dur=60, skill="connection", at=HOME),
        req("R2", window=("09:00", "12:00"), dur=60, skill="connection", at=HOME),
        req("R3", window=("09:00", "12:00"), dur=60, skill="local", at=HOME),
        req("R4", window=("11:30", "12:00"), dur=60, skill="connection", at=HOME),
        req("R5", window=("09:00", "09:30"), dur=60, skill="connection", at=HOME),
    ]
    return sc(requests, engineers, name="manual-baseline")


def test_baseline_reproduces_hand_computed_assignment():
    """Точный список назначений вручную посчитанного сценария."""
    scenario = manual_scenario()
    result = plan_baseline(scenario)
    by_id = assignments_by_id(result)

    assert by_id["R1"].engineer_id == "E1"
    assert by_id["R2"].engineer_id == "E1"
    assert by_id["R3"].engineer_id == "E2"  # у E1 нет навыка local
    assert by_id["R4"].engineer_id == "E1"
    assert by_id["R5"].status == AssignmentStatus.UNASSIGNED
    assert by_id["R5"].reason == ReasonCode.TIME_CONFLICT


def test_baseline_reproduces_hand_computed_times():
    """Точные времена: 09:00-10:00, 10:00-11:00, 11:30-12:30 у E1 и 09:00-10:00 у E2."""
    result = plan_baseline(manual_scenario())
    by_id = assignments_by_id(result)

    assert_dt(by_id["R1"].service_start_at, t("09:00"), "R1 старт")
    assert_dt(by_id["R1"].service_end_at, t("10:00"), "R1 финиш")
    assert_dt(by_id["R2"].service_start_at, t("10:00"), "R2 старт")
    assert_dt(by_id["R2"].service_end_at, t("11:00"), "R2 финиш")
    assert_dt(by_id["R4"].service_start_at, t("11:30"), "R4 старт (ожидание до начала окна)")
    assert_dt(by_id["R4"].service_end_at, t("12:30"), "R4 финиш")
    assert_dt(by_id["R3"].service_start_at, t("09:00"), "R3 старт у E2")
    assert_dt(by_id["R3"].service_end_at, t("10:00"), "R3 финиш у E2")


def test_baseline_visit_order_equals_assignment_order():
    """SPEC §6.1: порядок посещения совпадает с порядком назначения (input_order)."""
    result = plan_baseline(manual_scenario())
    assert route_request_ids(result, "E1") == ["R1", "R2", "R4"]
    assert route_request_ids(result, "E2") == ["R3"]


def test_baseline_positions_are_continuous_from_one():
    """Позиции в маршруте нумеруются с 1 без разрывов."""
    result = plan_baseline(manual_scenario())
    for route in result.routes:
        assert [v.position for v in route.visits] == list(range(1, len(route.visits) + 1))


def test_baseline_waiting_is_recorded_for_early_arrival():
    """R4: инженер освободился в 11:00, а окно с 11:30 — 30 минут ожидания."""
    result = plan_baseline(manual_scenario())
    visit = {v.request_id: v for v in routes_by_engineer(result)["E1"].visits}["R4"]
    assert visit.waiting_minutes == pytest.approx(30.0, abs=1e-6)


def test_baseline_picks_first_suitable_engineer_by_input_order():
    """Из двух одинаково подходящих инженеров выбирается первый во входе."""
    engineers = [eng("E1", order=0, at=HOME), eng("E2", order=1, at=HOME)]
    scenario = sc([req("R1", at=HOME)], engineers)
    assert assignments_by_id(plan_baseline(scenario))["R1"].engineer_id == "E1"


def test_baseline_order_of_engineers_is_respected_after_reordering():
    """Меняем порядок инженеров во входе — меняется и выбор baseline."""
    scenario = sc([req("R1", at=HOME)], [eng("E2", at=HOME), eng("E1", at=HOME)])
    assert assignments_by_id(plan_baseline(scenario))["R1"].engineer_id == "E2"


def test_baseline_processes_requests_in_input_order():
    """Заявки разбираются в порядке input_order: ресурс достаётся ранним."""
    engineer = eng("E1", shift=("09:00", "12:00"), at=HOME)
    scenario = sc(
        [
            req("R1", window=("09:00", "11:00"), dur=120, at=HOME),
            req("R2", window=("09:00", "11:00"), dur=120, at=HOME),
        ],
        [engineer],
    )
    by_id = assignments_by_id(plan_baseline(scenario))
    assert by_id["R1"].status == AssignmentStatus.ASSIGNED, "ранняя заявка должна получить ресурс"
    assert by_id["R2"].status == AssignmentStatus.UNASSIGNED


def test_baseline_appends_only_to_route_end():
    """Baseline не вставляет в середину: обратный порядок окон разводит инженеров.

    Три заявки с убывающими окнами не могут лечь в один маршрут «в конец»,
    хотя физически один инженер выполнил бы их все.
    """
    engineers = [eng(f"E{i}", shift=("09:00", "18:00"), at=HOME, order=i) for i in range(1, 4)]
    requests = [
        req("R1", window=("14:00", "14:00"), dur=60, at=HOME),
        req("R2", window=("12:00", "12:00"), dur=60, at=HOME),
        req("R3", window=("10:00", "10:00"), dur=60, at=HOME),
    ]
    result = plan_baseline(sc(requests, engineers))
    by_id = assignments_by_id(result)
    assert {by_id["R1"].engineer_id, by_id["R2"].engineer_id, by_id["R3"].engineer_id} == {
        "E1",
        "E2",
        "E3",
    }, "baseline обязан задействовать трёх инженеров при убывающих окнах"


def test_baseline_respects_static_constraints():
    """Baseline не имеет права назначить заявку без навыка/региона/транспорта."""
    scenario = sc(
        [
            req("R1", skill="emergency", at=HOME),
            req("R2", region="south", at=HOME),
            req("R3", transport="bicycle", at=HOME),
        ],
        [eng("E1", skills=["connection", "local"], region="east", transport="car", at=HOME)],
    )
    result = plan_baseline(scenario)
    assert result.metrics.assigned_count == 0
    assert validate_plan(result, scenario) == []


def test_baseline_result_is_valid():
    """Любой baseline-план обязан проходить независимый верификатор."""
    scenario = manual_scenario()
    result = plan_baseline(scenario)
    assert validate_plan(result, scenario) == []


def test_baseline_is_deterministic():
    """Три прогона baseline дают идентичный результат."""
    scenario = manual_scenario()
    dumps = [normalized_dict(plan_baseline(scenario)) for _ in range(3)]
    assert dumps[0] == dumps[1] == dumps[2]


def test_baseline_algorithm_is_reported_in_result():
    """PlanResult.algorithm отражает выбранный алгоритм."""
    result = plan_baseline(manual_scenario())
    assert result.algorithm == Algorithm.BASELINE


def test_baseline_does_not_create_empty_routes():
    """Маршрут без визитов не создаётся (SPEC §9 п.7)."""
    scenario = sc([req("R1", at=HOME)], [eng("E1", at=HOME), eng("E2", at=HOME)])
    result = plan_baseline(scenario)
    assert all(route.visits for route in result.routes)
    assert result.metrics.used_engineer_count == 1
    assert result.metrics.available_engineer_count == 2

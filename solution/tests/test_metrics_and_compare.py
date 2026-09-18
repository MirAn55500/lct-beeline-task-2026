# -*- coding: utf-8 -*-
"""Метрики плана (SPEC §7.2, §7.4) и функция сравнения (SPEC §8).

Метрики попадают на дашборд и в отчёт жюри, поэтому они обязаны сходиться с
маршрутами до последнего знака: сумма пробегов, баланс загрузки, покрытие
заявок. Расхождение здесь — это неверная демонстрация выигрыша.
"""
from __future__ import annotations

import pytest

from factories import (
    AssignmentStatus,
    Priority,
    eng,
    oracle_calendar,
    plan_baseline,
    plan_both,
    plan_optimized,
    random_scenario,
    req,
    sc,
    validate_plan,
)

HOME = (55.70, 37.60)


def rich_scenario():
    """Сценарий со всем сразу: назначенные, неназначенные, срочные, ожидание."""
    engineers = [
        eng("E1", shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=(55.72, 37.63), order=1),
        eng("E3", shift=("09:00", "18:00"), at=HOME, skills=["local"], order=2),
    ]
    requests = [
        req("R1", window=("09:30", "11:00"), dur=70, at=(55.71, 37.61)),
        req("R2", window=("11:00", "13:00"), dur=80, at=(55.74, 37.66)),
        req("R3", window=("14:00", "16:00"), dur=30, at=(55.68, 37.57)),
        req("R4", window=("15:00", "17:00"), dur=20, at=(55.75, 37.69), priority="urgent"),
        req("R5", window=("09:00", "18:00"), dur=30, skill="local", at=(55.69, 37.59)),
        req("R6", window=("03:00", "04:00"), dur=30, at=HOME),  # заведомо неназначаемая
        req("R7", window=("09:00", "17:00"), dur=30, skill="emergency", at=HOME),  # нет навыка
    ]
    return sc(requests, engineers, name="rich")


@pytest.fixture(scope="module")
def rich():
    """План по «богатому» сценарию — переиспользуется несколькими тестами."""
    scenario = rich_scenario()
    return scenario, plan_optimized(scenario)


# --------------------------------------------------------------------------
# Покрытие заявок
# --------------------------------------------------------------------------


def test_assigned_plus_unassigned_equals_number_of_requests(rich):
    """SPEC §9 п.1: каждая заявка входа учтена ровно один раз."""
    scenario, result = rich
    m = result.metrics
    assert m.assigned_count + m.unassigned_count == len(scenario.requests)
    assert len(result.assignments) == len(scenario.requests)


def test_unassigned_tuple_is_a_slice_of_assignments(rich):
    """SPEC §7.5: unassigned — именно срез assignments со статусом UNASSIGNED."""
    _scenario, result = rich
    expected = [a for a in result.assignments if a.status == AssignmentStatus.UNASSIGNED]
    assert list(result.unassigned) == expected
    assert result.metrics.unassigned_count == len(expected)


def test_assignments_are_sorted_by_request_input_order(rich):
    """SPEC §7.5: порядок assignments повторяет input_order заявок."""
    scenario, result = rich
    order = {r.id: r.input_order for r in scenario.requests}
    keys = [order[a.request_id] for a in result.assignments]
    assert keys == sorted(keys)


def test_urgent_unassigned_count_matches_priorities(rich):
    """Счётчик срочных отказов согласован с приоритетами заявок входа."""
    scenario, result = rich
    urgent = {r.id for r in scenario.requests if r.priority == Priority.URGENT}
    expected = len([a for a in result.unassigned if a.request_id in urgent])
    assert result.metrics.urgent_unassigned_count == expected


# --------------------------------------------------------------------------
# Пробег и время
# --------------------------------------------------------------------------


def test_total_distance_equals_sum_of_routes(rich):
    """SPEC §9 п.8: сумма пробегов маршрутов равна total_distance_km."""
    _scenario, result = rich
    assert result.metrics.total_distance_km == pytest.approx(
        sum(r.distance_km for r in result.routes), abs=1e-6
    )


def test_total_travel_minutes_equals_sum_of_routes(rich):
    """Суммарное время в пути собирается из маршрутов."""
    _scenario, result = rich
    assert result.metrics.total_travel_minutes == pytest.approx(
        sum(r.travel_minutes for r in result.routes), abs=1e-6
    )


def test_route_totals_equal_sum_of_visits(rich):
    """Итоги маршрута — сумма по визитам, без «потерянных» участков."""
    _scenario, result = rich
    for route in result.routes:
        assert route.distance_km == pytest.approx(sum(v.distance_km for v in route.visits), abs=1e-6)
        assert route.travel_minutes == pytest.approx(
            sum(v.travel_minutes for v in route.visits), abs=1e-6
        )
        assert route.waiting_minutes == pytest.approx(
            sum(v.waiting_minutes for v in route.visits), abs=1e-6
        )


def test_total_service_minutes_equals_sum_of_assigned_durations(rich):
    """Время работ — сумма длительностей назначенных заявок."""
    scenario, result = rich
    durations = {r.id: r.duration_minutes for r in scenario.requests}
    expected = sum(
        durations[a.request_id]
        for a in result.assignments
        if a.status == AssignmentStatus.ASSIGNED
    )
    assert result.metrics.total_service_minutes == pytest.approx(expected, abs=1e-6)


def test_route_service_minutes_equals_sum_of_durations(rich):
    """Время работ по маршруту — сумма длительностей его визитов."""
    scenario, result = rich
    durations = {r.id: r.duration_minutes for r in scenario.requests}
    for route in result.routes:
        expected = sum(durations[v.request_id] for v in route.visits)
        assert route.service_minutes == pytest.approx(expected, abs=1e-6)


# --------------------------------------------------------------------------
# Загрузка инженера
# --------------------------------------------------------------------------


def test_busy_minutes_equal_service_plus_travel_plus_waiting(rich):
    """SPEC §7.2: busy = service + travel + waiting."""
    _scenario, result = rich
    for route in result.routes:
        assert route.busy_minutes == pytest.approx(
            route.service_minutes + route.travel_minutes + route.waiting_minutes, abs=1e-6
        ), f"{route.engineer_id}: busy не сходится"


def test_free_minutes_equal_capacity_minus_busy(rich):
    """SPEC §7.2: free = capacity - busy."""
    _scenario, result = rich
    for route in result.routes:
        assert route.free_minutes == pytest.approx(
            route.capacity_minutes - route.busy_minutes, abs=1e-6
        ), f"{route.engineer_id}: free не сходится"


def test_capacity_matches_engineer_calendar(rich):
    """Ёмкость маршрута берётся из рабочего календаря инженера."""
    scenario, result = rich
    engineers = {e.id: e for e in scenario.engineers}
    for route in result.routes:
        expected = oracle_calendar(engineers[route.engineer_id]).capacity_minutes
        assert route.capacity_minutes == pytest.approx(expected, abs=1e-6)


def test_utilization_is_within_unit_interval(rich):
    """Загрузка — доля, значит строго в [0, 1]."""
    _scenario, result = rich
    for route in result.routes:
        assert 0.0 <= route.utilization <= 1.0, f"{route.engineer_id}: utilization={route.utilization}"
        assert route.utilization == pytest.approx(
            route.busy_minutes / route.capacity_minutes, abs=1e-9
        )
    assert 0.0 <= result.metrics.avg_utilization <= 1.0


def test_utilization_is_zero_for_zero_capacity():
    """SPEC §7.2: при capacity == 0 загрузка равна 0.0, а не деление на ноль."""
    scenario = sc([req("R1", at=HOME)], [eng("E1", shift=(), at=HOME), eng("E2", at=HOME)])
    result = plan_optimized(scenario)
    assert result.metrics.avg_utilization >= 0.0
    for route in result.routes:
        if route.capacity_minutes == 0:
            assert route.utilization == pytest.approx(0.0)


def test_busy_never_exceeds_capacity(rich):
    """Инженер не может быть занят больше, чем длится его смена."""
    _scenario, result = rich
    for route in result.routes:
        assert route.busy_minutes <= route.capacity_minutes + 1e-6, (
            f"{route.engineer_id}: переработка {route.busy_minutes} > {route.capacity_minutes}"
        )
        assert route.free_minutes >= -1e-6


def test_per_engineer_metrics_cover_used_engineers(rich):
    """per_engineer покрывает как минимум всех задействованных инженеров."""
    _scenario, result = rich
    per_ids = {m.engineer_id for m in result.metrics.per_engineer}
    used_ids = {r.engineer_id for r in result.routes}
    assert used_ids <= per_ids, f"нет метрик для {sorted(used_ids - per_ids)}"


def test_used_and_available_engineer_counts(rich):
    """used считает непустые маршруты, available — доступных инженеров входа."""
    scenario, result = rich
    assert result.metrics.used_engineer_count == len([r for r in result.routes if r.visits])
    assert result.metrics.available_engineer_count <= len(scenario.engineers)
    assert result.metrics.used_engineer_count <= result.metrics.available_engineer_count


def test_polyline_starts_at_engineer_start_point(rich):
    """SPEC §9 п.9: маршрут стартует в стартовой точке, возврат не планируется."""
    scenario, result = rich
    engineers = {e.id: e for e in scenario.engineers}
    for route in result.routes:
        start = engineers[route.engineer_id].start_point
        assert route.start_point == start
        assert route.polyline[0] == start
        assert len(route.polyline) == len(route.visits) + 1, "в polyline лишняя или недостающая точка"
        assert route.polyline[-1] == route.visits[-1].to_point, "запланирован возврат на базу"


def test_constraints_valid_flag_agrees_with_validator(rich):
    """Флаг constraints_valid согласован с независимым верификатором."""
    scenario, result = rich
    assert result.metrics.constraints_valid is (validate_plan(result, scenario) == [])


def test_computation_ms_is_non_negative(rich):
    """Время расчёта измеряется и неотрицательно."""
    _scenario, result = rich
    assert result.metrics.computation_ms >= 0


# --------------------------------------------------------------------------
# compare()
# --------------------------------------------------------------------------


def test_compare_returns_deltas_in_both_directions():
    """compare() симметрична по знаку: перестановка аргументов меняет знак дельт."""
    scenario = rich_scenario()
    baseline, optimized = plan_both(scenario)
    forward = compare_dict(baseline, optimized)
    backward = compare_dict(optimized, baseline)

    numeric_keys = [
        key
        for key in forward
        if isinstance(forward[key], (int, float))
        and not isinstance(forward[key], bool)
        and key in backward
        and isinstance(backward[key], (int, float))
    ]
    assert numeric_keys, f"compare() не вернула числовых дельт: {sorted(forward)}"
    opposite = [
        key
        for key in numeric_keys
        if forward[key] != 0 and forward[key] == pytest.approx(-backward[key])
    ]
    assert opposite, (
        "ни одна числовая величина не поменяла знак при перестановке аргументов: "
        f"{ {k: (forward[k], backward[k]) for k in numeric_keys} }"
    )


def compare_dict(baseline, optimized):
    """Все числовые листья результата compare() по точечным путям."""
    from factories import compare as _compare

    raw = _compare(baseline, optimized)
    assert isinstance(raw, dict), "compare() обязана возвращать dict (SPEC §8)"

    flat = {}

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        else:
            flat[path] = node

    walk(raw)
    return flat


def test_compare_is_json_serializable():
    """Результат сравнения уходит в отчёт, значит сериализуется без хаков."""
    import json

    from factories import compare as _compare

    scenario = rich_scenario()
    baseline, optimized = plan_both(scenario)
    json.dumps(_compare(baseline, optimized))


def test_compare_reflects_improvement_on_trap_scenario():
    """На сценарии, где optimized строго лучше, сравнение это показывает."""
    engineers = [
        eng("E1", shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", shift=("12:00", "18:00"), at=HOME, order=1),
    ]
    requests = [
        req("RW1", window=("09:00", "17:00"), dur=150, at=HOME),
        req("RW2", window=("09:00", "17:00"), dur=150, at=HOME),
        req("RW3", window=("09:00", "17:00"), dur=150, at=HOME),
        req("R_EARLY", window=("09:00", "09:30"), dur=60, at=HOME),
    ]
    scenario = sc(requests, engineers)
    baseline, optimized = plan_both(scenario)
    assert optimized.metrics.assigned_count > baseline.metrics.assigned_count
    flat = compare_dict(baseline, optimized)
    assert any(
        isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0 for v in flat.values()
    ), "compare() не отразила выигрыш"


@pytest.mark.slow
@pytest.mark.parametrize("seed", [5, 15])
def test_metrics_are_consistent_on_random_scenarios(seed):
    """Те же тождества на случайных сценариях — метрики не «плывут» на объёме."""
    scenario = random_scenario(seed, n_engineers=6, n_requests=35, time_limit_seconds=2.0)
    for result in (plan_baseline(scenario), plan_optimized(scenario)):
        m = result.metrics
        assert m.assigned_count + m.unassigned_count == len(scenario.requests)
        assert m.total_distance_km == pytest.approx(
            sum(r.distance_km for r in result.routes), abs=1e-6
        )
        assert m.used_engineer_count == len([r for r in result.routes if r.visits])
        for route in result.routes:
            assert route.busy_minutes == pytest.approx(
                route.service_minutes + route.travel_minutes + route.waiting_minutes, abs=1e-6
            )
            assert 0.0 <= route.utilization <= 1.0

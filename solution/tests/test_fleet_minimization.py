# -*- coding: utf-8 -*-
"""Минимизация числа задействованных исполнителей (SPEC §6.2 п.3, §5.1).

База знаний ставит число исполнителей выше времени в пути: лишний выехавший
инженер дороже лишних километров. При этом «схлопывание» маршрута не имеет
права стоить ни одной размещённой заявки.
"""
from __future__ import annotations

import pytest

from factories import (
    assigned_ids,
    eng,
    plan_baseline,
    plan_both,
    plan_optimized,
    random_scenario,
    req,
    sc,
    validate_plan,
)

HOME = (55.70, 37.60)


def scenario_five_fit_two():
    """Пять заявок по 90 минут, входной порядок — по убыванию окон.

    Физически хватает двух инженеров (12:00+14:00+16:00 и 13:00+15:00),
    но жадное «в конец маршрута» раскидывает их по пяти.
    """
    engineers = [eng(f"E{i}", shift=("09:00", "19:00"), at=HOME, order=i - 1) for i in range(1, 6)]
    requests = [
        req("R16", window=("16:00", "16:00"), dur=90, at=HOME),
        req("R15", window=("15:00", "15:00"), dur=90, at=HOME),
        req("R14", window=("14:00", "14:00"), dur=90, at=HOME),
        req("R13", window=("13:00", "13:00"), dur=90, at=HOME),
        req("R12", window=("12:00", "12:00"), dur=90, at=HOME),
    ]
    return sc(requests, engineers, name="five-fit-two")


def test_baseline_uses_many_engineers_on_this_scenario():
    """Контроль: жадный вариант действительно задействует лишних инженеров."""
    baseline = plan_baseline(scenario_five_fit_two())
    assert baseline.metrics.assigned_count == 5
    assert baseline.metrics.used_engineer_count >= 4, (
        f"baseline задействовал {baseline.metrics.used_engineer_count} — сценарий не показателен"
    )


def test_optimized_uses_fewer_engineers_than_baseline():
    """Optimized обязан собрать те же заявки меньшим числом исполнителей."""
    scenario = scenario_five_fit_two()
    baseline, optimized = plan_both(scenario)
    assert optimized.metrics.assigned_count == baseline.metrics.assigned_count == 5
    assert optimized.metrics.used_engineer_count < baseline.metrics.used_engineer_count, (
        f"used: optimized {optimized.metrics.used_engineer_count} vs "
        f"baseline {baseline.metrics.used_engineer_count}"
    )
    assert validate_plan(optimized, scenario) == []


def test_optimized_reaches_two_engineers_or_fewer():
    """Физически достижимый минимум для этого сценария — два инженера."""
    optimized = plan_optimized(scenario_five_fit_two())
    assert optimized.metrics.used_engineer_count <= 2


def test_fleet_minimization_never_reduces_assigned_count():
    """SPEC §6.2 п.3: число назначенных заявок не имеет права уменьшиться."""
    base = scenario_five_fit_two()
    without = plan_optimized(sc(base.requests, base.engineers, enable_fleet_minimization=False))
    with_fm = plan_optimized(sc(base.requests, base.engineers, enable_fleet_minimization=True))
    assert with_fm.metrics.assigned_count >= without.metrics.assigned_count, (
        "минимизация парка потеряла заявку"
    )
    assert with_fm.metrics.used_engineer_count <= without.metrics.used_engineer_count


def test_fleet_minimization_is_tempting_but_must_not_drop_request():
    """Схлопывание соблазнительно: один маршрут из одной «неудобной» заявки.

    R_LONELY можно выполнить только E2 (узкое окно + смена E1 начинается позже),
    поэтому распустить маршрут E2 нельзя — заявка потеряется.
    """
    engineers = [
        eng("E1", shift=("12:00", "20:00"), at=HOME, order=0),
        eng("E2", shift=("08:00", "12:00"), at=HOME, order=1),
    ]
    requests = [
        req("R_LONELY", window=("08:30", "09:00"), dur=60, at=HOME),
        req("RA", window=("13:00", "17:00"), dur=60, at=HOME),
        req("RB", window=("13:00", "17:00"), dur=60, at=HOME),
    ]
    scenario = sc(requests, engineers, name="tempting-collapse")

    for enabled in (False, True):
        result = plan_optimized(
            sc(scenario.requests, scenario.engineers, enable_fleet_minimization=enabled)
        )
        assert "R_LONELY" in assigned_ids(result), (
            f"enable_fleet_minimization={enabled}: одинокая заявка потеряна"
        )
        assert result.metrics.assigned_count == 3


@pytest.mark.slow
@pytest.mark.parametrize("seed", [101, 202, 303])
def test_fleet_minimization_preserves_assigned_count_on_random_scenarios(seed):
    """На случайных сценариях включение минимизации не теряет заявок."""
    base = random_scenario(seed, n_engineers=8, n_requests=40, time_limit_seconds=2.0)
    without = plan_optimized(
        sc(base.requests, base.engineers, enable_fleet_minimization=False, time_limit_seconds=2.0)
    )
    with_fm = plan_optimized(
        sc(base.requests, base.engineers, enable_fleet_minimization=True, time_limit_seconds=2.0)
    )
    assert with_fm.metrics.assigned_count >= without.metrics.assigned_count
    assert with_fm.metrics.quality_key() <= without.metrics.quality_key()


def test_used_engineer_count_equals_number_of_non_empty_routes():
    """SPEC §9 п.7: метрика считает именно непустые маршруты."""
    scenario = scenario_five_fit_two()
    for result in plan_both(scenario):
        non_empty = [r for r in result.routes if r.visits]
        assert result.metrics.used_engineer_count == len(non_empty)
        assert len(result.routes) == len(non_empty), "в результате остались пустые маршруты"


def test_routes_are_sorted_by_engineer_input_order():
    """SPEC §7.5: маршруты упорядочены по input_order инженера."""
    scenario = scenario_five_fit_two()
    order = {e.id: e.input_order for e in scenario.engineers}
    for result in plan_both(scenario):
        keys = [order[r.engineer_id] for r in result.routes]
        assert keys == sorted(keys), f"маршруты не отсортированы: {keys}"


def test_unused_engineer_has_no_route_but_is_counted_as_available():
    """Незадействованный инженер не создаёт маршрут, но попадает в available."""
    scenario = sc(
        [req("R1", at=HOME)],
        [eng("E1", at=HOME), eng("E2", at=HOME), eng("E3", at=HOME)],
    )
    result = plan_optimized(scenario)
    assert result.metrics.used_engineer_count == 1
    assert result.metrics.available_engineer_count == 3
    assert len(result.routes) == 1

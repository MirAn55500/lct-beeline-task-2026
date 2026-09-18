# -*- coding: utf-8 -*-
"""Публичные точки расширения: `PlanContext` и `solve()` (SPEC §8, §6.2).

`plan()` — это `PlanContext` + `solve()` + сборка отчёта. Обе части объявлены
публичными, значит на них можно строить свои сценарии использования (подменить
модель перемещения, прогнать несколько алгоритмов на одном окружении), и их
контракт должен быть зафиксирован отдельно от `plan()`.
"""
from __future__ import annotations

import copy

import pytest

from factories import (
    Algorithm,
    TransportMode,
    eng,
    oracle_calendar,
    oracle_travel_minutes,
    plan,
    random_scenario,
    req,
    sc,
    solve,
    sym,
    t,
)

PlanContext = sym("PlanContext")
HaversineTravelModel = sym("HaversineTravelModel")
MatrixTravelModel = sym("MatrixTravelModel")

HOME = (55.70, 37.60)


def small_scenario():
    """Небольшой сценарий с перерывом и двумя точками."""
    engineers = [
        eng("E1", shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=(55.72, 37.63), order=1),
    ]
    requests = [
        req("R1", window=("09:30", "12:00"), dur=70, at=(55.71, 37.61)),
        req("R2", window=("14:00", "16:00"), dur=30, at=(55.74, 37.66)),
    ]
    return sc(requests, engineers, name="context")


# --------------------------------------------------------------------------
# PlanContext
# --------------------------------------------------------------------------


def test_context_exposes_scenario_and_settings():
    """Контекст не копирует вход, а ссылается на него."""
    scenario = small_scenario()
    ctx = PlanContext(scenario)
    assert ctx.scenario is scenario
    assert ctx.settings is scenario.settings


def test_context_origin_is_midnight_of_plan_date():
    """origin — полночь даты плана: общая нулевая отметка всех расчётов."""
    ctx = PlanContext(small_scenario())
    assert ctx.origin == t("00:00")
    assert ctx.origin.utcoffset() is not None, "origin обязан быть timezone-aware"


def test_context_minutes_conversion_is_reversible():
    """to_minutes/to_datetime — взаимно обратные преобразования."""
    ctx = PlanContext(small_scenario())
    for label in ("09:00", "13:47", "18:00"):
        moment = t(label)
        assert ctx.to_datetime(ctx.to_minutes(moment)) == moment


def test_context_to_minutes_matches_offset_from_origin():
    """Минуты считаются именно от origin, без скрытых сдвигов."""
    ctx = PlanContext(small_scenario())
    assert ctx.to_minutes(t("09:00")) == pytest.approx(540.0)
    assert ctx.to_minutes(t("00:00")) == pytest.approx(0.0)


def test_context_to_datetime_of_none_is_none():
    """None прозрачно проходит через конвертацию — так удобнее в расчётах."""
    ctx = PlanContext(small_scenario())
    assert ctx.to_datetime(None) is None


def test_context_builds_calendar_per_engineer():
    """У каждого инженера свой календарь с его собственной ёмкостью."""
    scenario = small_scenario()
    ctx = PlanContext(scenario)
    for engineer in scenario.engineers:
        calendar = ctx.calendar(engineer)
        assert calendar.capacity_minutes == pytest.approx(
            oracle_calendar(engineer).capacity_minutes
        ), f"{engineer.id}: ёмкость календаря не совпала"


def test_context_reuses_the_same_calendar_object():
    """Календари строятся один раз: это горячий путь конструктивной фазы."""
    scenario = small_scenario()
    ctx = PlanContext(scenario)
    engineer = scenario.engineers[0]
    assert ctx.calendar(engineer) is ctx.calendar(engineer)


def test_context_default_travel_model_is_haversine():
    """Без явной модели перемещения берётся расчёт по координатам."""
    ctx = PlanContext(small_scenario())
    assert isinstance(ctx.travel, HaversineTravelModel)


def test_context_accepts_injected_travel_model():
    """Модель перемещения подменяется без правок алгоритма (SPEC §3.2)."""
    scenario = small_scenario()
    injected = MatrixTravelModel({}, {}, HaversineTravelModel(scenario.settings))
    ctx = PlanContext(scenario, injected)
    assert ctx.travel is injected


def test_context_travel_matches_formula():
    """Контекст отдаёт те же значения, что и независимый расчёт по SPEC."""
    scenario = small_scenario()
    ctx = PlanContext(scenario)
    a = scenario.engineers[0].start_point
    b = scenario.requests[0].point
    assert ctx.travel.travel_minutes(a, b, TransportMode.CAR) == pytest.approx(
        oracle_travel_minutes(a, b, TransportMode.CAR, scenario.settings), rel=1e-9
    )


def test_context_timing_matches_request_window():
    """timing() переводит окно заявки в минуты от origin без искажений."""
    scenario = small_scenario()
    ctx = PlanContext(scenario)
    request = scenario.requests[0]
    timing = ctx.timing(request)
    assert timing.window_start == pytest.approx(ctx.to_minutes(request.window_start))
    assert timing.window_end == pytest.approx(ctx.to_minutes(request.window_end))
    assert timing.duration == pytest.approx(float(request.duration_minutes))


def test_context_does_not_mutate_scenario():
    """Построение контекста — операция только на чтение."""
    scenario = small_scenario()
    snapshot = copy.deepcopy(scenario)
    PlanContext(scenario)
    assert scenario == snapshot


# --------------------------------------------------------------------------
# solve()
# --------------------------------------------------------------------------


@pytest.mark.parametrize("algorithm", [Algorithm.BASELINE, Algorithm.OPTIMIZED])
def test_solve_returns_solution_with_quality_key(algorithm):
    """solve() отдаёт внутреннее решение, по которому уже можно судить о качестве."""
    ctx = PlanContext(small_scenario())
    solution = solve(ctx, algorithm)
    assert hasattr(solution, "quality_key")
    key = solution.quality_key()
    assert isinstance(key, tuple) and len(key) >= 3


@pytest.mark.parametrize("algorithm", [Algorithm.BASELINE, Algorithm.OPTIMIZED])
def test_solve_is_deterministic(algorithm):
    """Два вызова на одинаковом контексте дают одинаковое качество и состав."""
    scenario = small_scenario()
    first = solve(PlanContext(scenario), algorithm)
    second = solve(PlanContext(scenario), algorithm)
    assert first.quality_key() == second.quality_key()
    assert first.assigned_ids() == second.assigned_ids()


def test_solve_optimized_is_not_worse_than_baseline():
    """Та же гарантия качества, что и у plan(), но на уровне solve()."""
    scenario = random_scenario(31, n_engineers=5, n_requests=25, time_limit_seconds=2.0)
    baseline = solve(PlanContext(scenario), Algorithm.BASELINE)
    optimized = solve(PlanContext(scenario), Algorithm.OPTIMIZED)
    assert optimized.quality_key() <= baseline.quality_key()


def test_solve_agrees_with_plan_on_the_same_scenario():
    """solve() и plan() описывают одно и то же решение, а не расходятся."""
    scenario = small_scenario()
    solution = solve(PlanContext(scenario), Algorithm.OPTIMIZED)
    result = plan(scenario, Algorithm.OPTIMIZED)
    # assigned_count у Solution — метод, а суммарные показатели — свойства.
    assert solution.assigned_count() == result.metrics.assigned_count
    assert solution.used_engineer_count == result.metrics.used_engineer_count
    assert solution.total_distance_km == pytest.approx(result.metrics.total_distance_km, abs=1e-6)
    assert solution.total_travel_minutes == pytest.approx(
        result.metrics.total_travel_minutes, abs=1e-6
    )


def test_solve_totals_are_non_negative():
    """Суммарные показатели решения не могут быть отрицательными."""
    solution = solve(PlanContext(small_scenario()), Algorithm.OPTIMIZED)
    for name in (
        "total_distance_km",
        "total_travel_minutes",
        "total_service_minutes",
        "total_waiting_minutes",
    ):
        assert getattr(solution, name) >= 0.0, f"{name} отрицательный"


def test_solve_respects_injected_travel_model():
    """Подменённая модель перемещения доходит до решения через контекст."""
    scenario = sc(
        [req("R1", window=("09:00", "17:00"), dur=30, at=(55.80, 37.75))],
        [eng("E1", shift=("09:00", "18:00"), at=HOME, transport="car")],
    )
    start = scenario.engineers[0].start_point
    point = scenario.requests[0].point
    key_a = f"{start.lat:.6f},{start.lon:.6f}"
    key_b = f"{point.lat:.6f},{point.lon:.6f}"
    key = (key_a, key_b, TransportMode.CAR) if key_a <= key_b else (key_b, key_a, TransportMode.CAR)

    matrix = MatrixTravelModel(
        {key: 2.0}, {key: 4.0}, HaversineTravelModel(scenario.settings)
    )
    solution = solve(PlanContext(scenario, matrix), Algorithm.OPTIMIZED)
    assert solution.total_distance_km == pytest.approx(2.0)
    assert solution.total_travel_minutes == pytest.approx(4.0)

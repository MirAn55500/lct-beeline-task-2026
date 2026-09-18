# -*- coding: utf-8 -*-
"""Детерминизм, чистота и производительность (SPEC §0, §6.2, §9 п.10).

Детерминизм — требование ТЗ: демонстрация не должна «плавать» между запусками.
Чистота plan() — требование к API: сценарий переиспользуется для baseline и
optimized, мутация одного прогона отравит второй.
"""
from __future__ import annotations

import copy
import json
import random
import time

import pytest

from factories import (
    Algorithm,
    eng,
    normalized_dict,
    plan,
    plan_baseline,
    plan_optimized,
    random_scenario,
    req,
    sc,
    validate_plan,
)

HOME = (55.70, 37.60)


def medium_scenario():
    """Сценарий среднего размера — достаточно разнообразный, но быстрый."""
    return random_scenario(2026, n_engineers=6, n_requests=30, time_limit_seconds=2.0)


# --------------------------------------------------------------------------
# Детерминизм
# --------------------------------------------------------------------------


@pytest.mark.parametrize("algorithm", [Algorithm.BASELINE, Algorithm.OPTIMIZED])
def test_three_runs_produce_identical_result(algorithm):
    """Три прогона одного сценария дают идентичный to_dict() (без времени расчёта)."""
    scenario = medium_scenario()
    dumps = [normalized_dict(plan(scenario, algorithm)) for _ in range(3)]
    assert dumps[0] == dumps[1], f"{algorithm}: прогоны 1 и 2 различаются"
    assert dumps[1] == dumps[2], f"{algorithm}: прогоны 2 и 3 различаются"


def test_identical_scenarios_built_separately_give_identical_plans():
    """Два одинаково собранных сценария планируются одинаково (нет скрытого состояния)."""
    first = normalized_dict(plan_optimized(medium_scenario()))
    second = normalized_dict(plan_optimized(medium_scenario()))
    assert first == second


def test_metrics_are_identical_across_runs():
    """Ключ качества стабилен между прогонами — иначе сравнение планов бессмысленно."""
    scenario = medium_scenario()
    keys = [plan_optimized(scenario).metrics.quality_key() for _ in range(3)]
    assert keys[0] == keys[1] == keys[2]


# --------------------------------------------------------------------------
# Сериализация
# --------------------------------------------------------------------------


@pytest.mark.parametrize("algorithm", [Algorithm.BASELINE, Algorithm.OPTIMIZED])
def test_result_is_json_serializable_without_default_hook(algorithm):
    """SPEC §7.5: json.dumps(result.to_dict()) работает без default=."""
    scenario = medium_scenario()
    payload = json.dumps(plan(scenario, algorithm).to_dict(), ensure_ascii=False)
    assert payload and json.loads(payload)


def test_to_dict_contains_no_python_objects():
    """В to_dict() только примитивы, списки и словари — иначе фронт не прочитает."""
    allowed = (str, int, float, bool, type(None), list, dict)

    def walk(node, path="root"):
        assert isinstance(node, allowed), f"{path}: непримитивный тип {type(node).__name__}"
        if isinstance(node, dict):
            for key, value in node.items():
                assert isinstance(key, str), f"{path}: нестроковый ключ {key!r}"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(plan_optimized(medium_scenario()).to_dict())


def test_serialized_plans_are_byte_identical_across_runs():
    """Побайтовое равенство JSON — самая жёсткая формулировка детерминизма."""
    scenario = medium_scenario()
    dumps = [
        json.dumps(normalized_dict(plan_optimized(scenario)), ensure_ascii=False, sort_keys=True)
        for _ in range(2)
    ]
    assert dumps[0] == dumps[1]


# --------------------------------------------------------------------------
# Чистота plan()
# --------------------------------------------------------------------------


def test_plan_does_not_mutate_scenario():
    """SPEC §9 п.10: plan() не меняет переданный Scenario и его объекты."""
    scenario = medium_scenario()
    before = copy.deepcopy(scenario)
    plan_optimized(scenario)
    plan_baseline(scenario)
    assert scenario == before, "plan() изменил сценарий"


def test_plan_does_not_mutate_settings():
    """Настройки мутабельны — тем важнее, что планировщик их не правит."""
    import dataclasses

    scenario = medium_scenario()
    names = [f.name for f in dataclasses.fields(scenario.settings)]
    snapshot = {name: copy.deepcopy(getattr(scenario.settings, name)) for name in names}
    plan_optimized(scenario)
    actual = {name: getattr(scenario.settings, name) for name in names}
    assert actual == snapshot, "plan() изменил Settings"


def test_running_both_algorithms_does_not_cross_contaminate():
    """Порядок запуска алгоритмов не влияет на результат каждого из них."""
    scenario = medium_scenario()
    baseline_first = normalized_dict(plan_baseline(scenario))
    plan_optimized(scenario)
    baseline_again = normalized_dict(plan_baseline(scenario))
    assert baseline_first == baseline_again


# --------------------------------------------------------------------------
# Устойчивость к перестановке входа
# --------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_shuffled_input_still_produces_valid_plan(seed):
    """Перестановка заявок и инженеров может менять качество, но не валидность."""
    base = random_scenario(seed, n_engineers=5, n_requests=25)
    rnd = random.Random(seed * 977)
    requests = list(base.requests)
    engineers = list(base.engineers)
    rnd.shuffle(requests)
    rnd.shuffle(engineers)
    shuffled = sc(requests, engineers, name=f"shuffled-{seed}")

    for result in (plan_baseline(shuffled), plan_optimized(shuffled)):
        assert validate_plan(result, shuffled) == [], (
            f"seed={seed}/{result.algorithm}: перестановка входа сломала план"
        )


@pytest.mark.parametrize("seed", [4, 5])
def test_shuffled_input_keeps_every_request_accounted(seed):
    """После перестановки все заявки по-прежнему учтены ровно один раз."""
    base = random_scenario(seed, n_engineers=5, n_requests=20)
    rnd = random.Random(seed)
    requests = list(base.requests)
    rnd.shuffle(requests)
    shuffled = sc(requests, base.engineers)
    result = plan_optimized(shuffled)
    assert {a.request_id for a in result.assignments} == {r.id for r in shuffled.requests}


# --------------------------------------------------------------------------
# Производительность
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_large_scenario_completes_in_reasonable_time():
    """15 инженеров x 100 заявок — секунды, не минуты (SPEC §6.2)."""
    scenario = random_scenario(777, n_engineers=15, n_requests=100, time_limit_seconds=5.0)
    started = time.perf_counter()
    result = plan_optimized(scenario)
    elapsed = time.perf_counter() - started

    assert elapsed < 30.0, f"оптимизация заняла {elapsed:.1f} с"
    assert validate_plan(result, scenario) == []
    assert result.metrics.assigned_count > 0


@pytest.mark.slow
def test_baseline_is_fast_on_large_scenario():
    """Baseline без поиска обязан быть заметно быстрее оптимизации."""
    scenario = random_scenario(778, n_engineers=15, n_requests=100)
    started = time.perf_counter()
    result = plan_baseline(scenario)
    elapsed = time.perf_counter() - started
    assert elapsed < 10.0, f"baseline занял {elapsed:.1f} с"
    assert validate_plan(result, scenario) == []


@pytest.mark.slow
def test_time_limit_setting_is_respected():
    """time_limit_seconds ограничивает локальный поиск, а не игнорируется."""
    scenario = random_scenario(779, n_engineers=12, n_requests=80, time_limit_seconds=1.0)
    started = time.perf_counter()
    plan_optimized(scenario)
    elapsed = time.perf_counter() - started
    assert elapsed < 20.0, f"лимит 1 с не соблюдён: расчёт занял {elapsed:.1f} с"


def test_small_scenario_is_instant():
    """Мелкий сценарий планируется мгновенно — важно для интерактивного UI."""
    scenario = sc(
        [req(f"R{i}", window=("09:00", "17:00"), dur=30, at=HOME) for i in range(5)],
        [eng("E1", at=HOME), eng("E2", at=HOME)],
    )
    started = time.perf_counter()
    plan_optimized(scenario)
    assert time.perf_counter() - started < 5.0


# --------------------------------------------------------------------------
# Фазовый бюджет: anytime-свойство
# --------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [0.2, 0.5, 1.0])
def test_tiny_time_budget_still_produces_valid_plan(limit):
    """При жёстком лимите план всё равно валиден — алгоритм anytime.

    Конструктивная фаза не урезается (без допустимого решения оптимизировать
    нечего), а локальный поиск обязан уметь остановиться в любой момент, не
    оставив маршрут в недостроенном состоянии.
    """
    scenario = random_scenario(
        901, n_engineers=10, n_requests=60, time_limit_seconds=limit
    )
    result = plan_optimized(scenario)
    assert validate_plan(result, scenario) == [], f"лимит {limit} с оставил невалидный план"
    assert result.metrics.assigned_count > 0


def test_tiny_budget_is_not_worse_than_baseline():
    """Даже с лимитом 0.2 с оптимизация не должна проигрывать baseline."""
    scenario = random_scenario(
        902, n_engineers=8, n_requests=40, time_limit_seconds=0.2
    )
    baseline = plan_baseline(scenario)
    optimized = plan_optimized(scenario)
    assert optimized.metrics.quality_key() <= baseline.metrics.quality_key()


def test_larger_budget_is_not_worse_than_tiny_one():
    """Больше времени — не хуже результат: поиск не деградирует от бюджета."""
    base = random_scenario(903, n_engineers=8, n_requests=45)
    quick = plan_optimized(sc(base.requests, base.engineers, time_limit_seconds=0.2))
    slow = plan_optimized(sc(base.requests, base.engineers, time_limit_seconds=3.0))
    assert slow.metrics.quality_key() <= quick.metrics.quality_key()


def test_tiny_budget_keeps_determinism():
    """Жёсткий лимит не должен вносить недетерминизм «по таймеру».

    Если результат начнёт зависеть от скорости машины, демонстрация перестанет
    быть воспроизводимой — это прямое требование SPEC §0.
    """
    scenario = random_scenario(
        904, n_engineers=8, n_requests=40, time_limit_seconds=0.2
    )
    dumps = [normalized_dict(plan_optimized(scenario)) for _ in range(3)]
    assert dumps[0] == dumps[1] == dumps[2], (
        "результат зависит от фактической скорости расчёта, а не только от входа"
    )

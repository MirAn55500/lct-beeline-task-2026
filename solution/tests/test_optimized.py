# -*- coding: utf-8 -*-
"""Оптимизированный алгоритм (SPEC §6.2) и критерий качества (SPEC §5.2).

Главная гарантия: optimized никогда не хуже baseline по лексикографическому
ключу качества. Дополнительно проверяются эффекты, ради которых он и нужен:
приоритет авария → подключение → ремонт/дозаказ, regret-эффект для
«безальтернативных» заявок и выигрыш на сценарии-ловушке из ТЗ п.6.
"""
from __future__ import annotations

import pytest

from factories import (
    Algorithm,
    AssignmentStatus,
    assigned_ids,
    assignments_by_id,
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


# --------------------------------------------------------------------------
# Именованные сценарии для сравнения качества
# --------------------------------------------------------------------------


def scenario_trap():
    """Ловушка ТЗ п.6: baseline «съедает» первого инженера и теряет заявку.

    R_EARLY с узким ранним окном стоит последней во входе; к моменту её разбора
    E1 уже забит широкими заявками, а E2 выходит только с 12:00.
    """
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
    return sc(requests, engineers, name="trap")


def scenario_reverse_windows():
    """Окна во входе идут «задом наперёд» — baseline плодит маршруты."""
    engineers = [eng(f"E{i}", shift=("09:00", "18:00"), at=HOME, order=i - 1) for i in range(1, 6)]
    requests = [
        req("R1", window=("16:00", "16:00"), dur=90, at=HOME),
        req("R2", window=("15:00", "15:00"), dur=90, at=HOME),
        req("R3", window=("14:00", "14:00"), dur=90, at=HOME),
        req("R4", window=("13:00", "13:00"), dur=90, at=HOME),
        req("R5", window=("12:00", "12:00"), dur=90, at=HOME),
    ]
    return sc(requests, engineers, name="reverse-windows")


def scenario_two_clusters():
    """Два удалённых кластера: качество зависит от группировки по географии."""
    north = (55.82, 37.60)
    south = (55.60, 37.62)
    engineers = [
        eng("E1", shift=("09:00", "18:00"), at=(55.71, 37.61), order=0),
        eng("E2", shift=("09:00", "18:00"), at=(55.71, 37.61), order=1),
    ]
    requests = [
        req("N1", window=("09:00", "17:00"), dur=60, at=north),
        req("S1", window=("09:00", "17:00"), dur=60, at=south),
        req("N2", window=("09:00", "17:00"), dur=60, at=(55.83, 37.61)),
        req("S2", window=("09:00", "17:00"), dur=60, at=(55.59, 37.63)),
        req("N3", window=("09:00", "17:00"), dur=60, at=(55.81, 37.59)),
        req("S3", window=("09:00", "17:00"), dur=60, at=(55.61, 37.64)),
    ]
    return sc(requests, engineers, name="two-clusters")


def scenario_skill_bottleneck():
    """Единственный носитель редкого навыка — его время нельзя тратить зря."""
    engineers = [
        eng("E1", skills=["connection", "local"], shift=("09:00", "13:00"), at=HOME, order=0),
        eng("E2", skills=["connection"], shift=("09:00", "13:00"), at=HOME, order=1),
    ]
    requests = [
        req("R_CONN", window=("09:00", "12:00"), dur=180, skill="connection", at=HOME),
        req("R_LOCAL", window=("09:00", "12:00"), dur=180, skill="local", at=HOME),
    ]
    return sc(requests, engineers, name="skill-bottleneck")


def scenario_tight_capacity():
    """Ресурса заведомо меньше, чем заявок — важно, какие именно потеряны."""
    engineers = [eng("E1", shift=("09:00", "13:00"), at=HOME, order=0)]
    requests = [
        req("R1", window=("09:00", "12:00"), dur=90, at=HOME),
        req("R2", window=("09:00", "12:00"), dur=90, at=HOME),
        req("R3", window=("09:00", "12:00"), dur=90, at=HOME),
        req("R4", window=("09:00", "12:00"), dur=90, at=HOME, priority="emergency"),
        req("R5", window=("09:00", "12:00"), dur=90, at=HOME, priority="emergency"),
    ]
    return sc(requests, engineers, name="tight-capacity")


NAMED_SCENARIOS = {
    "trap": scenario_trap,
    "reverse_windows": scenario_reverse_windows,
    "two_clusters": scenario_two_clusters,
    "skill_bottleneck": scenario_skill_bottleneck,
    "tight_capacity": scenario_tight_capacity,
}


# --------------------------------------------------------------------------
# Главная гарантия качества
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(NAMED_SCENARIOS))
def test_optimized_is_never_worse_than_baseline_on_named_scenarios(name):
    """SPEC §6.2: optimized.quality_key() <= baseline.quality_key() всегда."""
    scenario = NAMED_SCENARIOS[name]()
    baseline, optimized = plan_both(scenario)
    assert optimized.metrics.quality_key() <= baseline.metrics.quality_key(), (
        f"{name}: optimized {optimized.metrics.quality_key()} хуже "
        f"baseline {baseline.metrics.quality_key()}"
    )


@pytest.mark.parametrize("name", sorted(NAMED_SCENARIOS))
def test_both_algorithms_produce_valid_plans_on_named_scenarios(name):
    """Ни один алгоритм не имеет права нарушить жёсткие ограничения."""
    scenario = NAMED_SCENARIOS[name]()
    for result in plan_both(scenario):
        assert validate_plan(result, scenario) == [], f"{name}/{result.algorithm}: план невалиден"


@pytest.mark.slow
@pytest.mark.parametrize("seed", [11, 22, 33, 44, 55])
def test_optimized_is_never_worse_than_baseline_on_random_scenarios(seed):
    """Псевдослучайные сценарии 10-15 инженеров и 60-100 заявок."""
    n_eng = 10 + seed % 6
    n_req = 60 + (seed * 7) % 41
    scenario = random_scenario(seed, n_engineers=n_eng, n_requests=n_req, time_limit_seconds=2.0)
    baseline, optimized = plan_both(scenario)

    assert validate_plan(baseline, scenario) == []
    assert validate_plan(optimized, scenario) == []
    assert optimized.metrics.quality_key() <= baseline.metrics.quality_key(), (
        f"seed={seed}: optimized {optimized.metrics.quality_key()} хуже "
        f"baseline {baseline.metrics.quality_key()}"
    )


# --------------------------------------------------------------------------
# Сценарий-ловушка: строгий выигрыш
# --------------------------------------------------------------------------


def test_trap_scenario_baseline_loses_request():
    """В ловушке baseline действительно теряет заявку — иначе тест бессмыслен."""
    scenario = scenario_trap()
    baseline = plan_baseline(scenario)
    assert "R_EARLY" not in assigned_ids(baseline), (
        "baseline неожиданно разместил R_EARLY — сценарий-ловушка перестал быть ловушкой"
    )


def test_trap_scenario_optimized_places_all_requests():
    """Optimized обязан разместить все четыре заявки ловушки."""
    scenario = scenario_trap()
    optimized = plan_optimized(scenario)
    assert optimized.metrics.unassigned_count == 0, (
        f"optimized не разместил: {[a.request_id for a in optimized.unassigned]}"
    )
    assert validate_plan(optimized, scenario) == []


def test_trap_scenario_optimized_is_strictly_better():
    """На ловушке выигрыш строгий, а не «не хуже»."""
    scenario = scenario_trap()
    baseline, optimized = plan_both(scenario)
    assert optimized.metrics.quality_key() < baseline.metrics.quality_key()
    assert optimized.metrics.assigned_count > baseline.metrics.assigned_count


# --------------------------------------------------------------------------
# Приоритеты: авария → подключение → ремонт / дозаказ
# --------------------------------------------------------------------------


def test_emergency_requests_are_placed_first_under_scarcity():
    """Ресурса хватает на часть — аварии обязаны быть размещены полностью."""
    scenario = scenario_tight_capacity()
    optimized = plan_optimized(scenario)
    assert optimized.metrics.emergency_unassigned_count == 0, (
        f"аварии потеряны: {[a.request_id for a in optimized.unassigned]}"
    )
    assert assigned_ids(optimized) == {"R4", "R5"}


def test_emergency_priority_beats_input_order():
    """Авария, стоящая последней во входе, всё равно получает ресурс вместо подключения."""
    engineers = [eng("E1", shift=("09:00", "11:00"), at=HOME)]
    requests = [
        req("R_CONN", window=("09:00", "10:00"), dur=120, at=HOME, priority="connection"),
        req("R_EMERGENCY", window=("09:00", "10:00"), dur=120, at=HOME, priority="emergency"),
    ]
    scenario = sc(requests, engineers)
    optimized = plan_optimized(scenario)
    assert assigned_ids(optimized) == {"R_EMERGENCY"}
    assert optimized.metrics.emergency_unassigned_count == 0


def test_emergency_unassigned_count_counts_only_emergency():
    """Метрика emergency_unassigned_count не смешивается с общим числом отказов."""
    scenario = scenario_tight_capacity()
    optimized = plan_optimized(scenario)
    assert optimized.metrics.unassigned_count == 3
    assert optimized.metrics.emergency_unassigned_count == 0
    assert optimized.metrics.connection_unassigned_count == 3


def test_priority_scarcity_keeps_emergency_then_connection():
    """Один инженер, три заявки не влезают: авария, затем подключение, не наоборот.

    Навык и приоритет независимы: все три заявки может выполнить один исполнитель,
    различается только важность. Влезают две из трёх — ремонт/дозаказ отбрасывается.
    """
    engineer = eng(
        "E1",
        skills=["emergency", "connection", "local"],
        shift=("09:00", "13:00"),
        at=HOME,
    )
    requests = [
        req(
            "R_REPAIR",
            window=("09:00", "13:00"),
            dur=90,
            skill="local",
            priority="repair_or_addon",
            at=HOME,
        ),
        req(
            "R_CONN",
            window=("09:00", "13:00"),
            dur=90,
            skill="connection",
            priority="connection",
            at=HOME,
        ),
        req(
            "R_EMERGENCY",
            window=("09:00", "13:00"),
            dur=90,
            skill="emergency",
            priority="emergency",
            at=HOME,
        ),
    ]
    scenario = sc(requests, [engineer])
    optimized = plan_optimized(scenario)
    ids = assigned_ids(optimized)
    assert "R_EMERGENCY" in ids, f"авария потеряна: {ids}"
    assert "R_CONN" in ids, f"подключение потеряно при наличии места: {ids}"
    assert "R_REPAIR" not in ids, f"ремонт вытеснил более важный приоритет: {ids}"
    assert optimized.metrics.emergency_unassigned_count == 0
    assert optimized.metrics.connection_unassigned_count == 0


def test_emergency_displaces_packed_lower_priority_on_static_plan():
    """Авария сдвигает/вытесняет менее приоритетные уже в основном расчёте, не только в replan.

    Четыре плотных подключения занимают весь день. Авария с тем же окном, что и
    последнее подключение, должна получить место: либо хвост сдвигается, либо
    менее важная заявка уходит в неназначенные.
    """
    engineer = eng(
        "E1",
        skills=["connection", "emergency"],
        shift=("09:00", "18:00"),
        at=HOME,
    )
    requests = [
        req("N1", window=("09:00", "09:00"), dur=120, at=HOME, skill="connection"),
        req("N2", window=("11:00", "11:00"), dur=120, at=HOME, skill="connection"),
        req("N3", window=("13:00", "13:00"), dur=120, at=HOME, skill="connection"),
        req("N4", window=("15:00", "15:00"), dur=120, at=HOME, skill="connection"),
        req(
            "EM",
            window=("15:00", "15:00"),
            dur=120,
            at=HOME,
            skill="emergency",
            priority="emergency",
            order=99,
        ),
    ]
    scenario = sc(requests, [engineer], enable_local_search=False, enable_fleet_minimization=False)
    optimized = plan_optimized(scenario)
    assert "EM" in assigned_ids(optimized), (
        f"авария не размещена в статическом плане: {assigned_ids(optimized)}"
    )
    assert optimized.metrics.emergency_unassigned_count == 0
    assert optimized.metrics.assigned_count <= 4


# --------------------------------------------------------------------------
# Regret-эффект
# --------------------------------------------------------------------------


def test_request_with_single_possible_engineer_is_always_placed():
    """Заявка с единственным исполнителем не должна проигрывать конкуренцию.

    R_LOCAL может выполнить только E1 (у E2 нет навыка local), а R_CONN —
    оба. Жадный выбор отдаёт E1 заявке R_CONN и теряет R_LOCAL; regret-k
    обязан отдать E1 безальтернативной заявке.
    """
    scenario = scenario_skill_bottleneck()
    optimized = plan_optimized(scenario)
    assert optimized.metrics.unassigned_count == 0, (
        f"безальтернативная заявка потеряна: {[a.request_id for a in optimized.unassigned]}"
    )
    assert assignments_by_id(optimized)["R_LOCAL"].engineer_id == "E1"


def test_baseline_loses_bottleneck_request():
    """Контроль: на этом же сценарии baseline действительно теряет заявку."""
    baseline = plan_baseline(scenario_skill_bottleneck())
    assert baseline.metrics.unassigned_count >= 1


# --------------------------------------------------------------------------
# Настройки поиска
# --------------------------------------------------------------------------


def test_plan_is_valid_with_local_search_disabled():
    """Только конструктивная фаза — план обязан оставаться валидным."""
    scenario = sc(
        scenario_two_clusters().requests,
        scenario_two_clusters().engineers,
        enable_local_search=False,
    )
    result = plan_optimized(scenario)
    assert validate_plan(result, scenario) == []


def test_local_search_does_not_worsen_quality():
    """Локальный поиск принимает только неухудшающие ходы (SPEC §6.2 п.2)."""
    base = scenario_two_clusters()
    without = plan_optimized(sc(base.requests, base.engineers, enable_local_search=False))
    with_ls = plan_optimized(sc(base.requests, base.engineers, enable_local_search=True))
    assert with_ls.metrics.quality_key() <= without.metrics.quality_key()


def test_regret_k_setting_does_not_break_validity():
    """Разные значения regret_k дают валидные планы."""
    base = scenario_two_clusters()
    for k in (1, 2, 3, 5):
        scenario = sc(base.requests, base.engineers, regret_k=k)
        result = plan_optimized(scenario)
        assert validate_plan(result, scenario) == [], f"regret_k={k}: план невалиден"


def test_optimized_algorithm_is_reported_in_result():
    """PlanResult.algorithm отражает выбранный алгоритм."""
    assert plan_optimized(scenario_trap()).algorithm == Algorithm.OPTIMIZED


def test_optimized_never_assigns_request_twice():
    """Заявка назначена не более чем одному инженеру (SPEC §9 п.2)."""
    scenario = random_scenario(7, n_engineers=5, n_requests=25)
    result = plan_optimized(scenario)
    seen = [v.request_id for route in result.routes for v in route.visits]
    assert len(seen) == len(set(seen)), "заявка встречается в маршрутах дважды"
    assert set(seen) == assigned_ids(result)


def test_quality_key_components_match_metrics():
    """quality_key собирается ровно из полей метрик в порядке SPEC §5.2."""
    result = plan_optimized(scenario_tight_capacity())
    m = result.metrics
    assert m.quality_key() == (
        m.emergency_unassigned_count,
        m.connection_unassigned_count,
        m.unassigned_count,
        m.used_engineer_count,
        round(m.total_travel_minutes, 6),
        round(m.total_distance_km, 6),
    )
    assert len(m.quality_key()) == 6

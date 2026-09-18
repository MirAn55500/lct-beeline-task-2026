# -*- coding: utf-8 -*-
"""Главный страховочный тест: 10 инвариантов SPEC §9 на 20 сценариях.

Здесь ничего не конструируется руками — берутся псевдослучайные (но строго
детерминированные) сценарии, прогоняются обоими алгоритмами и проверяются
независимым верификатором плюс прямой проверкой каждого инварианта.
Если этот файл зелёный, план физически исполним.
"""
from __future__ import annotations

import pytest

from factories import (
    Algorithm,
    AssignmentStatus,
    OracleCalendar,
    assigned_ids,
    oracle_calendar,
    plan,
    plan_baseline,
    plan_optimized,
    random_scenario,
    validate_plan,
)

SEEDS = list(range(1, 21))


# --------------------------------------------------------------------------
# Проверка инвариантов SPEC §9
# --------------------------------------------------------------------------


def check_invariants(result, scenario) -> list[str]:
    """Вернуть список нарушений инвариантов SPEC §9 (пустой = всё хорошо)."""
    problems: list[str] = []
    requests = {r.id: r for r in scenario.requests}
    engineers = {e.id: e for e in scenario.engineers}

    # 1. Каждая заявка входа имеет ровно один Assignment.
    ids = [a.request_id for a in result.assignments]
    if sorted(ids) != sorted(requests):
        problems.append(f"инв.1: состав assignments не совпадает с заявками входа: {sorted(set(ids) ^ set(requests))}")
    if len(ids) != len(set(ids)):
        problems.append("инв.1: дублирующиеся Assignment")

    # 2. Заявка назначена не более чем одному инженеру.
    visited = [v.request_id for route in result.routes for v in route.visits]
    if len(visited) != len(set(visited)):
        problems.append("инв.2: заявка встречается в нескольких маршрутах")
    if set(visited) != assigned_ids(result):
        problems.append("инв.2: маршруты и статусы назначений расходятся")

    # 3. Окна и рабочее время назначенных заявок.
    for assignment in result.assignments:
        if assignment.status != AssignmentStatus.ASSIGNED:
            continue
        request = requests.get(assignment.request_id)
        if request is None:
            continue
        if assignment.arrival_at is None or assignment.arrival_at > request.window_end:
            problems.append(f"инв.3: {request.id} прибытие позже конца окна")
        if assignment.service_start_at is None or assignment.service_start_at < request.window_start:
            problems.append(f"инв.3: {request.id} работа начата раньше окна")
        if assignment.service_start_at is not None and assignment.arrival_at is not None:
            if assignment.service_start_at < assignment.arrival_at:
                problems.append(f"инв.3: {request.id} работа начата раньше прибытия")
        engineer = engineers.get(assignment.engineer_id)
        if engineer is not None and assignment.service_end_at is not None:
            if not oracle_calendar(engineer).contains(assignment.service_end_at):
                problems.append(f"инв.3: {request.id} работа кончается вне рабочего времени")

    # 4/5. Внутри маршрута работы не пересекаются, позиции непрерывны с 1.
    for route in result.routes:
        positions = [v.position for v in route.visits]
        if positions != list(range(1, len(route.visits) + 1)):
            problems.append(f"инв.5: позиции маршрута {route.engineer_id}: {positions}")
        for prev, nxt in zip(route.visits, route.visits[1:]):
            if prev.service_end_at > nxt.departure_at:
                problems.append(
                    f"инв.4: пересечение работ {prev.request_id} и {nxt.request_id} у {route.engineer_id}"
                )

    # 6. У неназначенной заявки заполнены reason и explanation.
    for assignment in result.unassigned:
        if assignment.reason is None:
            problems.append(f"инв.6: {assignment.request_id} без reason")
        if not (assignment.explanation or "").strip():
            problems.append(f"инв.6: {assignment.request_id} без explanation")
        if assignment.engineer_id is not None:
            problems.append(f"инв.6: у неназначенной {assignment.request_id} указан инженер")

    # 7. used_engineer_count == число маршрутов с >= 1 визитом; пустых нет.
    non_empty = [r for r in result.routes if r.visits]
    if len(non_empty) != len(result.routes):
        problems.append("инв.7: в результате есть маршрут без визитов")
    if result.metrics.used_engineer_count != len(non_empty):
        problems.append(
            f"инв.7: used_engineer_count={result.metrics.used_engineer_count}, маршрутов {len(non_empty)}"
        )

    # 8. Сумма distance_km маршрутов == total_distance_km.
    total = sum(r.distance_km for r in result.routes)
    if abs(total - result.metrics.total_distance_km) > 1e-6:
        problems.append(f"инв.8: сумма пробегов {total} != {result.metrics.total_distance_km}")

    # 9. Маршрут стартует в стартовой точке инженера, возврата нет.
    for route in result.routes:
        engineer = engineers.get(route.engineer_id)
        if engineer is None:
            problems.append(f"инв.9: маршрут неизвестного инженера {route.engineer_id}")
            continue
        if route.visits[0].from_point != engineer.start_point:
            problems.append(f"инв.9: маршрут {route.engineer_id} стартует не из офиса")
        if route.polyline and route.polyline[-1] == engineer.start_point and len(route.visits) > 0:
            if route.visits[-1].to_point != engineer.start_point:
                problems.append(f"инв.9: маршрут {route.engineer_id} возвращается на базу")

    return problems


def assert_plan_is_sound(result, scenario, label: str) -> None:
    """Совместная проверка: верификатор SPEC §8 плюс инварианты SPEC §9."""
    violations = validate_plan(result, scenario)
    assert violations == [], f"{label}: validate_plan нашёл нарушения: {violations}"
    problems = check_invariants(result, scenario)
    assert problems == [], f"{label}: нарушены инварианты: {problems}"


# --------------------------------------------------------------------------
# Property-style прогон
# --------------------------------------------------------------------------


@pytest.mark.property
@pytest.mark.parametrize("seed", SEEDS)
def test_baseline_satisfies_all_invariants(seed):
    """Baseline на 20 псевдослучайных сценариях не нарушает ни одного инварианта."""
    scenario = random_scenario(seed, n_engineers=4 + seed % 5, n_requests=15 + seed)
    assert_plan_is_sound(plan_baseline(scenario), scenario, f"baseline/seed={seed}")


@pytest.mark.property
@pytest.mark.parametrize("seed", SEEDS)
def test_optimized_satisfies_all_invariants(seed):
    """Optimized на тех же 20 сценариях — главный страховочный тест сьюта."""
    scenario = random_scenario(
        seed, n_engineers=4 + seed % 5, n_requests=15 + seed, time_limit_seconds=2.0
    )
    assert_plan_is_sound(plan_optimized(scenario), scenario, f"optimized/seed={seed}")


@pytest.mark.property
@pytest.mark.parametrize("seed", SEEDS)
def test_optimized_is_never_worse_than_baseline(seed):
    """SPEC §6.2: гарантия качества выполняется на всех проверяемых сценариях."""
    scenario = random_scenario(
        seed, n_engineers=4 + seed % 5, n_requests=15 + seed, time_limit_seconds=2.0
    )
    baseline = plan_baseline(scenario)
    optimized = plan_optimized(scenario)
    assert optimized.metrics.quality_key() <= baseline.metrics.quality_key(), (
        f"seed={seed}: {optimized.metrics.quality_key()} > {baseline.metrics.quality_key()}"
    )


@pytest.mark.property
@pytest.mark.parametrize("seed", [3, 9, 14])
def test_invariants_hold_with_equipment_and_region_checks_enabled(seed):
    """Те же инварианты при включённых проверках снаряжения и региона."""
    scenario = random_scenario(
        seed,
        n_engineers=6,
        n_requests=25,
        check_equipment=True,
        check_region=True,
        time_limit_seconds=2.0,
    )
    for algorithm in (Algorithm.BASELINE, Algorithm.OPTIMIZED):
        assert_plan_is_sound(plan(scenario, algorithm), scenario, f"{algorithm}/seed={seed}")


@pytest.mark.property
@pytest.mark.parametrize("seed", [2, 8])
def test_invariants_hold_without_local_search_and_fleet_minimization(seed):
    """Отключённые улучшатели не должны ломать корректность конструктивной фазы."""
    scenario = random_scenario(
        seed,
        n_engineers=5,
        n_requests=25,
        enable_local_search=False,
        enable_fleet_minimization=False,
    )
    assert_plan_is_sound(plan_optimized(scenario), scenario, f"construct-only/seed={seed}")


# --------------------------------------------------------------------------
# Публичный API
# --------------------------------------------------------------------------


def test_public_api_is_exported_from_package_root():
    """SPEC §8: функции API доступны как planner.<имя>."""
    import planner

    for name in ("plan", "replan", "apply_event", "compare", "validate_plan", "solve"):
        attribute = getattr(planner, name, None)
        assert callable(attribute), f"planner.{name} недоступен или не вызывается"


def test_output_models_are_reexported_from_package_root():
    """Выходные модели живут в planner.result и реэкспортируются из planner.

    Потребителю не нужно знать внутреннюю раскладку модулей: согласованное
    решение — импортировать всё из `planner`.
    """
    import planner
    import planner.result as result_module

    for name in (
        "PlanResult",
        "RouteResult",
        "Visit",
        "Assignment",
        "PlanMetrics",
        "EngineerMetrics",
        "PlanDiff",
    ):
        exported = getattr(planner, name, None)
        assert exported is not None, f"planner.{name} не реэкспортирован"
        assert exported is getattr(result_module, name), (
            f"planner.{name} и planner.result.{name} — разные объекты"
        )


def test_input_models_and_enums_are_reexported_from_package_root():
    """Вход и перечисления тоже доступны напрямую из planner."""
    import planner

    for name in (
        "Scenario",
        "Request",
        "Engineer",
        "Settings",
        "GeoPoint",
        "WorkInterval",
        "ReplanEvent",
        "Skill",
        "TransportMode",
        "Priority",
        "Algorithm",
        "AssignmentStatus",
        "EventType",
        "ReasonCode",
    ):
        assert getattr(planner, name, None) is not None, f"planner.{name} не реэкспортирован"


def test_extension_points_are_exported():
    """Точки расширения объявлены публично: модель перемещения и контекст."""
    import planner

    for name in ("TravelModel", "HaversineTravelModel", "MatrixTravelModel", "PlanContext"):
        assert getattr(planner, name, None) is not None, f"planner.{name} не экспортирован"


def test_dunder_all_matches_actual_attributes():
    """Всё, что обещано в __all__, реально существует в пакете."""
    import planner

    missing = [name for name in planner.__all__ if not hasattr(planner, name)]
    assert missing == [], f"в __all__ обещано, но отсутствует: {missing}"


def test_plan_defaults_to_optimized_algorithm():
    """SPEC §8: алгоритм по умолчанию — OPTIMIZED."""
    scenario = random_scenario(42, n_engineers=3, n_requests=10)
    assert plan(scenario).algorithm == Algorithm.OPTIMIZED


def test_oracle_calendar_matches_engineer_capacity():
    """Самопроверка тестового оракула: ёмкость календаря считается ожидаемо."""
    scenario = random_scenario(1, n_engineers=3, n_requests=5)
    for engineer in scenario.engineers:
        calendar = OracleCalendar(engineer.work_intervals)
        assert calendar.capacity_minutes in (480.0, 540.0)


# --------------------------------------------------------------------------
# Проверка самого верификатора (мутационные тесты)
# --------------------------------------------------------------------------

# Все утверждения вида `validate_plan(...) == []` стоят ровно столько, сколько
# стоит сам верификатор. Если он молча возвращает пустой список на любом входе,
# половина сьюта проходит впустую. Поэтому портим заведомо корректный план и
# требуем, чтобы нарушение было замечено.


def _mutation_scenario():
    """Небольшой заведомо выполнимый сценарий для порчи."""
    from factories import eng, req, sc

    home = (55.70, 37.60)
    return sc(
        [
            req("R1", window=("09:00", "11:00"), dur=60, at=(55.71, 37.61)),
            req("R2", window=("12:00", "14:00"), dur=60, at=(55.73, 37.64)),
        ],
        [eng("E1", shift=("09:00", "18:00"), at=home)],
    )


def _corrupt(result, **route_changes):
    """Копия плана с подменёнными полями первого маршрута."""
    import dataclasses

    route = result.routes[0]
    broken_route = dataclasses.replace(route, **route_changes)
    return dataclasses.replace(result, routes=(broken_route,) + tuple(result.routes[1:]))


def test_validator_catches_arrival_after_window_end():
    """Испорченное прибытие позже конца окна обязано быть замечено."""
    import dataclasses
    from datetime import timedelta

    scenario = _mutation_scenario()
    result = plan_optimized(scenario)
    assert validate_plan(result, scenario) == [], "исходный план должен быть корректен"

    route = result.routes[0]
    visit = route.visits[0]
    late = dataclasses.replace(
        visit,
        arrival_at=visit.arrival_at + timedelta(hours=6),
        service_start_at=visit.service_start_at + timedelta(hours=6),
        service_end_at=visit.service_end_at + timedelta(hours=6),
    )
    broken = _corrupt(result, visits=(late,) + tuple(route.visits[1:]))
    assert validate_plan(broken, scenario) != [], "верификатор не заметил выход за окно"


def test_validator_catches_overlapping_services():
    """Пересечение работ внутри маршрута обязано быть замечено."""
    import dataclasses
    from datetime import timedelta

    scenario = _mutation_scenario()
    result = plan_optimized(scenario)
    route = result.routes[0]
    if len(route.visits) < 2:
        pytest.skip("для проверки пересечения нужен маршрут из двух визитов")

    first = route.visits[0]
    stretched = dataclasses.replace(first, service_end_at=first.service_end_at + timedelta(hours=3))
    broken = _corrupt(result, visits=(stretched,) + tuple(route.visits[1:]))
    assert validate_plan(broken, scenario) != [], "верификатор не заметил пересечение работ"


def test_validator_catches_broken_position_numbering():
    """Разрыв в нумерации позиций обязан быть замечен (инвариант 5)."""
    import dataclasses

    scenario = _mutation_scenario()
    result = plan_optimized(scenario)
    route = result.routes[0]
    renumbered = tuple(
        dataclasses.replace(v, position=v.position + 10) for v in route.visits
    )
    broken = _corrupt(result, visits=renumbered)
    assert validate_plan(broken, scenario) != [], "верификатор не заметил разрыв нумерации"


def test_validator_catches_missing_assignment():
    """Заявка без Assignment обязана быть замечена (инвариант 1)."""
    import dataclasses

    scenario = _mutation_scenario()
    result = plan_optimized(scenario)
    broken = dataclasses.replace(result, assignments=result.assignments[:-1])
    assert validate_plan(broken, scenario) != [], "верификатор не заметил пропавшую заявку"


def test_validator_catches_route_of_unknown_engineer():
    """Маршрут несуществующего инженера обязан быть замечен."""
    import dataclasses

    scenario = _mutation_scenario()
    result = plan_optimized(scenario)
    broken = _corrupt(result, engineer_id="GHOST")
    assert validate_plan(broken, scenario) != [], "верификатор не заметил чужого инженера"


def test_validator_catches_distance_mismatch():
    """Расхождение заявленного пробега с пересчитанным обязано быть замечено."""
    import dataclasses

    scenario = _mutation_scenario()
    result = plan_optimized(scenario)
    broken = _corrupt(result, distance_km=result.routes[0].distance_km + 100.0)
    assert validate_plan(broken, scenario) != [], "верификатор не заметил подмену пробега"

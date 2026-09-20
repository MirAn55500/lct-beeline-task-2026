# -*- coding: utf-8 -*-
"""Крайние случаи и валидация входа (SPEC §2.1, §2.2, §2.6, §9).

Вырожденный вход — то, на чём чаще всего падают демонстрации: пустые списки,
дубли идентификаторов, заявка, совпадающая с офисом, полностью нерабочий день.
Планировщик обязан отвечать корректным планом или внятной диагностикой, но не
исключением.
"""
from __future__ import annotations

import pytest

from factories import (
    AssignmentStatus,
    GeoPoint,
    Priority,
    ReasonCode,
    Scenario,
    WorkInterval,
    assigned_ids,
    assignments_by_id,
    eng,
    plan_baseline,
    plan_both,
    plan_optimized,
    req,
    sc,
    t,
    unassigned_ids,
    validate_plan,
)

HOME = (55.70, 37.60)


# --------------------------------------------------------------------------
# Вырожденные сценарии
# --------------------------------------------------------------------------


def test_empty_request_list_produces_empty_plan():
    """Нет заявок — пустой план без маршрутов и без ошибок."""
    scenario = sc([], [eng("E1", at=HOME)])
    for result in plan_both(scenario):
        assert result.assignments == ()
        assert result.routes == ()
        assert result.metrics.assigned_count == 0
        assert result.metrics.unassigned_count == 0
        assert result.metrics.used_engineer_count == 0
        assert validate_plan(result, scenario) == []


def test_empty_engineer_list_marks_everything_no_engineers():
    """Нет инженеров — все заявки с кодом no_engineers и объяснением."""
    scenario = sc([req("R1", at=HOME), req("R2", at=HOME)], [])
    for result in plan_both(scenario):
        assert result.metrics.assigned_count == 0
        assert result.metrics.unassigned_count == 2
        assert result.metrics.available_engineer_count == 0
        for assignment in result.unassigned:
            assert assignment.reason == ReasonCode.NO_ENGINEERS
            assert assignment.explanation.strip()
        assert validate_plan(result, scenario) == []


def test_empty_scenario_is_handled():
    """Ни заявок, ни инженеров — план строится и он валиден."""
    scenario = sc([], [])
    result = plan_optimized(scenario)
    assert result.metrics.assigned_count == 0
    assert validate_plan(result, scenario) == []


def test_single_engineer_single_request():
    """Минимальный содержательный сценарий работает end-to-end."""
    scenario = sc([req("R1", window=("10:00", "12:00"), dur=60, at=HOME)], [eng("E1", at=HOME)])
    result = plan_optimized(scenario)
    assert assigned_ids(result) == {"R1"}
    assert result.metrics.used_engineer_count == 1
    assert validate_plan(result, scenario) == []


def test_request_at_engineer_start_point_has_zero_travel():
    """Заявка в точке офиса: нулевое расстояние и нулевое время перемещения."""
    scenario = sc([req("R1", window=("09:00", "12:00"), dur=60, at=HOME)], [eng("E1", at=HOME)])
    result = plan_optimized(scenario)
    visit = result.routes[0].visits[0]
    assert visit.distance_km == pytest.approx(0.0)
    assert visit.travel_minutes == pytest.approx(0.0)
    assert result.metrics.total_distance_km == pytest.approx(0.0)


def test_all_engineers_inactive_leaves_everything_unassigned():
    """Все инженеры неактивны — заявки не назначены, причина no_work_time."""
    scenario = sc(
        [req("R1", at=HOME)],
        [eng("E1", at=HOME, active=False), eng("E2", at=HOME, active=False)],
    )
    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.reason == ReasonCode.NO_WORK_TIME
    assert result.metrics.available_engineer_count == 0


def test_all_engineers_have_empty_schedule():
    """Выходной день у всех: пустые графики дают no_work_time."""
    scenario = sc([req("R1", at=HOME)], [eng("E1", at=HOME, shift=()), eng("E2", at=HOME, shift=())])
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.reason == ReasonCode.NO_WORK_TIME


def test_required_transport_nobody_has():
    """Требуется транспорт, которого нет ни у кого — no_transport."""
    scenario = sc(
        [req("R1", transport="bicycle", at=HOME)],
        [eng("E1", transport="car", at=HOME), eng("E2", transport="walking", at=HOME)],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.reason == ReasonCode.NO_TRANSPORT


def test_all_requests_emergency_is_handled():
    """Все заявки аварийные — приоритет перестаёт различать, план остаётся валидным."""
    requests = [
        req(f"R{i}", window=("09:00", "16:00"), dur=60, at=HOME, priority="emergency")
        for i in range(6)
    ]
    scenario = sc(requests, [eng("E1", at=HOME), eng("E2", at=HOME)])
    result = plan_optimized(scenario)
    assert result.metrics.emergency_unassigned_count == result.metrics.unassigned_count
    assert validate_plan(result, scenario) == []


def test_engineer_with_split_shift_and_request_exactly_in_break():
    """Два интервала и заявка ровно в перерыве — работа не идёт в обед."""
    engineer = eng("E1", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME)
    scenario = sc([req("R1", window=("13:00", "14:00"), dur=30, at=HOME)], [engineer])
    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]

    if assignment.status == AssignmentStatus.ASSIGNED:
        assert assignment.service_start_at in (t("13:00"), t("14:00")), (
            f"старт {assignment.service_start_at} попал внутрь перерыва"
        )
    assert validate_plan(result, scenario) == []


def test_window_width_exactly_equal_to_duration():
    """Окно шириной ровно в длительность — граничный, но допустимый случай."""
    scenario = sc(
        [req("R1", window=("10:00", "11:00"), dur=60, at=HOME)],
        [eng("E1", at=HOME)],
    )
    result = plan_optimized(scenario)
    assert assigned_ids(result) == {"R1"}
    assert validate_plan(result, scenario) == []


def test_zero_width_window_is_supported():
    """window_start == window_end допустимо: прибытие ровно в момент."""
    scenario = sc(
        [req("R1", window=("10:00", "10:00"), dur=30, at=HOME)],
        [eng("E1", at=HOME)],
    )
    result = plan_optimized(scenario)
    assert assigned_ids(result) == {"R1"}
    assert validate_plan(result, scenario) == []


def test_many_requests_one_engineer_keeps_plan_valid():
    """Заведомая перегрузка: часть заявок теряется, но план остаётся корректным."""
    requests = [req(f"R{i}", window=("09:00", "17:00"), dur=80, at=HOME) for i in range(20)]
    scenario = sc(requests, [eng("E1", at=HOME)])
    result = plan_optimized(scenario)
    assert result.metrics.assigned_count < 20
    assert result.metrics.assigned_count >= 1
    assert validate_plan(result, scenario) == []


def test_one_engineer_is_preferred_over_short_travel():
    """Число исполнителей важнее пробега (SPEC §5.2): один инженер объезжает оба офиса.

    Следствие приоритетов: даже 60 км крюка дешевле второго выехавшего инженера.
    Тест фиксирует это как осознанное поведение, а не случайность.
    """
    scenario = sc(
        [
            req("N", window=("09:00", "17:00"), dur=60, at=(55.90, 37.60)),
            req("S", window=("09:00", "17:00"), dur=60, at=(55.50, 37.60)),
        ],
        [eng("E1", at=(55.90, 37.60)), eng("E2", at=(55.50, 37.60))],
    )
    result = plan_optimized(scenario)
    assert result.metrics.used_engineer_count == 1
    assert validate_plan(result, scenario) == []


def test_baseline_splits_far_apart_clusters_between_offices():
    """Baseline берёт первого подходящего: заявка у второго офиса уходит к E1, если влезает."""
    scenario = sc(
        [
            req("N", window=("09:00", "10:00"), dur=60, at=(55.90, 37.60)),
            req("S", window=("09:00", "10:00"), dur=60, at=(55.50, 37.60)),
        ],
        [eng("E1", at=(55.90, 37.60)), eng("E2", at=(55.50, 37.60))],
    )
    result = plan_baseline(scenario)
    by_id = assignments_by_id(result)
    assert by_id["N"].engineer_id == "E1"
    assert by_id["S"].engineer_id == "E2", "узкие окна обязаны развести заявки по бригадам"
    assert result.metrics.total_distance_km == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------
# Валидация входа
# --------------------------------------------------------------------------


def test_duplicate_request_ids_raise_value_error():
    """Дубли идентификаторов заявок — ошибка, а не предупреждение (SPEC §2.6)."""
    with pytest.raises(ValueError):
        sc([req("R1", at=HOME), req("R1", at=HOME)], [eng("E1", at=HOME)]).validate()


def test_duplicate_engineer_ids_raise_value_error():
    """Дубли идентификаторов инженеров — тоже ValueError."""
    with pytest.raises(ValueError):
        sc([req("R1", at=HOME)], [eng("E1", at=HOME), eng("E1", at=HOME)]).validate()


def test_reversed_window_produces_warning():
    """window_end < window_start — предупреждение Scenario.validate()."""
    request = req("R1", window=(t("12:00"), t("10:00")), at=HOME)
    warnings = sc([request], [eng("E1", at=HOME)]).validate()
    assert warnings, "перевёрнутое окно не попало в предупреждения"
    assert any("R1" in w for w in warnings), warnings


def test_non_positive_duration_produces_warning():
    """duration <= 0 — предупреждение (SPEC §2.6)."""
    warnings = sc([req("R1", dur=0, at=HOME)], [eng("E1", at=HOME)]).validate()
    assert warnings, "нулевая длительность не попала в предупреждения"
    assert any("R1" in w for w in warnings), warnings


def test_negative_duration_produces_warning():
    """Отрицательная длительность обрабатывается так же, как нулевая."""
    warnings = sc([req("R1", dur=-30, at=HOME)], [eng("E1", at=HOME)]).validate()
    assert warnings


def test_request_outside_scenario_date_produces_warning():
    """Заявка на другую дату — предупреждение, а не молчаливое назначение."""
    from datetime import date as _date

    other_day = _date(2026, 8, 18)
    request = req("R1", window=("10:00", "12:00"), at=HOME, day=other_day)
    warnings = sc([request], [eng("E1", at=HOME)]).validate()
    assert warnings, "заявка вне даты сценария не попала в предупреждения"


def test_valid_scenario_has_no_warnings():
    """Корректный сценарий не порождает ложных предупреждений."""
    scenario = sc([req("R1", at=HOME), req("R2", at=HOME)], [eng("E1", at=HOME)])
    assert scenario.validate() == []


def test_geopoint_validates_latitude_and_longitude():
    """GeoPoint проверяет диапазоны в __post_init__ (SPEC §2.1)."""
    GeoPoint(90.0, 180.0)
    GeoPoint(-90.0, -180.0)
    for bad in ((90.1, 0.0), (-90.1, 0.0), (0.0, 180.1), (0.0, -180.1)):
        with pytest.raises(ValueError):
            GeoPoint(*bad)


def test_work_interval_requires_positive_length():
    """WorkInterval требует end строго больше start (SPEC §2.2)."""
    WorkInterval(t("09:00"), t("09:01"))
    with pytest.raises(ValueError):
        WorkInterval(t("09:00"), t("09:00"))


def test_input_models_are_frozen():
    """Входные модели неизменяемы — защита от случайной мутации планировщиком."""
    engineer = eng("E1", at=HOME)
    request = req("R1", at=HOME)
    for obj, field in ((engineer, "id"), (request, "id")):
        with pytest.raises(Exception):
            setattr(obj, field, "hacked")


def test_scenario_can_be_planned_twice_with_same_result():
    """Повторное планирование того же объекта не зависит от предыдущего вызова."""
    scenario = sc(
        [req(f"R{i}", window=("09:00", "17:00"), dur=60, at=HOME) for i in range(5)],
        [eng("E1", at=HOME), eng("E2", at=HOME)],
    )
    first = plan_optimized(scenario).metrics.quality_key()
    second = plan_optimized(scenario).metrics.quality_key()
    assert first == second


def test_scenario_is_constructible_directly_without_factories():
    """Прямая сборка Scenario (как это сделает бэкенд) тоже работает."""
    scenario = Scenario(
        date=t("09:00").date(),
        requests=(req("R1", at=HOME),),
        engineers=(eng("E1", at=HOME),),
    )
    result = plan_optimized(scenario)
    assert validate_plan(result, scenario) == []


def test_unassigned_request_priority_is_reflected_in_metrics():
    """Неназначенная авария попадает в emergency_unassigned_count."""
    scenario = sc(
        [req("R1", window=("03:00", "04:00"), dur=30, at=HOME, priority="emergency")],
        [eng("E1", at=HOME)],
    )
    result = plan_optimized(scenario)
    assert result.metrics.emergency_unassigned_count == 1
    assert result.metrics.unassigned_count == 1


def test_baseline_and_optimized_agree_on_trivially_infeasible_requests():
    """Заведомо невыполнимая заявка отвергается обоими алгоритмами одинаково."""
    scenario = sc([req("R1", window=("02:00", "03:00"), dur=30, at=HOME)], [eng("E1", at=HOME)])
    baseline, optimized = plan_both(scenario)
    assert baseline.metrics.unassigned_count == optimized.metrics.unassigned_count == 1
    assert (
        assignments_by_id(baseline)["R1"].reason == assignments_by_id(optimized)["R1"].reason
    )


def test_priority_enum_values_are_stable():
    """Значения приоритетов сериализуются как строки БЗ; ранг — авария > подключение > ремонт."""
    assert Priority.EMERGENCY.value == "emergency"
    assert Priority.CONNECTION.value == "connection"
    assert Priority.REPAIR.value == "repair_or_addon"
    assert Priority.EMERGENCY.rank == 2
    assert Priority.CONNECTION.rank == 1
    assert Priority.REPAIR.rank == 0


def test_request_default_priority_is_connection():
    """Дефолт заявки — подключение, независимо от навыка (SPEC §2.4)."""
    request = req("R1", at=HOME)
    assert request.priority == Priority.CONNECTION
    assert request.is_emergency is False


def test_completed_request_is_excluded_from_assignments():
    """Закрытая заявка не входит в planning_requests и не получает Assignment."""
    closed = req("RDONE", window=("09:00", "12:00"), dur=60, at=HOME, execution_status="completed")
    open_request = req("R1", window=("09:00", "12:00"), dur=60, at=HOME)
    scenario = sc([closed, open_request], [eng("E1", at=HOME)])

    assert closed.id not in {r.id for r in scenario.planning_requests()}
    result = plan_optimized(scenario)
    assert closed.id not in {a.request_id for a in result.assignments}
    assert assigned_ids(result) == {"R1"}
    assert validate_plan(result, scenario) == []


def test_future_received_at_is_excluded_when_as_of_is_earlier():
    """Авария, поступившая после as_of, в этот снимок плана не входит."""
    emergency = req(
        "RE",
        window=("09:00", "21:00"),
        dur=100,
        skill="emergency",
        priority="emergency",
        at=HOME,
        received_at="13:00",
    )
    scenario = sc(
        [emergency],
        [eng("E1", skills=["emergency"], at=HOME)],
        as_of="09:00",
    )
    assert emergency.id not in {r.id for r in scenario.planning_requests()}
    result = plan_optimized(scenario)
    assert result.assignments == ()
    assert assigned_ids(result) == set()
    assert validate_plan(result, scenario) == []


def test_engineer_home_start_survives_dict_round_trip():
    """home_start — часть входа и обязан переживать сериализацию (SPEC §2.3)."""
    engineer = eng("E1", at=HOME, home_start=True)
    restored = type(engineer).from_dict(engineer.to_dict())
    assert restored.home_start is True
    assert eng("E2", at=HOME).home_start is False


def test_request_that_cannot_fit_any_shift_is_reported_as_a_warning():
    """Заявка, не помещающаяся в смену ни к кому, попадает в предупреждения плана.

    Реальный случай «Востока»: в выгрузке есть окна 20:00–22:00, а смена задана до 21:00.
    Авария длится 80 минут и не может начаться раньше 20:00 — её не выполнить ни при каком
    распределении. Без предупреждения такая заявка молча оседает в «не назначено»,
    и причину ищут в алгоритме, а не в границах смены.
    """
    scenario = sc(
        [
            req("R1", window=("10:00", "12:00"), dur=60),
            req("R2", window=("20:00", "22:00"), dur=80, skill="emergency", priority="emergency"),
        ],
        [eng("E1", skills=["connection", "emergency"], shift=("09:00", "21:00"))],
    )
    result = plan_optimized(scenario)

    assert "R2" in unassigned_ids(result)
    hint = [w for w in result.warnings if "не помещающихся в смену" in w]
    assert hint, f"нет предупреждения о заявке вне смены: {result.warnings}"
    assert "R2" in hint[0]
    assert "R1" not in hint[0], "нормальная заявка не должна попадать в предупреждение"


def test_explanation_says_the_work_does_not_fit_even_an_empty_day():
    """Объяснение отличает «не влезает в принципе» от «инженер занят».

    Инженер полностью свободен, и всё равно не может взять заявку: работа начинается
    не раньше 20:00 и длится 80 минут, а смена заканчивается в 21:00. Говорить про
    «уже запланированные работы» здесь было бы неправдой.
    """
    scenario = sc(
        [req("R1", window=("20:00", "22:00"), dur=80, skill="emergency", priority="emergency")],
        [eng("E1", skills=["emergency"], shift=("09:00", "21:00"))],
    )
    result = plan_optimized(scenario)
    explanation = assignments_by_id(result)["R1"].explanation

    assert "не помещается даже в пустой день" in explanation, explanation
    assert "уже запланированных работ" not in explanation, explanation

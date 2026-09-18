# -*- coding: utf-8 -*-
"""Объяснения и диагностика назначений (SPEC §7.3, база знаний «Назначение на работу»).

Диспетчер видит не код причины, а текст. Поэтому проверяем, что объяснение
всегда есть, оно на русском и содержательно связано с причиной: про навык —
про навык, про время — про окно.
"""
from __future__ import annotations

import pytest

from factories import (
    AssignmentStatus,
    Priority,
    ReasonCode,
    Skill,
    TransportMode,
    assignments_by_id,
    eng,
    has_cyrillic,
    plan_baseline,
    plan_optimized,
    random_scenario,
    req,
    sc,
)

HOME = (55.70, 37.60)


def diagnostic_scenario():
    """Сценарий, в котором встречаются все интересные причины отказа сразу."""
    engineers = [
        eng("E1", skills=["connection"], region="east", transport="car", at=HOME, order=0),
        eng("E2", skills=["connection", "local"], region="east", transport="car", at=HOME, order=1),
    ]
    requests = [
        req("OK", window=("09:00", "12:00"), dur=60, region="east", at=HOME),
        req("NO_SKILL", window=("09:00", "12:00"), dur=60, skill="emergency", region="east", at=HOME),
        req("NO_REGION", window=("09:00", "12:00"), dur=60, region="south", at=HOME),
        req("NO_TRANSPORT", window=("09:00", "12:00"), dur=60, region="east", transport="bicycle", at=HOME),
        req("TIME", window=("19:00", "20:00"), dur=60, region="east", at=HOME),
    ]
    return sc(requests, engineers, name="diagnostics")


@pytest.fixture(scope="module")
def diagnostics():
    """План диагностического сценария."""
    scenario = diagnostic_scenario()
    return scenario, plan_optimized(scenario)


def test_every_unassigned_request_has_reason_and_explanation(diagnostics):
    """SPEC §9 п.6: у неназначенной заявки обязательны reason и explanation."""
    _scenario, result = diagnostics
    assert result.unassigned, "в диагностическом сценарии должны быть отказы"
    for assignment in result.unassigned:
        assert assignment.reason is not None, f"{assignment.request_id}: нет reason"
        assert assignment.explanation.strip(), f"{assignment.request_id}: пустое explanation"
        assert has_cyrillic(assignment.explanation), (
            f"{assignment.request_id}: объяснение не на русском: {assignment.explanation!r}"
        )


def test_assigned_request_also_has_non_empty_explanation(diagnostics):
    """SPEC §7.3: explanation всегда заполнен, в том числе при ASSIGNED."""
    _scenario, result = diagnostics
    assigned = [a for a in result.assignments if a.status == AssignmentStatus.ASSIGNED]
    assert assigned, "в сценарии нет ни одного назначения"
    for assignment in assigned:
        assert assignment.explanation.strip(), f"{assignment.request_id}: пустое explanation"
        assert has_cyrillic(assignment.explanation)


def test_no_skill_explanation_mentions_the_skill(diagnostics):
    """Причина no_skill объясняется через навык — диспетчеру нужно знать, какой."""
    _scenario, result = diagnostics
    assignment = assignments_by_id(result)["NO_SKILL"]
    assert assignment.reason == ReasonCode.NO_SKILL
    text = assignment.explanation.lower()
    assert "навык" in text or "квалиф" in text or "emergency" in text, (
        f"объяснение не про навык: {assignment.explanation!r}"
    )


def test_no_region_explanation_mentions_the_region(diagnostics):
    """Причина no_region объясняется через регион/территорию."""
    _scenario, result = diagnostics
    assignment = assignments_by_id(result)["NO_REGION"]
    assert assignment.reason == ReasonCode.NO_REGION
    text = assignment.explanation.lower()
    assert "регион" in text or "территор" in text or "south" in text, (
        f"объяснение не про регион: {assignment.explanation!r}"
    )


def test_no_transport_explanation_mentions_transport(diagnostics):
    """Причина no_transport объясняется через способ передвижения."""
    _scenario, result = diagnostics
    assignment = assignments_by_id(result)["NO_TRANSPORT"]
    assert assignment.reason == ReasonCode.NO_TRANSPORT
    text = assignment.explanation.lower()
    assert (
        "транспорт" in text
        or "передвиж" in text
        or "bicycle" in text
        or "велосипед" in text
    ), f"объяснение не про транспорт: {assignment.explanation!r}"


def test_time_conflict_explanation_mentions_time_or_window(diagnostics):
    """Причина time_conflict объясняется через время/окно/смену."""
    _scenario, result = diagnostics
    assignment = assignments_by_id(result)["TIME"]
    assert assignment.reason == ReasonCode.TIME_CONFLICT
    text = assignment.explanation.lower()
    assert any(word in text for word in ("врем", "окно", "окн", "смен", "график", "расписан")), (
        f"объяснение не про время: {assignment.explanation!r}"
    )


def test_no_engineers_explanation_is_meaningful():
    """Пустой список инженеров объясняется явно, а не пустой строкой."""
    result = plan_optimized(sc([req("R1", at=HOME)], []))
    assignment = assignments_by_id(result)["R1"]
    assert assignment.reason == ReasonCode.NO_ENGINEERS
    assert assignment.explanation.strip() and has_cyrillic(assignment.explanation)
    text = assignment.explanation.lower()
    assert "инженер" in text or "исполнител" in text


def test_no_equipment_explanation_mentions_equipment():
    """Причина no_equipment объясняется через снаряжение."""
    scenario = sc(
        [req("R1", equipment=["router"], at=HOME)],
        [eng("E1", equipment=["ladder"], at=HOME)],
        check_equipment=True,
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.reason == ReasonCode.NO_EQUIPMENT
    text = assignment.explanation.lower()
    assert "снаряж" in text or "оборудован" in text or "router" in text, (
        f"объяснение не про снаряжение: {assignment.explanation!r}"
    )


def test_checked_skill_copies_request_requirement(diagnostics):
    """checked_skill копируется из заявки — это поле для объяснения, а не вывод."""
    scenario, result = diagnostics
    required = {r.id: r.required_skill for r in scenario.requests}
    for assignment in result.assignments:
        assert assignment.checked_skill == required[assignment.request_id], (
            f"{assignment.request_id}: checked_skill не совпал с требованием заявки"
        )


def test_checked_transport_reflects_request_requirement(diagnostics):
    """checked_transport пуст, если требования не было, и равен требованию иначе."""
    scenario, result = diagnostics
    required = {r.id: r.required_transport for r in scenario.requests}
    for assignment in result.assignments:
        expected = required[assignment.request_id]
        actual = assignment.checked_transport
        if expected is None:
            assert actual in (None, "", ()), (
                f"{assignment.request_id}: checked_transport={actual!r} при отсутствии требования"
            )
        else:
            assert actual == expected


def test_checked_equipment_reflects_request_requirement():
    """checked_equipment — список требований заявки (пустой, если их не было)."""
    scenario = sc(
        [req("R1", equipment=["router", "ladder"], at=HOME), req("R2", at=HOME)],
        [eng("E1", equipment=["router", "ladder"], at=HOME)],
        check_equipment=True,
    )
    by_id = assignments_by_id(plan_optimized(scenario))
    assert set(by_id["R1"].checked_equipment) == {"router", "ladder"}
    assert not by_id["R2"].checked_equipment


def test_incremental_distance_is_absent_or_non_negative(diagnostics):
    """Добавленное расстояние либо не считалось (None), либо неотрицательно."""
    _scenario, result = diagnostics
    for assignment in result.assignments:
        value = assignment.incremental_distance_km
        if value is not None:
            assert value >= -1e-9, f"{assignment.request_id}: отрицательный вклад {value}"


def test_unassigned_assignment_has_no_schedule_fields(diagnostics):
    """При UNASSIGNED плановые поля пусты (правило БЗ «Назначение на работу»)."""
    _scenario, result = diagnostics
    for assignment in result.unassigned:
        assert assignment.engineer_id is None
        assert assignment.position is None
        assert assignment.arrival_at is None
        assert assignment.service_start_at is None
        assert assignment.service_end_at is None


def test_assigned_assignment_has_all_schedule_fields(diagnostics):
    """При ASSIGNED заполнены инженер, позиция и все три момента расписания."""
    _scenario, result = diagnostics
    for assignment in result.assignments:
        if assignment.status != AssignmentStatus.ASSIGNED:
            continue
        assert assignment.engineer_id
        assert assignment.position is not None and assignment.position >= 1
        assert assignment.arrival_at is not None
        assert assignment.service_start_at is not None
        assert assignment.service_end_at is not None
        assert assignment.reason is None, "у назначенной заявки не должно быть причины отказа"


@pytest.mark.parametrize("seed", [4, 12, 19])
def test_explanations_are_always_present_on_random_scenarios(seed):
    """На случайных сценариях ни одно объяснение не теряется."""
    scenario = random_scenario(seed, n_engineers=4, n_requests=25)
    for result in (plan_baseline(scenario), plan_optimized(scenario)):
        for assignment in result.assignments:
            assert assignment.explanation.strip(), (
                f"seed={seed}/{result.algorithm}: {assignment.request_id} без объяснения"
            )
            if assignment.status == AssignmentStatus.UNASSIGNED:
                assert assignment.reason is not None


def test_warnings_are_strings_and_russian():
    """PlanResult.warnings — человекочитаемые строки для интерфейса."""
    scenario = random_scenario(6, n_engineers=3, n_requests=12)
    result = plan_optimized(scenario)
    for warning in result.warnings:
        assert isinstance(warning, str) and warning.strip()


def test_checked_equipment_is_filled_regardless_of_check_equipment():
    """checked_equipment — снимок требования заявки, а не результат проверки.

    Поле заполняется всегда: диспетчеру нужно видеть, что заявка вообще
    требовала снаряжения, даже если проверка была выключена настройкой.
    """
    requests = [req("R1", equipment=["router", "ladder"], at=HOME), req("R2", at=HOME)]
    engineers = [eng("E1", equipment=["router", "ladder"], at=HOME)]

    for check in (False, True):
        scenario = sc(requests, engineers, check_equipment=check)
        by_id = assignments_by_id(plan_optimized(scenario))
        assert set(by_id["R1"].checked_equipment) == {"router", "ladder"}, (
            f"check_equipment={check}: требование заявки не отражено в снимке"
        )
        assert not by_id["R2"].checked_equipment, (
            f"check_equipment={check}: у заявки без требований список должен быть пуст"
        )


def test_checked_skill_is_filled_for_unassigned_requests_too():
    """Снимок требований заполнен и там, где назначения не случилось."""
    scenario = sc(
        [req("R1", skill="emergency", window=("03:00", "04:00"), at=HOME)],
        [eng("E1", skills=["connection"], at=HOME)],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.checked_skill == Skill.EMERGENCY


def test_checked_transport_is_filled_for_unassigned_requests_too():
    """То же для транспорта: требование видно независимо от исхода."""
    scenario = sc(
        [req("R1", transport="bicycle", at=HOME)],
        [eng("E1", transport="car", at=HOME)],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.checked_transport == TransportMode.BICYCLE

# -*- coding: utf-8 -*-
"""Статические жёсткие ограничения (SPEC §4.1) и коды причин (SPEC §1.1).

Каждая проверка разбирается отдельно и в комбинации: важен не только факт
отказа, но и КОД причины — он попадает в объяснение диспетчеру и определяет,
что именно нужно поменять в исходных данных.
"""
from __future__ import annotations

import pytest

from factories import (
    AssignmentStatus,
    ReasonCode,
    Skill,
    TransportMode,
    assignments_by_id,
    eng,
    has_cyrillic,
    plan_baseline,
    plan_optimized,
    req,
    sc,
    settings,
    sym,
)

check_static = sym("check_static")


def fr(engineer, request, **cfg):
    """Короткий вызов статической проверки с настройками по умолчанию."""
    return check_static(engineer, request, settings(**cfg))


# --------------------------------------------------------------------------
# Каждое ограничение по отдельности
# --------------------------------------------------------------------------


def test_matching_engineer_passes_all_static_checks():
    """Полностью подходящий инженер проходит проверку без причины отказа."""
    result = fr(eng("E1", skills=["connection"]), req("R1", skill="connection"))
    assert result.ok is True
    assert result.reason is None


def test_missing_skill_is_rejected_with_no_skill():
    """Нет требуемого навыка — код no_skill (SPEC §4.1 п.3)."""
    result = fr(eng("E1", skills=["local"]), req("R1", skill="connection"))
    assert result.ok is False
    assert result.reason == ReasonCode.NO_SKILL


def test_engineer_with_several_skills_passes():
    """Навыков может быть несколько; достаточно наличия требуемого."""
    result = fr(eng("E1", skills=["local", "connection", "emergency"]), req("R1", skill="emergency"))
    assert result.ok is True


def test_region_mismatch_is_rejected_with_no_region():
    """Межрегиональные назначения запрещены базой знаний — код no_region."""
    result = fr(eng("E1", region="east"), req("R1", region="south"))
    assert result.ok is False
    assert result.reason == ReasonCode.NO_REGION


def test_region_check_can_be_disabled():
    """При check_region=False регион не ограничивает назначение."""
    result = fr(eng("E1", region="east"), req("R1", region="south"), check_region=False)
    assert result.ok is True


def test_required_transport_none_does_not_restrict():
    """required_transport=None означает отсутствие требования (SPEC §2.4)."""
    result = fr(eng("E1", transport="walking"), req("R1", transport=None))
    assert result.ok is True


def test_required_transport_match_passes():
    """Совпадение требуемого и фактического транспорта — допустимо."""
    result = fr(eng("E1", transport="car"), req("R1", transport="car"))
    assert result.ok is True


def test_required_transport_mismatch_is_rejected_with_no_transport():
    """Транспорт не совпал — код no_transport (SPEC §4.1 п.4)."""
    result = fr(eng("E1", transport="walking"), req("R1", transport="car"))
    assert result.ok is False
    assert result.reason == ReasonCode.NO_TRANSPORT


def test_equipment_is_ignored_when_check_equipment_is_false():
    """По умолчанию снаряжение не проверяется («Could have» по ТЗ)."""
    result = fr(eng("E1", equipment=[]), req("R1", equipment=["router"]), check_equipment=False)
    assert result.ok is True


def test_missing_equipment_is_rejected_when_check_enabled():
    """При check_equipment=True недостающее снаряжение даёт no_equipment."""
    result = fr(eng("E1", equipment=["ladder"]), req("R1", equipment=["router"]), check_equipment=True)
    assert result.ok is False
    assert result.reason == ReasonCode.NO_EQUIPMENT


def test_superset_equipment_passes_when_check_enabled():
    """Требуемое снаряжение — подмножество имеющегося: проверка проходит."""
    result = fr(
        eng("E1", equipment=["router", "ladder", "tester"]),
        req("R1", equipment=["router", "ladder"]),
        check_equipment=True,
    )
    assert result.ok is True


def test_inactive_engineer_is_rejected_with_no_work_time():
    """active=False исключает инженера из расчёта (SPEC §4.1 п.1)."""
    result = fr(eng("E1", active=False), req("R1"))
    assert result.ok is False
    assert result.reason == ReasonCode.NO_WORK_TIME


def test_engineer_without_work_intervals_is_rejected_with_no_work_time():
    """Пустой график = выходной, инженер недоступен."""
    result = fr(eng("E1", shift=()), req("R1"))
    assert result.ok is False
    assert result.reason == ReasonCode.NO_WORK_TIME


# --------------------------------------------------------------------------
# Порядок проверок 1 -> 2 -> 3 -> 4 -> 5 (SPEC §4.1)
# --------------------------------------------------------------------------


def test_inactive_beats_every_other_violation():
    """Доступность проверяется первой: неактивный инженер даёт no_work_time."""
    engineer = eng("E1", active=False, skills=["local"], region="east", transport="walking")
    result = fr(engineer, req("R1", skill="connection", region="south", transport="car"))
    assert result.reason == ReasonCode.NO_WORK_TIME


def test_region_is_checked_before_skill():
    """Сначала территория, потом квалификация: no_region важнее no_skill."""
    result = fr(eng("E1", region="east", skills=["local"]), req("R1", region="south", skill="connection"))
    assert result.reason == ReasonCode.NO_REGION


def test_skill_is_checked_before_transport():
    """Квалификация важнее ресурса: no_skill перекрывает no_transport."""
    result = fr(
        eng("E1", skills=["local"], transport="walking"),
        req("R1", skill="connection", transport="car"),
    )
    assert result.reason == ReasonCode.NO_SKILL


def test_transport_is_checked_before_equipment():
    """Транспорт проверяется раньше снаряжения."""
    result = fr(
        eng("E1", transport="walking", equipment=[]),
        req("R1", transport="car", equipment=["router"]),
        check_equipment=True,
    )
    assert result.reason == ReasonCode.NO_TRANSPORT


# --------------------------------------------------------------------------
# FeasibilityResult
# --------------------------------------------------------------------------


def test_failed_check_has_human_readable_russian_detail():
    """detail — текст для диспетчера, значит он непустой и на русском."""
    result = fr(eng("E1", skills=["local"]), req("R1", skill="connection"))
    assert result.detail, "detail не заполнен при отказе"
    assert has_cyrillic(result.detail), f"detail не на русском: {result.detail!r}"


# --------------------------------------------------------------------------
# ReasonCode.rank
# --------------------------------------------------------------------------


def test_reason_code_ranks_match_spec_table():
    """Ранги кодов зафиксированы SPEC §1.1 — от них зависит выбор причины."""
    expected = {
        "NO_ENGINEERS": 0,
        "NO_REGION": 1,
        "NO_SKILL": 2,
        "NO_TRANSPORT": 3,
        "NO_EQUIPMENT": 4,
        "NO_WORK_TIME": 5,
        "TIME_CONFLICT": 6,
        "NOT_FOUND": 7,
    }
    for name, rank in expected.items():
        code = getattr(ReasonCode, name)
        assert code.rank == rank, f"{name}.rank == {code.rank}, ожидался {rank}"


def test_reason_code_ranks_are_unique():
    """Ранги обязаны различаться, иначе «максимальный rank» неоднозначен."""
    ranks = [c.rank for c in ReasonCode]
    assert len(set(ranks)) == len(ranks), f"дубли рангов: {ranks}"


# --------------------------------------------------------------------------
# Выбор итоговой причины по максимальному rank среди ВСЕХ инженеров
# --------------------------------------------------------------------------


def test_reason_is_max_rank_across_all_engineers_not_first_match():
    """Один инженер валится на навыке, другой — на времени: причина time_conflict.

    Это ключевая семантика SPEC §1.1: если кто-то дошёл до проверки времени,
    честная причина — время, а не отсутствие навыка у постороннего инженера.
    """
    no_skill_eng = eng("E1", skills=["local"], order=0)
    # Навык есть, но смена закончится раньше окна заявки -> дойдёт до проверки времени.
    time_eng = eng("E2", skills=["connection"], shift=("09:00", "11:00"), order=1)
    request = req("R1", window=("15:00", "16:00"), dur=60, skill="connection")

    result = plan_optimized(sc([request], [no_skill_eng, time_eng]))
    assignment = assignments_by_id(result)["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.reason == ReasonCode.TIME_CONFLICT, (
        f"ожидался time_conflict (max rank), получено {assignment.reason}"
    )


def test_reason_is_no_skill_when_nobody_has_it_regardless_of_order():
    """Если навыка нет ни у кого — причина no_skill независимо от порядка входа."""
    scenario = sc(
        [req("R1", skill="emergency")],
        [eng("E1", skills=["local"]), eng("E2", skills=["connection"])],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.reason == ReasonCode.NO_SKILL


def test_reason_is_no_region_when_nobody_covers_the_region():
    """Никто не работает в регионе заявки — no_region."""
    scenario = sc(
        [req("R1", region="south")],
        [eng("E1", region="east"), eng("E2", region="west")],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.reason == ReasonCode.NO_REGION


def test_reason_is_no_transport_when_required_mode_absent():
    """Требуемого транспорта нет ни у кого — no_transport."""
    scenario = sc(
        [req("R1", transport="bicycle")],
        [eng("E1", transport="car"), eng("E2", transport="walking")],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.reason == ReasonCode.NO_TRANSPORT


def test_reason_is_no_work_time_when_all_engineers_are_off():
    """Подходящие по профилю инженеры без рабочих интервалов — no_work_time."""
    scenario = sc([req("R1")], [eng("E1", shift=()), eng("E2", active=False)])
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.reason == ReasonCode.NO_WORK_TIME


def test_reason_is_no_engineers_when_input_has_none():
    """Пустой список инженеров — единственный случай кода no_engineers."""
    scenario = sc([req("R1")], [])
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.reason == ReasonCode.NO_ENGINEERS


def test_no_engineers_is_never_used_when_engineers_exist():
    """SPEC §1.1: no_engineers при непустом списке инженеров не выдаётся."""
    scenario = sc(
        [req("R1", skill="emergency"), req("R2", region="mars"), req("R3", transport="bicycle")],
        [eng("E1", skills=["local"], transport="car")],
    )
    for result in (plan_baseline(scenario), plan_optimized(scenario)):
        for assignment in result.unassigned:
            assert assignment.reason != ReasonCode.NO_ENGINEERS, (
                f"{assignment.request_id}: no_engineers при непустом списке инженеров"
            )


def test_equipment_reason_only_appears_when_check_enabled():
    """no_equipment невозможен при выключенной проверке снаряжения."""
    scenario = sc(
        [req("R1", equipment=["router"])],
        [eng("E1", equipment=[])],
        check_equipment=False,
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.status == AssignmentStatus.ASSIGNED
    assert assignment.reason is None


def test_equipment_reason_appears_when_check_enabled():
    """При включённой проверке недостающее снаряжение даёт no_equipment."""
    scenario = sc(
        [req("R1", equipment=["router"])],
        [eng("E1", equipment=["ladder"])],
        check_equipment=True,
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.reason == ReasonCode.NO_EQUIPMENT


def test_combined_static_constraints_all_hold_together():
    """Комбинация: регион + навык + транспорт + снаряжение одновременно."""
    good = eng(
        "E1",
        skills=["connection"],
        region="south",
        transport="car",
        equipment=["router"],
    )
    request = req("R1", skill="connection", region="south", transport="car", equipment=["router"])
    assert fr(good, request, check_equipment=True).ok is True

    for broken in (
        eng("E2", skills=["local"], region="south", transport="car", equipment=["router"]),
        eng("E3", skills=["connection"], region="east", transport="car", equipment=["router"]),
        eng("E4", skills=["connection"], region="south", transport="walking", equipment=["router"]),
        eng("E5", skills=["connection"], region="south", transport="car", equipment=[]),
    ):
        assert fr(broken, request, check_equipment=True).ok is False, f"{broken.id} прошёл проверку"

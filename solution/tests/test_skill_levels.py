# -*- coding: utf-8 -*-
"""Уровень квалификации: хранится и показывается, но на отбор не влияет (SPEC §2.3, §7.3).

Это осознанное решение, а не недоработка: шкала квалификации в базе знаний —
открытый вопрос, и правило «эксперт важнее новичка» пришлось бы придумать за
заказчика. Терять данные тоже нельзя, поэтому уровень доезжает до `Assignment`
как снимок проверенного требования.

Ключевой тест файла — `test_levels_do_not_change_any_assignment`: два сценария,
отличающиеся только уровнями, обязаны дать одинаковое распределение.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from factories import (
    AssignmentStatus,
    Skill,
    eng,
    normalized_dict,
    plan_baseline,
    plan_optimized,
    random_scenario,
    req,
    sc,
    validate_plan,
)

LEVEL_KEY = "checked_qualification_level"


def with_levels(engineer, *pairs):
    """Тот же инженер, но с проставленными уровнями владения навыками."""
    return replace(engineer, skill_levels=tuple(pairs))


def without_levels(scenario):
    """Тот же сценарий, но у всех инженеров уровни стёрты."""
    return replace(
        scenario,
        engineers=tuple(replace(e, skill_levels=()) for e in scenario.engineers),
    )


def shape_without_levels(result):
    """Слепок плана без единственного поля, которое обязано отличаться.

    Всё остальное — маршруты, порядок визитов, времена, метрики — должно совпасть
    до последнего знака: уровень в отборе не участвует.
    """

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != LEVEL_KEY}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return strip(normalized_dict(result))


# --------------------------------------------------------------------------
# Engineer.level_of
# --------------------------------------------------------------------------


def test_level_of_returns_declared_level():
    """SPEC §2.3: `level_of(skill)` отдаёт уровень по конкретному навыку."""
    engineer = with_levels(
        eng("E1", skills=["connection", "local"]),
        (Skill.CONNECTION, "эксперт"),
        (Skill.LOCAL, "новичок"),
    )

    assert engineer.level_of(Skill.CONNECTION) == "эксперт"
    assert engineer.level_of(Skill.LOCAL) == "новичок"


def test_level_of_returns_none_when_level_is_not_set():
    """Уровня может не быть — это нормальные данные, а не ошибка."""
    engineer = with_levels(
        eng("E1", skills=["connection", "local"]), (Skill.CONNECTION, "эксперт")
    )

    assert engineer.level_of(Skill.LOCAL) is None
    assert engineer.level_of(Skill.EMERGENCY) is None


def test_level_of_is_none_for_engineer_without_levels():
    """Пустой `skill_levels` — значение по умолчанию: уровней нет ни по одному навыку."""
    engineer = eng("E1", skills=["connection"])

    assert engineer.skill_levels == ()
    assert engineer.level_of(Skill.CONNECTION) is None


def test_levels_survive_dict_round_trip():
    """Уровень — часть входных данных и обязан переживать сериализацию."""
    engineer = with_levels(
        eng("E1", skills=["connection", "local"]),
        (Skill.CONNECTION, "3"),
        (Skill.LOCAL, "1"),
    )

    restored = type(engineer).from_dict(engineer.to_dict())

    assert restored.level_of(Skill.CONNECTION) == "3"
    assert restored.level_of(Skill.LOCAL) == "1"


def test_levels_are_normalized_to_enum_and_string():
    """Уровень приходит из выгрузки строкой произвольного вида — модель это принимает."""
    engineer = with_levels(eng("E1", skills=["connection"]), ("connection", 3))

    assert engineer.skill_levels == ((Skill.CONNECTION, "3"),)
    assert engineer.level_of(Skill.CONNECTION) == "3"


def test_level_without_the_matching_skill_does_not_grant_it():
    """Уровень — справочная величина; навык даёт только `skills`.

    Иначе запись об уровне «по ошибке» тихо расширила бы квалификацию инженера.
    """
    engineer = with_levels(eng("E1", skills=["connection"]), (Skill.LOCAL, "эксперт"))
    request = req("R1", skill="local", window=("09:30", "17:00"))
    scenario = sc([request], [engineer])

    result = plan_optimized(scenario)

    assert result.assignment_of("R1").status is AssignmentStatus.UNASSIGNED


# --------------------------------------------------------------------------
# Уровень не влияет на отбор
# --------------------------------------------------------------------------


def _paired_scenarios():
    """Пара сценариев, отличающихся ровно уровнями квалификации."""
    e1 = eng("E1", skills=["connection", "local"], at=(55.70, 37.60), order=0)
    e2 = eng("E2", skills=["connection", "local"], at=(55.72, 37.64), order=1)
    requests = [
        req(
            f"R{i}",
            window=("09:30", "17:00"),
            dur=40,
            skill="connection" if i % 2 else "local",
            at=(55.70 + 0.006 * i, 37.60 + 0.006 * i),
            order=i,
        )
        for i in range(8)
    ]
    plain = sc(requests, [e1, e2])
    # У «слабого» инженера уровень ниже, и он же идёт первым во входе: если бы
    # уровень учитывался, распределение обязано было бы измениться.
    leveled = replace(
        plain,
        engineers=(
            with_levels(e1, (Skill.CONNECTION, "новичок"), (Skill.LOCAL, "новичок")),
            with_levels(e2, (Skill.CONNECTION, "эксперт"), (Skill.LOCAL, "эксперт")),
        ),
    )
    return plain, leveled


@pytest.mark.parametrize("build", [plan_baseline, plan_optimized], ids=["baseline", "optimized"])
def test_levels_do_not_change_any_assignment(build):
    """Наличие уровней не меняет план ничем, кроме самого поля уровня.

    Это и есть зафиксированное решение SPEC §2.3: «хранится и показывается,
    НА ОТБОР НЕ ВЛИЯЕТ».
    """
    plain, leveled = _paired_scenarios()

    assert shape_without_levels(build(plain)) == shape_without_levels(build(leveled))


def test_level_value_does_not_change_any_assignment():
    """Не только наличие уровня, но и его значение обязано быть нейтральным."""
    _, leveled = _paired_scenarios()
    swapped = replace(
        leveled,
        engineers=tuple(
            replace(e, skill_levels=tuple((s, "1" if lvl == "эксперт" else "9") for s, lvl in e.skill_levels))
            for e in leveled.engineers
        ),
    )

    assert shape_without_levels(plan_optimized(leveled)) == shape_without_levels(
        plan_optimized(swapped)
    )


@pytest.mark.property
@pytest.mark.parametrize("seed", [11, 12, 13])
def test_levels_are_neutral_on_random_scenarios(seed):
    """То же свойство на псевдослучайных сценариях — на случай, если нейтральность
    держится только на маленьком примере."""
    plain = random_scenario(seed, n_engineers=4, n_requests=18)
    leveled = replace(
        plain,
        engineers=tuple(
            with_levels(e, *[(s, f"уровень-{i}") for i, s in enumerate(sorted(e.skills))])
            for e in plain.engineers
        ),
    )

    assert shape_without_levels(plan_optimized(plain)) == shape_without_levels(
        plan_optimized(leveled)
    )
    assert validate_plan(plan_optimized(leveled), leveled) == []


# --------------------------------------------------------------------------
# Assignment.checked_qualification_level
# --------------------------------------------------------------------------


def test_checked_level_is_the_level_of_the_required_skill():
    """В назначении показывается уровень именно по требуемому навыку, а не первый попавшийся."""
    engineer = with_levels(
        eng("E1", skills=["connection", "local"], at=(55.70, 37.60)),
        (Skill.LOCAL, "новичок"),
        (Skill.CONNECTION, "эксперт"),
    )
    scenario = sc([req("R1", skill="connection", window=("09:30", "17:00"))], [engineer])

    assignment = plan_optimized(scenario).assignment_of("R1")

    assert assignment.status is AssignmentStatus.ASSIGNED
    assert assignment.checked_qualification_level == "эксперт"


def test_checked_level_is_none_when_engineer_has_no_level():
    """Уровень не задан — в назначении честный `None`, а не пустая строка или выдумка."""
    scenario = sc(
        [req("R1", skill="connection", window=("09:30", "17:00"))],
        [eng("E1", skills=["connection"], at=(55.70, 37.60))],
    )

    assignment = plan_optimized(scenario).assignment_of("R1")

    assert assignment.status is AssignmentStatus.ASSIGNED
    assert assignment.checked_qualification_level is None


def test_checked_level_is_none_when_only_another_skill_is_graded():
    """Уровень по чужому навыку не подставляется в назначение."""
    engineer = with_levels(
        eng("E1", skills=["connection", "local"], at=(55.70, 37.60)), (Skill.LOCAL, "эксперт")
    )
    scenario = sc([req("R1", skill="connection", window=("09:30", "17:00"))], [engineer])

    assert plan_optimized(scenario).assignment_of("R1").checked_qualification_level is None


def test_unassigned_request_has_no_qualification_level():
    """Неназначенную заявку никто не проверял на квалификацию — поле пустое."""
    scenario = sc(
        [req("R1", skill="emergency", window=("09:30", "17:00"))],
        [eng("E1", skills=["connection"], at=(55.70, 37.60))],
    )

    assignment = plan_optimized(scenario).assignment_of("R1")

    assert assignment.status is AssignmentStatus.UNASSIGNED
    assert assignment.checked_qualification_level is None


def test_checked_level_is_serialized():
    """SPEC §7.3 перечисляет поле среди снимка требований — значит, оно есть в `to_dict()`."""
    engineer = with_levels(
        eng("E1", skills=["connection"], at=(55.70, 37.60)), (Skill.CONNECTION, "эксперт")
    )
    scenario = sc([req("R1", skill="connection", window=("09:30", "17:00"))], [engineer])
    result = plan_optimized(scenario)

    data = result.to_dict()
    assignment = data["assignments"][0]

    assert LEVEL_KEY in assignment
    assert assignment[LEVEL_KEY] == "эксперт"


def test_checked_level_key_exists_even_when_empty():
    """Ключ присутствует всегда — потребитель JSON не должен угадывать его наличие."""
    scenario = sc(
        [req("R1", skill="connection", window=("09:30", "17:00"))],
        [eng("E1", skills=["connection"], at=(55.70, 37.60))],
    )

    assignment = plan_optimized(scenario).to_dict()["assignments"][0]

    assert LEVEL_KEY in assignment
    assert assignment[LEVEL_KEY] is None

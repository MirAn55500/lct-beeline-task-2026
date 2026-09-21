# -*- coding: utf-8 -*-
"""Ручное переназначение диспетчером — `planner.reassign` (SPEC §8).

Смысл функции: диспетчер видит то, чего не видит алгоритм («на этом адресе злая
собака»), и вправе поставить своего исполнителя. Но ручное решение **не обходит
жёсткие ограничения**: недопустимый ход отклоняется, план возвращается неизменным,
причина уходит и в `warnings`, и в `diff.summary`.

Поэтому почти половина файла — про пути отказа. Молча принятый недопустимый ход
опаснее отказа: диспетчер получит расписание, которое невозможно выполнить, и узнает
об этом только от инженера в поле.
"""
from __future__ import annotations

import pytest

from factories import (
    Algorithm,
    AssignmentStatus,
    EventType,
    assignments_by_id,
    eng,
    has_cyrillic,
    normalized_dict,
    plan_optimized,
    replan,
    req,
    sc,
    scenario_after,
    event,
    sym,
    validate_plan,
)

reassign = sym("reassign")


# --------------------------------------------------------------------------
# Общий стенд: один «рабочий» инженер, один свободный и по инженеру на каждый
# путь отказа. Все они присутствуют во входе, поэтому reassign обязан различать
# «инженер есть, но ход недопустим» и «инженера нет вовсе».
# --------------------------------------------------------------------------


def _engineers():
    return [
        eng("E1", skills=["connection"], at=(55.70, 37.60), order=0),
        eng("E2", skills=["connection"], at=(55.70, 37.60), order=1),
        eng("E-NOSKILL", skills=["local"], at=(55.70, 37.60), order=2),
        eng("E-REGION", skills=["connection"], at=(55.70, 37.60), region="north", order=3),
        eng("E-WALK", skills=["connection"], at=(55.70, 37.60), transport="walking", order=4),
        # смена в полчаса: статические проверки проходит, но 60-минутная работа
        # не влезает ни на одну позицию — это отдельный путь отказа.
        eng("E-SHORT", skills=["connection"], at=(55.70, 37.60), shift=("09:00", "09:30"), order=5),
        eng("E-OFF", skills=["connection"], at=(55.70, 37.60), active=False, order=6),
    ]


def _requests():
    return [
        req("R1", window=("09:30", "16:00"), dur=60, transport="car", at=(55.705, 37.605), order=0),
        req("R2", window=("09:30", "16:00"), dur=60, transport="car", at=(55.706, 37.606), order=1),
        # позднее окно: на первые позиции маршрута E1 эта заявка не встаёт
        req("R3", window=("15:00", "16:00"), dur=60, transport="car", at=(55.707, 37.607), order=2),
    ]


@pytest.fixture
def scenario():
    return sc(_requests(), _engineers())


@pytest.fixture
def base(scenario):
    """Исходный план: все три заявки у E1, остальные инженеры свободны."""
    result = plan_optimized(scenario)
    assert validate_plan(result, scenario) == []
    return result


def route_map(result) -> dict[str, tuple[str, ...]]:
    """engineer_id -> порядок посещения заявок."""
    return {r.engineer_id: tuple(v.request_id for v in r.visits) for r in result.routes}


def plan_shape(result):
    """Содержательный слепок плана: маршруты и назначения без волатильных полей.

    Именно он обязан совпасть с исходным, когда ручной ход отклонён.
    """
    data = normalized_dict(result)
    return data["routes"], data["assignments"]


def new_warnings(result, previous) -> tuple[str, ...]:
    """Предупреждения, добавленные к плану этим ручным ходом."""
    return result.warnings[len(previous.warnings):]


# --------------------------------------------------------------------------
# Публичность и базовые свойства
# --------------------------------------------------------------------------


def test_reassign_is_exported_from_package_root():
    """SPEC §8 объявляет `reassign` частью публичного API пакета."""
    import planner

    assert callable(getattr(planner, "reassign", None))


def test_reassign_returns_plan_result_with_diff(base, scenario):
    """Ручной ход — это новая версия плана, и он обязан объяснить, что изменилось."""
    result = reassign(base, scenario, "R1", "E2")

    assert result.algorithm is Algorithm.OPTIMIZED
    assert result.diff is not None
    assert result.diff.previous_plan_id == base.plan_id


# --------------------------------------------------------------------------
# Успешный перенос
# --------------------------------------------------------------------------


def test_reassign_moves_request_to_chosen_engineer(base, scenario):
    """Главный сценарий: диспетчер назвал исполнителя — заявка у него."""
    assert route_map(base) == {"E1": ("R1", "R2", "R3")}

    result = reassign(base, scenario, "R1", "E2")

    assert result.assignment_of("R1").engineer_id == "E2"
    assert "R1" in route_map(result)["E2"]


def test_reassign_result_passes_independent_verifier(base, scenario):
    """Ручной ход не меняет состав заявок, поэтому верификатор зовётся с ИСХОДНЫМ сценарием.

    Этим ручное вмешательство отличается от `replan()`: там сценарий после события
    другой, здесь — тот же самый.
    """
    result = reassign(base, scenario, "R1", "E2")

    assert validate_plan(result, scenario) == []


def test_reassign_does_not_lose_other_requests(base, scenario):
    """Перенос одной заявки не имеет права уронить чужие назначения."""
    result = reassign(base, scenario, "R1", "E2")

    before = assignments_by_id(base)
    after = assignments_by_id(result)
    assert set(after) == {r.id for r in scenario.requests}
    for request_id in ("R2", "R3"):
        assert after[request_id].status is AssignmentStatus.ASSIGNED
        assert after[request_id].engineer_id == before[request_id].engineer_id


def test_reassign_keeps_one_assignment_per_request(base, scenario):
    """Инвариант §9 п. 1-2 обязан пережить ручное вмешательство."""
    result = reassign(base, scenario, "R1", "E2")

    ids = [a.request_id for a in result.assignments]
    assert sorted(ids) == sorted({r.id for r in scenario.requests})
    placed = [v.request_id for route in result.routes for v in route.visits]
    assert len(placed) == len(set(placed))


def test_reassign_to_the_same_engineer_is_idempotent(base, scenario):
    """Перенос к тому, у кого заявка уже есть, — законный «ничего не делать».

    Диспетчер не обязан помнить текущее распределение; повтор не должен ломать план.
    """
    result = reassign(base, scenario, "R1", "E1")

    assert new_warnings(result, base) == ()
    assert route_map(result) == route_map(base)
    assert validate_plan(result, scenario) == []


def test_reassign_is_deterministic(base, scenario):
    """SPEC §0: одинаковый вход — побайтово одинаковая содержательная часть выхода."""
    first = reassign(base, scenario, "R1", "E2")
    second = reassign(base, scenario, "R1", "E2")

    assert normalized_dict(first) == normalized_dict(second)


# --------------------------------------------------------------------------
# Позиция в маршруте
# --------------------------------------------------------------------------


@pytest.fixture
def one_route():
    """Один инженер и три одинаково гибкие заявки — стенд для проверки позиций."""
    requests = [
        req("RA", window=("09:00", "17:00"), dur=40, at=(55.705, 37.605), order=0),
        req("RB", window=("09:00", "17:00"), dur=40, at=(55.706, 37.606), order=1),
        req("RC", window=("09:00", "17:00"), dur=40, at=(55.707, 37.607), order=2),
    ]
    scenario = sc(requests, [eng("E1", skills=["connection"], at=(55.70, 37.60))])
    return scenario, plan_optimized(scenario)


@pytest.mark.parametrize(
    "position, expected",
    [
        (1, ("RC", "RA", "RB")),
        (2, ("RA", "RC", "RB")),
        (3, ("RA", "RB", "RC")),
    ],
)
def test_position_is_one_based_and_exact(one_route, position, expected):
    """SPEC §8: `position` нумеруется с 1 и означает именно это место в маршруте."""
    scenario, base = one_route
    assert route_map(base) == {"E1": ("RA", "RB", "RC")}

    result = reassign(base, scenario, "RC", "E1", position)

    assert new_warnings(result, base) == ()
    assert route_map(result)["E1"] == expected
    assert result.assignment_of("RC").position == position
    assert validate_plan(result, scenario) == []


def test_position_none_means_best_place(one_route):
    """`position=None` — «поставь, где дешевле»: план остаётся допустимым."""
    scenario, base = one_route

    result = reassign(base, scenario, "RC", "E1", None)

    assert new_warnings(result, base) == ()
    assert set(route_map(result)["E1"]) == {"RA", "RB", "RC"}
    assert validate_plan(result, scenario) == []


def test_visit_positions_stay_continuous_after_manual_move(base, scenario):
    """Инвариант §9 п. 5: нумерация позиций в маршруте — непрерывная, с 1."""
    result = reassign(base, scenario, "R1", "E2")

    for route in result.routes:
        assert [v.position for v in route.visits] == list(range(1, len(route.visits) + 1))


# --------------------------------------------------------------------------
# Снятие с исполнителя
# --------------------------------------------------------------------------


def test_none_engineer_unassigns_request(base, scenario):
    """`engineer_id=None` снимает заявку: она больше ни в одном маршруте."""
    result = reassign(base, scenario, "R1", None)

    assignment = result.assignment_of("R1")
    assert assignment.status is AssignmentStatus.UNASSIGNED
    assert assignment.engineer_id is None
    assert "R1" not in [v.request_id for route in result.routes for v in route.visits]


def test_unassigned_explanation_names_manual_removal(base, scenario):
    """Диспетчер должен видеть, что заявка без исполнителя не из-за ограничений, а по его команде.

    Иначе снятая вручную заявка неотличима от той, которую алгоритм не смог разместить.
    """
    result = reassign(base, scenario, "R1", None)
    text = result.assignment_of("R1").explanation

    assert has_cyrillic(text)
    assert "вручную" in text.lower()
    assert "диспетчер" in text.lower()


def test_unassigned_by_dispatcher_keeps_reason_filled(base, scenario):
    """Инвариант §9 п. 6: у неназначенной заявки заполнены `reason` и `explanation`."""
    result = reassign(base, scenario, "R1", None)
    assignment = result.assignment_of("R1")

    assert assignment.reason is not None
    assert assignment.explanation.strip() != ""


def test_unassigned_slice_sees_the_manual_explanation(base, scenario):
    """Срез `unassigned` — то же самое назначение, а не устаревшая копия."""
    result = reassign(base, scenario, "R1", None)

    in_slice = {a.request_id: a.explanation for a in result.unassigned}
    assert in_slice["R1"] == result.assignment_of("R1").explanation


def test_unassign_updates_metrics(base, scenario):
    """Снятая заявка обязана попасть в счётчики, иначе метрики врут диспетчеру."""
    result = reassign(base, scenario, "R1", None)

    assert result.metrics.unassigned_count == base.metrics.unassigned_count + 1
    assert result.metrics.assigned_count == base.metrics.assigned_count - 1
    assert result.metrics.feasible_count == result.metrics.assigned_count


def test_unassign_result_passes_independent_verifier(base, scenario):
    """План без одной заявки остаётся корректным планом того же сценария."""
    result = reassign(base, scenario, "R1", None)

    assert validate_plan(result, scenario) == []


def test_unassign_mentions_request_in_diff(base, scenario):
    """`diff` обязан показать, что заявка стала неназначенной."""
    result = reassign(base, scenario, "R1", None)

    assert "R1" in result.diff.newly_unassigned_request_ids
    assert "R1" in result.diff.changed_request_ids


# --------------------------------------------------------------------------
# Пути отказа: план возвращается неизменным
# --------------------------------------------------------------------------

REFUSALS = [
    pytest.param("R1", "E-NOSKILL", None, "навык", id="нет-навыка"),
    pytest.param("R1", "E-REGION", None, "регион", id="чужой-регион"),
    pytest.param("R1", "E-WALK", None, "транспорт", id="не-тот-транспорт"),
    pytest.param("R1", "E-SHORT", 1, "позицию 1", id="не-влезает-в-позицию"),
    pytest.param("R3", "E1", 1, "позицию 1", id="позиция-ломает-окна"),
    pytest.param("R1", "E-SHORT", None, "ни одного места", id="ни-одна-позиция-не-подходит"),
    pytest.param("НЕТ-ТАКОЙ", "E2", None, "НЕТ-ТАКОЙ", id="неизвестная-заявка"),
    pytest.param("R1", "НЕТ-ТАКОГО", None, "НЕТ-ТАКОГО", id="неизвестный-инженер"),
    pytest.param("R1", "E-OFF", None, "E-OFF", id="инженер-вне-расчёта"),
]


@pytest.mark.parametrize("request_id, engineer_id, position, fragment", REFUSALS)
def test_refused_move_returns_the_previous_plan_unchanged(
    base, scenario, request_id, engineer_id, position, fragment
):
    """SPEC §8: недопустимый ход отклоняется, план возвращается **неизменным**.

    Сверяется весь содержательный слепок, а не только состав маршрутов: порядок
    визитов и расписание обязаны совпасть до минуты.
    """
    result = reassign(base, scenario, request_id, engineer_id, position)

    assert plan_shape(result) == plan_shape(base)
    assert route_map(result) == route_map(base)


@pytest.mark.parametrize("request_id, engineer_id, position, fragment", REFUSALS)
def test_refused_move_explains_itself_in_warnings(
    base, scenario, request_id, engineer_id, position, fragment
):
    """Причина отказа обязана дойти до диспетчера — она попадает в `warnings`."""
    result = reassign(base, scenario, request_id, engineer_id, position)

    added = new_warnings(result, base)
    assert len(added) == 1
    assert has_cyrillic(added[0])
    assert fragment in added[0]


@pytest.mark.parametrize("request_id, engineer_id, position, fragment", REFUSALS)
def test_refused_move_explains_itself_in_diff_summary(
    base, scenario, request_id, engineer_id, position, fragment
):
    """SPEC §8 требует причину и в `diff.summary`: интерфейс показывает именно его."""
    result = reassign(base, scenario, request_id, engineer_id, position)

    assert result.diff is not None
    assert fragment in result.diff.summary
    assert has_cyrillic(result.diff.summary)


@pytest.mark.parametrize("request_id, engineer_id, position, fragment", REFUSALS)
def test_refused_move_reports_no_route_as_changed(
    base, scenario, request_id, engineer_id, position, fragment
):
    """Раз план не изменился, `diff` не имеет права объявлять маршруты изменёнными."""
    result = reassign(base, scenario, request_id, engineer_id, position)
    diff = result.diff

    assert diff.changed_request_ids == ()
    assert diff.changed_route_engineer_ids == ()
    assert diff.removed_route_engineer_ids == ()
    assert set(diff.unchanged_route_engineer_ids) == {r.engineer_id for r in base.routes}


@pytest.mark.parametrize("request_id, engineer_id, position, fragment", REFUSALS)
def test_refused_move_does_not_touch_the_previous_plan(
    base, scenario, request_id, engineer_id, position, fragment
):
    """Прошлый план — вход функции; дописывать в него предупреждения нельзя.

    Иначе повторный отказ накапливает мусор в объекте, который диспетчер всё ещё видит.
    """
    before = normalized_dict(base)
    warnings_before = base.warnings

    reassign(base, scenario, request_id, engineer_id, position)

    assert normalized_dict(base) == before
    assert base.warnings == warnings_before


def test_refusal_keeps_plan_valid(base, scenario):
    """Отклонённый ход оставляет план, который по-прежнему проходит верификатор."""
    result = reassign(base, scenario, "R1", "E-NOSKILL")

    assert validate_plan(result, scenario) == []


def test_position_beyond_route_length_is_refused(base, scenario):
    """Позиция за пределами маршрута — такой же недопустимый ход, а не «в конец».

    После снятия заявки в маршруте E1 остаётся два визита, поэтому позиция 4 не существует.
    """
    result = reassign(base, scenario, "R3", "E1", 4)

    assert plan_shape(result) == plan_shape(base)
    assert len(new_warnings(result, base)) == 1


# --------------------------------------------------------------------------
# Diff успешного хода
# --------------------------------------------------------------------------


def test_successful_move_marks_both_routes_changed(base, scenario):
    """Перенос меняет два маршрута — и отдающий, и принимающий."""
    result = reassign(base, scenario, "R1", "E2")
    diff = result.diff

    assert "R1" in diff.changed_request_ids
    assert {"E1", "E2"} <= set(diff.changed_route_engineer_ids)
    assert "E1" not in diff.unchanged_route_engineer_ids


def test_successful_move_summary_calls_it_manual(base, scenario):
    """Диспетчер должен отличать свой ход от реакции алгоритма на событие."""
    result = reassign(base, scenario, "R1", "E2")

    assert "Ручное переназначение" in result.diff.summary
    assert "отклонено" not in result.diff.summary


def test_emptied_route_is_reported_as_removed(one_route):
    """Если у инженера не осталось визитов, маршрут исчезает (инвариант §9 п. 7)."""
    scenario, base = one_route

    result = base
    for request_id in ("RA", "RB", "RC"):
        result = reassign(result, scenario, request_id, None)

    assert result.routes == ()
    assert result.metrics.used_engineer_count == 0
    assert validate_plan(result, scenario) == []


# --------------------------------------------------------------------------
# Начатая работа
# --------------------------------------------------------------------------


@pytest.fixture
def plan_with_locked_visit():
    """План после события, в котором один визит уже начат и помечен `locked`."""
    engineers = [
        eng("E1", skills=["connection"], at=(55.70, 37.60), order=0),
        eng("E2", skills=["connection"], at=(55.70, 37.60), order=1),
    ]
    requests = [
        req("RA", window=("09:30", "10:00"), dur=60, at=(55.705, 37.605), order=0),
        req("RB", window=("09:30", "10:00"), dur=60, at=(55.706, 37.606), order=1),
        req("RC", window=("13:00", "16:00"), dur=60, at=(55.707, 37.607), order=2),
    ]
    scenario = sc(requests, engineers)
    first = plan_optimized(scenario)
    ev = event("cancel_request", "11:00", request_id="RC")
    after = scenario_after(scenario, first, ev)
    repaired = replan(first, after, ev)
    locked = [v.request_id for r in repaired.routes for v in r.visits if v.locked]
    assert locked, "стенд сломан: ни один визит не оказался замороженным"
    return after, repaired, locked[0]


def test_started_request_cannot_be_taken_away_by_hand(plan_with_locked_visit):
    """Начатую работу нельзя снять задним числом — инженер уже у клиента.

    SPEC §6.3 объявляет заморозку безусловным инвариантом: «locked-назначения не
    меняются никогда». Ручной ход — не исключение.
    """
    scenario, previous, request_id = plan_with_locked_visit

    result = reassign(previous, scenario, request_id, None)

    assert result.assignment_of(request_id).status is AssignmentStatus.ASSIGNED
    assert len(result.warnings) > len(previous.warnings)


# --------------------------------------------------------------------------
# Тип изменения: ручной ход не притворяется аварией
# --------------------------------------------------------------------------


def test_diff_marks_the_change_as_manual(base, scenario):
    """`diff.event_type` отвечает «почему план изменился» — значит, «руками диспетчера».

    Раньше ручной ход подписывался чужим типом `urgent_request`, и в журнале событий
    выглядел как поступившая авария: `summary` говорил правду, а машиночитаемое поле
    врало.
    """
    result = reassign(base, scenario, "R1", "E2")

    assert result.diff.event_type is EventType.MANUAL_REASSIGN
    assert result.diff.to_dict()["event_type"] == "manual_reassign"


def test_refused_move_is_also_marked_as_manual(base, scenario):
    """Отклонённый ручной ход — тоже ручной ход, а не авария."""
    result = reassign(base, scenario, "НЕТ-ТАКОЙ", "E2")

    assert result.diff.event_type is EventType.MANUAL_REASSIGN


def test_manual_summary_names_the_dispatcher(base, scenario):
    """Пояснение по-прежнему начинается с того, кто изменил план."""
    result = reassign(base, scenario, "R1", "E2")

    assert has_cyrillic(result.diff.summary)
    assert "ручное переназначение" in result.diff.summary.lower()

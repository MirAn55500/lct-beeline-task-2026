# -*- coding: utf-8 -*-
"""`planner.apply_event()` — событие, внесённое во входные данные (SPEC §6.3 п.2).

Это единственный корректный способ узнать, какой сценарий описывает результат
`replan()`: после события состав заявок меняется, и проверять ремонт против
исходного сценария нельзя. Функция публичная, поэтому её контракт фиксируется
отдельно от самого перепланирования.
"""
from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from factories import (
    EventType,
    Priority,
    apply_event,
    eng,
    event,
    has_cyrillic,
    hhmm,
    minutes_between,
    plan_optimized,
    req,
    sc,
    t,
)

HOME = (55.70, 37.60)
EVENT_AT = "13:00"


def base_scenario():
    """Два инженера, работы до и после момента события."""
    engineers = [
        eng("E1", shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", shift=("09:00", "18:00"), at=HOME, order=1),
    ]
    requests = [
        req("R1", window=("09:00", "10:00"), dur=60, at=HOME),
        req("R2", window=("09:00", "10:00"), dur=60, at=HOME),
        req("R3", window=("14:00", "15:00"), dur=60, at=HOME),
        req("R4", window=("15:30", "16:30"), dur=45, at=HOME),
    ]
    return sc(requests, engineers, name="apply-event-base")


@pytest.fixture(scope="module")
def prepared():
    """Сценарий и построенный по нему план — общий вход для всех событий."""
    scenario = base_scenario()
    return scenario, plan_optimized(scenario)


def requests_by_id(scenario):
    """Отображение id -> Request для удобного сравнения составов."""
    return {r.id: r for r in scenario.requests}


def engineers_by_id(scenario):
    """Отображение id -> Engineer."""
    return {e.id: e for e in scenario.engineers}


# --------------------------------------------------------------------------
# Общий контракт
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["urgent", "cancel", "refusal", "unavailable"],
)
def test_apply_event_returns_scenario_and_string_notes(prepared, name):
    """Возвращается пара (Scenario, список примечаний) — контракт SPEC §6.3."""
    scenario, before = prepared
    events = {
        "urgent": event(
            EventType.URGENT_REQUEST,
            EVENT_AT,
            request=req(
                "RU",
                window=("13:30", "14:30"),
                dur=30,
                at=HOME,
                skill="emergency",
                priority="emergency",
            ),
        ),
        "cancel": event(EventType.CANCEL_REQUEST, EVENT_AT, request_id="R3"),
        "refusal": event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="R3"),
        "unavailable": event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="E2"),
    }
    updated, notes = apply_event(scenario, before, events[name])

    assert hasattr(updated, "requests") and hasattr(updated, "engineers")
    assert isinstance(notes, list)
    assert all(isinstance(note, str) and note.strip() for note in notes)
    assert updated.date == scenario.date
    assert updated.settings is scenario.settings or updated.settings == scenario.settings


@pytest.mark.parametrize(
    "name",
    ["urgent", "cancel", "refusal", "unavailable"],
)
def test_apply_event_does_not_mutate_input_scenario(prepared, name):
    """Исходный сценарий остаётся нетронутым — событие порождает новый снимок."""
    scenario, before = prepared
    events = {
        "urgent": event(
            EventType.URGENT_REQUEST,
            EVENT_AT,
            request=req("RU", window=("13:30", "14:30"), dur=30, at=HOME),
        ),
        "cancel": event(EventType.CANCEL_REQUEST, EVENT_AT, request_id="R3"),
        "refusal": event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="R3"),
        "unavailable": event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="E2"),
    }
    snapshot = copy.deepcopy(scenario)
    apply_event(scenario, before, events[name])
    assert scenario == snapshot, "apply_event изменил переданный сценарий"


def test_apply_event_is_deterministic(prepared):
    """Два одинаковых вызова дают одинаковый сценарий и одинаковые примечания."""
    scenario, before = prepared
    ev = event(EventType.CLIENT_REFUSAL, "14:30", request_id="R3")
    first, notes_first = apply_event(scenario, before, ev)
    second, notes_second = apply_event(scenario, before, ev)
    assert first == second
    assert notes_first == notes_second


# --------------------------------------------------------------------------
# URGENT_REQUEST
# --------------------------------------------------------------------------


def test_urgent_event_adds_the_request(prepared):
    """Срочная заявка появляется в действующем сценарии."""
    scenario, before = prepared
    urgent = req("RU", window=("13:30", "14:30"), dur=30, at=HOME, skill="emergency", priority="emergency")
    updated, _notes = apply_event(
        scenario, before, event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent)
    )

    assert "RU" in requests_by_id(updated)
    assert len(updated.requests) == len(scenario.requests) + 1


def test_urgent_event_forces_emergency_priority(prepared):
    """Заявка события URGENT_REQUEST — авария по определению, даже если пришла как подключение."""
    scenario, before = prepared
    connection = req("RU", window=("13:30", "14:30"), dur=30, at=HOME, priority="connection")
    updated, _notes = apply_event(
        scenario, before, event(EventType.URGENT_REQUEST, EVENT_AT, request=connection)
    )
    added = requests_by_id(updated)["RU"]
    assert added.priority == Priority.EMERGENCY
    assert added.is_emergency is True
    assert added.received_at == t(EVENT_AT)


def test_urgent_event_keeps_existing_received_at(prepared):
    """Если поступление уже задано, apply_event не подменяет его временем события."""
    scenario, before = prepared
    stamped = req(
        "RU",
        window=("13:30", "14:30"),
        dur=30,
        at=HOME,
        received_at="12:45",
    )
    updated, _notes = apply_event(
        scenario, before, event(EventType.URGENT_REQUEST, EVENT_AT, request=stamped)
    )
    assert requests_by_id(updated)["RU"].received_at == t("12:45")


def test_urgent_event_puts_the_request_last_in_input_order(prepared):
    """Новая заявка получает input_order после всех существующих."""
    scenario, before = prepared
    urgent = req("RU", window=("13:30", "14:30"), dur=30, at=HOME)
    updated, _notes = apply_event(
        scenario, before, event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent)
    )
    orders = {r.id: r.input_order for r in updated.requests}
    assert orders["RU"] > max(v for k, v in orders.items() if k != "RU")


def test_urgent_event_does_not_touch_existing_requests(prepared):
    """Остальные заявки переносятся в новый сценарий без изменений."""
    scenario, before = prepared
    urgent = req("RU", window=("13:30", "14:30"), dur=30, at=HOME)
    updated, _notes = apply_event(
        scenario, before, event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent)
    )
    original = requests_by_id(scenario)
    for request_id, request in requests_by_id(updated).items():
        if request_id == "RU":
            continue
        assert request == original[request_id], f"{request_id} изменилась при вставке аварийной"


def test_urgent_event_does_not_touch_engineers(prepared):
    """Состав исполнителей событием аварийной заявки не меняется."""
    scenario, before = prepared
    urgent = req("RU", window=("13:30", "14:30"), dur=30, at=HOME)
    updated, _notes = apply_event(
        scenario, before, event(EventType.URGENT_REQUEST, EVENT_AT, request=urgent)
    )
    assert updated.engineers == scenario.engineers


def test_urgent_event_with_existing_id_replaces_instead_of_duplicating(prepared):
    """Повторное событие по той же заявке не создаёт дубль id."""
    scenario, before = prepared
    replacement = req("R3", window=("13:30", "14:30"), dur=15, at=HOME)
    updated, _notes = apply_event(
        scenario, before, event(EventType.URGENT_REQUEST, EVENT_AT, request=replacement)
    )
    ids = [r.id for r in updated.requests]
    assert len(ids) == len(set(ids)), f"дубликаты id: {ids}"
    assert requests_by_id(updated)["R3"].duration_minutes == 15
    assert requests_by_id(updated)["R3"].priority == Priority.EMERGENCY


# --------------------------------------------------------------------------
# CANCEL_REQUEST
# --------------------------------------------------------------------------


def test_cancel_event_removes_the_request(prepared):
    """Отменённая заявка исчезает из действующего сценария."""
    scenario, before = prepared
    updated, _notes = apply_event(
        scenario, before, event(EventType.CANCEL_REQUEST, EVENT_AT, request_id="R3")
    )
    assert "R3" not in requests_by_id(updated)
    assert len(updated.requests) == len(scenario.requests) - 1


def test_cancel_event_keeps_other_requests_intact(prepared):
    """Отмена одной заявки не трогает остальные и не трогает инженеров."""
    scenario, before = prepared
    updated, _notes = apply_event(
        scenario, before, event(EventType.CANCEL_REQUEST, EVENT_AT, request_id="R3")
    )
    original = requests_by_id(scenario)
    for request_id, request in requests_by_id(updated).items():
        assert request == original[request_id]
    assert updated.engineers == scenario.engineers


def test_cancel_event_for_unknown_request_warns(prepared):
    """Отмена несуществующей заявки — примечание, а не исключение."""
    scenario, before = prepared
    updated, notes = apply_event(
        scenario, before, event(EventType.CANCEL_REQUEST, EVENT_AT, request_id="NOPE")
    )
    assert len(updated.requests) == len(scenario.requests)
    assert notes, "отмена неизвестной заявки должна попадать в примечания"
    assert any("NOPE" in note for note in notes), notes


# --------------------------------------------------------------------------
# CLIENT_REFUSAL
# --------------------------------------------------------------------------


def test_refusal_before_service_start_zeroes_the_duration(prepared):
    """Отказ до начала работ: работа не выполнялась вовсе, длительность 0."""
    scenario, before = prepared
    updated, notes = apply_event(
        scenario, before, event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="R3")
    )
    assert requests_by_id(updated)["R3"].duration_minutes == 0
    assert notes and any(has_cyrillic(note) for note in notes)


def test_refusal_mid_work_keeps_only_the_time_actually_spent(prepared):
    """Отказ посреди работы: засчитываются только фактически потраченные минуты."""
    scenario, before = prepared
    start = before.assignment_of("R3").service_start_at
    moment = start + timedelta(minutes=30)
    updated, _notes = apply_event(
        scenario, before, event(EventType.CLIENT_REFUSAL, moment, request_id="R3")
    )
    expected = round(minutes_between(start, moment))
    assert requests_by_id(updated)["R3"].duration_minutes == expected, (
        f"с {hhmm(start)} до {hhmm(moment)} прошло {expected} мин"
    )


def test_refusal_never_produces_negative_duration(prepared):
    """Событие раньше начала работ не даёт отрицательную длительность."""
    scenario, before = prepared
    updated, _notes = apply_event(
        scenario, before, event(EventType.CLIENT_REFUSAL, "09:00", request_id="R3")
    )
    assert requests_by_id(updated)["R3"].duration_minutes >= 0


def test_refusal_does_not_shift_the_window(prepared):
    """Окно отказной заявки остаётся исходным — меняется только объём работы."""
    scenario, before = prepared
    updated, _notes = apply_event(
        scenario, before, event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="R3")
    )
    original, changed = requests_by_id(scenario)["R3"], requests_by_id(updated)["R3"]
    assert changed.window_start == original.window_start
    assert changed.window_end == original.window_end
    assert changed.point == original.point
    assert changed.required_skill == original.required_skill


def test_refusal_keeps_the_request_in_scenario(prepared):
    """Заявка с отказом остаётся в сценарии: поездка состоялась, её надо учесть."""
    scenario, before = prepared
    updated, _notes = apply_event(
        scenario, before, event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="R3")
    )
    assert "R3" in requests_by_id(updated)
    assert len(updated.requests) == len(scenario.requests)


def test_refusal_does_not_touch_other_requests(prepared):
    """Остальные заявки при отказе не меняются."""
    scenario, before = prepared
    updated, _notes = apply_event(
        scenario, before, event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="R3")
    )
    original = requests_by_id(scenario)
    for request_id, request in requests_by_id(updated).items():
        if request_id == "R3":
            continue
        assert request == original[request_id]


# --------------------------------------------------------------------------
# ENGINEER_UNAVAILABLE
# --------------------------------------------------------------------------


def test_unavailable_event_trims_the_shift(prepared):
    """Смена выбывшего инженера обрезается моментом события."""
    scenario, before = prepared
    updated, notes = apply_event(
        scenario, before, event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="E2")
    )
    engineer = engineers_by_id(updated)["E2"]
    assert engineer.work_intervals, "уже отработанное время должно сохраниться"
    assert engineer.work_intervals[-1].end <= t(EVENT_AT), (
        f"смена не обрезана: конец {hhmm(engineer.work_intervals[-1].end)}"
    )
    assert notes and any(has_cyrillic(note) for note in notes)


def test_unavailable_event_keeps_other_engineers_intact(prepared):
    """Остальные инженеры и все заявки остаются прежними."""
    scenario, before = prepared
    updated, _notes = apply_event(
        scenario, before, event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="E2")
    )
    assert engineers_by_id(updated)["E1"] == engineers_by_id(scenario)["E1"]
    assert updated.requests == scenario.requests


def test_unavailable_before_shift_start_deactivates_engineer(prepared):
    """Событие до начала смены не оставляет рабочего времени — инженер неактивен."""
    scenario, before = prepared
    updated, _notes = apply_event(
        scenario, before, event(EventType.ENGINEER_UNAVAILABLE, "06:00", engineer_id="E2")
    )
    engineer = engineers_by_id(updated)["E2"]
    assert engineer.work_intervals == ()
    assert engineer.active is False


def test_unavailable_cutoff_never_cuts_a_started_visit():
    """Обрезка не раньше конца уже начатых работ — прошлое остаётся исполнимым.

    Событие в 09:30 попадает в середину первой работы; смена обязана дотянуться
    до её окончания, иначе замороженный визит перестанет помещаться в календарь.
    """
    # Узкие пересекающиеся окна гарантируют, что задействованы оба инженера.
    engineers = [
        eng("E1", shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", shift=("09:00", "18:00"), at=HOME, order=1),
    ]
    requests = [
        req("A1", window=("09:00", "09:10"), dur=60, at=HOME),
        req("A2", window=("09:00", "09:10"), dur=60, at=HOME),
    ]
    scenario = sc(requests, engineers, name="two-busy")
    before = plan_optimized(scenario)

    route = before.route_of("E2")
    assert route is not None and route.visits, "сценарий обязан задействовать обоих инженеров"
    first = route.visits[0]

    updated, _notes = apply_event(
        scenario, before, event(EventType.ENGINEER_UNAVAILABLE, "09:30", engineer_id="E2")
    )
    engineer = engineers_by_id(updated)["E2"]
    assert engineer.work_intervals, "начатая работа требует сохранения рабочего времени"
    assert engineer.work_intervals[-1].end >= first.service_end_at, (
        f"смена обрезана в {hhmm(engineer.work_intervals[-1].end)}, "
        f"а начатая работа заканчивается в {hhmm(first.service_end_at)}"
    )


def test_unavailable_keeps_intervals_sorted_and_non_overlapping(prepared):
    """Обрезанный график остаётся корректным: отсортирован и без пересечений."""
    scenario, before = prepared
    engineers = [
        eng("E1", shift=("09:00", "18:00"), at=HOME, order=0),
        eng("E2", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME, order=1),
    ]
    split_scenario = sc(scenario.requests, engineers, name="split")
    split_plan = plan_optimized(split_scenario)

    updated, _notes = apply_event(
        split_scenario,
        split_plan,
        event(EventType.ENGINEER_UNAVAILABLE, "15:00", engineer_id="E2"),
    )
    intervals = engineers_by_id(updated)["E2"].work_intervals
    for interval in intervals:
        assert interval.end > interval.start
    for prev, nxt in zip(intervals, intervals[1:]):
        assert prev.end <= nxt.start, "интервалы пересеклись после обрезки"

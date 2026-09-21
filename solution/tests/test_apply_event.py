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


# --------------------------------------------------------------------------
# Статусы исполнения
# --------------------------------------------------------------------------


def test_completed_status_writes_the_actual_duration(prepared):
    """«Работы завершены» переписывает норматив фактом — как и отказ клиента.

    Длительность в сценарии после события — это то, сколько работа заняла на самом
    деле: от неё считается остаток дня, и она же попадает в метрику объёма работ.
    """
    scenario, plan = prepared
    assignment = plan.assignment_of("R1")
    assert assignment.is_assigned, "сценарий собран неверно"

    moment = assignment.service_start_at + timedelta(minutes=25)
    updated, notes = apply_event(
        scenario, plan, event(EventType.VISIT_COMPLETED, moment, request_id="R1")
    )

    assert requests_by_id(updated)["R1"].duration_minutes == 25
    assert {r.id for r in updated.requests} == {r.id for r in scenario.requests}, (
        "статус состав заявок не меняет: выполненная работа остаётся в плане дня"
    )
    assert notes and any(has_cyrillic(n) for n in notes)


def test_arrival_status_does_not_touch_the_input(prepared):
    """«Инженер на месте» меняет только расписание, но не сам вход.

    Норматив работы от факта приезда не зависит: приехали позже — позже и начали,
    но сама работа короче не стала.
    """
    scenario, plan = prepared
    before = requests_by_id(scenario)["R1"].duration_minutes

    updated, notes = apply_event(
        scenario, plan, event(EventType.VISIT_ARRIVED, EVENT_AT, request_id="R1")
    )

    assert requests_by_id(updated)["R1"].duration_minutes == before
    assert {r.id for r in updated.requests} == {r.id for r in scenario.requests}


def test_status_event_requires_the_visit_id():
    """Статус без заявки бессмыслен: событие обязано указывать визит."""
    with pytest.raises(ValueError):
        event(EventType.VISIT_COMPLETED, EVENT_AT)
    with pytest.raises(ValueError):
        event(EventType.VISIT_ARRIVED, EVENT_AT)


def test_status_for_an_unknown_visit_is_reported(prepared):
    """Статус по заявке, которой нет в маршрутах, не молчит — он попадает в примечания."""
    scenario, plan = prepared
    _updated, notes = apply_event(
        scenario, plan, event(EventType.VISIT_COMPLETED, EVENT_AT, request_id="НЕТ-ТАКОЙ")
    )
    assert any("НЕТ-ТАКОЙ" in n for n in notes)


# --------------------------------------------------------------------------------------
# Отказ клиента считается по рабочим минутам, а не по часам на стене
# --------------------------------------------------------------------------------------


def lunch_scenario():
    """Один инженер с обедом 13:00–14:00 и длинная работа, которая его пересекает."""
    engineers = [eng("E1", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME)]
    requests = [req("L1", window=("12:00", "16:00"), dur=180, at=HOME, order=0)]
    return sc(requests, engineers, name="lunch")


def test_refusal_across_a_break_counts_working_minutes_only():
    """Обед посреди работы — не работа: в норматив идут рабочие минуты, а не стенные."""
    scenario = lunch_scenario()
    before = plan_optimized(scenario)
    start = before.assignment_of("L1").service_start_at
    assert hhmm(start).endswith("12:00:00"), f"предусловие: работа началась в 12:00, а не {hhmm(start)}"

    # Отказ в 14:00: на стене прошло 120 минут, но час из них съел перерыв.
    updated, _notes = apply_event(
        scenario, before, event(EventType.CLIENT_REFUSAL, "14:00", request_id="L1")
    )
    assert requests_by_id(updated)["L1"].duration_minutes == 60, (
        "перерыв не должен попадать в засчитанную работу"
    )


def test_refusal_and_completion_agree_on_the_duration():
    """Отказ и завершение на одних данных дают одинаковую длительность — правило одно."""
    scenario = lunch_scenario()
    before = plan_optimized(scenario)

    refused, _ = apply_event(
        scenario, before, event(EventType.CLIENT_REFUSAL, "14:00", request_id="L1")
    )
    completed, _ = apply_event(
        scenario, before, event(EventType.VISIT_COMPLETED, "14:00", request_id="L1")
    )
    assert (
        requests_by_id(refused)["L1"].duration_minutes
        == requests_by_id(completed)["L1"].duration_minutes
    )


def test_manual_reassign_is_not_a_replan_event():
    """`manual_reassign` — метка diff, а не вход `replan()`: событием его не создать."""
    with pytest.raises(ValueError):
        event(EventType.MANUAL_REASSIGN, EVENT_AT, request_id="R1")


def test_refusal_for_an_unknown_request_is_reported(prepared):
    """Отказ по заявке, которой нет во входе, не молчит — как и отмена такой заявки.

    Диспетчер считает, что снял работу; если событие ни к чему не применилось, он
    обязан узнать об этом сразу, а не по расписанию, в котором ничего не изменилось.
    """
    scenario, before = prepared
    _updated, notes = apply_event(
        scenario, before, event(EventType.CLIENT_REFUSAL, EVENT_AT, request_id="НЕТ-ТАКОЙ")
    )
    assert any("НЕТ-ТАКОЙ" in n for n in notes), notes


def test_cancel_and_refusal_both_report_an_unknown_request(prepared):
    """Два события, снимающих работу, ведут себя одинаково на неизвестной заявке."""
    scenario, before = prepared
    notes = {}
    for event_type in (EventType.CANCEL_REQUEST, EventType.CLIENT_REFUSAL):
        _updated, produced = apply_event(
            scenario, before, event(event_type, EVENT_AT, request_id="НЕТ-ТАКОЙ")
        )
        notes[event_type] = produced
    assert all(n for n in notes.values()), notes


def test_unavailable_unknown_engineer_is_reported(prepared):
    """Выбытие инженера, которого нет во входе, не молчит.

    Иначе смена никого не задевает, а `diff.summary` всё равно рапортует «Инженер стал
    недоступен»: журнал расходится с тем, что произошло.
    """
    scenario, before = prepared
    _updated, notes = apply_event(
        scenario,
        before,
        event(EventType.ENGINEER_UNAVAILABLE, EVENT_AT, engineer_id="НЕТ-ТАКОГО"),
    )
    assert any("НЕТ-ТАКОГО" in n for n in notes), notes


def test_completion_before_arrival_is_reported(prepared):
    """Работы не могли завершиться раньше, чем инженер доехал — противоречие в журнал."""
    scenario, before = prepared
    arrival = before.assignment_of("R3").arrival_at
    moment = arrival - timedelta(minutes=30)

    _updated, notes = apply_event(
        scenario, before, event(EventType.VISIT_COMPLETED, moment, request_id="R3")
    )
    assert any("до планового прибытия" in n for n in notes), notes


def test_cancelling_started_work_keeps_the_request_in_the_scenario():
    """Отмена начатой работы не стирает её из входа — иначе теряется адрес инженера.

    Заявка остаётся с урезанным до отработанного нормативом, ровно как при отказе
    клиента, и диспетчер узнаёт об этом из `warnings`, а не по странному пробегу.
    """
    scenario = lunch_scenario()
    before = plan_optimized(scenario)

    updated, notes = apply_event(
        scenario, before, event(EventType.CANCEL_REQUEST, "14:00", request_id="L1")
    )
    assert "L1" in requests_by_id(updated), "начатая заявка не может исчезнуть из входа"
    # Обед 13:00–14:00 посреди работы работой не является: 60 рабочих минут, не 120.
    assert requests_by_id(updated)["L1"].duration_minutes == 60
    assert any("L1" in n for n in notes), notes
    assert all(has_cyrillic(n) for n in notes), notes


def test_cancelling_pending_work_removes_it_from_the_scenario(prepared):
    """Граница обратная: пока по заявке ничего не произошло, отмена её просто снимает."""
    scenario, before = prepared
    updated, _notes = apply_event(
        scenario, before, event(EventType.CANCEL_REQUEST, EVENT_AT, request_id="R7")
    )
    assert "R7" not in requests_by_id(updated)


def test_cancel_and_refusal_agree_on_the_duration():
    """Отмена и отказ снимают работу по одному правилу — расхождению взяться неоткуда."""
    scenario = lunch_scenario()
    before = plan_optimized(scenario)

    cancelled, _ = apply_event(
        scenario, before, event(EventType.CANCEL_REQUEST, "14:00", request_id="L1")
    )
    refused, _ = apply_event(
        scenario, before, event(EventType.CLIENT_REFUSAL, "14:00", request_id="L1")
    )
    assert (
        requests_by_id(cancelled)["L1"].duration_minutes
        == requests_by_id(refused)["L1"].duration_minutes
    )

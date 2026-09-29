# -*- coding: utf-8 -*-
"""Обед инженера: час в окне, который планировщик сам ставит между заявками."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from planner import Lunch, plan, rebuild_unstarted
from planner.dispatch import Board, StoredLunch, StoredVisit

from factories import (
    assigned_ids,
    eng,
    gp,
    plan_optimized,
    req,
    sc,
    t,
    validate_plan,
)

HOME = (55.70, 37.60)
OFFICE = (55.72, 37.64)
A = (55.705, 37.605)
B = (55.695, 37.595)
C = (55.710, 37.610)


def lunched(engineer, window=("12:00", "14:00"), point=None, place="last_request"):
    return replace(
        engineer,
        lunch=Lunch(
            window_start=t(window[0]),
            window_end=t(window[1]),
            point=gp(point) if point is not None else None,
            place=place,
        ),
    )


def check_lunch(route, window=("12:00", "14:00")):
    lunch = route.lunch
    assert lunch is not None, f"у {route.engineer_id} нет обеда"
    assert lunch.start_at >= t(window[0])
    assert lunch.end_at <= t(window[1])
    assert abs(lunch.minutes - 60) < 1e-6
    for visit in route.visits:
        # Работа и обед не пересекаются: обед — отдельная остановка
        assert visit.service_end_at <= lunch.start_at or visit.service_start_at >= lunch.end_at


def test_lunch_is_placed_between_visits_inside_its_window():
    scenario = sc(
        [
            req("R1", window=("09:00", "10:00"), dur=60, at=A),
            req("R2", window=("12:00", "12:30"), dur=60, at=B),
            req("R3", window=("14:00", "16:00"), dur=45, at=C),
        ],
        [lunched(eng("E1", at=HOME), window=("12:00", "15:00"))],
    )
    result = plan_optimized(scenario)
    assert assigned_ids(result) == {"R1", "R2", "R3"}
    route = result.routes[0]
    check_lunch(route, window=("12:00", "15:00"))
    # До 12:30 надо успеть к R2 — обед после неё, а не в 12:00
    r2 = next(v for v in route.visits if v.request_id == "R2")
    assert route.lunch.start_at >= r2.service_end_at
    assert validate_plan(result, scenario) == []


def test_lunch_takes_an_hour_out_of_a_full_day():
    # Работа, которая заняла бы окно обеда целиком, не ставится: обед обязателен
    scenario = sc(
        [
            # Порознь каждая помещается, вместе с обедом — нет
            req("R1", window=("11:00", "11:05"), dur=80, at=A),
            req("R2", window=("12:40", "12:50"), dur=60, at=B),
        ],
        [lunched(eng("E1", at=HOME), window=("12:00", "14:00"))],
    )
    result = plan_optimized(scenario)
    route = next(r for r in result.routes if r.visits)
    check_lunch(route)
    assert len(assigned_ids(result)) == 1
    assert validate_plan(result, scenario) == []


def test_lunch_at_office_is_a_detour_and_next_visit_starts_there():
    scenario = sc(
        [
            req("R1", window=("10:00", "11:30"), dur=60, at=A),
            req("R2", window=("14:00", "16:00"), dur=60, at=B),
        ],
        [lunched(eng("E1", at=HOME), point=OFFICE, place="office")],
    )
    result = plan_optimized(scenario)
    route = result.routes[0]
    check_lunch(route)
    lunch = route.lunch
    assert lunch.is_detour and lunch.point.is_same_as(gp(OFFICE))
    assert lunch.travel_minutes > 0 and lunch.distance_km > 0
    after = route.visits[lunch.after_position]
    assert after.from_point.is_same_as(gp(OFFICE))
    assert after.departure_at >= lunch.end_at
    # Дорога к обеду входит в пробег маршрута
    assert abs(route.distance_km - sum(v.distance_km for v in route.visits) - lunch.distance_km) < 1e-6
    assert validate_plan(result, scenario) == []
    # Участки маршрута: к R1, к обеду, к R2
    assert [key for *_rest, key in route.legs()] == [0, None, 1]


def test_no_lunch_when_shift_misses_the_window():
    scenario = sc(
        [req("R1", window=("09:00", "10:00"), dur=60, at=A)],
        [lunched(eng("E1", at=HOME, shift=("08:00", "12:30")), window=("12:00", "14:00"))],
    )
    result = plan_optimized(scenario)
    assert result.routes[0].lunch is None
    assert validate_plan(result, scenario) == []


def test_lunch_window_is_clipped_by_shift():
    scenario = sc(
        [req("R1", window=("14:00", "15:00"), dur=60, at=A)],
        [lunched(eng("E1", at=HOME, shift=("13:00", "20:00")), window=("12:00", "15:00"))],
    )
    result = plan_optimized(scenario)
    lunch = result.routes[0].lunch
    assert lunch is not None and lunch.start_at >= t("13:00")
    assert validate_plan(result, scenario) == []


def test_lunch_reduces_capacity_for_utilization():
    engineer = eng("E1", at=HOME)
    scenario = sc([req("R1", window=("09:00", "10:00"), dur=60, at=A)], [lunched(engineer)])
    route = plan_optimized(scenario).routes[0]
    assert abs(route.capacity_minutes - (9 * 60 - 60)) < 1e-6


def test_started_lunch_is_kept_when_the_rest_of_the_day_is_rebuilt():
    scenario = sc(
        [
            req("R1", window=("09:00", "10:00"), dur=60, at=A),
            req("R2", window=("14:00", "16:00"), dur=60, at=B),
            req("R3", window=("15:00", "17:00"), dur=30, at=C),
        ],
        [lunched(eng("E1", at=HOME)), lunched(eng("E2", at=HOME))],
    )
    before = plan_optimized(scenario)
    route = next(r for r in before.routes if r.lunch is not None)
    now = route.lunch.start_at.replace(minute=route.lunch.start_at.minute + 10)
    after = rebuild_unstarted(before, scenario, now)
    kept = next(r for r in after.routes if r.engineer_id == route.engineer_id).lunch
    assert kept is not None and kept.locked
    assert kept.start_at == route.lunch.start_at and kept.end_at == route.lunch.end_at
    assert validate_plan(after, scenario) == []
    for r in after.routes:
        if r.lunch is not None and not r.lunch.locked:
            assert r.lunch.start_at >= now


def _stored(result):
    visits = [
        StoredVisit(
            request_id=v.request_id,
            engineer_id=route.engineer_id,
            position=v.position,
            departure_at=v.departure_at,
            arrival_at=v.arrival_at,
            service_start_at=v.service_start_at,
            service_end_at=v.service_end_at,
            travel_minutes=v.travel_minutes,
            distance_km=v.distance_km,
            waiting_minutes=v.waiting_minutes,
        )
        for route in result.routes
        for v in route.visits
    ]
    lunches = [
        StoredLunch(
            engineer_id=route.engineer_id,
            departure_at=route.lunch.departure_at,
            arrival_at=route.lunch.arrival_at,
            start_at=route.lunch.start_at,
            end_at=route.lunch.end_at,
            travel_minutes=route.lunch.travel_minutes,
            distance_km=route.lunch.distance_km,
            after_position=route.lunch.after_position,
        )
        for route in result.routes
        if route.lunch is not None
    ] + [
        # Начатый обед инженера без заявок — так же, как его сохраняет backend
        StoredLunch(
            engineer_id=engineer_id,
            departure_at=lunch.departure_at,
            arrival_at=lunch.arrival_at,
            start_at=lunch.start_at,
            end_at=lunch.end_at,
            travel_minutes=lunch.travel_minutes,
            distance_km=lunch.distance_km,
            after_position=0,
        )
        for engineer_id, lunch in result.idle_lunches
    ]
    return visits, lunches


def test_board_keeps_started_lunch_and_moves_future_one():
    scenario = sc(
        [
            req("R1", window=("09:00", "10:00"), dur=60, at=A),
            req("R2", window=("14:00", "16:00"), dur=60, at=B),
            req("R3", window=("12:00", "18:00"), dur=30, at=C),
        ],
        [lunched(eng("E1", at=HOME, shift=("09:00", "18:00")), point=OFFICE, place="office")],
    )
    result = plan(scenario)
    visits, lunches = _stored(result)
    lunch = result.routes[0].lunch
    now = lunch.departure_at.replace(minute=lunch.departure_at.minute + 1)
    board = Board(scenario, visits, lunches=lunches, now=now)
    again = board.result()
    kept = again.routes[0].lunch
    assert kept.locked and kept.start_at == lunch.start_at
    assert validate_plan(again, scenario) == []

    # Без «сейчас» обед не заморожен и сохранённый план восстанавливается как был
    board = Board(scenario, visits, lunches=lunches)
    same = board.result().routes[0]
    assert same.lunch is not None and not same.lunch.locked
    assert same.lunch.start_at == lunch.start_at


def test_gantt_window_at_lunch_gap_allows_before_and_after_lunch():
    scenario = sc(
        [
            req("R1", window=("09:00", "10:00"), dur=60, at=A),
            req("R2", window=("16:00", "17:00"), dur=60, at=B),
        ],
        [lunched(eng("E1", at=HOME))],
    )
    result = plan(scenario)
    visits, lunches = _stored(result)
    board = Board(scenario, visits, lunches=lunches)
    extra = req("X", window=("11:00", "15:00"), dur=30, at=C)
    scenario2 = replace(scenario, requests=scenario.requests + (replace(extra, input_order=9),))
    board = Board(scenario2, visits, lunches=lunches)
    slots = board.slots(["X"])[0]
    assert slots.movable and "E1" in slots.slots
    moved = board.move("X", "E1", commit=True)
    assert moved.ok
    placed = board.result()
    assert "X" in assigned_ids(placed)
    check_lunch(placed.routes[0])
    assert validate_plan(placed, scenario2) == []


def test_every_used_route_has_lunch_on_a_busy_day():
    requests = []
    points = [(55.70 + 0.004 * i, 37.60 + 0.003 * (i % 5)) for i in range(18)]
    for i, point in enumerate(points):
        hour = 9 + (i % 9)
        requests.append(
            req(f"R{i}", window=(f"{hour:02d}:00", f"{hour + 1:02d}:00"), dur=45, at=point)
        )
    engineers = [lunched(eng(f"E{i}", at=HOME)) for i in range(3)]
    scenario = sc(requests, engineers)
    result = plan_optimized(scenario)
    assert validate_plan(result, scenario) == []
    for route in result.routes:
        if route.visits:
            check_lunch(route)


def test_route_line_goes_through_lunch_place():
    """Линия по улицам проходит через место обеда, и у обеда свой срез линии."""
    from test_ors import client

    from planner import attach_route_geometry

    scenario = sc(
        [
            req("R1", window=("10:00", "11:30"), dur=60, at=A),
            req("R2", window=("14:00", "16:00"), dur=60, at=B),
        ],
        [lunched(eng("E1", at=HOME), point=OFFICE, place="office")],
    )
    route = attach_route_geometry(plan(scenario), client()).routes[0]
    assert route.lunch.geometry_range is not None
    spans = [route.visits[0].geometry_range, route.lunch.geometry_range, route.visits[1].geometry_range]
    for before, after in zip(spans, spans[1:]):
        assert before[1] == after[0], "участки должны идти встык"
    assert route.geometry[route.lunch.geometry_range[1]] == route.lunch.point


def test_lunch_added_after_plan_does_not_freeze_the_rest_of_the_day():
    """Обед включили после расчёта: сохранённый маршрут с ним не сходится, но пересчёт
    посреди дня замораживает только начатое, а обед ставит в оставшийся день."""
    requests = [
        req(f"R{i}", window=(f"{9 + i}:00", f"{9 + i}:10"), dur=50, at=(55.70 + 0.002 * i, 37.60))
        for i in range(9)
    ]
    plain = sc(requests, [eng("E1", at=HOME), eng("E2", at=HOME)])
    before = plan(plain)
    with_lunch = replace(plain, engineers=tuple(lunched(e, window=("15:00", "17:00")) for e in plain.engineers))
    visits, _ = _stored(before)
    now = t("12:30")
    board = Board(with_lunch, visits, now=now)
    restored = board.result()
    for route in restored.routes:
        started = [v for v in route.visits if v.departure_at <= now]
        assert [v for v in route.visits if v.locked] == started
    after = rebuild_unstarted(restored, with_lunch, now)
    assert validate_plan(after, with_lunch) == []
    for route in after.routes:
        if any(v.service_end_at > t("15:00") for v in route.visits):
            check_lunch(route, window=("15:00", "17:00"))


def test_empty_engineer_slots_leave_out_lunch_time():
    """У инженера без заявок окна постановки уже учитывают обед: до него и после — порознь."""
    scenario = sc(
        [
            req("R1", window=("09:00", "10:00"), dur=60, at=A),
            req("X", window=("09:00", "21:00"), dur=70, at=(55.75, 37.70)),
        ],
        [eng("E1", at=HOME), lunched(eng("E2", at=HOME, shift=("09:00", "22:00")), window=("16:00", "18:00"))],
    )
    result = plan(scenario)
    visits, lunches = _stored(result)
    visits = [v for v in visits if v.request_id != "X"]
    board = Board(scenario, visits, lunches=lunches)
    slots = board.slots(["X"])[0].slots.get("E2", [])
    assert len(slots) == 2, slots
    before, after = sorted(slots, key=lambda slot: slot.earliest)
    assert before.latest <= 17 * 60 - 70 + 1e-6  # закончить до последнего начала обеда
    assert after.earliest >= 17 * 60  # после обеда 16:00–17:00
    gap = (before.latest + after.earliest) / 2
    moved = board.move("X", "E2", start=gap)
    assert not moved.ok and "обед" in moved.reason
    for start in (before.latest, after.earliest):
        assert board.move("X", "E2", start=start).ok, start


def _slots_agree_with_moves(board, request_id, step=5):
    """Окна постановки совпадают с ходами, как их делает Гант (позиция — из окна): внутри
    окна ход проходит, вне всех окон — ни на какой позиции."""
    item = board.slots([request_id])[0]
    for engineer_id, slots in item.slots.items():
        for slot in slots:
            for start in (slot.earliest, slot.latest, (slot.earliest + slot.latest) / 2):
                moved = board.move(request_id, engineer_id, start=start, position=slot.position)
                assert moved.ok, (engineer_id, slot, start, moved.reason)
    for state in board.solution:
        slots = item.slots.get(state.engineer.id, [])
        positions = range(state.locked_count, state.size + 2)
        for start in range(9 * 60, 21 * 60, step):
            if any(s.earliest - 1e-6 <= start <= s.latest + 1e-6 for s in slots):
                continue
            for position in positions:
                moved = board.move(request_id, state.engineer.id, start=float(start), position=position)
                assert not moved.ok, (state.engineer.id, start, position, slots)


def test_request_dropped_on_lunch_moves_the_lunch():
    """Заявку поставили на время обеда: обед, которому есть куда подвинуться, уезжает сам —
    здесь через следующую заявку, на после неё."""
    scenario = sc(
        [
            req("R1", window=("09:00", "10:00"), dur=60, at=A),
            req("R2", window=("15:00", "15:10"), dur=60, at=B),
            req("X", window=("09:00", "20:00"), dur=150, at=C),
        ],
        [lunched(eng("E1", at=HOME), window=("12:00", "17:00"))],
    )
    result = plan(scenario)
    visits, lunches = _stored(result)
    visits = [v for v in visits if v.request_id != "X"]
    board = Board(scenario, visits, lunches=[l for l in lunches if l.engineer_id == "E1"])
    lunch = board.result().routes[0].lunch
    start = board.ctx.to_minutes(lunch.start_at) + 10  # посреди обеда
    slots = board.slots(["X"])[0].slots["E1"]
    assert any(s.earliest <= start <= s.latest for s in slots), slots
    moved = board.move("X", "E1", start=start)
    assert moved.ok, moved.reason
    [new_lunch] = moved.lunches
    assert new_lunch.after_position == 3  # после R2
    assert new_lunch.start >= start + 150 - 1e-6
    _slots_agree_with_moves(board, "X")


def test_slots_agree_with_moves_when_lunch_is_first_and_next_visit_is_far():
    """Обед в начале дня, а первая заявка далеко: окно «до обеда» учитывает, что раньше
    своего окна обед не начнётся."""
    far = (55.80, 37.75)
    scenario = sc(
        [
            req("R1", window=("13:30", "13:40"), dur=60, at=A),
            req("X", window=("09:00", "20:00"), dur=60, at=far),
        ],
        [lunched(eng("E1", at=HOME, shift=("09:00", "20:00")), window=("12:00", "13:00"))],
    )
    result = plan(scenario)
    visits, lunches = _stored(result)
    visits = [v for v in visits if v.request_id != "X"]
    board = Board(scenario, visits, lunches=[])
    _slots_agree_with_moves(board, "X")


def test_restored_plan_keeps_lunch_where_dispatcher_left_it():
    """Версия плана восстанавливается с обедом на своём месте, а не на равноценном другом."""
    scenario = sc(
        [
            req("R1", window=("09:00", "10:00"), dur=60, at=A),
            req("X", window=("12:00", "16:00"), dur=30, at=C),
        ],
        [lunched(eng("E1", at=HOME), window=("12:00", "16:00"))],
    )
    result = plan(scenario)
    visits, lunches = _stored(result)
    board = Board(scenario, visits, lunches=lunches)
    # Диспетчер ставит X на 12:05 — обед уходит после неё
    moved = board.move("X", "E1", start=t("12:05").hour * 60 + 5.0, commit=True)
    assert moved.ok, moved.reason
    edited = board.result()
    visits, lunches = _stored(edited)
    again = Board(scenario, visits, lunches=lunches).result().routes[0]
    route = edited.routes[0]
    assert again.lunch.after_position == route.lunch.after_position
    assert again.lunch.start_at == route.lunch.start_at
    assert [v.service_start_at for v in again.visits] == [v.service_start_at for v in route.visits]


def test_engineer_level_brings_back_lunch_changed_after_plan():
    """Обед поменяли после расчёта, и маршрут с ним не сходится. «Инженерный» возвращает
    обед, снимая менее важную заявку (она ищет место у других); «Фикс» заявки не трогает."""
    from planner.enums import ReplanScope

    requests = [
        req(f"R{i}", window=(f"{9 + i}:00", f"{9 + i}:05"), dur=55, at=(55.70 + 0.001 * i, 37.60))
        for i in range(8)
    ]
    plain = sc(requests, [eng("E1", at=HOME, shift=("09:00", "18:00")), eng("E2", at=HOME, shift=("09:00", "18:00"))])
    before = plan(plain)
    visits, _ = _stored(before)
    with_lunch = replace(plain, engineers=tuple(lunched(e, window=("12:00", "13:00")) for e in plain.engineers))
    busy = [r.engineer_id for r in before.routes if any(v.service_start_at.hour == 12 for v in r.visits)]
    assert busy, "нужен маршрут с работой в окне обеда"

    fixed = Board(with_lunch, visits)
    fixed.place_new([], scope=ReplanScope.LOW)
    kept = {r.engineer_id: r for r in fixed.result().routes}
    assert all(kept[e].lunch is None for e in busy)
    assert assigned_ids(fixed.result()) == assigned_ids(before)

    board = Board(with_lunch, visits)
    board.place_new([], scope=ReplanScope.MEDIUM)
    result = board.result()
    assert validate_plan(result, with_lunch) == []
    for route in result.routes:
        if route.visits:
            check_lunch(route, window=("12:00", "13:00"))


def test_before_lunch_window_when_visit_before_lunch_has_started():
    """Визит перед обедом уже начат: до обеда ещё можно успеть заявку — окно не пропадает."""
    scenario = sc(
        [
            req("R1", window=("15:00", "16:00"), dur=60, at=A),
            req("R2", window=("20:00", "21:00"), dur=30, at=B),
            req("X", window=("09:00", "22:00"), dur=20, at=C),
        ],
        [lunched(eng("E1", at=HOME, shift=("09:00", "23:00")), window=("18:00", "21:00"), point=OFFICE, place="office")],
    )
    result = plan(scenario)
    visits, lunches = _stored(result)
    visits = [v for v in visits if v.request_id != "X"]
    lunches = [l for l in lunches if l.engineer_id == "E1"]
    board = Board(scenario, visits, lunches=lunches, now=t("16:30"))
    route = board.solution.routes["E1"]
    assert route.locked_count == 1 and route.lunch_gap == 1
    slots = board.slots(["X"])[0].slots["E1"]
    lunch = board.result().routes[0].lunch
    assert any(s.position == 1 and s.earliest < board.ctx.to_minutes(lunch.start_at) for s in slots), slots
    _slots_agree_with_moves(board, "X")


def _seconds(moment):
    """Время обеда в `plans.lunches` — до секунды, визиты в БД — с долями."""
    return moment.replace(microsecond=0)


def test_started_lunch_after_visit_ending_with_fractions_of_second():
    """Визит кончился в 17:04:31.32, обед сохранён с выездом 17:04:31: обед всё равно после
    визита, и новая заявка не встаёт поверх начатого обеда (накладка у Рыбина)."""
    scenario = sc(
        [
            req("R1", window=("15:00", "16:00"), dur=64, at=A),
            req("R2", window=("19:00", "21:00"), dur=30, at=B),
            req("X", window=("09:00", "22:00"), dur=30, at=C),
        ],
        [lunched(eng("E1", at=HOME, shift=("09:00", "23:00")), window=("17:00", "20:00"), point=OFFICE, place="office")],
    )
    result = plan(scenario)
    visits, lunches = _stored(result)
    r1_end = next(v.service_end_at for v in visits if v.request_id == "R1")
    # Как у Рыбина: на обед выехали сразу после R1
    lunches = [replace(l, departure_at=r1_end) for l in lunches]
    visits = [replace(v, service_end_at=v.service_end_at.replace(microsecond=320000)) if v.request_id == "R1" else v
              for v in visits if v.request_id != "X"]
    lunches = [
        replace(l, departure_at=_seconds(l.departure_at), arrival_at=_seconds(l.arrival_at),
                start_at=_seconds(l.start_at), end_at=_seconds(l.end_at))
        for l in lunches if l.engineer_id == "E1"
    ]
    lunch = lunches[0]
    now = lunch.departure_at.replace(minute=lunch.departure_at.minute) + (lunch.start_at - lunch.departure_at) / 2
    board = Board(scenario, visits, lunches=lunches, now=now)
    route = board.result().routes[0]
    assert route.lunch.locked and route.lunch.after_position == 1
    for item in board.slots(["X"]):
        for slot in item.slots.get("E1", []):
            assert board.move("X", "E1", start=slot.earliest, position=slot.position, commit=False).ok
    moved = board.move("X", "E1", start=None, position=1, commit=True)
    if moved.ok:
        route = board.result().routes[0]
        second = timedelta(seconds=1)
        for visit in route.visits:
            assert (
                visit.service_end_at <= route.lunch.departure_at + second
                or visit.departure_at >= route.lunch.end_at - second
            )


def test_saved_route_overlapping_started_lunch_is_repaired_not_frozen():
    """В сохранённой версии заявка стоит поверх начатого обеда: доска снимает её в
    неназначенные, а не замораживает весь маршрут с накладкой."""
    scenario = sc(
        [
            req("R1", window=("15:00", "16:00"), dur=60, at=A),
            req("X", window=("17:00", "18:00"), dur=30, at=C),
        ],
        [lunched(eng("E1", at=HOME, shift=("09:00", "23:00")), window=("17:00", "18:30"), point=OFFICE, place="office")],
    )
    result = plan(replace(scenario, requests=scenario.requests[:1]))
    visits, lunches = _stored(result)
    lunch = lunches[0]
    r1 = visits[0]
    # X «выехала» сразу после R1, пока инженер едет на обед
    bad = StoredVisit(
        request_id="X", engineer_id="E1", position=2,
        departure_at=r1.service_end_at, arrival_at=lunch.start_at, service_start_at=lunch.start_at,
        service_end_at=lunch.start_at.replace(minute=lunch.start_at.minute) + (lunch.end_at - lunch.start_at) / 2,
    )
    now = lunch.start_at + (lunch.end_at - lunch.start_at) / 4
    board = Board(scenario, [r1, bad], lunches=lunches, now=now)
    assert "E1" not in board.frozen_routes
    after = board.result()
    assert "X" not in assigned_ids(after)
    route = after.routes[0]
    assert route.lunch is not None and route.lunch.locked


def test_started_lunch_survives_when_engineer_loses_all_visits():
    """Обед начат, а заявку инженера увели другому: обед остаётся фактом, и когда заявка
    вернётся, второго обеда не будет."""
    scenario = sc(
        [req("R1", window=("14:00", "15:00"), dur=60, at=A)],
        [lunched(eng("E1", at=HOME)), lunched(eng("E2", at=HOME))],
    )
    result = plan(scenario)
    owner = next(r for r in result.routes if r.visits)
    other = next(e.id for e in scenario.engineers if e.id != owner.engineer_id)
    started = owner.lunch.start_at
    now = started + (owner.lunch.end_at - started) / 2
    visits, lunches = _stored(result)
    board = Board(scenario, visits, lunches=lunches, now=now)
    assert board.move("R1", other, commit=True).ok
    moved = board.result()
    idle = dict(moved.idle_lunches)
    assert owner.engineer_id in idle and idle[owner.engineer_id].start_at == started

    visits, lunches = _stored(moved)
    board = Board(scenario, visits, lunches=lunches, now=now)
    assert board.move("R1", owner.engineer_id, commit=True).ok
    back = board.result().route_of(owner.engineer_id)
    assert back.lunch.locked and back.lunch.start_at == started

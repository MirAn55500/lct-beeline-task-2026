# -*- coding: utf-8 -*-
"""Ручная правка плана на Ганте (`planner.dispatch`): окна постановки и сам ход.

Окно постановки обещает диспетчеру «сюда встанет» ещё до хода — поэтому каждое окно
проверяется ходом на его границах: на краю окна ход проходит, за краем — нет.
"""
from __future__ import annotations

from planner import plan
from planner.dispatch import Board, StoredVisit

from factories import eng, req, sc, t

HOME = (55.70, 37.60)
A = (55.705, 37.605)
B = (55.715, 37.62)
C = (55.71, 37.61)


def stored(result, skip=()):
    return [
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
        if v.request_id not in skip
    ]


def minutes(moment):
    return moment.hour * 60 + moment.minute + moment.second / 60


def day_scenario():
    return sc(
        [
            req("R1", window=("10:00", "11:00"), dur=60, at=A),
            req("R2", window=("15:00", "15:10"), dur=60, at=B),
            req("R3", window=("12:00", "14:00"), dur=30, at=C),
        ],
        [eng("E1", shift=("09:00", "18:00"), at=HOME)],
    )


def board_without_r3(now=None):
    scenario = day_scenario()
    result = plan(scenario)
    return Board(scenario, stored(result, skip={"R3"}), now=now), result


def starts(board, engineer_id="E1"):
    route = board.solution.routes[engineer_id]
    return {route.stops[i].id: round(route.schedule_at(i)[2], 3) for i in range(route.size)}


def test_board_restores_the_saved_schedule():
    scenario = day_scenario()
    result = plan(scenario)
    board = Board(scenario, stored(result))
    expected = {v.request_id: round(minutes(v.service_start_at), 3) for v in result.routes[0].visits}
    assert starts(board) == expected
    assert not board.frozen_routes


def test_slot_edges_match_the_move():
    board, _ = board_without_r3()
    [info] = board.slots(["R3"])
    assert info.movable
    between = [s for s in info.slots["E1"] if s.position == 1]
    assert between, "между R1 и R2 есть время"
    slot = between[0]
    assert slot.earliest < slot.latest

    for edge in (slot.earliest, slot.latest):
        assert board.move("R3", "E1", start=edge, position=1).ok

    early = board.move("R3", "E1", start=slot.earliest - 5, position=1)
    assert not early.ok and "не успеет доехать" in early.reason
    late = board.move("R3", "E1", start=slot.latest + 5, position=1)
    assert not late.ok and "не успеют" in late.reason


def test_dry_run_leaves_the_board_unchanged_and_commit_keeps_the_move():
    board, _ = board_without_r3()
    before = starts(board)
    slot = next(s for s in board.slots(["R3"])[0].slots["E1"] if s.position == 1)

    preview = board.move("R3", "E1", start=slot.earliest, position=1)
    assert preview.ok and preview.engineers == ("E1",)
    assert [v.request_id for v in preview.visits] == ["R1", "R3", "R2"]
    assert starts(board) == before

    done = board.move("R3", "E1", start=slot.earliest, position=1, commit=True)
    assert done.ok
    assert starts(board)["R3"] == round(slot.earliest, 3)
    assert "R3" not in board.solution.unassigned


def test_rollback_undoes_a_committed_chain():
    """Черновик Ганта: цепочка ходов с commit для превью — и доска как была."""
    board, _ = board_without_r3()
    before = starts(board)
    slots_before = board.slots(["R3"])
    point = board.checkpoint()
    slot = next(s for s in slots_before[0].slots["E1"] if s.position == 1)
    assert board.move("R3", "E1", start=slot.earliest, position=1, commit=True).ok
    assert board.move("R1", None, commit=True).ok
    assert "R3" in starts(board) and "R1" not in starts(board)
    assert board._client["R3"].window_start == slot.earliest, "окно сдвинуто согласием"

    board.rollback(point)
    assert starts(board) == before
    assert board._client["R3"].window_start == minutes(t("12:00"))
    assert board.slots(["R3"]) == slots_before
    # Откат повторяемый: точка не испорчена второй цепочкой
    assert board.move("R3", "E1", start=slot.latest, position=1, commit=True).ok
    board.rollback(point)
    assert starts(board) == before


def test_start_outside_client_window_is_allowed_but_flagged():
    board, _ = board_without_r3()
    slot = next(s for s in board.slots(["R3"])[0].slots["E1"] if s.position == 1)
    client_start = minutes(t("12:00"))
    assert slot.earliest < client_start, "окно постановки не ограничено окном клиента"
    outcome = board.move("R3", "E1", start=slot.earliest, position=1)
    assert outcome.ok and outcome.outside_window
    inside = board.move("R3", "E1", start=client_start + 10, position=1)
    assert inside.ok and not inside.outside_window


def test_agreed_time_becomes_the_new_client_window():
    """Клиент согласился на время вне окна — окно той же длины начинается с него."""
    board, _ = board_without_r3()
    slot = next(s for s in board.slots(["R3"])[0].slots["E1"] if s.position == 1)
    start = slot.earliest
    preview = board.move("R3", "E1", start=start, position=1)
    assert preview.window_shift == start - minutes(t("12:00"))
    assert board._client["R3"].window_start == minutes(t("12:00")), "проверка окно не двигает"

    done = board.move("R3", "E1", start=start, position=1, commit=True)
    assert done.outside_window and done.window_shift == preview.window_shift
    client = board._client["R3"]
    assert client.window_start == start
    assert client.window_end - client.window_start == 120, "длина окна сохраняется"
    again = board.move("R3", "E1", start=start, position=1)
    assert again.ok and not again.outside_window and again.window_shift == 0


def test_move_inside_the_window_keeps_it():
    board, _ = board_without_r3()
    done = board.move("R3", "E1", start=minutes(t("12:10")), position=1, commit=True)
    assert done.ok and done.window_shift == 0
    assert board._client["R3"].window_start == minutes(t("12:00"))


def test_insertion_pushes_the_tail_within_its_window():
    board, _ = board_without_r3()
    r2_before = starts(board)["R2"]
    slot = next(s for s in board.slots(["R3"])[0].slots["E1"] if s.position == 1)
    outcome = board.move("R3", "E1", start=slot.latest, position=1)
    r2_after = next(v.start for v in outcome.visits if v.request_id == "R2")
    assert r2_before <= r2_after <= minutes(t("15:10")) + 1e-6


def test_removing_a_visit_does_not_pull_the_rest_earlier():
    """Клиенту уже назвали время: снятие соседа не переносит визит на раньше."""
    board, _ = board_without_r3()
    before = starts(board)
    assert board.move("R1", None, commit=True).ok
    assert starts(board) == {"R2": before["R2"]}
    assert "R1" in board.solution.unassigned


def test_departed_visits_are_frozen():
    board, result = board_without_r3(now=t("10:30"))
    [r1] = board.slots(["R1"])
    assert not r1.movable
    refused = board.move("R1", None)
    assert not refused.ok and "выехал" in refused.reason
    # До начатой работы ничего не поставить, после — можно.
    slots = board.slots(["R3"])[0].slots["E1"]
    assert all(s.position >= 1 for s in slots)
    assert all(s.earliest >= minutes(t("10:30")) - 1e-6 for s in slots)


def test_release_frees_the_place():
    """Окно R2 узкое: встать на его время можно, только сняв R2 с маршрута."""
    board, _ = board_without_r3()
    r2_start = starts(board)["R2"]
    blocked = board.move("R3", "E1", start=r2_start, position=1)
    assert not blocked.ok
    swapped = board.move("R3", "E1", start=r2_start, release=["R2"], commit=True)
    assert swapped.ok and swapped.released == ("R2",)
    assert "R2" in board.solution.unassigned
    assert starts(board) == {"R1": starts(board)["R1"], "R3": round(r2_start, 3)}


def test_result_is_a_regular_plan():
    board, _ = board_without_r3()
    slot = next(s for s in board.slots(["R3"])[0].slots["E1"] if s.position == 1)
    board.move("R3", "E1", start=slot.latest, position=1, commit=True)
    result = board.result()
    assert [v.request_id for v in result.routes[0].visits] == ["R1", "R3", "R2"]
    assert all(a.is_assigned for a in result.assignments)


# ---------------------------------------------------------------- новые заявки в готовый план


def test_place_new_fix_uses_a_free_window_and_moves_nobody():
    board, _ = board_without_r3()
    before = starts(board)
    assert board.place_new(["R3"], scope="low") == ["R3"]
    after = starts(board)
    assert {k: after[k] for k in before} == before
    assert "R3" in after and "R3" not in board.solution.unassigned


def tight_board():
    """R2 стоит сразу после R1; R3 встаёт только перед R2, отодвинув его в пределах окна."""
    known = [
        req("R1", window=("10:00", "11:00"), dur=60, at=A),
        req("R2", window=("11:00", "13:00"), dur=60, at=B),
    ]
    engineers = [eng("E1", shift=("09:00", "18:00"), at=HOME)]
    result = plan(sc(known, engineers))
    scenario = sc([*known, req("R3", window=("11:00", "11:20"), dur=30, at=C)], engineers)
    return Board(scenario, stored(result))


def test_place_new_fix_does_not_shift_client_times():
    board = tight_board()
    before = starts(board)
    assert board.place_new(["R3"], scope="low") == []
    assert starts(board) == before
    assert "R3" in board.solution.unassigned


def test_place_new_engineer_may_shift_one_route_within_windows():
    board = tight_board()
    before = starts(board)
    assert board.place_new(["R3"], scope="medium") == ["R3"]
    after = starts(board)
    assert after["R1"] == before["R1"]
    assert before["R2"] < after["R2"] <= minutes(t("13:00")) + 1e-6

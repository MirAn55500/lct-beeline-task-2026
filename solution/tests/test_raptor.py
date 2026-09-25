# -*- coding: utf-8 -*-
"""Поиск по расписанию GTFS без ORS (`planner/raptor.py`).

Фид собирается прямо в тесте: несколько остановок на одной широте, рейсы с круглыми
временами. Так ответ считается в уме, и проверяется именно алгоритм, а не данные.
Сверка с настоящим ORS — отдельный инструмент, `tools/raptor_check.py`.
"""
from __future__ import annotations

import zipfile
from datetime import date

import pytest

from planner import raptor
from planner.models import GeoPoint

MONDAY = date(2026, 8, 17)
TEN = 10 * 3600

# Остановки на широте 55.75 через 0.1° долготы (~6.3 км): пешком между ними больше часа.
STOPS = {"S1": 37.60, "S2": 37.70, "S3": 37.80, "S2b": 37.7015}


def at(lon: float) -> GeoPoint:
    return GeoPoint(55.75, lon)


def near(stop: str) -> GeoPoint:
    """Точка в ~60 м от остановки: минута пешком."""
    return at(STOPS[stop] + 0.001)


def feed(tmp_path, trips, *, transfers=(), service_days="1,0,0,0,0,0,0"):
    """GTFS-архив. `trips` — {trip_id: [(stop, "HH:MM"), ...]}."""
    path = tmp_path / "gtfs.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("agency.txt", "agency_id,agency_name,agency_url,agency_timezone\n1,A,http://a,Europe/Moscow\n")
        z.writestr(
            "stops.txt",
            "stop_id,stop_name,stop_lat,stop_lon\n"
            + "".join(f"{s},{s},55.75,{lon}\n" for s, lon in STOPS.items()),
        )
        z.writestr("routes.txt", "route_id,agency_id,route_short_name,route_long_name,route_type\nR,1,1,R,3\n")
        z.writestr(
            "calendar.txt",
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            f"W,{service_days},20260101,20301231\n",
        )
        z.writestr(
            "trips.txt",
            "route_id,service_id,trip_id\n" + "".join(f"R,W,{t}\n" for t in trips),
        )
        rows = "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        for trip, calls in trips.items():
            for seq, (stop, hhmm) in enumerate(calls, start=1):
                rows += f"{trip},{hhmm}:00,{hhmm}:00,{stop},{seq}\n"
        z.writestr("stop_times.txt", rows)
        z.writestr(
            "transfers.txt",
            "from_stop_id,to_stop_id,transfer_type,min_transfer_time\n"
            + "".join(f"{a},{b},2,{sec}\n" for a, b, sec in transfers),
        )
    return path


def router(path, day=MONDAY, **kw):
    return raptor.TransitRouter(raptor.load_timetable(path, day, TEN, **kw))


def minutes(r, origin, target, **kw):
    [value] = r.travel_minutes(origin, [target], **kw)
    return value


def test_ride_counts_wait_for_first_departure(tmp_path):
    path = feed(tmp_path, {"t1": [("S1", "10:10"), ("S2", "10:20")],
                           "t2": [("S1", "10:30"), ("S2", "10:40")]})
    value = minutes(router(path), near("S1"), near("S2"))
    # ожидание до 10:10 + 10 минут в пути + минута от остановки
    assert value == pytest.approx(21, abs=0.2)


def test_missed_trip_takes_next_one(tmp_path):
    path = feed(tmp_path, {"t1": [("S1", "10:00"), ("S2", "10:10")],
                           "t2": [("S1", "10:30"), ("S2", "10:40")]})
    # до остановки минута, к рейсу в 10:00 не успеть
    assert minutes(router(path), near("S1"), near("S2")) == pytest.approx(41, abs=0.2)


def test_change_at_same_stop(tmp_path):
    path = feed(tmp_path, {"a": [("S1", "10:05"), ("S2", "10:15")],
                           "b": [("S2", "10:20"), ("S3", "10:30")]})
    assert minutes(router(path), near("S1"), near("S3")) == pytest.approx(31, abs=0.2)


def test_transfer_from_feed_uses_its_time(tmp_path):
    trips = {"a": [("S1", "10:05"), ("S2", "10:15")],
             "b": [("S2b", "10:18"), ("S3", "10:30")],
             "c": [("S2b", "10:25"), ("S3", "10:37")]}
    # 300 с из transfers.txt: к 10:18 не успеть, едем в 10:25
    path = feed(tmp_path, trips, transfers=[("S2", "S2b", 300)])
    assert minutes(router(path, transfer_km=0), near("S1"), near("S3")) == pytest.approx(38, abs=0.2)


def test_walking_transfer_between_nearby_stops(tmp_path):
    trips = {"a": [("S1", "10:05"), ("S2", "10:15")],
             "b": [("S2b", "10:18"), ("S3", "10:30")],
             "c": [("S2b", "10:40"), ("S3", "10:52")]}
    path = feed(tmp_path, trips)
    # S2 → S2b ~95 м: ~1.5 мин пешком, со штрафом 2 мин — успеваем к 10:18
    assert minutes(router(path, transfer_penalty=0), near("S1"), near("S3")) == pytest.approx(31, abs=0.2)
    # без пеших пересадок остаётся только ждать другой остановки — не доехать вовсе
    assert minutes(router(path, transfer_km=0), near("S1"), near("S3")) > 60


def test_walk_wins_when_faster(tmp_path):
    path = feed(tmp_path, {"t": [("S1", "11:00"), ("S2", "11:05")]})
    r = router(path)
    origin, target = near("S1"), at(STOPS["S1"] + 0.004)  # ~250 м
    assert minutes(r, origin, target) < 5
    # известное время пешком по улицам важнее прямой
    assert minutes(r, origin, target, walk_minutes=[12.5]) == pytest.approx(12.5)


def test_walking_via_stops_does_not_bypass_street_walk(tmp_path):
    """До остановки у цели дойти пешком и выйти — это та же прогулка по прямой."""
    path = feed(tmp_path, {"t": [("S1", "12:00"), ("S2", "12:05")]})
    origin, target = near("S1"), at(STOPS["S1"] + 0.008)
    assert minutes(router(path), origin, target, walk_minutes=[40.0]) == pytest.approx(40.0)


def test_point_without_stops_is_outside_feed(tmp_path):
    path = feed(tmp_path, {"t": [("S1", "10:10"), ("S2", "10:20")]})
    far = GeoPoint(54.84, 38.19)  # Кашира
    r = router(path)
    assert minutes(r, near("S1"), far) is None
    assert minutes(r, far, near("S1")) is None


def test_service_not_running_that_day(tmp_path):
    path = feed(tmp_path, {"t": [("S1", "10:10"), ("S2", "10:20")]}, service_days="0,0,0,0,0,1,1")
    tt = raptor.load_timetable(path, MONDAY, TEN)
    assert tt.trips == 0
    # остановка без единого рейса не остановка: точка «вне фида», как Кашира
    assert minutes(raptor.TransitRouter(tt), near("S1"), near("S2")) is None


def test_trips_outside_window_are_dropped(tmp_path):
    path = feed(tmp_path, {"early": [("S1", "06:00"), ("S2", "06:10")],
                           "day": [("S1", "10:10"), ("S2", "10:20")],
                           "late": [("S1", "20:00"), ("S2", "20:10")]})
    assert raptor.load_timetable(path, MONDAY, TEN).trips == 1


def test_overtaking_trip_is_not_lost(tmp_path):
    """Экспресс выходит позже и приезжает раньше: бинарный поиск рейса не должен его пропустить."""
    path = feed(tmp_path, {"slow": [("S1", "10:05"), ("S2", "10:15"), ("S3", "10:50")],
                           "fast": [("S1", "10:07"), ("S2", "10:12"), ("S3", "10:20")]})
    tt = raptor.load_timetable(path, MONDAY, TEN)
    assert len(tt.routes) == 2
    assert minutes(raptor.TransitRouter(tt), near("S1"), near("S3")) == pytest.approx(21, abs=0.2)


def test_one_search_serves_many_targets(tmp_path):
    path = feed(tmp_path, {"t": [("S1", "10:10"), ("S2", "10:20"), ("S3", "10:30")]})
    got = router(path).travel_minutes(near("S1"), [near("S2"), near("S3")])
    assert got == [pytest.approx(21, abs=0.2), pytest.approx(31, abs=0.2)]


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _day_feed(tmp_path):
    """Автобус S1 → S2 каждые 20 минут с 08:00 до 20:00, пересадка на S3 раз в полчаса."""
    trips = {}
    for k in range(37):
        m = 8 * 60 + 20 * k
        trips[f"a{k}"] = [("S1", _hhmm(m)), ("S2", _hhmm(m + 10))]
    for k in range(25):
        m = 8 * 60 + 5 + 30 * k
        trips[f"b{k}"] = [("S2", _hhmm(m)), ("S3", _hhmm(m + 12))]
    return feed(tmp_path, trips)


def test_time_of_departure_matters(tmp_path):
    tt = raptor.load_timetable(_day_feed(tmp_path), MONDAY, 8 * 3600, horizon_minutes=14 * 60)
    r = raptor.TransitRouter(tt)
    # выйти в 9:59 — успеть на 10:00 (минута до остановки), в 10:01 — ждать 10:20
    just_in_time = minutes(r, near("S1"), near("S2"), depart=10 * 3600 - 60)
    just_missed = minutes(r, near("S1"), near("S2"), depart=10 * 3600 + 60)
    assert just_in_time == pytest.approx(12, abs=0.2)
    assert just_missed == pytest.approx(30, abs=0.2)


def test_profile_matches_plain_search_at_any_moment(tmp_path):
    """rRAPTOR — не приближение: на любой момент ответ обычного поиска."""
    tt = raptor.load_timetable(_day_feed(tmp_path), MONDAY, 8 * 3600, horizon_minutes=14 * 60)
    r = raptor.TransitRouter(tt)
    targets = [near("S2"), near("S3")]
    profiles = r.profiles(near("S1"), targets, 8 * 3600, 19 * 3600)
    for t in range(8 * 3600, 19 * 3600, 7 * 60 + 13):
        plain = r.travel_minutes(near("S1"), targets, depart=t)
        assert [p.minutes_at(t) for p in profiles] == pytest.approx(plain, abs=1e-9)


def test_grid_profile_is_never_optimistic(tmp_path):
    tt = raptor.load_timetable(_day_feed(tmp_path), MONDAY, 8 * 3600, horizon_minutes=14 * 60)
    r = raptor.TransitRouter(tt)
    exact = r.profiles(near("S1"), [near("S3")], 8 * 3600, 19 * 3600)[0]
    grid = r.profiles(near("S1"), [near("S3")], 8 * 3600, 19 * 3600, step=300)[0]
    for t in range(8 * 3600, 19 * 3600, 97):
        assert grid.minutes_at(t) >= exact.minutes_at(t) - 1e-9
    # в узлах сетки — точный ответ
    for t in range(8 * 3600, 19 * 3600, 300):
        assert grid.minutes_at(t) == pytest.approx(exact.minutes_at(t))


def test_itinerary_lists_rides_and_transfers(tmp_path):
    """Состав поездки: пешком до остановки, два автобуса с пересадкой пешком, пешком до цели."""
    trips = {"a": [("S1", "10:05"), ("S2", "10:15")],
             "b": [("S2b", "10:20"), ("S3", "10:30")]}
    path = feed(tmp_path, trips)
    r = router(path, transfer_penalty=0)
    got = r.itinerary(near("S1"), near("S3"), TEN)
    kinds = [leg["kind"] for leg in got["legs"]]
    assert kinds == ["walk", "bus", "walk", "bus", "walk"]
    first, second = got["legs"][1], got["legs"][3]
    assert (first["from"], first["to"], first["departure"]) == ("S1", "S2", 10 * 3600 + 5 * 60)
    assert (second["from"], second["to"], second["stops"]) == ("S2b", "S3", 1)
    # прибытие — то же, что у поиска без восстановления пути
    assert (got["arrival"] - TEN) / 60 == pytest.approx(minutes(r, near("S1"), near("S3")))
    # линия: точка выхода, остановки, точка прибытия
    assert got["line"][0] == [near("S1").lon, near("S1").lat]
    assert got["line"][-1] == [near("S3").lon, near("S3").lat]
    assert [STOPS["S2"], 55.75] in [[round(x, 4), y] for x, y in got["line"]]


def test_itinerary_walk_only_and_outside(tmp_path):
    path = feed(tmp_path, {"t": [("S1", "11:00"), ("S2", "11:05")]})
    r = router(path)
    walk = r.itinerary(near("S1"), at(STOPS["S1"] + 0.004), TEN)
    assert [leg["kind"] for leg in walk["legs"]] == ["walk"]
    assert r.itinerary(near("S1"), GeoPoint(54.84, 38.19), TEN) is None

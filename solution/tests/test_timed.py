# -*- coding: utf-8 -*-
"""Планирование со временем в пути от момента выезда (`planner/timed.py`).

Профили задаются руками — автобусы с круглым расписанием, — чтобы ответ считался в уме:
проверяется не RAPTOR (он в `test_raptor.py`), а то, что планировщик спрашивает время
на фактический момент выезда и что независимая проверка плана с ним согласна.
"""
from __future__ import annotations

import pytest

from factories import assert_dt, eng, req, routes_by_engineer, sc, t, validate_plan
from planner import plan
from planner.enums import TransportMode
from planner.raptor import Profile
from planner.timed import TimedTransitModel
from planner.travel import HaversineTravelModel

HOME = (55.70, 37.60)
A = (55.72, 37.62)
B = (55.74, 37.64)
PT = TransportMode.PUBLIC_TRANSPORT


def key(p):
    return f"{p[0]:.6f},{p[1]:.6f}"


def buses(first: str, every: int, ride: int, walk: int = 200) -> Profile:
    """Автобус от `first` каждые `every` минут до 20:00, в пути `ride` минут."""
    h, m = map(int, first.split(":"))
    deps = list(range((h * 60 + m) * 60, 20 * 3600, every * 60))
    return Profile(deps, [d + ride * 60 for d in deps], walk * 60)


def model(scenario):
    profiles = {
        (key(HOME), key(A)): buses("07:00", 30, 20),  # :00 и :30, 20 мин
        (key(A), key(B)): buses("07:15", 30, 10),  # :15 и :45, 10 мин
    }
    return TimedTransitModel(
        HaversineTravelModel(scenario.settings), profiles, scenario.settings,
        first=7 * 3600, last=22 * 3600,
    )


def scenario():
    return sc(
        [req("R1", window=("10:00", "12:00"), dur=30, at=A),
         req("R2", window=("10:00", "13:00"), dur=30, at=B)],
        [eng("E1", shift=("09:00", "18:00"), at=HOME, transport="public_transport")],
    )


def test_departure_fits_bus_timetable():
    s = scenario()
    travel = model(s)
    result = plan(s, travel=travel)
    visits = {v.request_id: v for v in routes_by_engineer(result)["E1"].visits}
    r1, r2 = visits["R1"], visits["R2"]
    # К 10:00 успевает автобус 09:30 (20 мин + 10 мин от остановки до квартиры);
    # выход за 2 мин до рейса — запас BOARDING_MARGIN_MINUTES
    assert_dt(r1.departure_at, t("09:28"), "выезд под автобус, а не сразу в начале смены")
    assert_dt(r1.arrival_at, t("10:00"))
    assert r1.travel_minutes == pytest.approx(32)
    # Освободился в 10:30, автобус в 10:45: выходит к автобусу, а не стоит на
    # остановке — 15 мин становятся простоем перед выездом, как и у машины
    assert_dt(r2.departure_at, t("10:43"))
    assert_dt(r2.arrival_at, t("11:05"))
    assert r2.travel_minutes == pytest.approx(22)
    assert r2.idle_before_minutes == pytest.approx(13)
    assert validate_plan(result, s, travel) == []


def test_float_minutes_do_not_lose_bus_on_second_boundary():
    """Минуты планировщика — float: 1037.9 × 60 = 62273.99999…, а рейс прибывает в 62274."""
    profile = Profile([61000], [62274], 10**6)
    assert profile.latest_departure(1037.9 * 60) == 61000
    assert profile.seconds_at(61000 - 1e-7) == 1274


def test_pair_without_profile_uses_base_value():
    s = scenario()
    travel = model(s)
    base = HaversineTravelModel(s.settings)
    from planner.models import GeoPoint

    home, b = GeoPoint(*HOME), GeoPoint(*B)
    assert travel.minutes_at(home, b, PT, 10 * 60) == pytest.approx(base.travel_minutes(home, b, PT))
    # вне окна профиля — тоже базовое число
    a = GeoPoint(*A)
    assert travel.minutes_at(home, a, PT, 23 * 60) == pytest.approx(base.travel_minutes(home, a, PT))
    # другие способы передвижения профиль не трогает
    assert not travel.is_timed(TransportMode.CAR)


def test_latest_departure_matches_profile():
    s = scenario()
    travel = model(s)
    from planner.models import GeoPoint

    home, a = GeoPoint(*HOME), GeoPoint(*A)
    # прибыть к 11:10 (с учётом 10 мин от остановки): автобус 10:30 → 10:50 +10 = 11:00,
    # выйти с запасом 2 мин — в 10:28
    assert travel.depart_by(home, a, PT, 11 * 60 + 10) == pytest.approx(10 * 60 + 28)
    assert travel.minutes_at(home, a, PT, 10 * 60 + 30) == pytest.approx(30)
    # вышли в 10:31 — ждём 11:00, приезжаем в 11:30
    assert travel.minutes_at(home, a, PT, 10 * 60 + 31) == pytest.approx(59)


def test_car_engineer_ignores_transit_profiles():
    s = sc(
        [req("R1", window=("10:00", "12:00"), dur=30, at=A)],
        [eng("E1", shift=("09:00", "18:00"), at=HOME, transport="car")],
    )
    timed = plan(s, travel=model(s))
    plain = plan(s, travel=HaversineTravelModel(s.settings))
    v1 = routes_by_engineer(timed)["E1"].visits[0]
    v2 = routes_by_engineer(plain)["E1"].visits[0]
    assert v1.departure_at == v2.departure_at and v1.travel_minutes == v2.travel_minutes


def test_profile_storage_roundtrip(tmp_path):
    """Файл профилей: те же ответы на любой момент, и записи «ехать дольше, чем идти» выброшены."""
    from planner import transit_profiles as tp

    fast = buses("07:00", 30, 20, walk=60)
    # последняя запись: ехать 90 мин при 60 мин пешком — ответа не меняет
    slow = Profile(fast.deps + [21 * 3600], fast.arrs + [21 * 3600 + 90 * 60], fast.walk)
    blob = tp.encode(slow)
    back = tp.decode(blob)
    assert len(back.deps) == len(fast.deps)
    for t in range(7 * 3600, 22 * 3600, 311):
        assert back.seconds_at(t) == slow.seconds_at(t)

    profiles = tp.ProfileSet(
        feed="f", first=7 * 3600, last=22 * 3600,
        weekdays={0: 0, 1: 0, 5: 1},
        pairs={0: {("a", "b"): blob}, 1: {("b", "a"): tp.encode(fast)}},
    )
    path = tmp_path / "p.bin"
    tp.write_file(path, profiles)
    loaded = tp.read_file(path)
    assert loaded.weekdays == {0: 0, 1: 0, 5: 1}
    assert set(loaded.for_weekday(1)) == {("a", "b")}
    assert set(loaded.for_weekday(5)) == {("b", "a")}
    assert loaded.for_weekday(6) == {}
    assert len(list(loaded.rows())) == 3  # по строке на день недели

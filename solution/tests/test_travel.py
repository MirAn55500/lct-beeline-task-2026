# -*- coding: utf-8 -*-
"""Модель перемещения (SPEC §3.2).

Время в пути — второй по важности критерий качества плана и единственный
источник «стоимости» вставки. Проверяем формулу, симметрию, кэш и поведение
разных профилей передвижения.
"""
from __future__ import annotations

import pytest

from factories import (
    TransportMode,
    gp,
    oracle_distance_km,
    oracle_haversine_km,
    oracle_travel_minutes,
    settings,
    sym,
)

# TravelModel — это Protocol (точка расширения под OSRM), инстанцировать его нельзя.
# Реализация по умолчанию — HaversineTravelModel(settings).
TravelModel = sym("TravelModel")
HaversineTravelModel = sym("HaversineTravelModel")
MatrixTravelModel = sym("MatrixTravelModel")

A = gp((55.7000, 37.6000))
B = gp((55.7500, 37.6500))
C = gp((55.8000, 37.7000))
FAR = gp((59.9386, 30.3141))  # Санкт-Петербург


def travel(cfg=None):
    """Реализация модели перемещения по умолчанию: HaversineTravelModel(settings)."""
    return HaversineTravelModel(cfg or settings())


def test_distance_km_is_symmetric():
    """Расстояние A->B равно B->A: асимметрия ломает оценку вставки."""
    tm = travel()
    assert tm.distance_km(A, B, TransportMode.CAR) == pytest.approx(
        tm.distance_km(B, A, TransportMode.CAR)
    )


def test_travel_minutes_is_symmetric():
    """Время в пути симметрично — прямой и обратный участок равнозначны."""
    tm = travel()
    assert tm.travel_minutes(A, B, TransportMode.CAR) == pytest.approx(
        tm.travel_minutes(B, A, TransportMode.CAR)
    )


def test_same_point_gives_zero_distance():
    """Совпадающие координаты: расстояние строго 0.0."""
    tm = travel()
    assert tm.distance_km(A, gp((55.7000, 37.6000)), TransportMode.CAR) == pytest.approx(0.0)


def test_same_point_gives_zero_minutes_without_overhead():
    """SPEC §3.2: на месте инженер уже находится — накладные не начисляются."""
    tm = travel()
    for mode in TransportMode:
        assert tm.travel_minutes(A, gp((55.7000, 37.6000)), mode) == pytest.approx(0.0), (
            f"режим {mode} начислил overhead на нулевом перемещении"
        )


def test_distance_is_monotonic_in_separation():
    """Дальше точка — больше расстояние: базовое свойство метрики."""
    tm = travel()
    d_ab = tm.distance_km(A, B, TransportMode.CAR)
    d_ac = tm.distance_km(A, C, TransportMode.CAR)
    assert 0 < d_ab < d_ac


def test_travel_minutes_is_monotonic_in_separation():
    """Больше расстояние — больше время при одном и том же режиме."""
    tm = travel()
    assert tm.travel_minutes(A, B, TransportMode.CAR) < tm.travel_minutes(A, C, TransportMode.CAR)


def test_distance_matches_haversine_times_detour_factor():
    """Проверяем формулу distance = haversine * detour_factor независимым расчётом."""
    cfg = settings()
    tm = travel(cfg)
    for mode in TransportMode:
        assert tm.distance_km(A, C, mode) == pytest.approx(
            oracle_distance_km(A, C, mode, cfg), rel=1e-9
        ), f"расстояние не совпало с формулой для {mode}"


def test_travel_minutes_matches_formula():
    """distance/speed*60 + overhead — сверка с независимой реализацией."""
    cfg = settings()
    tm = travel(cfg)
    for mode in TransportMode:
        assert tm.travel_minutes(A, C, mode) == pytest.approx(
            oracle_travel_minutes(A, C, mode, cfg), rel=1e-9
        ), f"время в пути не совпало с формулой для {mode}"


def test_overhead_is_added_once_per_leg():
    """Вклад overhead выделяется как свободный член: время минус ходовая часть."""
    cfg = settings()
    tm = travel(cfg)
    mode = TransportMode.CAR
    pure = tm.distance_km(A, C, mode) / cfg.speed_kmh[mode] * 60.0
    assert tm.travel_minutes(A, C, mode) - pure == pytest.approx(cfg.overhead_minutes[mode], abs=1e-9)


def test_modes_give_different_times_on_same_pair():
    """Четыре профиля передвижения дают четыре разных времени."""
    tm = travel()
    times = {mode: tm.travel_minutes(A, C, mode) for mode in TransportMode}
    assert len(set(round(v, 6) for v in times.values())) == len(TransportMode), (
        f"режимы дали неразличимые времена: {times}"
    )


def test_walking_is_slower_than_car():
    """Пешеход на той же паре точек медленнее авто — иначе профили бессмысленны."""
    tm = travel()
    assert tm.travel_minutes(A, C, TransportMode.WALKING) > tm.travel_minutes(
        A, C, TransportMode.CAR
    )


def test_bicycle_is_between_walking_and_car():
    """Порядок скоростей: пешком > велосипед > авто по времени."""
    tm = travel()
    walk = tm.travel_minutes(A, C, TransportMode.WALKING)
    bike = tm.travel_minutes(A, C, TransportMode.BICYCLE)
    car = tm.travel_minutes(A, C, TransportMode.CAR)
    assert walk > bike > car


def test_cache_does_not_change_values():
    """Повторные и обратные вызовы кэша возвращают то же самое (SPEC §3.2)."""
    tm = travel()
    first = tm.travel_minutes(A, B, TransportMode.CAR)
    for _ in range(5):
        assert tm.travel_minutes(A, B, TransportMode.CAR) == pytest.approx(first)
        assert tm.travel_minutes(B, A, TransportMode.CAR) == pytest.approx(first)
    assert tm.distance_km(A, B, TransportMode.CAR) == pytest.approx(
        tm.distance_km(B, A, TransportMode.CAR)
    )


def test_cache_does_not_leak_between_modes():
    """Кэш обязан учитывать режим: ключ — пара точек И режим."""
    tm = travel()
    car = tm.travel_minutes(A, B, TransportMode.CAR)
    walking = tm.travel_minutes(A, B, TransportMode.WALKING)
    assert car != pytest.approx(walking)
    assert tm.travel_minutes(A, B, TransportMode.CAR) == pytest.approx(car)


def test_haversine_matches_known_distance():
    """Москва — Санкт-Петербург по большому кругу ≈ 634 км."""
    tm = travel()
    raw = oracle_haversine_km(A, FAR)
    assert raw == pytest.approx(634.0, abs=8.0)
    assert tm.distance_km(A, FAR, TransportMode.CAR) > raw  # извилистость только увеличивает


def test_settings_speed_override_changes_travel_time():
    """Скорость — настройка: удвоение скорости сокращает ходовую часть вдвое."""
    base_cfg = settings()
    fast_cfg = settings()
    fast_cfg.speed_kmh = dict(base_cfg.speed_kmh)
    fast_cfg.speed_kmh[TransportMode.CAR] = base_cfg.speed_kmh[TransportMode.CAR] * 2

    base = travel(base_cfg).travel_minutes(A, C, TransportMode.CAR)
    fast = travel(fast_cfg).travel_minutes(A, C, TransportMode.CAR)
    overhead = base_cfg.overhead_minutes[TransportMode.CAR]
    assert (fast - overhead) == pytest.approx((base - overhead) / 2, rel=1e-9)


def test_detour_factor_override_changes_distance():
    """Коэффициент извилистости — настройка, а не константа в коде."""
    base_cfg = settings()
    cfg = settings()
    cfg.detour_factor = dict(base_cfg.detour_factor)
    cfg.detour_factor[TransportMode.CAR] = 1.0
    assert travel(cfg).distance_km(A, C, TransportMode.CAR) == pytest.approx(
        oracle_haversine_km(A, C), rel=1e-9
    )


def test_geopoint_rejects_out_of_range_coordinates():
    """GeoPoint валидирует диапазоны (SPEC §2.1)."""
    with pytest.raises(ValueError):
        gp((91.0, 37.0))
    with pytest.raises(ValueError):
        gp((55.0, 181.0))
    with pytest.raises(ValueError):
        gp((-90.5, 0.0))


# --------------------------------------------------------------------------
# MatrixTravelModel — точка расширения под реальную маршрутизацию
# --------------------------------------------------------------------------


def matrix_key(a, b, mode):
    """Ключ матрицы: координаты с 6 знаками, пара нормализована по возрастанию."""
    ka = f"{a.lat:.6f},{a.lon:.6f}"
    kb = f"{b.lat:.6f},{b.lon:.6f}"
    return (ka, kb, mode) if ka <= kb else (kb, ka, mode)


def test_matrix_model_returns_supplied_values():
    """Готовая матрица (например, ответ OSRM) подменяет расчёт по координатам."""
    fallback = travel()
    key = matrix_key(A, B, TransportMode.CAR)
    model = MatrixTravelModel({key: 42.0}, {key: 77.0}, fallback)

    assert model.distance_km(A, B, TransportMode.CAR) == pytest.approx(42.0)
    assert model.travel_minutes(A, B, TransportMode.CAR) == pytest.approx(77.0)


def test_matrix_model_is_symmetric_like_the_default_one():
    """Ключ нормализован, поэтому обратный участок берётся из той же ячейки."""
    fallback = travel()
    key = matrix_key(A, B, TransportMode.CAR)
    model = MatrixTravelModel({key: 42.0}, {key: 77.0}, fallback)

    assert model.distance_km(B, A, TransportMode.CAR) == pytest.approx(42.0)
    assert model.travel_minutes(B, A, TransportMode.CAR) == pytest.approx(77.0)


def test_matrix_model_falls_back_on_unknown_pair():
    """Неизвестная пара точек уходит в fallback, а не даёт ноль или исключение."""
    fallback = travel()
    key = matrix_key(A, B, TransportMode.CAR)
    model = MatrixTravelModel({key: 42.0}, {key: 77.0}, fallback)

    assert model.distance_km(A, C, TransportMode.CAR) == pytest.approx(
        fallback.distance_km(A, C, TransportMode.CAR)
    )
    assert model.travel_minutes(A, C, TransportMode.CAR) == pytest.approx(
        fallback.travel_minutes(A, C, TransportMode.CAR)
    )


def test_matrix_model_falls_back_per_transport_mode():
    """Матрица задана для авто — пешеход считается fallback'ом, а не берёт чужое число."""
    fallback = travel()
    key = matrix_key(A, B, TransportMode.CAR)
    model = MatrixTravelModel({key: 42.0}, {key: 77.0}, fallback)

    assert model.travel_minutes(A, B, TransportMode.WALKING) == pytest.approx(
        fallback.travel_minutes(A, B, TransportMode.WALKING)
    )


def test_matrix_model_both_agrees_with_separate_getters():
    """both() — то же самое одним вызовом, расхождений быть не может."""
    fallback = travel()
    key = matrix_key(A, B, TransportMode.CAR)
    model = MatrixTravelModel({key: 42.0}, {key: 77.0}, fallback)

    assert model.both(A, B, TransportMode.CAR) == (
        model.distance_km(A, B, TransportMode.CAR),
        model.travel_minutes(A, B, TransportMode.CAR),
    )


def test_matrix_model_changes_the_plan():
    """Подмена времён в пути действительно меняет расписание плана.

    Это и есть смысл точки расширения: алгоритм не правится, а маршруты
    пересчитываются по реальным данным.
    """
    from factories import eng, plan_optimized, req, routes_by_engineer, sc

    home = (55.70, 37.60)
    far = (55.80, 37.75)
    scenario = sc(
        [req("R1", window=("09:00", "17:00"), dur=30, at=far)],
        [eng("E1", shift=("09:00", "18:00"), at=home, transport="car")],
    )
    start = scenario.engineers[0].start_point
    point = scenario.requests[0].point

    default_plan = plan_optimized(scenario)
    default_minutes = routes_by_engineer(default_plan)["E1"].visits[0].travel_minutes

    key = matrix_key(start, point, TransportMode.CAR)
    matrix = MatrixTravelModel(
        {key: 3.0}, {key: 5.0}, HaversineTravelModel(scenario.settings)
    )
    from factories import Algorithm, plan as _plan

    patched = _plan(scenario, Algorithm.OPTIMIZED, travel=matrix)
    visit = routes_by_engineer(patched)["E1"].visits[0]

    assert visit.travel_minutes == pytest.approx(5.0)
    assert visit.distance_km == pytest.approx(3.0)
    assert visit.travel_minutes != pytest.approx(default_minutes)
    assert patched.metrics.total_distance_km == pytest.approx(3.0)


def test_travel_model_protocol_cannot_be_instantiated():
    """TravelModel — Protocol: это контракт расширения, а не готовый класс."""
    with pytest.raises(TypeError):
        TravelModel()

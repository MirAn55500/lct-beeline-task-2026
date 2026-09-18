"""Модель перемещения: расстояние и полное время в пути.

ТЗ (п. 2.4, п. 3.2) прямо разрешает упрощённый расчёт по координатам при условии, что
допущение описано. Здесь оно описано и вынесено в параметры:

    расстояние      = гаверсинус(A, B) × коэффициент извилистости(транспорт)
    время в пути    = расстояние / средняя скорость(транспорт) × 60 + сопутствующие затраты

«Сопутствующие затраты» (парковка, подход, подъём в квартиру) — требование базы знаний:
время перемещения должно включать их, а не только чистую дорогу.

Класс `TravelModel` — интерфейс. Подстановка реального маршрутного сервиса (OSRM) —
это отдельная реализация с тем же интерфейсом; алгоритм при этом не меняется.
"""

from __future__ import annotations

import math
from typing import Protocol

from .enums import TransportMode
from .models import GeoPoint, Settings

__all__ = ["TravelModel", "HaversineTravelModel", "MatrixTravelModel", "haversine_km"]

EARTH_RADIUS_KM = 6371.0088


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    """Расстояние по большому кругу между двумя точками, км."""
    if a.lat == b.lat and a.lon == b.lon:
        return 0.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


class TravelModel(Protocol):
    """Контракт источника расстояний и времён. Обе величины симметричны."""

    def distance_km(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> float: ...

    def travel_minutes(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> float: ...


class HaversineTravelModel:
    """Расчёт по координатам с кэшированием.

    Кэш обязателен по производительности: конструктивная фаза и локальный поиск
    обращаются к одним и тем же парам точек десятки тысяч раз.
    """

    __slots__ = ("_settings", "_cache")

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict[tuple[GeoPoint, GeoPoint, TransportMode], tuple[float, float]] = {}

    def _pair(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> tuple[float, float]:
        # Ключ нормализован по значению координат, а не по идентичности объектов:
        # одна и та же точка приходит разными экземплярами из разных мест.
        key = (a, b, mode) if (a.lat, a.lon) <= (b.lat, b.lon) else (b, a, mode)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        straight = haversine_km(a, b)
        if straight == 0.0:
            # Инженер уже на месте: ни пробега, ни сопутствующих затрат.
            result = (0.0, 0.0)
        else:
            distance = straight * self._settings.detour_factor[mode]
            speed = self._settings.speed_kmh[mode]
            minutes = distance / speed * 60.0 + self._settings.overhead_minutes[mode]
            result = (distance, minutes)

        self._cache[key] = result
        return result

    def distance_km(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> float:
        return self._pair(a, b, mode)[0]

    def travel_minutes(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> float:
        return self._pair(a, b, mode)[1]

    def both(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> tuple[float, float]:
        """Расстояние и время одним вызовом — основной способ обращения из алгоритма."""
        return self._pair(a, b, mode)


class MatrixTravelModel:
    """Готовая матрица расстояний/времён (например, ответ OSRM `/table`).

    Нужна, чтобы подменить упрощённый расчёт реальными данными без правок алгоритма.
    Для неизвестной пары точек делегирует расчёт `fallback`.
    """

    __slots__ = ("_distance", "_minutes", "_fallback")

    def __init__(
        self,
        distance: dict[tuple[str, str, TransportMode], float],
        minutes: dict[tuple[str, str, TransportMode], float],
        fallback: TravelModel,
    ) -> None:
        self._distance = distance
        self._minutes = minutes
        self._fallback = fallback

    @staticmethod
    def _key(a: GeoPoint, b: GeoPoint, mode: TransportMode) -> tuple[str, str, TransportMode]:
        ka = f"{a.lat:.6f},{a.lon:.6f}"
        kb = f"{b.lat:.6f},{b.lon:.6f}"
        return (ka, kb, mode) if ka <= kb else (kb, ka, mode)

    def distance_km(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> float:
        value = self._distance.get(self._key(a, b, mode))
        return value if value is not None else self._fallback.distance_km(a, b, mode)

    def travel_minutes(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> float:
        value = self._minutes.get(self._key(a, b, mode))
        return value if value is not None else self._fallback.travel_minutes(a, b, mode)

    def both(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> tuple[float, float]:
        return self.distance_km(a, b, mode), self.travel_minutes(a, b, mode)

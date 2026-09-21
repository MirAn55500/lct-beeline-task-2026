"""Модель перемещения: расстояние и полное время в пути.

ТЗ (п. 2.4, п. 3.2) прямо разрешает упрощённый расчёт по координатам при условии, что
допущение описано. Здесь оно описано и вынесено в параметры:

    расстояние      = гаверсинус(A, B) × коэффициент извилистости(транспорт)
    время в пути    = расстояние / средняя скорость(транспорт) × 60 + сопутствующие затраты

«Сопутствующие затраты» (парковка, подход, подъём в квартиру) — требование базы знаний:
время перемещения должно включать их, а не только чистую дорогу.

Класс `TravelModel` — интерфейс. Реальная маршрутизация по улицам реализована в
`planner/ors.py` (openrouteservice): это отдельная реализация того же интерфейса,
алгоритм при её подстановке не меняется. Расчёт по координатам остаётся режимом по
умолчанию, потому что он не требует ни сети, ни поднятого сервиса.
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


def _validate_transport_settings(settings: Settings) -> None:
    """Проверяет параметры перемещения по каждому режиму транспорта.

    Один раз на входе, а не на каждой паре точек: иначе мусор в настройках всплывает
    из горячего пути `KeyError`-ом или `ZeroDivisionError`-ом — без единого слова о том,
    что именно настроено не так и в каком режиме.

    Проверяются все три параметра, а не только скорость. Каждый из них по-своему
    подделывает результат молча: отрицательный коэффициент извилистости даёт
    **отрицательный пробег** (и `compare()` сочтёт такой план улучшением), нулевой —
    нулевой; `NaN` проходит любое сравнение с нулём, и заявки тихо уходят в отказ
    «не успевает доехать»; бесконечная скорость обнуляет дорогу; отрицательные
    сопутствующие затраты роняют расчёт из календаря. Ни один из этих случаев
    верификатор не ловит: знак километров он не смотрит.
    """
    # Название, поле настроек, таблица и два готовых требования: согласование по роду
    # разное у каждого параметра, а текст ошибки читает человек.
    checks = (
        ("скорость", "speed_kmh", settings.speed_kmh,
         "должна быть конечным числом", "должна быть положительной"),
        ("коэффициент извилистости", "detour_factor", settings.detour_factor,
         "должен быть конечным числом", "должен быть положительным"),
        ("сопутствующие затраты", "overhead_minutes", settings.overhead_minutes,
         "должны быть конечным числом", "не могут быть отрицательными"),
    )
    for mode in TransportMode:
        for title, field, table, finite_rule, sign_rule in checks:
            if mode not in table:
                raise ValueError(
                    f"Настройки перемещения: для режима «{mode.value}» "
                    f"не задан параметр {field}"
                )
            value = table[mode]
            if not math.isfinite(value):
                raise ValueError(
                    f"Настройки перемещения: {title} для режима «{mode.value}» "
                    f"{finite_rule}, задано {value}"
                )
            # Ноль допустим только у сопутствующих затрат: нулевая скорость — это деление
            # на ноль, нулевая извилистость — стёртый пробег, а нулевая парковка бывает.
            zero_ok = field == "overhead_minutes"
            if value < 0 or (value == 0 and not zero_ok):
                raise ValueError(
                    f"Настройки перемещения: {title} для режима «{mode.value}» "
                    f"{sign_rule}, задано {value}"
                )


class HaversineTravelModel:
    """Расчёт по координатам с кэшированием.

    Кэш обязателен по производительности: конструктивная фаза и локальный поиск
    обращаются к одним и тем же парам точек десятки тысяч раз.
    """

    __slots__ = ("_settings", "_cache")

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict[tuple[GeoPoint, GeoPoint, TransportMode], tuple[float, float]] = {}
        _validate_transport_settings(settings)

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


def _validate_matrix(
    title: str, table: dict[tuple[str, str, TransportMode], float], *, unit: str
) -> None:
    """Проверяет подставленную снаружи матрицу: значения конечны и неотрицательны.

    Матрица приходит из биллинга, из замеров диспетчера или от стороннего сервиса, то есть
    из места, за которое планировщик не отвечает. Отрицательный километр такой источник
    подделывает молча: расчёт по координатам его уже не пропускает, а здесь он доходил
    до метрик, и `compare()` счёл бы такой план улучшением — верификатор смотрит ту же
    матрицу и расхождения не видит.
    """
    for key, value in table.items():
        if not math.isfinite(value) or value < 0:
            point_a, point_b, mode = key
            raise ValueError(
                f"Матрица перемещения: {title} {point_a} → {point_b} "
                f"для режима «{mode.value}» должно быть неотрицательным конечным числом, "
                f"задано {value} {unit}"
            )


def _pairs_word(count: int) -> str:
    """«1 пары», «2 пар», «11 пар» — согласование числительного в родительном падеже."""
    return "пары" if count % 10 == 1 and count % 100 != 11 else "пар"


def _validate_matrix_pair(
    distance: dict[tuple[str, str, TransportMode], float],
    minutes: dict[tuple[str, str, TransportMode], float],
) -> None:
    """Требует, чтобы обе матрицы знали одни и те же пары точек.

    Расстояние и время одной пары обязаны приходить из одного источника. Если километры
    заданы, а минуты нет, время досчитывается `fallback`-ом по прямой — и получается
    «100 км за 13 минут»: скорость под 500 км/ч, которую никто не поймает. Верификатор
    смотрит ту же модель, поэтому расхождения не видит; метрики, `compare()` и оценка
    «успевает ли» принимают такую пару как обычную. «Неизвестная пара», ради которой
    и существует `fallback`, — это пара, неизвестная **обеим** матрицам.
    """
    for missing, given, gap in (
        ("время в пути", "расстояние", distance.keys() - minutes.keys()),
        ("расстояние", "время в пути", minutes.keys() - distance.keys()),
    ):
        if not gap:
            continue
        shown = "; ".join(
            f"{a} → {b} ({mode.value})"
            for a, b, mode in sorted(gap, key=lambda k: (k[0], k[1], k[2].value))[:3]
        )
        tail = ", …" if len(gap) > 3 else ""
        raise ValueError(
            f"Матрица перемещения: для {len(gap)} {_pairs_word(len(gap))} точек "
            f"задано {given}, но не "
            f"{missing} — обе матрицы должны знать одни и те же пары, иначе половина "
            f"пары считается по прямой и расчёт противоречит сам себе. "
            f"Пары: {shown}{tail}"
        )


class MatrixTravelModel:
    """Готовая матрица расстояний/времён, симметричная и заданная снаружи.

    Нужна, чтобы подменить упрощённый расчёт готовыми данными без правок алгоритма:
    выгрузка из биллинга, замеры диспетчера, ответ стороннего сервиса. Для неизвестной
    пары точек делегирует расчёт `fallback`.

    Для openrouteservice есть отдельная реализация (`planner.ors.OrsTravelModel`):
    там матрица направленная, потому что односторонние улицы делают A→B и B→A разными.
    """

    __slots__ = ("_distance", "_minutes", "_fallback")

    def __init__(
        self,
        distance: dict[tuple[str, str, TransportMode], float],
        minutes: dict[tuple[str, str, TransportMode], float],
        fallback: TravelModel,
    ) -> None:
        _validate_matrix("расстояние", distance, unit="км")
        _validate_matrix("время в пути", minutes, unit="мин")
        _validate_matrix_pair(distance, minutes)
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

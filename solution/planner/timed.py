"""Время в пути, зависящее от момента выезда: общественный транспорт по профилям rRAPTOR.

Обычная модель перемещения (`TravelModel`) отвечает одним числом на пару точек. Для
общественного транспорта этого мало: выйти за минуту до автобуса или через минуту
после — разница в интервал движения (см. `docs/transit-raptor.md`). Профиль rRAPTOR
знает время в пути на любой момент выезда, и эта модель отдаёт его планировщику.

Модель — обёртка над базовой: расстояния и все остальные способы передвижения берутся
из неё без изменений. Время по профилю планировщик спрашивает через два метода:

* `minutes_at(a, b, mode, depart)` — сколько ехать при выезде в `depart`;
* `depart_by(a, b, mode, arrive_by)` — самый поздний выезд, чтобы успеть к `arrive_by`
  (нужен отложенному выезду и обратному проходу `RouteState`).

Моменты — минуты от полуночи дня плана по местному времени, как в `PlanContext`.

Пары без профиля (новые адреса) и моменты вне окна профиля отвечают базовым числом —
тем же, что и раньше: для новых адресов это RAPTOR на 10:00.
"""

from __future__ import annotations

from typing import Mapping

from .enums import TransportMode
from .models import GeoPoint, Settings
from .raptor import Profile
from .travel import TravelModel

__all__ = ["TimedTransitModel", "BOARDING_MARGIN_MINUTES"]

BOARDING_MARGIN_MINUTES = 2.0
"""На сколько раньше «впритык» выходить к рейсу при отложенном выезде.

RAPTOR считает подход к остановке по прямой × 1.29, и выезд, подогнанный под рейс
секунда в секунду, на улицах иногда опаздывает: сверка с ORS на тот же момент выезда
(полная проверка системы, 24.09.2026) дала в среднем +1.2…4.6 мин, в худших случаях —
пропущенный автобус. Две минуты запаса закрывают типичный разброс; время в пути от
этого не меняется — тот же рейс, просто подождать его на остановке.
"""


def _key(p: GeoPoint) -> str:
    return f"{p.lat:.6f},{p.lon:.6f}"


class TimedTransitModel:
    """Базовая модель + профили общественного транспорта."""

    __slots__ = (
        "base", "_profiles", "_overhead", "_first", "_last",
        "_mode", "profile_hits", "constant_hits", "_seen",
    )

    def __init__(
        self,
        base: TravelModel,
        profiles: Mapping[tuple[str, str], Profile],
        settings: Settings,
        *,
        first: int,
        last: int,
        add_overhead: bool = True,
        mode: TransportMode = TransportMode.PUBLIC_TRANSPORT,
    ) -> None:
        self.base = base
        self._profiles = dict(profiles)
        self._mode = mode
        self._overhead = settings.overhead_minutes[mode] if add_overhead else 0.0
        self._first = first / 60
        self._last = last / 60
        self.profile_hits = 0
        self.constant_hits = 0
        self._seen: set[tuple[str, str]] = set()

    # -- протокол TravelModel: как у базовой модели --

    def distance_km(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> float:
        return self.base.distance_km(a, b, mode)

    def travel_minutes(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> float:
        return self.base.travel_minutes(a, b, mode)

    def both(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> tuple[float, float]:
        both = getattr(self.base, "both", None)
        if both is not None:
            return both(a, b, mode)
        return self.base.distance_km(a, b, mode), self.base.travel_minutes(a, b, mode)

    # -- время от момента выезда --

    def is_timed(self, mode: TransportMode) -> bool:
        return mode is self._mode and bool(self._profiles)

    def _profile(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> Profile | None:
        if mode is not self._mode:
            return None
        pair = (_key(a), _key(b))
        profile = self._profiles.get(pair)
        if pair not in self._seen:
            self._seen.add(pair)
            if profile is None:
                self.constant_hits += 1
            else:
                self.profile_hits += 1
        return profile

    def minutes_at(self, a: GeoPoint, b: GeoPoint, mode: TransportMode, depart: float) -> float:
        if a.lat == b.lat and a.lon == b.lon:
            return 0.0
        profile = self._profile(a, b, mode)
        if profile is None or not (self._first <= depart <= self._last):
            return self.base.travel_minutes(a, b, mode)
        return profile.seconds_at(depart * 60) / 60 + self._overhead

    def depart_by(self, a: GeoPoint, b: GeoPoint, mode: TransportMode, arrive_by: float) -> float:
        """Самый поздний выезд, чтобы прибыть не позже `arrive_by` (минуты)."""
        if a.lat == b.lat and a.lon == b.lon:
            return arrive_by
        profile = self._profile(a, b, mode)
        if profile is not None:
            depart = profile.latest_departure((arrive_by - self._overhead) * 60) / 60
            depart -= BOARDING_MARGIN_MINUTES
            if self._first <= depart <= self._last:
                return depart
        return arrive_by - self.base.travel_minutes(a, b, mode)

    # -- отчётность --

    @property
    def has_matrix(self) -> bool:
        return bool(self._profiles) or bool(getattr(self.base, "has_matrix", False))

    def report(self) -> tuple[str, ...]:
        lines = list(self.base.report()) if hasattr(self.base, "report") else []
        total = self.profile_hits + self.constant_hits
        if total:
            lines.append(
                f"Общественный транспорт: {self.profile_hits} пар из {total} — по "
                "расписанию на фактический момент выезда (rRAPTOR), "
                f"{self.constant_hits} — одним значением на 10:00 (новые адреса)"
            )
        return tuple(lines)

"""Общий контекст расчёта.

Всё, что вычисляется один раз и переиспользуется всеми фазами алгоритма: точка отсчёта
времени, календари инженеров, временные окна заявок в минутах, модель перемещения.

Смысл существования модуля — производительность и единообразие. Конструктивная фаза и
локальный поиск выполняют сотни тысяч проверок; каждая из них не должна заново переводить
`datetime` в минуты и пересоздавать календари.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from .calendar import WorkCalendar
from .models import Engineer, Request, Scenario, Settings
from .travel import HaversineTravelModel, TravelModel

__all__ = ["RequestTiming", "PlanContext"]


@dataclass(frozen=True, slots=True)
class RequestTiming:
    """Временные параметры заявки в минутах от точки отсчёта."""

    window_start: float
    window_end: float
    duration: float
    available_from: float
    """Момент поступления в минутах. Работа не начинается раньше этого значения."""

    @property
    def service_not_before(self) -> float:
        return self.window_start if self.window_start >= self.available_from else self.available_from


class PlanContext:
    """Неизменяемое окружение расчёта."""

    __slots__ = ("scenario", "settings", "travel", "origin", "_calendars", "_timings")

    def timed_for(self, mode):
        """Модель со временем от момента выезда для этого способа передвижения, или None.

        Такая модель (`planner.timed.TimedTransitModel`) умеет `minutes_at`/`depart_by`;
        обычная отвечает одним числом на пару, и тогда расчёт идёт прежним путём.
        """
        is_timed = getattr(self.travel, "is_timed", None)
        return self.travel if is_timed is not None and is_timed(mode) else None

    def __init__(self, scenario: Scenario, travel: TravelModel | None = None) -> None:
        self.scenario = scenario
        self.settings = scenario.settings
        self.travel = travel if travel is not None else HaversineTravelModel(scenario.settings)
        self.origin = self._resolve_origin(scenario)
        self._calendars: dict[str, WorkCalendar] = {
            e.id: WorkCalendar(e.work_intervals, self.origin) for e in scenario.engineers
        }
        self._timings: dict[str, RequestTiming] = {
            r.id: self._timing_of(r) for r in scenario.requests
        }

    # ------------------------------------------------------------------ точка отсчёта

    @staticmethod
    def _resolve_origin(scenario: Scenario) -> datetime:
        """Полночь даты плана в поясе данных: общая нулевая отметка для всех расчётов.

        Пояс берётся из самих данных, а не назначается: так расчёт не «съедет» на три
        часа, если набор придёт из другого региона.
        """
        tzinfo = None
        for engineer in scenario.engineers:
            if engineer.work_intervals:
                tzinfo = engineer.work_intervals[0].start.tzinfo
                break
        if tzinfo is None:
            for request in scenario.requests:
                tzinfo = request.window_start.tzinfo
                break
        if tzinfo is None:
            tzinfo = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))
        return datetime.combine(scenario.date, time(0, 0), tzinfo=tzinfo)

    def _minutes(self, moment: datetime) -> float:
        return (moment - self.origin).total_seconds() / 60.0

    def to_minutes(self, moment: datetime) -> float:
        return self._minutes(moment)

    def to_datetime(self, minutes: float | None) -> datetime | None:
        return None if minutes is None else self.origin + timedelta(minutes=minutes)

    # ------------------------------------------------------------------ доступ

    def calendar(self, engineer: Engineer) -> WorkCalendar:
        cal = self._calendars.get(engineer.id)
        if cal is None:
            cal = WorkCalendar(engineer.work_intervals, self.origin)
            self._calendars[engineer.id] = cal
        return cal

    def _timing_of(self, request: Request) -> RequestTiming:
        available = (
            self._minutes(request.received_at)
            if request.received_at is not None
            else self._minutes(request.window_start)
        )
        return RequestTiming(
            window_start=self._minutes(request.window_start),
            window_end=self._minutes(request.window_end),
            duration=float(request.duration_minutes),
            available_from=available,
        )

    def timing(self, request: Request) -> RequestTiming:
        timing = self._timings.get(request.id)
        if timing is None:
            timing = self._timing_of(request)
            self._timings[request.id] = timing
        return timing

    @property
    def request_settings(self) -> Settings:  # pragma: no cover - совместимость имён
        return self.settings

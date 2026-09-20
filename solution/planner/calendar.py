"""Арифметика рабочего времени.

Ключевое правило модели (БЗ «Правила модели → Рабочее время»): **и работа, и
перемещение** расходуют только рабочее время инженера. В разрывах между рабочими
интервалами (перерывах) время не течёт — обед не «съедает» дорогу.

Публичный API работает с `datetime`. Внутри всё считается в минутах (float) от общей
точки отсчёта `origin`: планировщик выполняет миллионы таких операций, и арифметика
на числах на порядок дешевле арифметики на `datetime`. Методы с суффиксом ``_m``
(`add_m`, `sub_m`, ...) — это тот же расчёт без конвертации, для горячего пути.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import WorkInterval

__all__ = ["WorkCalendar"]

_EPS = 1e-6
"""Допуск сравнения минут: защищает от ошибки округления на границах интервалов.

Порог выбран крупнее разрешения `datetime`: микросекунда — это 1.7e-8 минуты, и любой
путь «минуты → datetime → минуты» квантует значение именно на столько. При допуске 1e-9
такой round-trip ломал точное попадание в границу интервала: `sub(13:00, t)` и обратный
`add(…, t)` расходились на 5e-9 минуты, проверка «хватает ли остатка интервала» не
проходила, и момент перепрыгивал через обед — 13:00 превращалось в 14:00.
Одна миллионная минуты — 60 микросекунд: на расписание не влияет, округление переживает.
"""


class WorkCalendar:
    """Рабочий календарь одного инженера на дату плана."""

    __slots__ = ("_origin", "_starts", "_ends", "_capacity")

    def __init__(self, intervals: tuple[WorkInterval, ...], origin: datetime) -> None:
        self._origin = origin
        ordered = sorted(intervals, key=lambda i: i.start)
        self._starts: list[float] = [self.to_minutes(i.start) for i in ordered]
        self._ends: list[float] = [self.to_minutes(i.end) for i in ordered]
        self._capacity = sum(e - s for s, e in zip(self._starts, self._ends))

    # ------------------------------------------------------------------ конвертация

    @property
    def origin(self) -> datetime:
        return self._origin

    def to_minutes(self, moment: datetime) -> float:
        return (moment - self._origin).total_seconds() / 60.0

    def to_datetime(self, minutes: float) -> datetime:
        return self._origin + timedelta(minutes=minutes)

    # ------------------------------------------------------------------ свойства

    @property
    def is_empty(self) -> bool:
        return not self._starts

    @property
    def capacity_minutes(self) -> float:
        return self._capacity

    @property
    def start_m(self) -> float | None:
        return self._starts[0] if self._starts else None

    @property
    def end_m(self) -> float | None:
        return self._ends[-1] if self._ends else None

    @property
    def shift_start(self) -> datetime | None:
        return self.to_datetime(self._starts[0]) if self._starts else None

    @property
    def shift_end(self) -> datetime | None:
        return self.to_datetime(self._ends[-1]) if self._ends else None

    # ------------------------------------------------------------------ горячий путь (минуты)

    def contains_m(self, t: float) -> bool:
        """`t` внутри рабочего интервала (границы включительно)."""
        for s, e in zip(self._starts, self._ends):
            if s - _EPS <= t <= e + _EPS:
                return True
        return False

    def first_m(self, t: float) -> float | None:
        """Ближайший рабочий момент не раньше `t`. `None`, если смена уже кончилась.

        Границы интервалов включительные — ровно так же, как в `contains_m`: момент
        окончания утреннего интервала является рабочим моментом, просто работать из
        него дальше нельзя, пока не начнётся следующий интервал. Расходование времени
        (`add_m`) исчерпанные интервалы пропускает само, поэтому расхождения между
        «в рабочем времени» и «можно продолжать работу» здесь не возникает.
        """
        for s, e in zip(self._starts, self._ends):
            if t <= s + _EPS:
                return s
            if t <= e + _EPS:
                return t
        return None

    def last_m(self, t: float) -> float | None:
        """Ближайший рабочий момент не позже `t` (границы включительно)."""
        result: float | None = None
        for s, e in zip(self._starts, self._ends):
            if t >= e - _EPS:
                result = e
            elif t >= s - _EPS:
                return t
            else:
                break
        return result

    def add_m(self, t: float, minutes: float) -> float | None:
        """Момент после расходования `minutes` рабочих минут начиная с `t`."""
        if minutes < 0:
            raise ValueError("Нельзя расходовать отрицательное время")
        cur = self.first_m(t)
        if cur is None:
            return None
        if minutes <= _EPS:
            # Нулевой расход не должен перепрыгивать через перерыв: `add(t, 0)` — это
            # ровно «ближайший рабочий момент», а не «момент, в котором можно работать».
            return cur
        remaining = minutes
        for s, e in zip(self._starts, self._ends):
            if e <= cur + _EPS:
                continue
            seg_start = cur if cur > s else s
            available = e - seg_start
            if remaining <= available + _EPS:
                return seg_start + remaining
            remaining -= available
        return None

    def sub_m(self, t: float, minutes: float) -> float | None:
        """Момент, из которого через `minutes` рабочих минут окажемся в `t`."""
        if minutes < 0:
            raise ValueError("Нельзя расходовать отрицательное время")
        cur = self.last_m(t)
        if cur is None:
            return None
        if minutes <= _EPS:
            return cur
        remaining = minutes
        for s, e in zip(reversed(self._starts), reversed(self._ends)):
            if s >= cur - _EPS:
                continue
            seg_end = cur if cur < e else e
            available = seg_end - s
            if remaining <= available + _EPS:
                return seg_end - remaining
            remaining -= available
        return None

    def working_between_m(self, a: float, b: float) -> float:
        """Рабочие минуты в отрезке [a, b]. Ноль, если `b <= a`."""
        if b <= a:
            return 0.0
        total = 0.0
        for s, e in zip(self._starts, self._ends):
            lo = a if a > s else s
            hi = b if b < e else e
            if hi > lo:
                total += hi - lo
        return total

    # ------------------------------------------------------------------ публичный API (datetime)

    def contains(self, moment: datetime) -> bool:
        return self.contains_m(self.to_minutes(moment))

    def first_moment_at_or_after(self, moment: datetime) -> datetime | None:
        value = self.first_m(self.to_minutes(moment))
        return None if value is None else self.to_datetime(value)

    def last_moment_at_or_before(self, moment: datetime) -> datetime | None:
        value = self.last_m(self.to_minutes(moment))
        return None if value is None else self.to_datetime(value)

    def add(self, moment: datetime, minutes: float) -> datetime | None:
        value = self.add_m(self.to_minutes(moment), minutes)
        return None if value is None else self.to_datetime(value)

    def sub(self, moment: datetime, minutes: float) -> datetime | None:
        value = self.sub_m(self.to_minutes(moment), minutes)
        return None if value is None else self.to_datetime(value)

    def working_between(self, start: datetime, end: datetime) -> float:
        return self.working_between_m(self.to_minutes(start), self.to_minutes(end))

    def __repr__(self) -> str:  # pragma: no cover - диагностика
        parts = ", ".join(
            f"{self.to_datetime(s):%H:%M}-{self.to_datetime(e):%H:%M}"
            for s, e in zip(self._starts, self._ends)
        )
        return f"WorkCalendar({parts or 'пусто'})"

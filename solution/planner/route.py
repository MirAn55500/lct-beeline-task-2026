"""Состояние маршрута одного инженера: расписание, проверка вставки, изменение состава.

Два расчёта задают всю механику:

* **прямой проход** — фактическое расписание: выезд, прибытие, ожидание, начало и конец
  работ. Он же авторитетно решает, допустим ли маршрут;
* **обратный проход** (`_latest`) — «самый поздний допустимый старт» каждого визита,
  при котором весь хвост маршрута ещё укладывается в окна и смену.

Обратный проход превращает проверку вставки из O(n) (протянуть время по всему хвосту)
в O(1): достаточно сравнить новое время прибытия к следующему визиту с его запасом.
Это классический приём из эвристик VRPTW; здесь он нужен не столько ради скорости,
сколько ради того, чтобы проверка «а не сломает ли вставка более поздние заявки»
была одной строкой, а не отдельным циклом, который легко забыть обновить.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from .context import PlanContext
from .cost import InsertionCost
from .enums import ReasonCode
from .feasibility import FeasibilityResult, check_static
from .models import Engineer, GeoPoint, Request
from .textutil import plural

__all__ = ["RouteState"]

_EPS = 1e-9
_NEG_INF = -math.inf


class RouteState:
    """Изменяемое состояние маршрута. Все времена — минуты от `context.origin`."""

    __slots__ = (
        "ctx",
        "engineer",
        "cal",
        "mode",
        "stops",
        "locked_count",
        "_dep",
        "_arr",
        "_start",
        "_end",
        "_wait",
        "_leg_minutes",
        "_leg_km",
        "_latest",
        "_static",
        "feasible",
        "distance_km",
        "travel_minutes",
        "service_minutes",
        "waiting_minutes",
    )

    def __init__(
        self,
        ctx: PlanContext,
        engineer: Engineer,
        stops: Sequence[Request] = (),
        locked_count: int = 0,
    ) -> None:
        self.ctx = ctx
        self.engineer = engineer
        self.cal = ctx.calendar(engineer)
        self.mode = engineer.transport_mode
        self.stops: list[Request] = list(stops)
        self.locked_count = locked_count
        self._static: dict[str, bool] = {}
        self.recompute()

    # ------------------------------------------------------------------ допуск инженера

    def accepts(self, request: Request) -> bool:
        """Проходит ли заявка статические ограничения этого инженера.

        Результат кэшируется: проверка вызывается на каждом шаге локального поиска.
        Она встроена в каждый путь изменения состава маршрута намеренно — иначе
        оператор переноса между маршрутами способен отдать заявку инженеру без
        нужного навыка, и план останется корректным по времени, но неисполнимым.
        """
        cached = self._static.get(request.id)
        if cached is None:
            cached = check_static(self.engineer, request, self.ctx.settings).ok
            self._static[request.id] = cached
        return cached

    # ------------------------------------------------------------------ базовое

    def clone(self) -> "RouteState":
        copy = RouteState.__new__(RouteState)
        copy.ctx = self.ctx
        copy.engineer = self.engineer
        copy.cal = self.cal
        copy.mode = self.mode
        copy.stops = list(self.stops)
        copy.locked_count = self.locked_count
        copy._dep = list(self._dep)
        copy._arr = list(self._arr)
        copy._start = list(self._start)
        copy._end = list(self._end)
        copy._wait = list(self._wait)
        copy._leg_minutes = list(self._leg_minutes)
        copy._leg_km = list(self._leg_km)
        copy._latest = list(self._latest)
        copy._static = dict(self._static)
        copy.feasible = self.feasible
        copy.distance_km = self.distance_km
        copy.travel_minutes = self.travel_minutes
        copy.service_minutes = self.service_minutes
        copy.waiting_minutes = self.waiting_minutes
        return copy

    @property
    def is_empty(self) -> bool:
        return not self.stops

    @property
    def size(self) -> int:
        return len(self.stops)

    @property
    def request_ids(self) -> tuple[str, ...]:
        return tuple(r.id for r in self.stops)

    def index_of(self, request_id: str) -> int:
        for i, r in enumerate(self.stops):
            if r.id == request_id:
                return i
        return -1

    def _point_before(self, position: int) -> GeoPoint:
        return self.stops[position - 1].point if position > 0 else self.engineer.start_point

    def _time_before(self, position: int) -> float:
        if position > 0:
            return self._end[position - 1]
        start = self.cal.start_m
        return start if start is not None else _NEG_INF

    # ------------------------------------------------------------------ прямой проход

    def recompute(self) -> bool:
        """Пересчитывает расписание с нуля. Возвращает допустимость маршрута."""
        cal = self.cal
        ctx = self.ctx
        travel = ctx.travel
        mode = self.mode
        strict = ctx.settings.service_must_start_within_window

        n = len(self.stops)
        self._dep = [0.0] * n
        self._arr = [0.0] * n
        self._start = [0.0] * n
        self._end = [0.0] * n
        self._wait = [0.0] * n
        self._leg_minutes = [0.0] * n
        self._leg_km = [0.0] * n
        self._latest = [_NEG_INF] * n
        self.distance_km = 0.0
        self.travel_minutes = 0.0
        self.service_minutes = 0.0
        self.waiting_minutes = 0.0

        if n == 0:
            self.feasible = True
            return True

        shift_start = cal.start_m
        if shift_start is None:
            self.feasible = False
            return False

        point = self.engineer.start_point
        cursor = shift_start

        for i, request in enumerate(self.stops):
            timing = ctx.timing(request)
            km, minutes = travel.both(point, request.point, mode)

            departure = cal.first_m(cursor)
            if departure is None:
                self.feasible = False
                return False
            arrival = cal.add_m(departure, minutes)
            if arrival is None or arrival > timing.window_end + _EPS:
                self.feasible = False
                return False
            target = arrival if arrival > timing.window_start else timing.window_start
            service_start = cal.first_m(target)
            if service_start is None:
                self.feasible = False
                return False
            if strict and service_start > timing.window_end + _EPS:
                self.feasible = False
                return False
            service_end = cal.add_m(service_start, timing.duration)
            if service_end is None:
                self.feasible = False
                return False

            self._dep[i] = departure
            self._arr[i] = arrival
            self._start[i] = service_start
            self._end[i] = service_end
            self._wait[i] = cal.working_between_m(arrival, service_start)
            self._leg_minutes[i] = minutes
            self._leg_km[i] = km

            self.distance_km += km
            self.travel_minutes += minutes
            self.service_minutes += timing.duration
            self.waiting_minutes += self._wait[i]

            cursor = service_end
            point = request.point

        self._recompute_slack()
        self.feasible = True
        return True

    # ------------------------------------------------------------------ обратный проход

    def _recompute_slack(self) -> None:
        cal = self.cal
        ctx = self.ctx
        travel = ctx.travel
        mode = self.mode
        shift_end = cal.end_m
        n = len(self.stops)
        if n == 0 or shift_end is None:
            return

        latest = self._latest
        for i in range(n - 1, -1, -1):
            request = self.stops[i]
            timing = ctx.timing(request)
            if i == n - 1:
                bound = cal.sub_m(shift_end, timing.duration)
            else:
                nxt = self.stops[i + 1]
                leg = travel.travel_minutes(request.point, nxt.point, mode)
                latest_departure = cal.sub_m(latest[i + 1], leg)
                bound = None if latest_departure is None else cal.sub_m(latest_departure, timing.duration)
            if bound is None:
                latest[i] = _NEG_INF
            else:
                latest[i] = bound if bound < timing.window_end else timing.window_end

    # ------------------------------------------------------------------ оценка вставки

    def evaluate_insertion(self, request: Request, position: int) -> InsertionCost | None:
        """Быстрая оценка вставки заявки перед визитом `position`.

        Возвращает стоимость либо `None`, если вставка недопустима. Проверка
        оптимистична на границах перерывов, поэтому фактическая вставка всегда
        подтверждается полным пересчётом (`insert_checked`).
        """
        if position < self.locked_count or position > len(self.stops):
            return None
        if not self.feasible or not self.accepts(request):
            return None

        cal = self.cal
        ctx = self.ctx
        travel = ctx.travel
        mode = self.mode
        strict = ctx.settings.service_must_start_within_window
        timing = ctx.timing(request)

        prev_point = self._point_before(position)
        cursor = self._time_before(position)
        if cursor == _NEG_INF:
            return None

        in_km, in_min = travel.both(prev_point, request.point, mode)

        departure = cal.first_m(cursor)
        if departure is None:
            return None
        arrival = cal.add_m(departure, in_min)
        if arrival is None or arrival > timing.window_end + _EPS:
            return None
        target = arrival if arrival > timing.window_start else timing.window_start
        service_start = cal.first_m(target)
        if service_start is None:
            return None
        if strict and service_start > timing.window_end + _EPS:
            return None
        service_end = cal.add_m(service_start, timing.duration)
        if service_end is None:
            return None

        waiting = cal.working_between_m(arrival, service_start)

        if position == len(self.stops):
            out_km = out_min = 0.0
            removed_km = removed_min = 0.0
            delta_wait = waiting
        else:
            nxt = self.stops[position]
            nxt_timing = ctx.timing(nxt)
            out_km, out_min = travel.both(request.point, nxt.point, mode)
            removed_km = self._leg_km[position]
            removed_min = self._leg_minutes[position]

            nxt_departure = cal.first_m(service_end)
            if nxt_departure is None:
                return None
            nxt_arrival = cal.add_m(nxt_departure, out_min)
            if nxt_arrival is None or nxt_arrival > nxt_timing.window_end + _EPS:
                return None
            nxt_target = nxt_arrival if nxt_arrival > nxt_timing.window_start else nxt_timing.window_start
            nxt_start = cal.first_m(nxt_target)
            if nxt_start is None:
                return None
            if nxt_start > self._latest[position] + _EPS:
                return None
            if strict and nxt_start > nxt_timing.window_end + _EPS:
                return None
            new_nxt_wait = cal.working_between_m(nxt_arrival, nxt_start)
            delta_wait = waiting + new_nxt_wait - self._wait[position]

        return InsertionCost(
            opens_new_engineer=1 if self.is_empty else 0,
            delta_travel_minutes=in_min + out_min - removed_min,
            delta_distance_km=in_km + out_km - removed_km,
            delta_waiting_minutes=delta_wait,
        )

    def best_insertion(self, request: Request) -> tuple[InsertionCost, int] | None:
        """Лучшая по стоимости допустимая позиция. Ничья разрешается меньшей позицией."""
        best: tuple[InsertionCost, int] | None = None
        for position in range(self.locked_count, len(self.stops) + 1):
            cost = self.evaluate_insertion(request, position)
            if cost is None:
                continue
            if best is None or cost < best[0]:
                best = (cost, position)
        return best

    def can_hold(self, request: Request) -> bool:
        return self.best_insertion(request) is not None

    # ------------------------------------------------------------------ изменение состава

    def insert_checked(self, request: Request, position: int) -> bool:
        """Вставляет заявку и подтверждает допустимость полным пересчётом.

        Быстрая оценка — фильтр; авторитетен прямой проход. Если он не сошёлся,
        изменение откатывается, и маршрут остаётся ровно таким, каким был.
        """
        if position < self.locked_count or position > len(self.stops):
            return False
        if not self.accepts(request):
            return False
        snapshot = self.stops[:]
        self.stops.insert(position, request)
        if self.recompute():
            return True
        self.stops = snapshot
        self.recompute()
        return False

    def remove_at(self, index: int) -> Request:
        if index < self.locked_count:
            raise ValueError("Зафиксированный визит нельзя убрать из маршрута")
        request = self.stops.pop(index)
        self.recompute()
        return request

    def remove_request(self, request_id: str) -> Request | None:
        index = self.index_of(request_id)
        if index < 0 or index < self.locked_count:
            return None
        return self.remove_at(index)

    def try_sequence(self, stops: Iterable[Request]) -> bool:
        """Пробует заменить порядок визитов. При недопустимости откатывает."""
        candidate = list(stops)
        if [r.id for r in candidate[: self.locked_count]] != [
            r.id for r in self.stops[: self.locked_count]
        ]:
            return False
        if any(not self.accepts(r) for r in candidate):
            return False
        snapshot = self.stops[:]
        self.stops = candidate
        if self.recompute():
            return True
        self.stops = snapshot
        self.recompute()
        return False

    # ------------------------------------------------------------------ диагностика

    def reject_reason(self, request: Request) -> FeasibilityResult:
        """Почему заявка не влезает именно в этот маршрут.

        Диагностика строится по самому показательному варианту — дописать заявку в конец
        маршрута: диспетчеру нужно знать не «не влезло», а когда инженер освобождается
        и во сколько он смог бы доехать.
        """
        if not self.stops:
            return FeasibilityResult(False, ReasonCode.TIME_CONFLICT, self._solo_detail(request))

        ctx = self.ctx
        cal = self.cal
        timing = ctx.timing(request)
        name = self.engineer.name
        free_at = self._end[-1]
        minutes = ctx.travel.travel_minutes(self.stops[-1].point, request.point, self.mode)
        departure = cal.first_m(free_at)
        arrival = cal.add_m(departure, minutes) if departure is not None else None

        if arrival is None:
            return FeasibilityResult(
                False,
                ReasonCode.TIME_CONFLICT,
                f"{name} освобождается в {self._end_time_text()}, и смена заканчивается "
                f"раньше, чем он успеет доехать",
            )
        if arrival > timing.window_end + _EPS:
            return FeasibilityResult(
                False,
                ReasonCode.TIME_CONFLICT,
                f"{name} освобождается в {self._end_time_text()} и доедет только к "
                f"{ctx.to_datetime(arrival):%H:%M}, а окно закрывается в "
                f"{ctx.to_datetime(timing.window_end):%H:%M}",
            )
        return FeasibilityResult(
            False,
            ReasonCode.TIME_CONFLICT,
            f"у {name} ({len(self.stops)} "
            f"{plural(len(self.stops), 'заявка', 'заявки', 'заявок')}, освобождается "
            f"в {self._end_time_text()}) не остаётся {int(timing.duration)} мин в смене",
        )

    def _solo_detail(self, request: Request) -> str:
        cal = self.cal
        ctx = self.ctx
        timing = ctx.timing(request)
        shift_start = cal.start_m
        if shift_start is None:
            return f"у {self.engineer.name} нет рабочего времени"
        minutes = ctx.travel.travel_minutes(self.engineer.start_point, request.point, self.mode)
        arrival = cal.add_m(shift_start, minutes)
        if arrival is None:
            return f"{self.engineer.name} не успевает доехать в пределах смены"
        if arrival > timing.window_end + _EPS:
            arr_dt = ctx.to_datetime(arrival)
            end_dt = ctx.to_datetime(timing.window_end)
            return (
                f"{self.engineer.name} доедет только к {arr_dt:%H:%M}, "
                f"а окно закрывается в {end_dt:%H:%M}"
            )
        return (
            f"работа длительностью {int(timing.duration)} мин не помещается "
            f"в смену {self.engineer.name}"
        )

    def _end_time_text(self) -> str:
        if not self._end:
            return "—"
        moment = self.ctx.to_datetime(self._end[-1])
        return f"{moment:%H:%M}" if moment else "—"

    # ------------------------------------------------------------------ доступ к расписанию

    def schedule_at(self, index: int) -> tuple[float, float, float, float, float, float, float]:
        """(выезд, прибытие, начало, конец, ожидание, минуты в пути, км) для визита."""
        return (
            self._dep[index],
            self._arr[index],
            self._start[index],
            self._end[index],
            self._wait[index],
            self._leg_minutes[index],
            self._leg_km[index],
        )

    def slack_m(self, index: int) -> float:
        """На сколько можно задержать начало работы, не сломав хвост маршрута.

        Берётся прямо из обратного прохода: `_latest[i]` — самый поздний допустимый
        старт визита с учётом всех последующих заявок. Разница с фактическим стартом и
        есть запас, который диспетчеру нужен как прогноз опозданий.
        """
        latest = self._latest[index]
        if latest == _NEG_INF:
            return 0.0
        return max(0.0, self.cal.working_between_m(self._start[index], latest))

    def latest_departure_m(self, index: int) -> float | None:
        """Самый поздний выезд к визиту без сдвига начала работ — подсказка диспетчеру."""
        return self.cal.sub_m(self._start[index], self._leg_minutes[index])

    @property
    def start_m(self) -> float | None:
        return self._dep[0] if self.stops else None

    @property
    def end_m(self) -> float | None:
        return self._end[-1] if self.stops else None

    @property
    def busy_minutes(self) -> float:
        return self.service_minutes + self.travel_minutes + self.waiting_minutes

    def __repr__(self) -> str:  # pragma: no cover - диагностика
        return f"RouteState({self.engineer.id}: {' → '.join(self.request_ids) or 'пусто'})"

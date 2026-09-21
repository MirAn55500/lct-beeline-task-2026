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


def schedule_leg(cal, timing, free_from: float, minutes: float, strict: bool):
    """Расписание одного визита: выезд, прибытие, начало и конец работ, ожидание.

    Возвращает `None`, если визит недопустим.

    **Выезд откладывается.** Наивный расчёт «освободился — сразу поехал» отправляет
    инженера к клиенту за два часа до открытия окна, и он стоит у подъезда. Это неверно
    и по жизни, и по отчётности: ожидание попадает в занятость, маршрут из четырёх
    заявок показывает 97 % загрузки, и диспетчер не видит, что у человека свободны часы.

    Поэтому сначала считается самое раннее возможное начало работ (оно и решает
    допустимость визита), а затем выезд откатывается назад ровно настолько, чтобы
    приехать к началу работ. Раньше, чем инженер освободился, выехать нельзя;
    позже конца окна прибыть нельзя — на этом откат и останавливается.
    """
    earliest_departure = cal.first_m(free_from)
    if earliest_departure is None:
        return None
    earliest_arrival = cal.add_m(earliest_departure, minutes)
    if earliest_arrival is None or earliest_arrival > timing.window_end + _EPS:
        return None

    not_before = timing.service_not_before
    target = earliest_arrival if earliest_arrival > not_before else not_before
    service_start = cal.first_m(target)
    if service_start is None:
        return None
    if strict and service_start > timing.window_end + _EPS:
        return None
    service_end = cal.add_m(service_start, timing.duration)
    if service_end is None:
        return None

    # Целимся прибыть к началу работ, но не позже конца окна прибытия: при выключенном
    # `service_must_start_within_window` работа может начинаться и после окна, а вот
    # приехать в него обязаны — иначе отложенный выезд сам сорвал бы окно.
    aim = service_start if service_start < timing.window_end else timing.window_end
    departure = cal.sub_m(aim, minutes)
    if departure is None or departure < earliest_departure:
        departure, arrival = earliest_departure, earliest_arrival
    else:
        arrival = cal.add_m(departure, minutes)
        if arrival is None or arrival > timing.window_end + _EPS:
            departure, arrival = earliest_departure, earliest_arrival

    waiting = cal.working_between_m(arrival, service_start)
    idle = cal.working_between_m(earliest_departure, departure)
    return departure, arrival, service_start, service_end, waiting, idle


class RouteState:
    """Изменяемое состояние маршрута. Все времена — минуты от `context.origin`."""

    __slots__ = (
        "ctx",
        "engineer",
        "cal",
        "mode",
        "stops",
        "locked_count",
        "floor_m",
        "_dep",
        "_arr",
        "_start",
        "_end",
        "_wait",
        "_idle",
        "_leg_minutes",
        "_leg_km",
        "_latest",
        "_frozen",
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
        self.floor_m: float = _NEG_INF
        """Раньше этого момента новая работа начаться не может.

        При перепланировании это «сейчас»: событие произошло в 13:00, и ставить
        освободившуюся заявку на 09:00 — значит выдать расписание задним числом.
        Замороженных визитов не касается: они уже факт.
        """
        self._frozen: list[tuple[float, float, float, float, float, float, float]] = []
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
        copy.floor_m = self.floor_m
        copy._dep = list(self._dep)
        copy._arr = list(self._arr)
        copy._start = list(self._start)
        copy._end = list(self._end)
        copy._wait = list(self._wait)
        copy._idle = list(self._idle)
        copy._leg_minutes = list(self._leg_minutes)
        copy._leg_km = list(self._leg_km)
        copy._latest = list(self._latest)
        copy._frozen = list(self._frozen)
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
            end = self._end[position - 1]
            return end if end > self.floor_m else self.floor_m
        start = self.cal.start_m
        if start is None:
            return _NEG_INF
        return start if start > self.floor_m else self.floor_m

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
        self._idle = [0.0] * n
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
            if i < self.locked_count and i < len(self._frozen):
                # Начатая работа — это факт, а не решение планировщика: её время не
                # пересчитывается. Иначе исчезновение более раннего визита сдвигало бы
                # прошлое назад, и план утверждал бы, что работа шла не тогда, когда шла.
                dep, arr, start, end, wait, minutes, km = self._frozen[i]
                self._dep[i] = dep
                self._arr[i] = arr
                self._start[i] = start
                self._end[i] = end
                self._wait[i] = wait
                self._idle[i] = 0.0
                self._leg_minutes[i] = minutes
                self._leg_km[i] = km
                self.distance_km += km
                self.travel_minutes += minutes
                self.service_minutes += ctx.timing(request).duration
                self.waiting_minutes += wait
                cursor = end
                point = request.point
                continue

            timing = ctx.timing(request)
            km, minutes = travel.both(point, request.point, mode)

            # Выехать раньше, чем наступило «сейчас», нельзя: см. `floor_m`.
            free_from = cursor if cursor > self.floor_m else self.floor_m
            leg = schedule_leg(cal, timing, free_from, minutes, strict)
            if leg is None:
                self.feasible = False
                return False
            departure, arrival, service_start, service_end, waiting, idle = leg

            self._dep[i] = departure
            self._arr[i] = arrival
            self._start[i] = service_start
            self._end[i] = service_end
            self._wait[i] = waiting
            self._idle[i] = idle
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
            if i < self.locked_count and i < len(self._frozen):
                # Начатую работу задержать уже нельзя: запас по определению нулевой.
                latest[i] = self._start[i]
                continue
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

        leg = schedule_leg(cal, timing, cursor, in_min, strict)
        if leg is None:
            return None
        _, _, service_start, service_end, waiting, _ = leg

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

            nxt_leg = schedule_leg(cal, nxt_timing, service_end, out_min, strict)
            if nxt_leg is None:
                return None
            nxt_start, new_nxt_wait = nxt_leg[2], nxt_leg[4]
            if nxt_start > self._latest[position] + _EPS:
                return None
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

        Повторная вставка уже стоящей в маршруте заявки отклоняется: одна заявка —
        один выезд. Проверка стоит обхода короткого списка, а без неё событие,
        переобъявляющее уже назначенную заявку, размножало визит.
        """
        if position < self.locked_count or position > len(self.stops):
            return False
        if self.index_of(request.id) >= 0:
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

    def adopt(
        self,
        stops: Sequence[Request],
        locked_count: int,
        frozen: Sequence[tuple[float, float, float, float, float, float, float]] = (),
    ) -> bool:
        """Принимает состав маршрута из готового плана вместе с фактами по начатым визитам.

        `frozen` — расписание locked-префикса в минутах от `ctx.origin`, взятое из
        предыдущего плана. Оно подставляется как есть: работа, которая уже идёт,
        не может «переехать» из-за того, что событие изменило остальной день.
        При недопустимости состава изменение откатывается целиком.
        """
        snapshot = (self.stops[:], self.locked_count, list(self._frozen))
        self.stops = list(stops)
        self.locked_count = max(0, min(locked_count, len(self.stops)))
        self._frozen = list(frozen)[: self.locked_count]
        if self.recompute():
            return True
        self.stops, self.locked_count, self._frozen = snapshot
        self.recompute()
        return False

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
        ctx = self.ctx
        cal = self.cal
        timing = ctx.timing(request)
        name = self.engineer.name

        # Сначала — случай «не помещается в принципе»: работа не может начаться раньше
        # окна (и поступления), а смена заканчивается раньше, чем она успеет закончиться.
        # Здесь ни загрузка, ни дорога ни при чём, и говорить про «уже запланированные
        # работы» нечестно: заявку не взять даже в совершенно пустой день.
        shift_end = cal.end_m
        if shift_end is not None:
            latest_start = cal.sub_m(shift_end, timing.duration)
            if latest_start is None or timing.service_not_before > latest_start + _EPS:
                return FeasibilityResult(
                    False,
                    ReasonCode.TIME_CONFLICT,
                    # Имя инженера намеренно не упоминается: причина общая, и одинаковые
                    # формулировки схлопнутся в одну вместо списка из десяти строк.
                    f"работа {int(timing.duration)} мин не может начаться раньше "
                    f"{ctx.to_datetime(timing.service_not_before):%H:%M}, а смена "
                    f"заканчивается в {ctx.to_datetime(shift_end):%H:%M} — "
                    f"заявка не помещается даже в пустой день",
                )

        if not self.stops:
            return FeasibilityResult(False, ReasonCode.TIME_CONFLICT, self._solo_detail(request))
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

    def schedule_at(
        self, index: int
    ) -> tuple[float, float, float, float, float, float, float, float]:
        """(выезд, прибытие, начало, конец, ожидание, простой до выезда, минуты в пути, км)."""
        return (
            self._dep[index],
            self._arr[index],
            self._start[index],
            self._end[index],
            self._wait[index],
            self._idle[index],
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

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
from typing import Iterable, NamedTuple, Sequence

from .context import PlanContext
from .cost import InsertionCost
from .enums import Priority, ReasonCode
from .feasibility import FeasibilityResult, check_static
from .models import Engineer, GeoPoint, Request
from .textutil import plural

__all__ = ["RouteState", "InsertionWindow"]


class InsertionWindow(NamedTuple):
    """Допустимое начало работ при вставке на позицию; минуты от `context.origin`."""

    earliest: float
    latest: float
    departure: float
    """Выезд к заявке при самом раннем начале."""
    travel_minutes: float
    """Дорога от предыдущей точки маршрута при самом раннем начале."""


_EPS = 1e-6
"""Допуск сравнения минут: больше, чем дают минуты↔время с микросекундами в БД (1.7e-8),
иначе визит на самом краю окна после перезагрузки плана «выпадал» из него."""
_SECOND = 1 / 60
_EMERGENCY_DELAY = 0.5
"""Насколько (мин) обычная заявка может отодвинуть аварию при автоматической вставке:
только на шум округления. Ручной ход диспетчера это правило не проверяет."""
"""Допуск для времени по профилю rRAPTOR: он хранит целые секунды, а расписание — минуты."""
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


def schedule_leg_timed(cal, timing, free_from: float, timed, a, b, mode, strict: bool):
    """То же, что `schedule_leg`, но время в пути зависит от момента выезда.

    Возвращает ещё и минуты в пути при выбранном выезде (седьмым элементом): у
    общественного транспорта они свои для каждого момента — выехав позже, можно
    попасть на тот же автобус и ждать его меньше.

    Отложенный выезд берётся прямо из профиля: `depart_by` — самый поздний выезд,
    при котором успеваем к началу работ. Перерывы профиль не видит, поэтому выезд
    проверяется календарём, и если прибытие с ним не сходится — выезжаем сразу.
    """
    earliest_departure = cal.first_m(free_from)
    if earliest_departure is None:
        return None
    first_minutes = timed.minutes_at(a, b, mode, earliest_departure)
    earliest_arrival = cal.add_m(earliest_departure, first_minutes)
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

    aim = service_start if service_start < timing.window_end else timing.window_end
    departure, arrival, minutes = earliest_departure, earliest_arrival, first_minutes
    later = cal.first_m(timed.depart_by(a, b, mode, aim))
    if later is not None and later > earliest_departure + _EPS:
        later_minutes = timed.minutes_at(a, b, mode, later)
        later_arrival = cal.add_m(later, later_minutes)
        if later_arrival is not None and later_arrival <= aim + _SECOND:
            departure, arrival, minutes = later, later_arrival, later_minutes

    waiting = cal.working_between_m(arrival, service_start)
    idle = cal.working_between_m(earliest_departure, departure)
    return departure, arrival, service_start, service_end, waiting, idle, minutes


def latest_departure_timed(cal, timed, a, b, mode, arrive_by: float) -> float | None:
    """Самый поздний выезд из `a`, чтобы быть в `b` не позже `arrive_by`, с учётом календаря."""
    depart = timed.depart_by(a, b, mode, arrive_by)
    minutes = timed.minutes_at(a, b, mode, depart)
    arrival = cal.add_m(depart, minutes)
    if arrival is not None and arrival <= arrive_by + _SECOND and cal.contains_m(depart):
        return depart
    # Между выездом и прибытием перерыв: время по профилю — но отсчёт по календарю.
    return cal.sub_m(arrive_by, minutes)


class RouteState:
    """Изменяемое состояние маршрута. Все времена — минуты от `context.origin`."""

    __slots__ = (
        "ctx",
        "engineer",
        "cal",
        "mode",
        "timed",
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
        "lunch",
        "lunch_fact",
        "lunch_gap",
        "_lunch",
        "_lunch_point",
        "_lunch_latest",
        "lunch_shift_allowed",
        "feasible",
        "distance_km",
        "travel_minutes",
        "service_minutes",
        "waiting_minutes",
        "emergency_minutes",
        "_last_emergency",
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
        self.timed = ctx.timed_for(self.mode)
        """Модель со временем от момента выезда (общественный транспорт) или None."""
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
        self.lunch = ctx.lunch(engineer)
        """Обед инженера (окно начала в минутах и где обедать) или None."""
        self.lunch_fact: tuple[float, float, float, float, float, float, float] | None = None
        """Обед, который уже начался: (выезд, прибытие, начало, конец, ожидание, минуты
        в пути, км). Как и начатые визиты, он факт и не пересчитывается."""
        self.lunch_shift_allowed = False
        """Может ли авария сдвинуть обед за окно. Только когда без сдвига её не поставить
        (`construct.place_shifting_lunch`), в сохранённом плане со сдвигом и на Ганте:
        иначе оптимизатор раздвигал бы обеды ради пары лишних обычных заявок."""
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
        copy.timed = self.timed
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
        copy.lunch = self.lunch
        copy.lunch_fact = self.lunch_fact
        copy.lunch_gap = self.lunch_gap
        copy._lunch = self._lunch
        copy._lunch_point = self._lunch_point
        copy._lunch_latest = self._lunch_latest
        copy.lunch_shift_allowed = self.lunch_shift_allowed
        copy.feasible = self.feasible
        copy.distance_km = self.distance_km
        copy.travel_minutes = self.travel_minutes
        copy.service_minutes = self.service_minutes
        copy.waiting_minutes = self.waiting_minutes
        copy.emergency_minutes = self.emergency_minutes
        copy._last_emergency = self._last_emergency
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

    def recompute(self, lunch_gap: int | None = None) -> bool:
        """Пересчитывает расписание с нуля. Возвращает допустимость маршрута.

        Обед — в своём окне. Только если с ним маршрут не сходится, а в маршруте есть
        авария, окно обеда раздвигается (`PlanContext.lunch_shifted`): авария важнее обеда
        по расписанию. Сдвиг не держится — каждый пересчёт сначала пробует обычное окно.
        """
        lunch = self.lunch
        if lunch is not None and lunch.shifted:
            lunch = self.lunch = self.ctx.lunch(self.engineer)
        if self._recompute(lunch_gap):
            return True
        if lunch is None or self.lunch_fact is not None or not self.lunch_shift_allowed:
            return False
        if not any(r.priority is Priority.EMERGENCY for r in self.stops):
            return False
        shifted = self.ctx.lunch_shifted(self.engineer)
        if shifted is None:
            return False
        self.lunch = shifted
        if self._recompute(lunch_gap):
            return True
        self.lunch = lunch
        self._recompute(lunch_gap)
        return False

    def _recompute(self, lunch_gap: int | None = None) -> bool:
        """`recompute` с тем обедом, что сейчас в `self.lunch`.

        Обед — не заявка и в `stops` не входит: операторы поиска его не видят и увезти
        к другому инженеру не могут. Место обеда выбирается здесь, при каждом пересчёте:
        между какими визитами он меньше всего удлиняет день, при равенстве — где визиты
        раньше. Поэтому любая перестановка заявок сама переносит обед туда, где ему
        теперь лучше. `lunch_gap` — место обеда из сохранённого плана: если он там ещё
        сходится, он там и остаётся.
        """
        n = len(self.stops)
        self.lunch_gap = None
        self._lunch = None
        self._lunch_point = None
        self._lunch_latest = _NEG_INF
        self._store([])
        if n == 0:
            self.feasible = True
            return True

        shift_start = self.cal.start_m
        if shift_start is None:
            self.feasible = False
            return False
        start_point = self.engineer.start_point

        lunch = self.lunch
        if lunch is not None and self.lunch_fact is None:
            base = self._forward(0, shift_start, start_point, None)
            if base is None:
                # Без обеда не сходится — с обедом, который только отнимает время, тоже.
                self.feasible = False
                return False
            gaps = self._lunch_gaps(base[0], shift_start)
            if gaps is None:
                # Окно обеда прошло раньше, чем инженер освободился от начатого: обед
                # уже не поставить, а прошлое из-за него не переписывается.
                self._store(base[0])
                self._recompute_slack()
                self.feasible = True
                return True
            if lunch.shifted:
                # Сдвинутый обед — только вплотную к аварии: авария его и сдвинула. Иначе
                # оптимизатор раздвигал бы обед ради обычных заявок маршрута
                near = {i for i, r in enumerate(self.stops) if r.priority is Priority.EMERGENCY}
                gaps = [[g for g in group if g in near or g - 1 in near] for group in gaps]
            chosen = None
            # Сохранённое место — первым и вне конкурса: иначе при равных вариантах версия
            # плана восстанавливалась бы с обедом в другом месте и визитами в другое время
            order = [[lunch_gap]] if lunch_gap is not None and any(lunch_gap in g for g in gaps) else []
            for group in order + gaps:
                for gap in group:
                    cursor = base[0][gap - 1][3] if gap > 0 else shift_start
                    point = self.stops[gap - 1].point if gap > 0 else start_point
                    tail = self._forward(gap, cursor, point, gap)
                    if tail is None:
                        continue
                    legs = base[0][:gap] + tail[0]
                    lunch_leg = tail[1]
                    finish = max(legs[-1][3], lunch_leg[3])
                    score = (
                        self.lunch_shift_minutes(lunch_leg[2]),
                        # Обед не встаёт перед аварией, если может встать после неё
                        self._emergency_starts(legs),
                        sum(leg[6] for leg in legs) + lunch_leg[6],
                        finish,
                        sum(leg[2] for leg in legs),
                    )
                    if chosen is None or score < chosen[0]:
                        chosen = (score, gap, legs, lunch_leg, tail[2])
                if chosen is not None:
                    break
            if chosen is None:
                self.feasible = False
                return False
            _, gap, legs, lunch_leg, lunch_point = chosen
        else:
            gap = self._fact_gap() if lunch is not None else None
            run = self._forward(0, shift_start, start_point, gap)
            if run is None:
                self.feasible = False
                return False
            legs, lunch_leg, lunch_point = run

        self._store(legs)
        if lunch_leg is not None:
            self.lunch_gap = gap
            self._lunch = lunch_leg
            self._lunch_point = lunch_point
            self.distance_km += lunch_leg[7]
            self.travel_minutes += lunch_leg[6]
            self.waiting_minutes += lunch_leg[4]
        self._recompute_slack()
        self.feasible = True
        return True

    def lunch_shift_minutes(self, start: float) -> float:
        """На сколько минут начало обеда ушло за его обычное окно: 0 без сдвига аварией.

        Сдвинутый обед ставится как можно ближе к своему окну, а не туда, где короче день.
        """
        if self.lunch is None:
            return 0.0
        # По обычному окну, а не по тому, с которым считали: начатый обед (факт) после
        # сдвига аварией тоже вне окна, хотя пересчитывается уже без сдвига
        normal = self.ctx.lunch(self.engineer)
        if normal is None:
            return 0.0
        return max(0.0, normal.timing.window_start - start, start - normal.timing.window_end)

    def _store(self, legs) -> None:
        """Расписание визитов — в массивы маршрута, и итоги по нему."""
        self._dep = [leg[0] for leg in legs]
        self._arr = [leg[1] for leg in legs]
        self._start = [leg[2] for leg in legs]
        self._end = [leg[3] for leg in legs]
        self._wait = [leg[4] for leg in legs]
        self._idle = [leg[5] for leg in legs]
        self._leg_minutes = [leg[6] for leg in legs]
        self._leg_km = [leg[7] for leg in legs]
        self._latest = [_NEG_INF] * len(legs)
        self.distance_km = sum(self._leg_km)
        self.travel_minutes = sum(self._leg_minutes)
        self.waiting_minutes = sum(self._wait)
        timing = self.ctx.timing
        self.service_minutes = sum(timing(r).duration for r in self.stops[: len(legs)])
        self.emergency_minutes = self._emergency_starts(legs)
        self._last_emergency = max(
            (i for i, r in enumerate(self.stops[: len(legs)]) if r.priority is Priority.EMERGENCY),
            default=-1,
        )

    def _emergency_starts(self, legs) -> float:
        """Сумма начал аварий маршрута, минуты: чем меньше, тем раньше их устраняют."""
        stops = self.stops
        return sum(leg[2] for i, leg in enumerate(legs) if stops[i].priority is Priority.EMERGENCY)

    def _forward(self, begin: int, cursor: float, point: GeoPoint, lunch_gap: int | None):
        """Прямой проход с визита `begin`: инженер свободен с `cursor` в точке `point`.

        `lunch_gap` — перед каким визитом обедать (`len(stops)` — после последнего).
        Возвращает (расписания визитов с `begin`, расписание обеда, где обедал) или None,
        если маршрут недопустим. Расписание визита — (выезд, прибытие, начало, конец,
        ожидание, простой до выезда, минуты в пути, км).
        """
        cal = self.cal
        ctx = self.ctx
        travel = ctx.travel
        mode = self.mode
        strict = ctx.settings.service_must_start_within_window
        stops = self.stops
        n = len(stops)
        legs: list[tuple[float, float, float, float, float, float, float, float]] = []
        lunch_leg = None
        lunch_point = None

        for i in range(begin, n):
            if i == lunch_gap:
                taken = self._lunch_leg(cursor, point)
                if taken is None:
                    return None
                lunch_leg, lunch_point = taken
                cursor = lunch_leg[3]
                point = lunch_point
            request = stops[i]
            if i < self.locked_count and i < len(self._frozen):
                # Начатая работа — это факт, а не решение планировщика: её время не
                # пересчитывается. Иначе исчезновение более раннего визита сдвигало бы
                # прошлое назад, и план утверждал бы, что работа шла не тогда, когда шла.
                dep, arr, start, end, wait, minutes, km = self._frozen[i]
                legs.append((dep, arr, start, end, wait, 0.0, minutes, km))
                cursor = end
                point = request.point
                continue

            timing = ctx.timing(request)
            # Выехать раньше, чем наступило «сейчас», нельзя: см. `floor_m`.
            free_from = cursor if cursor > self.floor_m else self.floor_m
            if self.timed is None:
                km, minutes = travel.both(point, request.point, mode)
                leg = schedule_leg(cal, timing, free_from, minutes, strict)
            else:
                km = travel.distance_km(point, request.point, mode)
                leg = schedule_leg_timed(
                    cal, timing, free_from, self.timed, point, request.point, mode, strict
                )
            if leg is None:
                return None
            if self.timed is not None:
                minutes = leg[6]
            legs.append((leg[0], leg[1], leg[2], leg[3], leg[4], leg[5], minutes, km))
            cursor = leg[3]
            point = request.point

        if lunch_gap == n:
            taken = self._lunch_leg(cursor, point)
            if taken is None:
                return None
            lunch_leg, lunch_point = taken
        return legs, lunch_leg, lunch_point

    def _lunch_leg(self, cursor: float, point: GeoPoint):
        """Обед, когда инженер свободен с `cursor` в точке `point`: (расписание, где обедал).

        Расписание — как у визита: (выезд, прибытие, начало, конец, ожидание, простой до
        выезда, минуты в пути, км). Обед начинается как можно раньше в своём окне —
        так остаток дня свободнее всего. None — обед здесь не помещается.
        """
        lunch = self.lunch
        assert lunch is not None
        target = lunch.point if lunch.point is not None else point
        if self.lunch_fact is not None:
            dep, arr, start, end, wait, minutes, km = self.lunch_fact
            return (dep, arr, start, end, wait, 0.0, minutes, km), target
        cal = self.cal
        free_from = cursor if cursor > self.floor_m else self.floor_m
        if lunch.point is None:
            km = minutes = 0.0
            leg = schedule_leg(cal, lunch.timing, free_from, 0.0, True)
        elif self.timed is None:
            km, minutes = self.ctx.travel.both(point, target, self.mode)
            leg = schedule_leg(cal, lunch.timing, free_from, minutes, True)
        else:
            km = self.ctx.travel.distance_km(point, target, self.mode)
            leg = schedule_leg_timed(
                cal, lunch.timing, free_from, self.timed, point, target, self.mode, True
            )
            if leg is not None:
                minutes = leg[6]
        if leg is None:
            return None
        return (leg[0], leg[1], leg[2], leg[3], leg[4], leg[5], minutes, km), target

    def _lunch_gaps(self, base, shift_start: float) -> list[list[int]] | None:
        """Где пробовать обед: сначала места, перекрывающие окно обеда, затем остальные.

        `base` — расписание без обеда. Место перед визитом, который целиком кончается до
        открытия окна обеда, заведомо не лучше места после него: обед начнётся в то же
        время, а визит будет сделан раньше. Такие места — запасные. Места, где инженер
        освобождается уже после последнего допустимого начала обеда, не годятся вовсе.

        None — обед уже не поставить: инженер освобождается от начатого слишком поздно.
        """
        timing = self.lunch.timing
        n = len(self.stops)
        low = min(self.locked_count, n)

        def free(gap: int) -> float:
            moment = base[gap - 1][3] if gap > 0 else shift_start
            return moment if moment > self.floor_m else self.floor_m

        if free(low) > timing.window_end + _EPS:
            return None
        primary: list[int] = []
        spare: list[int] = []
        for gap in range(low, n + 1):
            if free(gap) > timing.window_end + _EPS:
                break
            if gap < n and base[gap][3] <= timing.window_start + _EPS:
                spare.append(gap)
            else:
                primary.append(gap)
        return [primary, spare]

    def _fact_gap(self) -> int:
        """Место начатого обеда: после начатых визитов, работа по которым началась раньше обеда.

        По началу работ, а не по концу визита и выезду на обед: времена в БД хранятся с
        разной точностью (выезд на обед — до секунды, конец визита — с долями), и визит,
        кончившийся в 17:04:31.32, оказывался «после» обеда с выездом в 17:04:31. Обед
        тогда вставал перед этим визитом, а следующая заявка — поверх начатого обеда.
        """
        fact = self.lunch_fact
        assert fact is not None
        gap = 0
        for i in range(min(self.locked_count, len(self._frozen), len(self.stops))):
            if self._frozen[i][2] < fact[2]:
                gap = i + 1
            else:
                break
        return gap

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

        # Обед, который ещё не начался, держит визит перед собой: после визита нужно успеть
        # доехать до места обеда, начать обед в его окне и после обеда успеть к следующему
        # визиту. Начатый обед — факт, визиты до него заморожены.
        gap = self.lunch_gap if self._lunch is not None and self.lunch_fact is None else None
        latest = self._latest
        for i in range(n - 1, -1, -1):
            request = self.stops[i]
            timing = ctx.timing(request)
            if i < self.locked_count and i < len(self._frozen):
                # Начатую работу задержать уже нельзя: запас по определению нулевой.
                latest[i] = self._start[i]
                continue
            if gap is not None and i == gap - 1:
                self._lunch_latest = self._lunch_latest_start(gap)
                depart = self._latest_departure_to_lunch(request.point, self._lunch_latest)
                bound = None if depart is None else cal.sub_m(depart, timing.duration)
                if bound is not None and i == n - 1:
                    last = cal.sub_m(shift_end, timing.duration)
                    bound = None if last is None else min(bound, last)
            elif i == n - 1:
                bound = cal.sub_m(shift_end, timing.duration)
            else:
                nxt = self.stops[i + 1]
                if self.timed is None:
                    leg = travel.travel_minutes(request.point, nxt.point, mode)
                    latest_departure = cal.sub_m(latest[i + 1], leg)
                elif latest[i + 1] == _NEG_INF:
                    latest_departure = None
                else:
                    latest_departure = latest_departure_timed(
                        cal, self.timed, request.point, nxt.point, mode, latest[i + 1]
                    )
                bound = None if latest_departure is None else cal.sub_m(latest_departure, timing.duration)
            if bound is None:
                latest[i] = _NEG_INF
            else:
                latest[i] = bound if bound < timing.window_end else timing.window_end
        if gap is not None:
            # И когда визит перед обедом уже начат (цикл его пропустил): иначе окна
            # «до обеда» пропадали бы, хотя успеть что-то до обеда ещё можно
            self._lunch_latest = self._lunch_latest_start(gap)

    def _lunch_latest_start(self, gap: int) -> float:
        """Самое позднее начало обеда перед визитом `gap`, при котором хвост ещё сходится."""
        cal = self.cal
        timing = self.lunch.timing
        if gap >= len(self.stops):
            bound = cal.sub_m(cal.end_m, timing.duration) if cal.end_m is not None else None
        else:
            latest_next = self._latest[gap]
            if latest_next == _NEG_INF:
                return _NEG_INF
            here, nxt = self._lunch_point, self.stops[gap].point
            if self.timed is None:
                minutes = self.ctx.travel.travel_minutes(here, nxt, self.mode)
                depart = cal.sub_m(latest_next, minutes)
            else:
                depart = latest_departure_timed(cal, self.timed, here, nxt, self.mode, latest_next)
            bound = None if depart is None else cal.sub_m(depart, timing.duration)
        if bound is None:
            return _NEG_INF
        return bound if bound < timing.window_end else timing.window_end

    def _latest_departure_to_lunch(self, origin: GeoPoint, lunch_latest: float) -> float | None:
        """Самый поздний выезд из `origin`, чтобы начать обед не позже `lunch_latest`."""
        if lunch_latest == _NEG_INF:
            return None
        target = self.lunch.point
        if target is None:
            return lunch_latest
        if self.timed is None:
            minutes = self.ctx.travel.travel_minutes(origin, target, self.mode)
            return self.cal.sub_m(lunch_latest, minutes)
        return latest_departure_timed(self.cal, self.timed, origin, target, self.mode, lunch_latest)

    # ------------------------------------------------------------------ оценка вставки

    def evaluate_insertion(self, request: Request, position: int) -> InsertionCost | None:
        """Быстрая оценка вставки заявки перед визитом `position`.

        Возвращает стоимость либо `None`, если вставка недопустима. Проверка
        оптимистична на границах перерывов, поэтому фактическая вставка всегда
        подтверждается полным пересчётом (`insert_checked`).

        Рядом с обедом (и в пустом маршруте, где обеда ещё нет) быстрой оценки нет:
        заявка может встать и до обеда, и после, а обед — переехать на другое место.
        Там маршрут пересчитывается честно, это одна позиция из всех.
        """
        if position < self.locked_count or position > len(self.stops):
            return None
        if not self.feasible or not self.accepts(request):
            return None
        if (self.lunch is not None and (self.is_empty or position == self.lunch_gap)) or (
            position <= self._last_emergency
        ):
            # Перед аварией — полным пересчётом: сдвиг доходит до неё через весь хвост
            cost = self._evaluate_exact(request, position)
        else:
            cost = self._evaluate_between(
                request, position, self._point_before(position), self._time_before(position)
            )
        if (
            cost is not None
            and request.priority is not Priority.EMERGENCY
            and cost.delta_emergency_minutes > _EMERGENCY_DELAY
        ):
            return None  # обычная работа аварию не отодвигает
        return cost

    def _evaluate_between(
        self, request: Request, position: int, prev_point: GeoPoint, cursor: float
    ) -> InsertionCost | None:
        """Вставка перед визитом `position`, если инженер свободен с `cursor` в `prev_point`."""
        cal = self.cal
        ctx = self.ctx
        travel = ctx.travel
        mode = self.mode
        strict = ctx.settings.service_must_start_within_window
        timing = ctx.timing(request)

        if cursor == _NEG_INF:
            return None

        timed = self.timed
        if timed is None:
            in_km, in_min = travel.both(prev_point, request.point, mode)
            leg = schedule_leg(cal, timing, cursor, in_min, strict)
        else:
            in_km = travel.distance_km(prev_point, request.point, mode)
            leg = schedule_leg_timed(cal, timing, cursor, timed, prev_point, request.point, mode, strict)
        if leg is None:
            return None
        _, _, service_start, service_end, waiting, _ = leg[:6]
        if timed is not None:
            in_min = leg[6]

        emergency = service_start if request.priority is Priority.EMERGENCY else 0.0
        if position == len(self.stops):
            out_km = out_min = 0.0
            removed_km = removed_min = 0.0
            delta_wait = waiting
        else:
            nxt = self.stops[position]
            nxt_timing = ctx.timing(nxt)
            removed_km = self._leg_km[position]
            removed_min = self._leg_minutes[position]
            if timed is None:
                out_km, out_min = travel.both(request.point, nxt.point, mode)
                nxt_leg = schedule_leg(cal, nxt_timing, service_end, out_min, strict)
            else:
                out_km = travel.distance_km(request.point, nxt.point, mode)
                nxt_leg = schedule_leg_timed(
                    cal, nxt_timing, service_end, timed, request.point, nxt.point, mode, strict
                )
                if nxt_leg is not None:
                    out_min = nxt_leg[6]
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
            delta_emergency_minutes=emergency,
        )

    def _evaluate_exact(self, request: Request, position: int) -> InsertionCost | None:
        """Оценка вставки полным пересчётом; маршрут после неё остаётся ровно прежним."""
        saved = self._save()
        opens = 1 if self.is_empty else 0
        travel_before, km_before, wait_before, emergency_before = (
            self.travel_minutes, self.distance_km, self.waiting_minutes, self.emergency_minutes
        )
        self.stops.insert(position, request)
        try:
            ok = self.recompute()
            after = (
                self.travel_minutes, self.distance_km, self.waiting_minutes, self.emergency_minutes
            )
        finally:
            self.stops.pop(position)
            self._restore(saved)
        if not ok:
            return None
        return InsertionCost(
            opens_new_engineer=opens,
            delta_travel_minutes=after[0] - travel_before,
            delta_distance_km=after[1] - km_before,
            delta_waiting_minutes=after[2] - wait_before,
            delta_emergency_minutes=after[3] - emergency_before,
        )

    def _save(self) -> tuple:
        # `recompute` заводит новые списки, а не правит старые, — хватает ссылок.
        return (
            self._dep, self._arr, self._start, self._end, self._wait, self._idle,
            self._leg_minutes, self._leg_km, self._latest, self.feasible,
            self.distance_km, self.travel_minutes, self.service_minutes, self.waiting_minutes,
            self.lunch_gap, self._lunch, self._lunch_point, self._lunch_latest,
            # Пробный пересчёт мог сменить окно обеда (сдвиг аварией) — оно тоже часть состояния
            self.lunch, self.emergency_minutes, self._last_emergency,
        )

    def _restore(self, saved: tuple) -> None:
        (
            self._dep, self._arr, self._start, self._end, self._wait, self._idle,
            self._leg_minutes, self._leg_km, self._latest, self.feasible,
            self.distance_km, self.travel_minutes, self.service_minutes, self.waiting_minutes,
            self.lunch_gap, self._lunch, self._lunch_point, self._lunch_latest,
            self.lunch, self.emergency_minutes, self._last_emergency,
        ) = saved

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

    def insertion_window(self, request: Request, position: int) -> InsertionWindow | None:
        """Когда можно начать работу по заявке, вставленной перед визитом `position`.

        Нужна ручной постановке на Ганте: диспетчер выбирает не позицию, а время.
        Раньше `earliest` инженер не доедет от предыдущего визита, позже `latest` —
        сорвётся хвост маршрута (следующие окна, смена) или окно самой заявки.
        Следующие визиты при этом могут сдвинуться позже в пределах своего запаса.

        Одним окном — от самого раннего из вариантов до самого позднего; сами варианты
        (до обеда и после) отдаёт `insertion_windows`.

        Как и `evaluate_insertion`, оценка оптимистична на границах перерывов:
        окончательно ход подтверждает `insert_checked`.
        """
        options = self.insertion_windows(request, position)
        if not options:
            return None
        first = min(options, key=lambda w: w.earliest)
        return InsertionWindow(
            first.earliest, max(w.latest for w in options), first.departure, first.travel_minutes
        )

    def insertion_windows(self, request: Request, position: int) -> list[InsertionWindow]:
        """Окна начала работ при вставке перед визитом `position` — по вариантам.

        На месте обеда (и в пустом маршруте, где обед встанет вместе с первой заявкой)
        заявка встаёт либо до обеда, либо после него — это два отдельных окна. Слить их
        в одно нельзя: между ними время, в которое заявка не встанет никак, а Гант
        подсвечивал бы его как свободное.
        """
        if position < self.locked_count or position > len(self.stops):
            return []
        if not self.feasible or not self.accepts(request):
            return []
        if self.lunch is not None and self.is_empty:
            shift_start = self.cal.start_m
            if shift_start is None:
                return []
            if self.lunch_fact is not None:
                # Обед уже идёт: заявка — только после него
                leg, where = self._lunch_leg(shift_start, self.engineer.start_point)
                after = self._window_from(request, position, where, max(leg[3], self.floor_m))
                return [after] if after is not None else []
            if max(shift_start, self.floor_m) > self.lunch.timing.window_end + _EPS:
                # Окно обеда прошло, а заявок не было: обеда в этот день уже не будет
                window = self._window_from(
                    request, position, self.engineer.start_point, self._time_before(position)
                )
                return [window] if window is not None else []
            after = None
            taken = self._lunch_leg(shift_start, self.engineer.start_point)
            if taken is not None:
                leg, where = taken
                after = self._window_from(request, position, where, max(leg[3], self.floor_m))
            before = self._window_before_lunch(request, position)
            return [w for w in (before, after) if w is not None]
        if self._lunch is None or position != self.lunch_gap:
            window = self._window_from(
                request, position, self._point_before(position), self._time_before(position)
            )
            return [window] if window is not None else []

        lunch_end = self._lunch[3]
        after = self._window_from(
            request, position, self._lunch_point,
            lunch_end if lunch_end > self.floor_m else self.floor_m,
        )
        before = None if self.lunch_fact is not None else self._window_before_lunch(request, position)
        return [w for w in (before, after) if w is not None]

    def without_lunch(self) -> "RouteState | None":
        """Тот же маршрут, расписанный без обеда, — для окон «обед сразу после новой заявки».

        Обед у последней заявки переезжает к новой заявке, а в своё место (офис, точка)
        едут прямо от неё: такого места обеда в маршруте до вставки ещё нет, и ни один
        вариант с обедом между прежними визитами его не покажет. None — обеда нет или он
        уже начат (тогда он остаётся где есть).
        """
        if self.lunch is None or self.lunch_fact is not None or self.is_empty:
            return None
        free = self.clone()
        lunch = free.lunch
        free.lunch = None
        feasible = free.recompute()
        free.lunch = lunch
        if not feasible:
            return None
        free._lunch_point = lunch.point
        return free

    def window_lunch_after(self, request: Request, position: int) -> InsertionWindow | None:
        """Окно заявки перед визитом `position`, если обед — сразу после неё.

        Вызывается у маршрута из `without_lunch`: визиты до заявки идут без обеда, после
        заявки — обед, за ним остальные визиты со своим запасом.
        """
        if position < self.locked_count or position > len(self.stops):
            return None
        if not self.feasible or not self.accepts(request) or self.lunch is None:
            return None
        if self.lunch.point is not None:
            self._lunch_latest = self._lunch_latest_start(position)
        return self._window_before_lunch(request, position)

    def _arrival(self, request: Request, prev_point: GeoPoint, cursor: float):
        """(выезд, самое раннее начало работ, минуты в пути) от `prev_point` с `cursor`."""
        if cursor == _NEG_INF:
            return None
        strict = self.ctx.settings.service_must_start_within_window
        timing = self.ctx.timing(request)
        if self.timed is None:
            minutes = self.ctx.travel.travel_minutes(prev_point, request.point, self.mode)
            leg = schedule_leg(self.cal, timing, cursor, minutes, strict)
        else:
            leg = schedule_leg_timed(
                self.cal, timing, cursor, self.timed, prev_point, request.point, self.mode, strict
            )
        if leg is None:
            return None
        if self.timed is not None:
            minutes = leg[6]
        return leg[0], leg[2], minutes

    def _window_from(
        self, request: Request, position: int, prev_point: GeoPoint, cursor: float
    ) -> InsertionWindow | None:
        arrival = self._arrival(request, prev_point, cursor)
        if arrival is None:
            return None
        departure, earliest, minutes = arrival
        cal = self.cal
        timing = self.ctx.timing(request)

        if position == len(self.stops):
            shift_end = cal.end_m
            bound = None if shift_end is None else cal.sub_m(shift_end, timing.duration)
        else:
            latest_next = self._latest[position]
            if latest_next == _NEG_INF:
                return None
            nxt = self.stops[position]
            if self.timed is None:
                out = self.ctx.travel.travel_minutes(request.point, nxt.point, self.mode)
                latest_departure = cal.sub_m(latest_next, out)
            else:
                latest_departure = latest_departure_timed(
                    cal, self.timed, request.point, nxt.point, self.mode, latest_next
                )
            bound = None if latest_departure is None else cal.sub_m(latest_departure, timing.duration)
        if bound is None:
            return None
        latest = bound if bound < timing.window_end else timing.window_end
        if latest < earliest - _EPS:
            return None
        return InsertionWindow(earliest, latest, departure, minutes)

    def _window_before_lunch(self, request: Request, position: int) -> InsertionWindow | None:
        """Заявка перед обедом: после неё ещё нужно успеть пообедать и доехать дальше."""
        arrival = self._arrival(request, self._point_before(position), self._time_before(position))
        if arrival is None:
            return None
        departure, earliest, minutes = arrival
        cal = self.cal
        lunch = self.lunch
        timing = self.ctx.timing(request)
        if lunch.point is None:
            # Обед переедет к этой заявке — и дорога после обеда начнётся отсюда же.
            if position == len(self.stops):
                end = cal.end_m
                lunch_latest = None if end is None else cal.sub_m(end, lunch.timing.duration)
            else:
                latest_next = self._latest[position]
                nxt = self.stops[position].point
                if latest_next == _NEG_INF:
                    depart = None
                elif self.timed is None:
                    out = self.ctx.travel.travel_minutes(request.point, nxt, self.mode)
                    depart = cal.sub_m(latest_next, out)
                else:
                    depart = latest_departure_timed(
                        cal, self.timed, request.point, nxt, self.mode, latest_next
                    )
                lunch_latest = None if depart is None else cal.sub_m(depart, lunch.timing.duration)
            if lunch_latest is None:
                return None
            lunch_latest = min(lunch_latest, lunch.timing.window_end)
        else:
            # В пустом маршруте обеда ещё нет: после заявки — только конец смены
            lunch_latest = self._lunch_latest if not self.is_empty else self._lunch_latest_start(0)
        # Раньше своего окна обед не начнётся, как рано ни кончи заявку: если к открытию
        # окна уже поздно — после обеда хвост не успеть
        if lunch_latest < lunch.timing.window_start - _EPS:
            return None
        depart = self._latest_departure_to_lunch(request.point, lunch_latest)
        bound = None if depart is None else cal.sub_m(depart, timing.duration)
        if bound is None:
            return None
        latest = bound if bound < timing.window_end else timing.window_end
        if latest < earliest - _EPS:
            return None
        return InsertionWindow(earliest, latest, departure, minutes)

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
        lunch_fact: tuple[float, float, float, float, float, float, float] | None = None,
        lunch_gap: int | None = None,
    ) -> bool:
        """Принимает состав маршрута из готового плана вместе с фактами по начатым визитам.

        `frozen` — расписание locked-префикса в минутах от `ctx.origin`, взятое из
        предыдущего плана. Оно подставляется как есть: работа, которая уже идёт,
        не может «переехать» из-за того, что событие изменило остальной день.
        `lunch_fact` — так же подставляемый обед, если он уже начался (см. `lunch_fact`).
        `lunch_gap` — место ещё не начатого обеда в плане (см. `recompute`).
        При недопустимости состава изменение откатывается целиком.
        """
        snapshot = (self.stops[:], self.locked_count, list(self._frozen), self.lunch_fact)
        self.stops = list(stops)
        self.locked_count = max(0, min(locked_count, len(self.stops)))
        self._frozen = list(frozen)[: self.locked_count]
        self.lunch_fact = lunch_fact if self.lunch is not None else None
        if self.recompute(lunch_gap):
            return True
        self.stops, self.locked_count, self._frozen, self.lunch_fact = snapshot
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
        if timing.window_end + _EPS < free_at:
            # Окно клиента закрывается раньше, чем кончается день инженера: про «освобождается
            # в 21:32» говорить нечестно — мешает то, чем он занят именно в это окно
            busy = self._busy_text(timing.window_start, cal.add_m(timing.window_end, timing.duration))
            if busy:
                return FeasibilityResult(
                    False,
                    ReasonCode.TIME_CONFLICT,
                    f"в окне {ctx.to_datetime(timing.window_start):%H:%M}–"
                    f"{ctx.to_datetime(timing.window_end):%H:%M} {name} занят: {busy}",
                )
        departure = cal.first_m(free_at)
        minutes = self._minutes_from(self.stops[-1].point, request.point, departure)
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

    def _busy_text(self, since: float, until: float | None) -> str:
        """Что занимает инженера между `since` и `until`: работы (с дорогой к ним) и обед."""
        until = until if until is not None else math.inf
        ctx = self.ctx
        items: list[tuple[float, str]] = []
        for i, stop in enumerate(self.stops):
            if self._dep[i] < until - _EPS and self._end[i] > since + _EPS:
                items.append((
                    self._start[i],
                    f"заявка {stop.id} {ctx.to_datetime(self._start[i]):%H:%M}–"
                    f"{ctx.to_datetime(self._end[i]):%H:%M}",
                ))
        if self._lunch is not None and self._lunch[0] < until - _EPS and self._lunch[3] > since + _EPS:
            items.append((
                self._lunch[2],
                f"обед {ctx.to_datetime(self._lunch[2]):%H:%M}–{ctx.to_datetime(self._lunch[3]):%H:%M}",
            ))
        items.sort()
        text = ", ".join(label for _, label in items[:3])
        return text + (" и другие" if len(items) > 3 else "")

    def _solo_detail(self, request: Request) -> str:
        cal = self.cal
        ctx = self.ctx
        timing = ctx.timing(request)
        shift_start = cal.start_m
        if shift_start is None:
            return f"у {self.engineer.name} нет рабочего времени"
        minutes = self._minutes_from(self.engineer.start_point, request.point, shift_start)
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
        if self.lunch is not None:
            # Доехать успевает, смены хватает — значит, мешает обед
            lunch = self.lunch.timing
            return (
                f"у {self.engineer.name} обед {ctx.to_datetime(lunch.window_start):%H:%M}–"
                f"{ctx.to_datetime(lunch.window_end + lunch.duration):%H:%M}: работа "
                f"{int(timing.duration)} мин с окном {ctx.to_datetime(timing.window_start):%H:%M}–"
                f"{ctx.to_datetime(timing.window_end):%H:%M} не помещается ни до, ни после него"
            )
        return (
            f"работа длительностью {int(timing.duration)} мин не помещается "
            f"в смену {self.engineer.name}"
        )

    def _minutes_from(self, a: GeoPoint, b: GeoPoint, depart: float | None) -> float:
        """Минуты в пути при выезде в `depart` — для текстов диагностики."""
        if self.timed is not None and depart is not None:
            return self.timed.minutes_at(a, b, self.mode, depart)
        return self.ctx.travel.travel_minutes(a, b, self.mode)

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
        if not self.stops:
            return None
        if self._lunch is not None and self.lunch_gap == 0:
            return min(self._lunch[0], self._dep[0])
        return self._dep[0]

    @property
    def end_m(self) -> float | None:
        if not self.stops:
            return None
        if self._lunch is not None and self.lunch_gap == len(self.stops):
            return max(self._lunch[3], self._end[-1])
        return self._end[-1]

    def lunch_schedule(self):
        """Обед маршрута: (перед каким визитом, расписание, где обедает) или None.

        Расписание — как у визита в `schedule_at`: выезд, прибытие, начало, конец,
        ожидание, простой до выезда, минуты в пути, км.
        """
        if self._lunch is None or self.lunch_gap is None:
            return None
        return self.lunch_gap, self._lunch, self._lunch_point

    def point_before(self, index: int) -> GeoPoint:
        """Откуда инженер едет к визиту `index`: с прошлого адреса или с места обеда."""
        if self._lunch is not None and self.lunch_gap == index and self._lunch_point is not None:
            return self._lunch_point
        return self._point_before(index)

    @property
    def busy_minutes(self) -> float:
        return self.service_minutes + self.travel_minutes + self.waiting_minutes

    def __repr__(self) -> str:  # pragma: no cover - диагностика
        return f"RouteState({self.engineer.id}: {' → '.join(self.request_ids) or 'пусто'})"

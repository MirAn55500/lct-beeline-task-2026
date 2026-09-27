"""Ручная правка готового плана на Ганте: куда можно поставить заявку и сам ход.

Диспетчер тащит плашку по ленте и должен сразу видеть, встанет ли она: успеет ли
инженер доехать от предыдущего адреса, не сорвутся ли следующие окна и смена. Считать
это на каждое движение мыши по сети — медленно, а приблизительно на клиенте — нечестно:
у общественного транспорта время в пути зависит от момента выезда. Поэтому расчёт
разделён на две части:

* `Board.slots` — заранее, для каждой подвижной заявки: у каждого инженера на каждой
  позиции маршрута окно «начать можно с … по …» (`RouteState.insertion_window`).
  Во время перетаскивания интерфейс только сверяется с этими окнами;
* `Board.move` — сам ход: заявка ставится на выбранное время, маршрут пересчитывается
  целиком тем же прямым проходом, что и в планировщике. Без `commit` — проверка
  с превью расписания, с `commit` — ход остаётся на доске.

Маршруты восстанавливаются из сохранённого расписания. Чтобы правка одной заявки не
переставляла весь день, каждый визит держится **не раньше своего времени** из плана:
клиенту уже назвали время, и уехать к нему раньше из-за того, что соседний визит
убрали, нельзя. Позже — можно, в пределах окна клиента: так вставка раздвигает хвост.
Начатые визиты (выезд уже был) заморожены, как в `replan`.

Окно клиента при ручной постановке не ограничивает: поставить заявку вне окна можно,
если клиент согласился на новое время, — это отмечает `MoveOutcome.outside_window`.
Согласованное время становится новым окном клиента той же длины (`window_shift`):
иначе полный пересчёт плана вернул бы заявку в старое окно.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from .context import PlanContext, RequestTiming
from .enums import Algorithm, ReasonCode, ReplanScope
from .feasibility import check_static
from .models import Scenario
from .result import PlanResult
from .route import RouteState
from .solution import Solution
from .travel import TravelModel

__all__ = ["Board", "MoveOutcome", "RequestSlots", "Slot", "StoredVisit", "VisitTimes"]

_FAR = 1e6
"""«Окна нет» в минутах: ±два года от полуночи дня плана — конечные числа безопаснее inf."""
_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class StoredVisit:
    """Визит сохранённого плана — вход для восстановления маршрута."""

    request_id: str
    engineer_id: str
    position: int
    departure_at: datetime
    arrival_at: datetime
    service_start_at: datetime
    service_end_at: datetime
    travel_minutes: float = 0.0
    distance_km: float = 0.0
    waiting_minutes: float = 0.0


@dataclass(frozen=True, slots=True)
class Slot:
    """Место в маршруте инженера и допустимое начало работ — минуты от полуночи дня плана."""

    position: int
    earliest: float
    latest: float
    departure: float
    travel_minutes: float


@dataclass(frozen=True, slots=True)
class RequestSlots:
    """Куда можно поставить заявку: окна по инженерам и причины, почему к остальным нельзя."""

    request_id: str
    movable: bool
    reason: str = ""
    slots: dict[str, list[Slot]] = field(default_factory=dict)
    refusals: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VisitTimes:
    """Расписание визита после хода — для превью на ленте. Минуты от полуночи дня плана."""

    request_id: str
    engineer_id: str
    position: int
    departure: float
    arrival: float
    start: float
    end: float
    travel_minutes: float


@dataclass(frozen=True, slots=True)
class MoveOutcome:
    ok: bool
    reason: str = ""
    outside_window: bool = False
    """Работа начнётся вне окна клиента — время нужно согласовать."""
    window_shift: float = 0.0
    """На сколько минут переезжает окно клиента: новое начинается с согласованного времени."""
    visits: tuple[VisitTimes, ...] = ()
    """Новое расписание изменившихся маршрутов."""
    engineers: tuple[str, ...] = ()
    """Инженеры, чьи маршруты изменились (в том числе ставшие пустыми)."""
    released: tuple[str, ...] = ()
    """Заявки, снятые с маршрутов, чтобы освободить место."""


def _clock(minutes: float) -> str:
    total = int(round(minutes))
    return f"{total // 60}:{total % 60:02d}"


class Board:
    """План, открытый для ручной правки. Методы не потокобезопасны: снаружи — под замком."""

    def __init__(
        self,
        scenario: Scenario,
        visits: Iterable[StoredVisit],
        *,
        unassigned: Mapping[str, ReasonCode] | None = None,
        travel: TravelModel | None = None,
        now: datetime | None = None,
    ) -> None:
        self.ctx = ctx = PlanContext(scenario, travel)
        self._by_id = scenario.request_by_id
        # Окна клиентов: удержания визитов подменяют тайминги в контексте, а исходные нужны
        # и для проверки «вне окна», и чтобы вернуть заявке её окно.
        self._client: dict[str, RequestTiming] = {r.id: ctx.timing(r) for r in scenario.requests}
        self.floor = -_FAR if now is None else ctx.to_minutes(now)
        self.solution = Solution(ctx)
        self.frozen_routes: set[str] = set()
        for state in self.solution.routes.values():
            state.floor_m = self.floor

        by_engineer: dict[str, list[StoredVisit]] = {}
        for visit in visits:
            if visit.request_id in self._by_id:
                by_engineer.setdefault(visit.engineer_id, []).append(visit)
        for engineer_id, items in by_engineer.items():
            items.sort(key=lambda v: (v.position, v.service_start_at))
            state = self.solution.routes.get(engineer_id)
            if state is None:
                continue  # инженер выбыл — его заявки уйдут в неназначенные ниже
            self._restore(state, items)

        assigned = self.solution.assigned_ids()
        reasons = unassigned or {}
        for request in scenario.planning_requests():
            if request.id not in assigned:
                self.solution.mark_unassigned(request, reasons.get(request.id, ReasonCode.NOT_FOUND))

    # ------------------------------------------------------------------ восстановление

    def _restore(self, state: RouteState, items: list[StoredVisit]) -> None:
        ctx = self.ctx
        stops = [self._by_id[v.request_id] for v in items]
        locked = 0
        while locked < len(items) and ctx.to_minutes(items[locked].departure_at) <= self.floor:
            locked += 1
        frozen = [self._frozen(v) for v in items[:locked]]
        for visit in items[locked:]:
            self._hold(visit.request_id, ctx.to_minutes(visit.service_start_at))
        if state.adopt(stops, locked, frozen):
            return
        # План считали на другой модели поездок (кэш обновился): без удержаний маршрут
        # ещё может сойтись, а если нет — остаётся ровно как сохранён, без правок внутри.
        for visit in items[locked:]:
            self._release(visit.request_id)
        if state.adopt(stops, locked, frozen):
            return
        state.adopt(stops, len(stops), [self._frozen(v) for v in items])
        self.frozen_routes.add(state.engineer.id)

    def _frozen(self, visit: StoredVisit) -> tuple[float, float, float, float, float, float, float]:
        m = self.ctx.to_minutes
        return (
            m(visit.departure_at),
            m(visit.arrival_at),
            m(visit.service_start_at),
            m(visit.service_end_at),
            visit.waiting_minutes,
            visit.travel_minutes,
            visit.distance_km,
        )

    # ------------------------------------------------------------------ тайминги

    def _set_timing(self, request_id: str, timing: RequestTiming) -> None:
        self.ctx._timings[request_id] = timing  # noqa: SLF001 - контекст расчёта общий на доску

    def _hold(self, request_id: str, start: float) -> None:
        """Визит не раньше `start`, позже — до конца окна клиента (или до `start`, если оно уже позади)."""
        client = self._client[request_id]
        self._set_timing(
            request_id,
            RequestTiming(
                window_start=start,
                window_end=client.window_end if client.window_end > start else start,
                duration=client.duration,
                available_from=client.available_from if client.available_from < start else start,
            ),
        )

    def _release(self, request_id: str) -> None:
        self._set_timing(request_id, self._client[request_id])

    def _open(self, request_id: str) -> RequestTiming:
        """Без окна клиента: ручная постановка может увести работу за окно с согласия клиента."""
        client = self._client[request_id]
        received = self._by_id[request_id].received_at is not None
        return RequestTiming(
            window_start=-_FAR,
            window_end=_FAR,
            duration=client.duration,
            available_from=client.available_from if received else -_FAR,
        )

    def _pinned(self, request_id: str, start: float) -> RequestTiming:
        """Начало ровно в `start`: окно из одной точки."""
        open_ = self._open(request_id)
        return RequestTiming(start, start, open_.duration, open_.available_from)

    # ------------------------------------------------------------------ окна вставки

    def slots(self, request_ids: Iterable[str] | None = None) -> list[RequestSlots]:
        """Окна постановки для заявок; без списка — для всех, кого можно двигать."""
        ids = list(request_ids) if request_ids is not None else [
            r.id for r in self.ctx.scenario.planning_requests()
        ]
        return [self._slots_of(request_id) for request_id in ids if request_id in self._by_id]

    def _slots_of(self, request_id: str) -> RequestSlots:
        request = self._by_id[request_id]
        current = self.solution.route_of(request_id)
        if current is not None:
            if current.index_of(request_id) < current.locked_count:
                return RequestSlots(request_id, False, "Инженер уже выехал на заявку")
            if current.engineer.id in self.frozen_routes:
                return RequestSlots(request_id, False, "Маршрут инженера не пересчитывается")

        saved = self.ctx.timing(request)
        self._set_timing(request_id, self._open(request_id))
        slots: dict[str, list[Slot]] = {}
        refusals: dict[str, str] = {}
        try:
            for state in self.solution:
                static = check_static(state.engineer, request, self.ctx.settings)
                if not static.ok:
                    refusals[state.engineer.id] = static.detail
                    continue
                route = state
                if state is current:
                    route = state.clone()
                    route.remove_request(request_id)
                found = []
                for position in range(route.locked_count, route.size + 1):
                    window = route.insertion_window(request, position)
                    if window is not None:
                        found.append(Slot(position, *window))
                if found:
                    slots[state.engineer.id] = found
                else:
                    refusals[state.engineer.id] = (
                        f"У {state.engineer.name} нет времени: между заявками не успеть "
                        f"доехать и выполнить работу, а после последней — не хватает смены"
                    )
        finally:
            self._set_timing(request_id, saved)
        return RequestSlots(request_id, True, slots=slots, refusals=refusals)

    # ------------------------------------------------------------------ ход

    def move(
        self,
        request_id: str,
        engineer_id: str | None,
        *,
        start: float | None = None,
        position: int | None = None,
        release: Sequence[str] = (),
        commit: bool = False,
    ) -> MoveOutcome:
        """Ставит заявку к инженеру на время `start` (минуты от полуночи дня плана).

        `engineer_id=None` снимает заявку с маршрута. `position` — место в маршруте;
        без него — по времени: после визитов, которые начинаются раньше. `release` —
        заявки, которые снимаются, чтобы освободить место («замена» на Ганте).
        Без `commit` доска не меняется — это проверка с превью расписания.
        """
        request = self._by_id.get(request_id)
        if request is None:
            return MoveOutcome(False, f"Заявки {request_id} нет в плане")
        timings = dict(self.ctx._timings)  # noqa: SLF001
        solution = self.solution.clone()
        before = {state.engineer.id: self._schedule(state) for state in solution}
        try:
            outcome = self._apply(solution, request_id, engineer_id, start, position, release)
        except Exception:
            self.ctx._timings = timings  # noqa: SLF001
            raise
        if not outcome.ok or not commit:
            self.ctx._timings = timings  # noqa: SLF001
        else:
            self.solution = solution
            if outcome.window_shift:
                client = self._client[request_id]
                self._client[request_id] = RequestTiming(
                    client.window_start + outcome.window_shift,
                    client.window_end + outcome.window_shift,
                    client.duration,
                    client.available_from,
                )
            for state in solution:
                for index in range(state.locked_count, state.size):
                    self._hold(state.stops[index].id, state.schedule_at(index)[2])
        if not outcome.ok:
            return outcome
        changed = [s for s in solution if self._schedule(s) != before.get(s.engineer.id)]
        return MoveOutcome(
            True,
            outside_window=outcome.outside_window,
            window_shift=outcome.window_shift,
            visits=tuple(visit for state in changed for visit in self._visits(state)),
            engineers=tuple(state.engineer.id for state in changed),
            released=outcome.released,
        )

    def _apply(
        self,
        solution: Solution,
        request_id: str,
        engineer_id: str | None,
        start: float | None,
        position: int | None,
        release: Sequence[str],
    ) -> MoveOutcome:
        request = self._by_id[request_id]
        for other_id in (request_id, *release):
            route = solution.route_of(other_id)
            if route is None:
                continue
            if route.index_of(other_id) < route.locked_count:
                return MoveOutcome(False, f"По заявке {other_id} инженер уже выехал — её не сдвинуть")
            if route.engineer.id in self.frozen_routes:
                return MoveOutcome(False, f"Маршрут {route.engineer.name} не пересчитывается")
            route.remove_request(other_id)
        released = tuple(r for r in release if r in self._by_id and r != request_id)
        for other_id in released:
            self._release(other_id)
            solution.mark_unassigned(self._by_id[other_id], ReasonCode.MANUAL, [
                f"Снята вручную: место заняла заявка {request_id}"
            ])

        if engineer_id is None:
            self._release(request_id)
            solution.mark_unassigned(request, ReasonCode.MANUAL)
            return MoveOutcome(True, released=released)

        target = solution.routes.get(engineer_id)
        if target is None:
            known = self.ctx.scenario.engineer_by_id.get(engineer_id)
            name = known.name if known is not None else f"Инженер {engineer_id}"
            return MoveOutcome(False, f"У {name} нет рабочего времени на дату плана")
        static = check_static(target.engineer, request, self.ctx.settings)
        if not static.ok:
            return MoveOutcome(False, static.detail)

        outside = False
        shift = 0.0
        if start is None:
            self._release(request_id)
            best = target.best_insertion(request)
            if best is None or not target.insert_checked(request, best[1]):
                return MoveOutcome(False, f"У {target.engineer.name} нет места для заявки в окне клиента")
        else:
            if position is None:
                position = max(
                    target.locked_count,
                    sum(1 for i in range(target.size) if target.schedule_at(i)[2] < start),
                )
            self._set_timing(request_id, self._pinned(request_id, start))
            if not target.insert_checked(request, position):
                return MoveOutcome(False, self._why_not(target, request_id, start, position))
            client = self._client[request_id]
            outside = start < client.window_start - _EPS or start > client.window_end + _EPS
            shift = start - client.window_start if outside else 0.0
        solution.clear_unassigned(request_id)
        return MoveOutcome(True, outside_window=outside, window_shift=shift, released=released)

    def _why_not(self, route: RouteState, request_id: str, start: float, position: int) -> str:
        """Почему заявка не встала на это время — по окну вставки без окна клиента."""
        name = route.engineer.name
        if position < route.locked_count:
            return f"{name} уже в работе — раньше начатых визитов не поставить"
        if start < self.floor - _EPS:
            return "Это время уже прошло"
        self._set_timing(request_id, self._open(request_id))
        window = route.insertion_window(self._by_id[request_id], position)
        if window is None:
            return f"У {name} здесь нет времени: не успеть доехать и выполнить работу"
        if start < window.earliest - _EPS:
            return f"{name} не успеет доехать: начать можно не раньше {_clock(window.earliest)}"
        if start > window.latest + _EPS:
            return f"Следующие заявки {name} не успеют: начать нужно не позже {_clock(window.latest)}"
        return f"Заявка не помещается в маршрут {name} на {_clock(start)}"

    # ------------------------------------------------------------------ новые заявки

    def place_new(self, request_ids: Iterable[str], *, scope: ReplanScope | str) -> list[str]:
        """Ставит новые заявки в готовый план, не пересобирая его. Возвращает поставленные.

        Уровень перестроения при загрузке заявок (Figma: Фикс / Инженерный / Свободный):

        * `LOW` («Фикс») — только свободные окна: остальные визиты остаются ровно на
          своём времени, клиентам ничего не переносим;
        * `MEDIUM` («Инженерный») — ещё и вытеснение менее приоритетных работ внутри
          маршрута одного инженера (`place_with_ejection`); хвост маршрута может
          сдвинуться в пределах окон клиентов, вытесненные ищут свободное окно у других.

        Весь день заново («Свободный») считает `planner.plan`, а не доска.
        """
        from .construct import place_single, place_with_ejection

        scope = ReplanScope(scope)
        ctx, solution = self.ctx, self.solution
        if not scope.allows_ejection:
            for state in solution.routes.values():
                if state.engineer.id in self.frozen_routes or state.locked_count >= state.size:
                    continue
                held = [(state.stops[i].id, state.schedule_at(i)[2]) for i in range(state.locked_count, state.size)]
                for request_id, start in held:
                    self._pin_at(request_id, start)
                if not state.recompute():
                    # Расписание не сошлось в точку — остаётся «не раньше своего времени»
                    for request_id, start in held:
                        self._hold(request_id, start)
                    state.recompute()

        assigned = solution.assigned_ids()
        pending = sorted(
            {i: self._by_id[i] for i in request_ids if i in self._by_id and i not in assigned}.values(),
            key=lambda r: (-r.priority.rank, r.input_order, r.id),
        )
        placed: list[str] = []
        for request in pending:
            found = place_single(ctx, solution, request)
            if found is None and scope.allows_ejection:
                found = place_with_ejection(ctx, solution, request)
            if found is not None:
                placed.append(request.id)
        return placed

    def _pin_at(self, request_id: str, start: float) -> None:
        """Визит ровно в `start`: «Фикс» не переносит клиентам время."""
        client = self._client[request_id]
        self._set_timing(
            request_id,
            RequestTiming(
                window_start=start,
                window_end=start,
                duration=client.duration,
                available_from=client.available_from if client.available_from < start else start,
            ),
        )

    # ------------------------------------------------------------------ расписание

    @staticmethod
    def _schedule(state: RouteState) -> tuple:
        return tuple(
            (state.stops[i].id, round(state.schedule_at(i)[2], 3)) for i in range(state.size)
        )

    @staticmethod
    def _visits(state: RouteState) -> list[VisitTimes]:
        out = []
        for index, request in enumerate(state.stops):
            dep, arr, start, end, _wait, _idle, minutes, _km = state.schedule_at(index)
            out.append(VisitTimes(request.id, state.engineer.id, index + 1, dep, arr, start, end, minutes))
        return out

    def result(self, *, plan_id: str | None = None) -> PlanResult:
        """План после правок — в том же виде, что у `planner.plan`."""
        from .solver import build_result

        return build_result(
            self.ctx,
            self.solution,
            Algorithm.OPTIMIZED,
            warnings=tuple(self.ctx.scenario.validate()),
            plan_id=plan_id,
        )

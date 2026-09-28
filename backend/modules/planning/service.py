import asyncio
from collections.abc import Iterable
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

from sqlmodel.ext.asyncio.session import AsyncSession

from core.exceptions import AppError
from modules.algorithm.service import AlgorithmService
from modules.planning import background
from modules.planning import board as boards
from modules.planning import transit
from modules.planning.models.assignment import Assignment
from modules.planning.models.plan import Plan
from modules.planning.repository import PlanningRepository
from modules.planning.scenario_builder import (
    _REASON_LABELS,
    assignments_from_result,
    build_travel,
    finish_plan,
    route_legs,
    build_scenario,
    reason_index,
    restrict_availability,
    run_plan,
)
from modules.planning.schemas import (
    CounterPair,
    MoveRequest,
    MoveResponse,
    MoveVisitExport,
    PlanSlotsResponse,
    RequestSlotsExport,
    PlanEngineerExport,
    PlanExportResponse,
    PlanRequestExport,
    PlanRouteExport,
    PlanUnassignedExport,
    PlanVisitExport,
    DayOverviewResponse,
    Distribution,
    EngineersCounter,
    PlanComparison,
    ComparisonLine,
    PlanEventRequest,
    PlanEventResponse,
    PlanVersionResponse,
    RecalculateResponse,
    RemakeLevel,
)
from planner import Algorithm
from planner.dispatch import Board, MoveOutcome, StoredVisit
from planner.enums import EventType, ReasonCode, ReplanScope
from planner.metrics import compare as compare_plans
from planner.models import ReplanEvent, Scenario
from planner.replan import replan
from planner.result import PlanResult

_REMAKE_TO_SCOPE = {
    RemakeLevel.FIX: ReplanScope.LOW,
    RemakeLevel.ENGINEER: ReplanScope.MEDIUM,
    RemakeLevel.FREE: ReplanScope.HIGH,
}

_DISTRIBUTION_TO_ALGORITHM = {
    Distribution.EVEN: Algorithm.BASELINE,
    Distribution.EFFICIENT: Algorithm.OPTIMIZED,
}


def reason_code(label: str) -> str:
    """Код причины неназначения по значению словаря: там код или старая подпись."""
    label = label.strip().lower()
    return next((c for c, text in _REASON_LABELS.items() if label in {c, text}), "not_found")


def _minutes(value: float) -> float:
    return round(value, 2)


class PlanningService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = PlanningRepository(session)
        self._rows: tuple[list, list] = ([], [])
        self._algorithm = AlgorithmService()

    def health(self) -> dict[str, str]:
        return {"module": "planning", "status": "ok"}

    async def get_day_overview(
        self, region_id: int, day: date, plan_id: int | None = None
    ) -> DayOverviewResponse:
        planning, planning_error, planning_eta = background.status(region_id, day)
        tickets_total = await self._repo.count_requests(region_id, day)
        engineers_total = await self._repo.count_engineers(region_id)
        planned_dates = await self._repo.list_planned_dates(region_id)
        plans = await self._repo.list_plans(region_id, day)
        versions = [
            PlanVersionResponse(
                plan_id=item.plan_id,
                version=item.version,
                created_at=item.created_at,
            )
            for item in plans
            if item.plan_id is not None
        ]
        if plan_id is None:
            plan = plans[0] if plans else None
        else:
            plan = next((item for item in plans if item.plan_id == plan_id), None)
            if plan is None:
                raise AppError("План не найден", status_code=404)

        if plan is None or plan.plan_id is None:
            return DayOverviewResponse(
                plan_id=None,
                plan_version=None,
                has_plan=False,
                tickets=CounterPair(assigned=None, total=tickets_total),
                engineers=EngineersCounter(engaged=None, total=engineers_total),
                planned_dates=planned_dates,
                plans=versions,
                planning=planning,
                planning_error=planning_error,
                planning_eta_seconds=planning_eta,
            )

        assigned = await self._repo.count_assigned_requests(plan.plan_id, region_id)
        engaged = await self._repo.count_engaged_engineers(plan.plan_id, region_id)
        travel_minutes, distance_km = await self._repo.travel_totals(plan.plan_id)

        return DayOverviewResponse(
            plan_id=plan.plan_id,
            plan_version=plan.version,
            has_plan=True,
            tickets=CounterPair(assigned=assigned, total=tickets_total),
            engineers=EngineersCounter(engaged=engaged, total=engineers_total),
            planned_dates=planned_dates,
            plans=versions,
            planning=planning,
            planning_error=planning_error,
            planning_eta_seconds=planning_eta,
            travel_minutes=round(travel_minutes, 1),
            distance_km=round(distance_km, 1),
        )

    async def _scenario(self, region_id: int, day: date):
        region = await self._repo.get_region(region_id)
        if region is None:
            raise AppError("Регион не найден", status_code=404)

        requests = await self._repo.list_requests_for_plan(region_id, day)
        if not requests:
            raise AppError("На эту дату в регионе нет заявок")

        engineers = await self._repo.list_engineers_for_plan(region_id)
        # Инженеры в выходной (свой или бригады) в новый план не попадают
        working = [e for e in engineers if e.works_on(day)]
        if engineers and not working:
            raise AppError(
                "В этот день никто из инженеров региона не работает — проверьте рабочий "
                "график в карточках бригады и инженеров"
            )
        engineers = working
        scenario, transport_by_engineer = build_scenario(
            day=day,
            region_id=region_id,
            region_name=region.region_name,
            requests=requests,
            engineers=engineers,
        )
        scenario = restrict_availability(scenario, await self._repo.unavailable_cutoffs(day))
        if not scenario.requests:
            raise AppError("Нет открытых заявок для расчёта")
        self._rows = (requests, engineers)
        return scenario, transport_by_engineer

    async def recalculate(
        self,
        region_id: int,
        day: date,
        *,
        remake_level: RemakeLevel = RemakeLevel.FREE,
        distribution: Distribution = Distribution.EFFICIENT,
        fresh: Iterable[int] = (),
        compare: bool = False,
    ) -> RecalculateResponse:
        """Новая версия плана дня.

        «Свободный» (и первый план дня) — расчёт с нуля. «Фикс» и «Инженерный» берут
        последнюю версию и только ставят в неё заявки, которых там нет: в свободные окна
        или (Инженерный) с вытеснением внутри маршрута одного инженера, см. `Board.place_new`.
        `fresh` — id добавленных и изменённых загрузкой заявок: их прежние визиты
        не сохраняются, заявки ставятся заново.
        """
        scenario, transport_by_engineer = await self._scenario(region_id, day)
        scenario.settings.replan_scope = _REMAKE_TO_SCOPE[remake_level]
        algorithm = _DISTRIBUTION_TO_ALGORITHM[distribution]

        previous = await self._repo.find_latest_plan(region_id, day)
        profiles = await transit.load_profiles(self._repo.session, scenario)
        result = None
        if remake_level is not RemakeLevel.FREE and previous is not None:
            result = await self._extend(previous.plan_id or 0, day, scenario, profiles, fresh, remake_level)
        if result is None:
            result = await asyncio.to_thread(run_plan, scenario, algorithm, profiles)
        comparison = None
        if compare and algorithm is Algorithm.OPTIMIZED:
            baseline = await asyncio.to_thread(run_plan, scenario, Algorithm.BASELINE, profiles)
            comparison = _comparison(compare_plans(baseline, result))
        plan, assigned, unassigned = await self._persist(
            region_id, day, scenario, result, transport_by_engineer
        )
        return RecalculateResponse(
            plan_id=plan.plan_id or 0,
            version=plan.version,
            assigned=assigned,
            unassigned=unassigned,
            comparison=comparison,
        )

    async def _persist(self, region_id: int, day: date, scenario, result, transport_by_engineer):
        reasons = await self._repo.ensure_unassigned_reasons()
        rows, assigned, unassigned = assignments_from_result(
            result,
            transport_by_engineer=transport_by_engineer,
            reason_by_code=reason_index(reasons),
            offset_hours=scenario.settings.timezone_offset_hours,
        )
        previous = await self._repo.find_latest_plan(region_id, day)
        version = (previous.version + 1) if previous is not None else 1
        requests, engineers = self._rows
        plan = await self._repo.save_plan(
            region_id=region_id,
            day=day,
            version=version,
            reference_plan_id=previous.plan_id if previous is not None else None,
            rows=rows,
            legs=route_legs(
                result,
                address_of={r.request_id: r.address_id for r in requests if r.request_id is not None},
                office_of={
                    e.engineer_id: e.brigade.office_address_id
                    for e in engineers
                    if e.engineer_id is not None and e.brigade is not None
                },
                transport_of=transport_by_engineer,
                offset_hours=scenario.settings.timezone_offset_hours,
            ),
        )
        if previous is not None and previous.plan_id is not None:
            boards.drop(previous.plan_id)
        return plan, assigned, unassigned

    async def apply_event(
        self, region_id: int, day: date, body: PlanEventRequest
    ) -> PlanEventResponse:
        """Отмена заявки или недоступность инженера: ремонт остатка дня и разница с прошлым планом."""
        previous_plan = await self._repo.find_latest_plan(region_id, day)
        if previous_plan is None or previous_plan.plan_id is None:
            raise AppError("Сначала составьте план на этот день")
        moment = datetime.combine(day, body.at or time(12, 0), tzinfo=timezone(timedelta(hours=3)))
        scenario, transport_by_engineer = await self._scenario(region_id, day)
        scenario.settings.replan_scope = ReplanScope.HIGH

        if body.type == "cancel_request":
            if body.request_id is None:
                raise AppError("Для отмены нужна заявка")
            if str(body.request_id) not in {request.id for request in scenario.requests}:
                raise AppError("Этой заявки нет среди открытых на выбранный день")
            event = ReplanEvent(
                type=EventType.CANCEL_REQUEST,
                at=moment,
                request_id=str(body.request_id),
            )
        else:
            if body.engineer_id is None:
                raise AppError("Для недоступности нужен инженер")
            if str(body.engineer_id) not in {engineer.id for engineer in scenario.engineers}:
                raise AppError("Этого инженера нет в расчёте на выбранный день")
            event = ReplanEvent(
                type=EventType.ENGINEER_UNAVAILABLE,
                at=moment,
                engineer_id=str(body.engineer_id),
            )

        boards.drop(previous_plan.plan_id)
        entry = await self._open_board(previous_plan.plan_id)
        entry.scenario.settings.replan_scope = ReplanScope.HIGH

        def run():
            with entry.lock:
                previous = entry.board.result(plan_id=str(previous_plan.plan_id))
                repaired = replan(previous, entry.scenario, event, travel=entry.travel)
                return finish_plan(entry.scenario, repaired, entry.routing, entry.travel)

        result = await asyncio.to_thread(run)
        if body.type == "cancel_request" and body.request_id is not None:
            await self._repo.cancel_request(body.request_id, moment.replace(tzinfo=None))
        await self._repo.add_replan_event(
            event_type=body.type,
            event_time=moment,
            request_id=body.request_id,
            engineer_id=body.engineer_id,
        )
        plan, assigned, unassigned = await self._persist(
            region_id, day, entry.scenario, result, transport_by_engineer
        )
        summary = result.diff.summary if result.diff is not None else "План пересчитан"
        return PlanEventResponse(
            plan_id=plan.plan_id or 0,
            version=plan.version,
            assigned=assigned,
            unassigned=unassigned,
            summary=summary,
            warnings=list(result.warnings),
        )

    async def _extend(
        self,
        plan_id: int,
        day: date,
        scenario: Scenario,
        profiles,
        fresh: Iterable[int],
        remake_level: RemakeLevel,
    ) -> PlanResult | None:
        """Версия плана + заявки, которых в ней нет. None — восстановить нечего, считать с нуля.

        Кандидаты — новые и изменённые заявки, а также оставшиеся в версии без инженера:
        свободное окно могло найтись и для них.
        """
        fresh_ids = {str(i) for i in fresh}
        rows = [r for r in await self._repo.list_assignments(plan_id) if str(r.request_id) not in fresh_ids]
        visits, unassigned = self._stored_visits(rows, scenario)
        if not visits and any(r.engineer_id is not None for r in rows):
            return None  # в версии нет расписания визитов
        in_plan = {v.request_id for v in visits}
        candidates = [r.id for r in scenario.planning_requests() if r.id not in in_plan]
        zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))
        now = datetime.now(zone)
        # Начатое замораживается только сегодня. Прошедший день (разбор выгрузки задним
        # числом) считается, как и расчёт с нуля, без «сейчас» — иначе заморожен весь день.
        if now.date() != day:
            now = None

        def compute() -> PlanResult:
            routing, travel = build_travel(scenario, profiles)
            board = Board(scenario, visits, unassigned=unassigned, travel=travel, now=now)
            board.place_new(candidates, scope=_REMAKE_TO_SCOPE[remake_level])
            return finish_plan(scenario, board.result(), routing, travel)

        return await asyncio.to_thread(compute)

    @staticmethod
    def _stored_visits(
        rows: list[Assignment], scenario: Scenario
    ) -> tuple[list[StoredVisit], dict[str, ReasonCode]]:
        """Сохранённая версия плана → визиты для `Board` и причины неназначенных."""
        zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))

        def aware(moment: datetime | None, fallback: datetime | None = None) -> datetime:
            moment = moment or fallback
            assert moment is not None
            return moment.replace(tzinfo=zone) if moment.tzinfo is None else moment

        visits = [
            StoredVisit(
                request_id=str(r.request_id),
                engineer_id=str(r.engineer_id),
                position=r.position or 0,
                departure_at=aware(r.planned_departure_at, r.planned_start_at),
                arrival_at=aware(r.planned_arrival_at, r.planned_start_at),
                service_start_at=aware(r.planned_start_at),
                service_end_at=aware(r.planned_end_at, r.planned_start_at),
                travel_minutes=r.travel_minutes or 0.0,
                distance_km=r.distance_km or 0.0,
                waiting_minutes=r.waiting_minutes or 0.0,
            )
            for r in rows
            if r.engineer_id is not None and r.planned_start_at is not None
        ]
        unassigned = {
            str(r.request_id): ReasonCode(
                reason_code(r.unassigned_reason.value if r.unassigned_reason else "")
            )
            for r in rows
            if r.engineer_id is None
        }
        return visits, unassigned

    async def get_plan(
        self, region_id: int, day: date, plan_id: int | None = None
    ) -> PlanExportResponse:
        """План дня с расписанием визитов — для карты и Ганта.

        Форма ответа — как у выгрузки планировщика, на которой сделаны моки frontend
        (`PlanExport`): инженеры, заявки, маршруты с выездом/прибытием/работой и
        неназначенные с причиной. Геометрии по улицам backend не строит — маршрут
        рисуется прямыми между точками (`geometrySource: "straight"`).
        """
        plans = await self._repo.list_plans(region_id, day)
        if plan_id is None:
            plan = plans[0] if plans else None
        else:
            plan = next((item for item in plans if item.plan_id == plan_id), None)
        if plan is None or plan.plan_id is None:
            raise AppError("План не найден", status_code=404)
        region = await self._repo.get_region(region_id)
        requests = await self._repo.list_requests_for_plan(region_id, day)
        engineers = await self._repo.list_engineers_for_plan(region_id)
        scenario, _ = build_scenario(
            day=day,
            region_id=region_id,
            region_name=region.region_name if region else "",
            requests=requests,
            engineers=engineers,
        )
        zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))
        suffix = datetime(2000, 1, 1, tzinfo=zone).strftime("%z")
        suffix = f"{suffix[:3]}:{suffix[3:]}"

        def iso(moment: datetime | None) -> str:
            if moment is None:
                return ""
            if moment.tzinfo is not None:
                moment = moment.astimezone(zone).replace(tzinfo=None)
            return moment.isoformat(timespec="seconds") + suffix

        requests_out = [
            PlanRequestExport(
                id=r.id,
                point=[r.point.lon, r.point.lat],
                window=[iso(r.window_start), iso(r.window_end)],
                address=r.address,
                type=r.request_type_bk,
                skill=r.required_skill.value,
                duration=r.duration_minutes,
                priority=r.priority.value,
                equipment=sorted(r.required_equipment),
            )
            for r in scenario.requests
        ]
        known = {r.id for r in scenario.requests}
        engineers_out = [
            PlanEngineerExport(
                id=e.id,
                name=e.name,
                start=[e.start_point.lon, e.start_point.lat],
                workIntervals=[[iso(w.start), iso(w.end)] for w in e.work_intervals],
                skills=sorted(s.value for s in e.skills),
                transport=e.transport_mode.value,
                equipment=sorted(e.equipment),
            )
            for e in scenario.engineers
        ]
        shift_minutes = {
            e.id: sum((w.end - w.start).total_seconds() / 60 for w in e.work_intervals)
            for e in scenario.engineers
        }
        points = {r.id: [r.point.lon, r.point.lat] for r in scenario.requests}
        starts = {e.id: [e.start_point.lon, e.start_point.lat] for e in scenario.engineers}
        durations = {r.id: r.duration_minutes for r in scenario.requests}

        paths = await self._repo.list_route_paths(plan.plan_id)
        by_engineer: dict[str, list] = {}
        unassigned_out: list[PlanUnassignedExport] = []
        for row in await self._repo.list_assignments(plan.plan_id):
            request_id = str(row.request_id)
            if request_id not in known:
                continue
            if row.engineer_id is None:
                label = row.unassigned_reason.value if row.unassigned_reason else ""
                unassigned_out.append(PlanUnassignedExport(
                    requestId=request_id, reason=reason_code(label), explanation=row.explanation or label,
                ))
            elif row.planned_start_at is not None and str(row.engineer_id) in starts:
                by_engineer.setdefault(str(row.engineer_id), []).append(row)

        routes_out = []
        for engineer_id, rows in by_engineer.items():
            rows.sort(key=lambda r: (r.position or 0, r.planned_start_at))
            busy = sum(
                durations.get(str(r.request_id), 0) + (r.travel_minutes or 0) + (r.waiting_minutes or 0)
                for r in rows
            )
            shift = shift_minutes.get(engineer_id) or 0
            # Линия маршрута — участки подряд; у визита — его срез (geometryRange)
            geometry: list[list[float]] = []
            ranges: list[list[int] | None] = []
            real = 0
            for r in rows:
                path = paths.get(r.assignment_id) or {}
                segment = path.get("line") or []
                if len(segment) < 2:
                    ranges.append(None)
                    continue
                skip = 1 if geometry and geometry[-1] == segment[0] else 0
                start = len(geometry) - 1 if skip else len(geometry)
                geometry.extend(segment[skip:])
                ranges.append([max(0, start), len(geometry) - 1])
                real += 0 if path.get("straight") else 1
            source = "ors" if real == len(rows) else ("mixed" if real else "straight")
            routes_out.append(PlanRouteExport(
                engineerId=engineer_id,
                startAt=iso(rows[0].planned_departure_at),
                endAt=iso(rows[-1].planned_end_at),
                utilization=round(busy / shift, 4) if shift else 0.0,
                polyline=[starts[engineer_id]] + [points[str(r.request_id)] for r in rows],
                geometrySource=source,
                geometry=geometry if real else [],
                visits=[
                    PlanVisitExport(
                        requestId=str(r.request_id),
                        departureAt=iso(r.planned_departure_at),
                        arrivalAt=iso(r.planned_arrival_at),
                        serviceStartAt=iso(r.planned_start_at),
                        serviceEndAt=iso(r.planned_end_at),
                        travelMinutes=r.travel_minutes or 0.0,
                        distanceKm=r.distance_km or 0.0,
                        waitingMinutes=r.waiting_minutes or 0.0,
                        idleMinutes=r.idle_minutes or 0.0,
                        geometryRange=ranges[i] if real else None,
                        explanation=r.explanation or "",
                        transit=[
                            leg.get("title", "")
                            for leg in (paths.get(r.assignment_id) or {}).get("transit", [])
                        ],
                    )
                    for i, r in enumerate(rows)
                ],
            ))
        order = {e.id: i for i, e in enumerate(scenario.engineers)}
        routes_out.sort(key=lambda r: order.get(r.engineerId, 0))

        return PlanExportResponse(
            planId=plan.plan_id,
            version=plan.version,
            key=str(region_id),
            region=scenario.name,
            date=day,
            engineers=engineers_out,
            requests=requests_out,
            routes=routes_out,
            unassigned=unassigned_out,
        )

    # ------------------------------------------------------------ ручная правка на Ганте

    async def _open_board(self, plan_id: int) -> boards.OpenBoard:
        """Доска плана для ручных ходов: из кэша процесса или собранная из БД."""
        cached = boards.get(plan_id)
        if cached is not None:
            return cached
        plan = await self._repo.session.get(Plan, plan_id)
        if plan is None:
            raise AppError("План не найден", status_code=404)
        region = await self._repo.get_region(plan.region_id)
        requests = await self._repo.list_requests_for_plan(plan.region_id, plan.date)
        engineers = await self._repo.list_engineers_for_plan(plan.region_id)
        scenario, transport_of = build_scenario(
            day=plan.date,
            region_id=plan.region_id,
            region_name=region.region_name if region else "",
            requests=requests,
            engineers=engineers,
        )
        scenario = restrict_availability(
            scenario, await self._repo.unavailable_cutoffs(plan.date)
        )
        zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))
        rows = await self._repo.list_assignments(plan_id)
        visits, unassigned = self._stored_visits(rows, scenario)
        if not visits and any(r.engineer_id is not None for r in rows):
            raise AppError(
                "В этой версии плана нет расписания визитов — обновите план", status_code=409
            )
        profiles = await transit.load_profiles(self._repo.session, scenario)

        def build():
            routing, travel = build_travel(scenario, profiles)
            board = Board(
                scenario, visits, unassigned=unassigned, travel=travel, now=datetime.now(zone)
            )
            return routing, travel, board

        routing, travel, board = await asyncio.to_thread(build)
        entry = boards.OpenBoard(
            board=board,
            scenario=scenario,
            routing=routing,
            travel=travel,
            region_id=plan.region_id,
            day=plan.date,
            transport_of=transport_of,
            address_of={r.request_id: r.address_id for r in requests if r.request_id is not None},
            office_of={
                e.engineer_id: e.brigade.office_address_id
                for e in engineers
                if e.engineer_id is not None and e.brigade is not None
            },
        )
        boards.put(plan_id, entry)
        return entry

    async def get_slots(
        self, plan_id: int, request_ids: list[str] | None = None
    ) -> PlanSlotsResponse:
        """Куда можно поставить заявки плана: окна по инженерам и позициям маршрута."""
        entry = await self._open_board(plan_id)

        def compute():
            with entry.lock:
                return entry.board.slots(request_ids or None)

        items = await asyncio.to_thread(compute)
        return PlanSlotsResponse(
            planId=plan_id,
            requests=[
                RequestSlotsExport(
                    requestId=item.request_id,
                    movable=item.movable,
                    reason=item.reason,
                    slots={
                        engineer_id: [
                            [
                                slot.position,
                                _minutes(slot.earliest),
                                _minutes(slot.latest),
                                _minutes(slot.departure),
                                _minutes(slot.travel_minutes),
                            ]
                            for slot in slots
                        ]
                        for engineer_id, slots in item.slots.items()
                    },
                    refusals=item.refusals,
                )
                for item in items
            ],
        )

    async def move(self, plan_id: int, body: MoveRequest) -> MoveResponse:
        """Ручной ход: проверка с превью или (commit) новая версия плана."""
        entry = await self._open_board(plan_id)
        options = dict(
            start=body.start, position=body.position, release=body.release, commit=body.commit
        )

        def apply():
            with entry.lock:
                outcome = entry.board.move(body.requestId, body.engineerId, **options)
                if not outcome.ok or not body.commit:
                    return outcome, None, None
                result = entry.board.result()
                # Линии по улицам — только изменившимся маршрутам: на весь план это секунды,
                # а участки остальных переносятся из исходной версии как есть.
                changed = set(outcome.engineers)
                partial = replace(result, routes=tuple(r for r in result.routes if r.engineer_id in changed))
                return outcome, result, finish_plan(entry.scenario, partial, entry.routing, entry.travel)

        try:
            outcome, result, drawn = await asyncio.to_thread(apply)
        except Exception:
            boards.drop(plan_id)
            raise
        if result is None:
            return self._move_response(outcome)

        # Доска уже сделала ход: если сохранить не вышло, она расходится с БД — выбрасываем.
        try:
            reasons = await self._repo.ensure_unassigned_reasons()
            offset = entry.scenario.settings.timezone_offset_hours
            rows, _, _ = assignments_from_result(
                result,
                transport_by_engineer=entry.transport_of,
                reason_by_code=reason_index(reasons),
                offset_hours=offset,
            )
            changed = set(outcome.engineers)
            legs = {
                request_id: leg
                for request_id, (engineer_id, leg) in (await self._repo.list_route_legs(plan_id)).items()
                if engineer_id is not None and str(engineer_id) not in changed
            }
            legs.update(
                route_legs(
                    drawn,
                    address_of=entry.address_of,
                    office_of=entry.office_of,
                    transport_of=entry.transport_of,
                    offset_hours=offset,
                )
            )
            if outcome.window_shift:
                # Клиент согласился на время вне окна: иначе пересчёт вернул бы заявку в старое.
                await self._repo.shift_request_window(int(body.requestId), outcome.window_shift)
            latest = await self._repo.find_latest_plan(entry.region_id, entry.day)
            saved = await self._repo.save_plan(
                region_id=entry.region_id,
                day=entry.day,
                version=(latest.version + 1) if latest is not None else 1,
                reference_plan_id=plan_id,
                rows=rows,
                legs=legs,
            )
        except Exception:
            boards.drop(plan_id)
            raise
        boards.rename(plan_id, saved.plan_id or 0)
        response = self._move_response(outcome)
        response.planId = saved.plan_id
        response.version = saved.version
        return response

    @staticmethod
    def _move_response(outcome: MoveOutcome) -> MoveResponse:
        return MoveResponse(
            ok=outcome.ok,
            reason=outcome.reason,
            outsideWindow=outcome.outside_window,
            windowShift=_minutes(outcome.window_shift),
            engineers=list(outcome.engineers),
            visits=[
                MoveVisitExport(
                    requestId=v.request_id,
                    engineerId=v.engineer_id,
                    position=v.position,
                    departure=_minutes(v.departure),
                    arrival=_minutes(v.arrival),
                    start=_minutes(v.start),
                    end=_minutes(v.end),
                    travelMinutes=_minutes(v.travel_minutes),
                )
                for v in outcome.visits
            ],
            released=list(outcome.released),
        )


_COMPARE_LINES = (
    ("assigned_count", "Назначено заявок", True),
    ("used_engineer_count", "Инженеров", True),
    ("total_travel_minutes", "Минут в пути", True),
    ("total_distance_km", "Пробег, км", False),
    ("distance_per_assigned_km", "Км на заявку", False),
)


def _comparison(raw: dict) -> PlanComparison:
    lines: list[ComparisonLine] = []
    metrics = raw["metrics"]
    for key, label, whole in _COMPARE_LINES:
        item = metrics[key]
        render = (lambda value: str(int(round(value)))) if whole else (lambda value: f"{value:.1f}")
        lines.append(
            ComparisonLine(
                label=label,
                baseline=render(item["baseline"]),
                optimized=render(item["optimized"]),
                verdict=item["verdict"],
            )
        )
    return PlanComparison(summary=raw["summary"], lines=lines)

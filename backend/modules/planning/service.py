import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlmodel.ext.asyncio.session import AsyncSession

from core.exceptions import AppError
from modules.algorithm.service import AlgorithmService
from modules.planning import transit
from modules.planning.repository import PlanningRepository
from modules.planning.scenario_builder import (
    _REASON_LABELS,
    assignments_from_result,
    route_legs,
    build_scenario,
    reason_index,
    run_plan,
)
from modules.planning.schemas import (
    CounterPair,
    PlanEngineerExport,
    PlanExportResponse,
    PlanRequestExport,
    PlanRouteExport,
    PlanUnassignedExport,
    PlanVisitExport,
    DayOverviewResponse,
    Distribution,
    EngineersCounter,
    PlanVersionResponse,
    RecalculateResponse,
    RemakeLevel,
)
from planner import Algorithm
from planner.enums import ReplanScope

_REMAKE_TO_SCOPE = {
    RemakeLevel.FIX: ReplanScope.LOW,
    RemakeLevel.ENGINEER: ReplanScope.MEDIUM,
    RemakeLevel.FREE: ReplanScope.HIGH,
}

_DISTRIBUTION_TO_ALGORITHM = {
    Distribution.EVEN: Algorithm.BASELINE,
    Distribution.EFFICIENT: Algorithm.OPTIMIZED,
}


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
            )

        assigned = await self._repo.count_assigned_requests(plan.plan_id, region_id)
        engaged = await self._repo.count_engaged_engineers(plan.plan_id, region_id)

        return DayOverviewResponse(
            plan_id=plan.plan_id,
            plan_version=plan.version,
            has_plan=True,
            tickets=CounterPair(assigned=assigned, total=tickets_total),
            engineers=EngineersCounter(engaged=engaged, total=engineers_total),
            planned_dates=planned_dates,
            plans=versions,
        )

    async def _scenario(self, region_id: int, day: date):
        region = await self._repo.get_region(region_id)
        if region is None:
            raise AppError("Регион не найден", status_code=404)

        requests = await self._repo.list_requests_for_plan(region_id, day)
        if not requests:
            raise AppError("На эту дату в регионе нет заявок")

        engineers = await self._repo.list_engineers_for_plan(region_id)
        scenario, transport_by_engineer = build_scenario(
            day=day,
            region_id=region_id,
            region_name=region.region_name,
            requests=requests,
            engineers=engineers,
        )
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
    ) -> RecalculateResponse:
        scenario, transport_by_engineer = await self._scenario(region_id, day)
        scenario.settings.replan_scope = _REMAKE_TO_SCOPE[remake_level]
        algorithm = _DISTRIBUTION_TO_ALGORITHM[distribution]

        profiles = await transit.load_profiles(self._repo.session, scenario)
        result = await asyncio.to_thread(run_plan, scenario, algorithm, profiles)
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
                    for e in engineers if e.engineer_id is not None and e.brigade is not None
                },
                transport_of=transport_by_engineer,
                offset_hours=scenario.settings.timezone_offset_hours,
            ),
        )
        return RecalculateResponse(
            plan_id=plan.plan_id or 0,
            version=plan.version,
            assigned=assigned,
            unassigned=unassigned,
        )

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
                code = next(
                    (c for c, text in _REASON_LABELS.items() if label.strip().lower() in {c, text}),
                    "not_found",
                )
                unassigned_out.append(PlanUnassignedExport(
                    requestId=request_id, reason=code, explanation=row.explanation or label,
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

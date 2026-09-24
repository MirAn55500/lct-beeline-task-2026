import asyncio
from datetime import date

from sqlmodel.ext.asyncio.session import AsyncSession

from core.exceptions import AppError
from modules.algorithm.service import AlgorithmService
from modules.planning import transit_warmup
from modules.planning.repository import PlanningRepository
from modules.planning.scenario_builder import (
    assignments_from_result,
    build_scenario,
    reason_index,
    run_plan,
)
from modules.planning.schemas import (
    CounterPair,
    DayOverviewResponse,
    EngineersCounter,
    PlanVersionResponse,
    RecalculateResponse,
)


class PlanningService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = PlanningRepository(session)
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
        return scenario, transport_by_engineer

    async def scenario_for(self, region_id: int, day: date):
        """Сценарий дня для фонового досчёта; None, если считать нечего."""
        try:
            scenario, _ = await self._scenario(region_id, day)
        except AppError:
            return None
        return scenario

    async def recalculate(
        self, region_id: int, day: date, *, warm_transit: bool = True
    ) -> RecalculateResponse:
        scenario, transport_by_engineer = await self._scenario(region_id, day)

        result = await asyncio.to_thread(run_plan, scenario)
        reasons = await self._repo.list_unassigned_reasons()
        rows, assigned, unassigned = assignments_from_result(
            result,
            transport_by_engineer=transport_by_engineer,
            reason_by_code=reason_index(reasons),
        )

        previous = await self._repo.find_latest_plan(region_id, day)
        version = (previous.version + 1) if previous is not None else 1
        plan = await self._repo.save_plan(
            region_id=region_id,
            day=day,
            version=version,
            reference_plan_id=previous.plan_id if previous is not None else None,
            rows=rows,
        )
        if warm_transit:
            # Новые точки на общественном транспорте пока по координатам — досчитать
            # расписания в фоне и пересчитать план ещё раз (modules/planning/transit_warmup)
            transit_warmup.schedule(region_id, day)
        return RecalculateResponse(
            plan_id=plan.plan_id or 0,
            version=plan.version,
            assigned=assigned,
            unassigned=unassigned,
        )

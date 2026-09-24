from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from modules.planning.dependencies import get_planning_service
from modules.planning.schemas import (
    DayOverviewResponse,
    Distribution,
    HealthResponse,
    RecalculateResponse,
    RemakeLevel,
)
from modules.planning.service import PlanningService

router = APIRouter(prefix="/planning", tags=["planning"])

PlanningServiceDep = Annotated[PlanningService, Depends(get_planning_service)]


@router.get("/health", response_model=HealthResponse)
async def planning_health(service: PlanningServiceDep) -> HealthResponse:
    return HealthResponse(**service.health())


@router.get("/day-overview", response_model=DayOverviewResponse)
async def get_day_overview(
    service: PlanningServiceDep,
    region_id: Annotated[int, Query(ge=1)],
    date: Annotated[date, Query()],
    plan_id: Annotated[int | None, Query(ge=1)] = None,
) -> DayOverviewResponse:
    """Сводка обзора дня для региона и даты.

    `plan_id` выбирает версию. Без него берётся последняя версия этой даты и региона.
    Пример: `/api/planning/day-overview?region_id=1&date=2026-10-10`
    """
    return await service.get_day_overview(region_id, date, plan_id)


@router.post("/recalculate", response_model=RecalculateResponse)
async def recalculate(
    service: PlanningServiceDep,
    region_id: Annotated[int, Query(ge=1)],
    date: Annotated[date, Query()],
    remake_level: Annotated[RemakeLevel, Query()] = RemakeLevel.FREE,
    distribution: Annotated[Distribution, Query()] = Distribution.EFFICIENT,
) -> RecalculateResponse:
    """Пересчёт плана: заявки и инженеры региона на дату → `planner.plan`.

    `remake_level` — степень изменения (fix / engineer / free).
    `distribution` — алгоритм (even = baseline, efficient = optimized).
    Пример: `POST /api/planning/recalculate?region_id=1&date=2026-10-10&remake_level=free&distribution=efficient`
    """
    return await service.recalculate(
        region_id,
        date,
        remake_level=remake_level,
        distribution=distribution,
    )

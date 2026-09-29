import time
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from core.exceptions import ConflictError
from modules.planning import background
from modules.planning.dependencies import get_planning_service
from modules.planning.schemas import (
    DayOverviewResponse,
    Distribution,
    HealthResponse,
    MoveRequest,
    MoveResponse,
    PlanExportResponse,
    PlanSlotsResponse,
    RecalculateResponse,
    PlanEventRequest,
    PlanEventResponse,
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
    compare: Annotated[bool, Query()] = False,
) -> RecalculateResponse:
    """Пересчёт плана: заявки и инженеры региона на дату → `planner.plan`.

    `remake_level` — степень изменения (fix / engineer / free).
    `distribution` — алгоритм (even = baseline, efficient = optimized).
    Пример: `POST /api/planning/recalculate?region_id=1&date=2026-10-10&remake_level=free&distribution=efficient`
    """
    if background.status(region_id, date)[0]:
        # Иначе два расчёта одного дня разом: лишняя нагрузка и две версии с одним номером
        raise ConflictError("План уже считается после загрузки заявок — дождитесь окончания")
    started = time.monotonic()
    result = await service.recalculate(
        region_id,
        date,
        remake_level=remake_level,
        distribution=distribution,
        compare=compare,
    )
    background.learn_rebuild(time.monotonic() - started)
    return result


@router.post("/event", response_model=PlanEventResponse)
async def apply_plan_event(
    service: PlanningServiceDep,
    body: PlanEventRequest,
    region_id: Annotated[int, Query(ge=1)],
    date: Annotated[date, Query()],
) -> PlanEventResponse:
    """Событие дня: отмена заявки или инженер недоступен с указанного времени.

    Считает остаток дня через `planner.replan` и возвращает, что изменилось.
    Пример: `POST /api/planning/event?region_id=1&date=2026-08-17`
    тело `{"type":"engineer_unavailable","engineer_id":6,"at":"12:00"}`.
    """
    if background.status(region_id, date)[0]:
        raise ConflictError("План уже считается — дождитесь окончания")
    return await service.apply_event(region_id, date, body)


@router.get("/plan", response_model=PlanExportResponse)
async def get_plan(
    service: PlanningServiceDep,
    region_id: Annotated[int, Query(ge=1)],
    date: Annotated[date, Query()],
    plan_id: Annotated[int | None, Query(ge=1)] = None,
    baseline: Annotated[bool, Query()] = False,
) -> PlanExportResponse:
    """План дня с расписанием: маршруты инженеров (выезд, прибытие, работа), неназначенные.

    Для карты и Ганта. `plan_id` выбирает версию, без него — последняя.
    `baseline=true` — базовый план при этой версии (алгоритм ТЗ по тем же данным), для сравнения.
    Пример: `/api/planning/plan?region_id=1&date=2026-08-17`
    """
    return await service.get_plan(region_id, date, plan_id, baseline=baseline)


@router.get("/plan/{plan_id}/slots", response_model=PlanSlotsResponse)
async def get_plan_slots(
    service: PlanningServiceDep,
    plan_id: int,
    request_id: Annotated[list[str] | None, Query()] = None,
) -> PlanSlotsResponse:
    """Куда можно поставить заявки плана — для перетаскивания на Ганте без запросов на ход.

    У каждой подвижной заявки по инженерам: позиция в маршруте и окно начала работ
    (минуты от полуночи дня плана) — раньше не доехать, позже сорвутся следующие визиты
    или смена. Окно клиента не ограничивает: вне его — с согласованием.
    `request_id` (можно несколько) сужает ответ, без него — все заявки плана.
    """
    return await service.get_slots(plan_id, request_id)


@router.post("/plan/{plan_id}/move", response_model=MoveResponse)
async def move_request(
    service: PlanningServiceDep, plan_id: int, body: MoveRequest
) -> MoveResponse:
    """Ручной ход на Ганте: поставить заявку к инженеру на время, снять или заменить.

    `commit: false` — только проверка и новое расписание изменившихся маршрутов;
    `commit: true` — ход сохраняется новой версией плана (`planId` в ответе).
    Недопустимый ход плана не меняет: `ok: false` и причина.
    """
    return await service.move(plan_id, body)

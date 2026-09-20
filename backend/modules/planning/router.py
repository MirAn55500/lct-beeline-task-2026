from typing import Annotated

from fastapi import APIRouter, Depends

from modules.planning.dependencies import get_planning_service
from modules.planning.schemas import HealthResponse
from modules.planning.service import PlanningService

router = APIRouter(prefix="/planning", tags=["planning"])

PlanningServiceDep = Annotated[PlanningService, Depends(get_planning_service)]


@router.get("/health", response_model=HealthResponse)
async def planning_health(service: PlanningServiceDep) -> HealthResponse:
    return HealthResponse(**service.health())

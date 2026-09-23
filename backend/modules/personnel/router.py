from typing import Annotated

from fastapi import APIRouter, Depends, Query

from modules.personnel.dependencies import get_personnel_service
from modules.personnel.schemas import EngineerResponse, HealthResponse
from modules.personnel.service import PersonnelService

router = APIRouter(prefix="/personnel", tags=["personnel"])

PersonnelServiceDep = Annotated[PersonnelService, Depends(get_personnel_service)]


@router.get("/health", response_model=HealthResponse)
async def personnel_health(service: PersonnelServiceDep) -> HealthResponse:
    return HealthResponse(**service.health())


@router.get("/engineers", response_model=list[EngineerResponse])
async def list_engineers(
    service: PersonnelServiceDep,
    region_id: Annotated[int, Query(ge=1)],
) -> list[EngineerResponse]:
    return await service.list_engineers(region_id)

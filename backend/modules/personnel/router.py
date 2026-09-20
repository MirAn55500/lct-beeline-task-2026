from typing import Annotated

from fastapi import APIRouter, Depends

from modules.personnel.dependencies import get_personnel_service
from modules.personnel.schemas import HealthResponse
from modules.personnel.service import PersonnelService

router = APIRouter(prefix="/personnel", tags=["personnel"])

PersonnelServiceDep = Annotated[PersonnelService, Depends(get_personnel_service)]


@router.get("/health", response_model=HealthResponse)
async def personnel_health(service: PersonnelServiceDep) -> HealthResponse:
    return HealthResponse(**service.health())

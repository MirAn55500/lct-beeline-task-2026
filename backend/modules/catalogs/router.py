from typing import Annotated

from fastapi import APIRouter, Depends

from modules.catalogs.dependencies import get_catalogs_service
from modules.catalogs.schemas import HealthResponse, RegionResponse
from modules.catalogs.service import CatalogsService

router = APIRouter(prefix="/catalogs", tags=["catalogs"])

CatalogsServiceDep = Annotated[CatalogsService, Depends(get_catalogs_service)]


@router.get("/health", response_model=HealthResponse)
async def catalogs_health(service: CatalogsServiceDep) -> HealthResponse:
    return HealthResponse(**service.health())


@router.get("/regions", response_model=list[RegionResponse])
async def list_regions(service: CatalogsServiceDep) -> list[RegionResponse]:
    regions = await service.list_regions()
    return [RegionResponse.model_validate(region) for region in regions]

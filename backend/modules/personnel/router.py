from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from modules.personnel.dependencies import get_personnel_service
from modules.personnel.schemas import (
    BrigadeResponse,
    CreateEngineerRequest,
    EngineerResponse,
    EngineersQuery,
    HealthResponse,
    PersonnelFilterOptions,
)
from modules.personnel.service import PersonnelService

router = APIRouter(prefix="/personnel", tags=["personnel"])

PersonnelServiceDep = Annotated[PersonnelService, Depends(get_personnel_service)]


@router.get("/health", response_model=HealthResponse)
async def personnel_health(service: PersonnelServiceDep) -> HealthResponse:
    return HealthResponse(**service.health())


@router.get("/filter-options", response_model=PersonnelFilterOptions)
async def personnel_filter_options(
    service: PersonnelServiceDep,
) -> PersonnelFilterOptions:
    """Справочники фильтров страницы «Персонал»."""
    return service.filter_options()


@router.get("/brigades", response_model=list[BrigadeResponse])
async def list_brigades(
    service: PersonnelServiceDep,
    region_id: Annotated[int | None, Query(ge=1)] = None,
) -> list[BrigadeResponse]:
    """Бригады региона или все бригады, если region_id не задан."""
    return await service.list_brigades(region_id)


@router.get("/engineers", response_model=list[EngineerResponse])
async def list_engineers(
    service: PersonnelServiceDep,
    region_id: Annotated[int | None, Query(ge=1)] = None,
    brigade_id: Annotated[int | None, Query(ge=1)] = None,
    q: Annotated[str | None, Query()] = None,
    qualification: Annotated[list[str] | None, Query()] = None,
    skill: Annotated[list[str] | None, Query()] = None,
    transport: Annotated[list[str] | None, Query()] = None,
) -> list[EngineerResponse]:
    """Инженеры региона и/или бригады с фильтрами страницы «Персонал».

    Для обзора дня достаточно `region_id`. Для таблицы бригады — `brigade_id`.
    """
    return await service.list_engineers(
        EngineersQuery(
            region_id=region_id,
            brigade_id=brigade_id,
            q=q,
            qualification=qualification or [],
            skill=skill or [],
            transport=transport or [],
        )
    )


@router.post(
    "/engineers",
    response_model=EngineerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_engineer(
    service: PersonnelServiceDep,
    body: CreateEngineerRequest,
) -> EngineerResponse:
    return await service.create_engineer(body)


@router.delete("/engineers/{engineer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_engineer(
    service: PersonnelServiceDep,
    engineer_id: int,
) -> None:
    await service.delete_engineer(engineer_id)

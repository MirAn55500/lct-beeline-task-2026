from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from modules.personnel.dependencies import get_personnel_service
from modules.planning import board as plan_boards
from modules.personnel.schemas import (
    AddressSuggestionResponse,
    AreaResponse,
    BrigadeResponse,
    CreateBrigadeRequest,
    CreateEngineerRequest,
    EngineerResponse,
    EngineersQuery,
    HealthResponse,
    PersonnelFilterOptions,
    ReverseGeocodeResponse,
    UpdateBrigadeRequest,
    UpdateBrigadeResponse,
    UpdateEngineerRequest,
    UpdateEngineerPlanningRequest,
    UploadEngineersResult,
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


@router.post(
    "/brigades",
    response_model=BrigadeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_brigade(
    service: PersonnelServiceDep,
    body: CreateBrigadeRequest,
) -> BrigadeResponse:
    """Новая бригада в регионе: офис, смена и рабочие дни."""
    return await service.create_brigade(body)


@router.patch("/brigades/{brigade_id}", response_model=UpdateBrigadeResponse)
async def update_brigade(
    service: PersonnelServiceDep,
    brigade_id: int,
    body: UpdateBrigadeRequest,
) -> UpdateBrigadeResponse:
    """Карточка «Управление бригадой»: офис, районы, рабочие дни и часы."""
    response = await service.update_brigade(brigade_id, body)
    # Доски ручной правки держат смены и обеды в памяти — окна Ганта считались бы по старым
    plan_boards.clear()
    return response


@router.get("/address-suggest", response_model=list[AddressSuggestionResponse])
async def address_suggest(
    service: PersonnelServiceDep,
    q: Annotated[str, Query(min_length=3, max_length=200)],
) -> list[AddressSuggestionResponse]:
    """Подсказки адресов Москвы и области для поля «Адрес офиса»."""
    return await service.suggest_addresses(q)


@router.get("/reverse-geocode", response_model=ReverseGeocodeResponse)
async def reverse_geocode(
    service: PersonnelServiceDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> ReverseGeocodeResponse:
    """Адрес точки, которую поставили на карте, — подпись офиса бригады."""
    return await service.reverse_geocode(lat, lon)


@router.get("/areas", response_model=list[AreaResponse])
async def list_areas(
    service: PersonnelServiceDep,
    region_id: Annotated[int, Query(ge=1)],
) -> list[AreaResponse]:
    """Районы региона — варианты для районов бригады."""
    return await service.list_areas(region_id)


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
    response = await service.create_engineer(body)
    plan_boards.clear()
    return response


@router.post("/engineers/upload", response_model=UploadEngineersResult)
async def upload_engineers(
    service: PersonnelServiceDep,
    file: Annotated[UploadFile, File()],
    brigade_id: Annotated[int, Form(ge=1)],
) -> UploadEngineersResult:
    """Загрузка CSV/JSON профилей в бригаду. Поля: `file`, `brigade_id`."""
    raw = await file.read()
    return await service.upload_engineers(
        brigade_id=brigade_id,
        filename=file.filename or "engineers.csv",
        raw=raw,
    )


@router.patch("/engineers/{engineer_id}", response_model=EngineerResponse)
async def update_engineer(
    service: PersonnelServiceDep,
    engineer_id: int,
    body: UpdateEngineerRequest,
) -> EngineerResponse:
    """Карточка инженера: не переданные часы и рабочие дни — как у бригады."""
    response = await service.update_engineer(engineer_id, body)
    plan_boards.clear()
    return response


@router.patch("/engineers/{engineer_id}/planning", response_model=EngineerResponse)
async def update_engineer_planning(
    service: PersonnelServiceDep,
    engineer_id: int,
    body: UpdateEngineerPlanningRequest,
) -> EngineerResponse:
    """Включить или исключить инженера из следующих расчётов плана."""
    response = await service.update_engineer_planning(engineer_id, body)
    plan_boards.clear()
    return response


@router.delete("/engineers/{engineer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_engineer(
    service: PersonnelServiceDep,
    engineer_id: int,
) -> None:
    await service.delete_engineer(engineer_id)
    plan_boards.clear()

from datetime import date, time
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from modules.tickets.dependencies import get_tickets_service
from modules.planning.schemas import RemakeLevel
from modules.tickets.schemas import (
    CreateTicketRequest,
    CreateTicketResult,
    HealthResponse,
    TicketAssignmentFilter,
    TicketResponse,
    TicketsQuery,
    UploadTicketsResult,
)
from modules.tickets.service import TicketsService

router = APIRouter(prefix="/tickets", tags=["tickets"])

TicketsServiceDep = Annotated[TicketsService, Depends(get_tickets_service)]


@router.get("/health", response_model=HealthResponse)
async def tickets_health(service: TicketsServiceDep) -> HealthResponse:
    return HealthResponse(**service.health())


@router.get("", response_model=list[TicketResponse])
async def list_tickets(
    service: TicketsServiceDep,
    region_id: Annotated[int, Query(ge=1)],
    date: Annotated[date, Query()],
    plan_id: Annotated[int | None, Query(ge=1)] = None,
    assignment: Annotated[TicketAssignmentFilter, Query()] = TicketAssignmentFilter.ALL,
    q: Annotated[str | None, Query()] = None,
    work_type: Annotated[list[str] | None, Query()] = None,
    reason: Annotated[list[str] | None, Query()] = None,
    time_from: Annotated[time | None, Query()] = None,
    time_to: Annotated[time | None, Query()] = None,
) -> list[TicketResponse]:
    """Заявки региона на дату: все, только назначенные или только неназначенные.

    Пример:
    `/api/tickets?region_id=1&date=2026-08-17&assignment=assigned`
    """
    return await service.list_tickets(
        TicketsQuery(
            region_id=region_id,
            date=date,
            plan_id=plan_id,
            assignment=assignment,
            q=q,
            work_type=work_type or [],
            reason=reason or [],
            time_from=time_from,
            time_to=time_to,
        )
    )


@router.get("/unassigned", response_model=list[TicketResponse])
async def list_unassigned(
    service: TicketsServiceDep,
    region_id: Annotated[int, Query(ge=1)],
    date: Annotated[date, Query()],
    q: Annotated[str | None, Query()] = None,
    work_type: Annotated[list[str] | None, Query()] = None,
    reason: Annotated[list[str] | None, Query()] = None,
    time_from: Annotated[time | None, Query()] = None,
    time_to: Annotated[time | None, Query()] = None,
) -> list[TicketResponse]:
    """Неназначенные заявки региона на дату."""
    return await service.list_unassigned(
        TicketsQuery(
            region_id=region_id,
            date=date,
            q=q,
            work_type=work_type or [],
            reason=reason or [],
            time_from=time_from,
            time_to=time_to,
        )
    )


@router.post("/upload", response_model=UploadTicketsResult)
async def upload_tickets(
    service: TicketsServiceDep,
    file: Annotated[UploadFile, File()],
    region_id: Annotated[int, Form(ge=1)],
    date: Annotated[date, Form()],
    remake_level: Annotated[RemakeLevel, Form()] = RemakeLevel.FREE,
) -> UploadTicketsResult:
    """Загрузка CSV заявок и расчёт плана на даты из файла.

    Ответ приходит, как только заявки записаны; план считается в фоне, и пока он не
    готов, `/api/planning/day-overview` отдаёт `planning: true`.
    Поля формы: `file`, `region_id`, `date` (`YYYY-MM-DD`), `remake_level`.
    Дата заявки берётся из файла. `date` нужен, только если в строке времени нет даты.
    `remake_level` — уровень перестроения: `fix` и `engineer` ставят новые заявки
    в последнюю версию плана дня, `free` (по умолчанию) считает день заново.
    """
    raw = await file.read()
    return await service.upload(
        region_id=region_id,
        day=date,
        filename=file.filename or "upload.csv",
        raw=raw,
        remake_level=remake_level,
    )


@router.post("", response_model=CreateTicketResult)
async def create_ticket(service: TicketsServiceDep, body: CreateTicketRequest) -> CreateTicketResult:
    """Одна заявка вручную (окно «Добавить заявку») и её постановка в план дня.

    Номер назначается следующим после самого большого. План считается в фоне, как после
    загрузки; `remake_level` по умолчанию `free` для аварии (пересчёт дня), иначе `fix` —
    только свободные окна.
    """
    return await service.create(body)

from typing import Annotated

from fastapi import APIRouter, Depends

from modules.tickets.dependencies import get_tickets_service
from modules.tickets.schemas import HealthResponse
from modules.tickets.service import TicketsService

router = APIRouter(prefix="/tickets", tags=["tickets"])

TicketsServiceDep = Annotated[TicketsService, Depends(get_tickets_service)]


@router.get("/health", response_model=HealthResponse)
async def tickets_health(service: TicketsServiceDep) -> HealthResponse:
    return HealthResponse(**service.health())

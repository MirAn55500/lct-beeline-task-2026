from core.deps import SessionDep
from modules.tickets.service import TicketsService


def get_tickets_service(session: SessionDep) -> TicketsService:
    return TicketsService(session)

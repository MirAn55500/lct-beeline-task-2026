from sqlmodel.ext.asyncio.session import AsyncSession

from modules.tickets.repository import TicketsRepository


class TicketsService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = TicketsRepository(session)

    def health(self) -> dict[str, str]:
        return {"module": "tickets", "status": "ok"}

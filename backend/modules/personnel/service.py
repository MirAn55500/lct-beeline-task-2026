from sqlmodel.ext.asyncio.session import AsyncSession

from modules.personnel.repository import PersonnelRepository


class PersonnelService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = PersonnelRepository(session)

    def health(self) -> dict[str, str]:
        return {"module": "personnel", "status": "ok"}

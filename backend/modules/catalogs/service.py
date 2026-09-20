from sqlmodel.ext.asyncio.session import AsyncSession

from modules.catalogs.repository import CatalogsRepository


class CatalogsService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = CatalogsRepository(session)

    def health(self) -> dict[str, str]:
        return {"module": "catalogs", "status": "ok"}

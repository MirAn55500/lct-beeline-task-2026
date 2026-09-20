from sqlmodel.ext.asyncio.session import AsyncSession


class CatalogsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.catalogs.models.region import Region


class CatalogsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_regions(self) -> list[Region]:
        result = await self._session.exec(
            select(Region).order_by(Region.region_name)
        )
        return list(result.all())

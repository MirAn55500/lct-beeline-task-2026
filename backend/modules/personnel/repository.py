from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.personnel.models.brigade import Brigade
from modules.personnel.models.engineer import Engineer
from modules.personnel.models.engineer_skill import EngineerSkill


class PersonnelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_engineers_by_region(self, region_id: int) -> list[Engineer]:
        result = await self._session.exec(
            select(Engineer)
            .join(Brigade, Engineer.brigade_id == Brigade.brigade_id)
            .where(Brigade.region_id == region_id)
            .options(
                selectinload(Engineer.transport),
                selectinload(Engineer.skills).selectinload(EngineerSkill.skill),
            )
            .order_by(Engineer.name)
        )
        return list(result.all())

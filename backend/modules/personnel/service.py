from sqlmodel.ext.asyncio.session import AsyncSession

from modules.personnel.repository import PersonnelRepository
from modules.personnel.schemas import EngineerResponse
from modules.personnel.transport import map_transport


class PersonnelService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = PersonnelRepository(session)

    def health(self) -> dict[str, str]:
        return {"module": "personnel", "status": "ok"}

    async def list_engineers(self, region_id: int) -> list[EngineerResponse]:
        engineers = await self._repo.list_engineers_by_region(region_id)
        items: list[EngineerResponse] = []

        for engineer in engineers:
            transport_code, transport_label = map_transport(
                engineer.transport.value if engineer.transport else None
            )
            skill_label = None
            if engineer.skills:
                first = engineer.skills[0].skill
                if first is not None:
                    skill_label = first.value

            items.append(
                EngineerResponse(
                    id=engineer.engineer_id or 0,
                    name=engineer.name,
                    transport=transport_code,
                    transport_label=transport_label,
                    skill=skill_label,
                )
            )

        return items

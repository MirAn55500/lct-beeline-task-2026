from sqlmodel.ext.asyncio.session import AsyncSession

from modules.algorithm.service import AlgorithmService
from modules.planning.repository import PlanningRepository


class PlanningService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = PlanningRepository(session)
        self._algorithm = AlgorithmService()

    def health(self) -> dict[str, str]:
        return {"module": "planning", "status": "ok"}

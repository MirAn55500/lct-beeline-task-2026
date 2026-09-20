from core.deps import SessionDep
from modules.planning.service import PlanningService


def get_planning_service(session: SessionDep) -> PlanningService:
    return PlanningService(session)

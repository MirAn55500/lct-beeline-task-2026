from core.deps import SessionDep
from modules.personnel.service import PersonnelService


def get_personnel_service(session: SessionDep) -> PersonnelService:
    return PersonnelService(session)

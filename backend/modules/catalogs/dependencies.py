from fastapi import Depends

from core.deps import SessionDep
from modules.catalogs.service import CatalogsService


def get_catalogs_service(session: SessionDep) -> CatalogsService:
    return CatalogsService(session)

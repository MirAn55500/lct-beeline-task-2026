from fastapi import APIRouter

from modules.catalogs.router import router as catalogs_router
from modules.personnel.router import router as personnel_router
from modules.planning.router import router as planning_router
from modules.tickets.router import router as tickets_router

api_router = APIRouter(prefix="/api")
api_router.include_router(catalogs_router)
api_router.include_router(personnel_router)
api_router.include_router(tickets_router)
api_router.include_router(planning_router)

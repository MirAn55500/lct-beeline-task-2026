from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import selectinload
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.catalogs.enums import DictGroup
from modules.catalogs.models.dictionary import Dictionary
from modules.personnel.models.brigade import Brigade
from modules.personnel.models.engineer import Engineer
from modules.personnel.models.engineer_equipment import EngineerEquipment
from modules.personnel.models.engineer_skill import EngineerSkill
from modules.planning.models.assignment import Assignment
from modules.planning.models.plan import Plan
from modules.planning.models.replan_event import ReplanEvent
from modules.planning.models.route import Route
from modules.tickets.models.request import Request
from modules.tickets.models.status_change import StatusChange


class PlanningRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def find_latest_plan(self, region_id: int, day: date) -> Plan | None:
        result = await self._session.exec(
            select(Plan)
            .where(Plan.region_id == region_id, Plan.date == day)
            .order_by(col(Plan.version).desc(), col(Plan.created_at).desc())
            .limit(1)
        )
        return result.first()

    async def list_plans(self, region_id: int, day: date) -> list[Plan]:
        result = await self._session.exec(
            select(Plan)
            .where(Plan.region_id == region_id, Plan.date == day)
            .order_by(col(Plan.version).desc(), col(Plan.created_at).desc())
        )
        return list(result.all())

    async def count_requests(self, region_id: int, day: date) -> int:
        result = await self._session.exec(
            select(func.count())
            .select_from(Request)
            .where(Request.region_id == region_id, Request.date == day)
        )
        return int(result.one())

    async def count_assigned_requests(
        self, plan_id: int, region_id: int
    ) -> int:
        result = await self._session.exec(
            select(func.count())
            .select_from(Assignment)
            .join(Request, Assignment.request_id == Request.request_id)
            .where(
                Assignment.plan_id == plan_id,
                Request.region_id == region_id,
                Assignment.engineer_id.is_not(None),
            )
        )
        return int(result.one())

    async def count_engineers(self, region_id: int) -> int:
        result = await self._session.exec(
            select(func.count())
            .select_from(Engineer)
            .join(Brigade, Engineer.brigade_id == Brigade.brigade_id)
            .where(Brigade.region_id == region_id)
        )
        return int(result.one())

    async def count_engaged_engineers(
        self, plan_id: int, region_id: int
    ) -> int:
        result = await self._session.exec(
            select(func.count(func.distinct(Assignment.engineer_id)))
            .select_from(Assignment)
            .join(Request, Assignment.request_id == Request.request_id)
            .where(
                Assignment.plan_id == plan_id,
                Request.region_id == region_id,
                Assignment.engineer_id.is_not(None),
            )
        )
        return int(result.one())

    async def list_planned_dates(self, region_id: int) -> list[date]:
        result = await self._session.exec(
            select(Plan.date)
            .where(Plan.region_id == region_id)
            .distinct()
            .order_by(col(Plan.date).asc())
        )
        return list(result.all())

    async def list_requests_for_plan(self, region_id: int, day: date) -> list[Request]:
        result = await self._session.exec(
            select(Request)
            .where(Request.region_id == region_id, Request.date == day)
            .options(
                selectinload(Request.address_ref),
                selectinload(Request.skill),
                selectinload(Request.priority),
                selectinload(Request.transport),
                selectinload(Request.status),
                selectinload(Request.request_type_vk),
            )
            .order_by(col(Request.request_id).asc())
        )
        return list(result.all())

    async def list_engineers_for_plan(self, region_id: int) -> list[Engineer]:
        result = await self._session.exec(
            select(Engineer)
            .join(Brigade, Engineer.brigade_id == Brigade.brigade_id)
            .where(Brigade.region_id == region_id)
            .options(
                selectinload(Engineer.transport),
                selectinload(Engineer.brigade).selectinload(Brigade.office_address),
                selectinload(Engineer.skills).selectinload(EngineerSkill.skill),
                selectinload(Engineer.equipment).selectinload(EngineerEquipment.item),
            )
            .order_by(col(Engineer.engineer_id).asc())
        )
        return list(result.all())

    async def get_region(self, region_id: int):
        from modules.catalogs.models.region import Region

        return await self._session.get(Region, region_id)

    async def list_unassigned_reasons(self) -> list[Dictionary]:
        result = await self._session.exec(
            select(Dictionary).where(Dictionary.group == DictGroup.UNASSIGNED_REASON)
        )
        return list(result.all())

    async def ensure_dict(self, group: DictGroup, value: str) -> int:
        found = (
            await self._session.exec(
                select(Dictionary).where(
                    Dictionary.group == group, Dictionary.value == value
                )
            )
        ).first()
        if found is not None and found.dict_id is not None:
            return found.dict_id
        row = Dictionary(value=value, group=group)
        self._session.add(row)
        await self._session.flush()
        return row.dict_id or 0

    async def ensure_unassigned_reasons(self) -> list[Dictionary]:
        from modules.catalogs.seed_values import UNASSIGNED_REASON_SEED

        for _, code in UNASSIGNED_REASON_SEED:
            await self.ensure_dict(DictGroup.UNASSIGNED_REASON, code)
        return await self.list_unassigned_reasons()

    async def list_route_paths(self, plan_id: int) -> dict[int, dict]:
        """assignment_id → path участка (линия и состав поездки) для плана."""
        result = await self._session.exec(
            select(Route.assignment_id, Route.path)
            .join(Assignment, Route.assignment_id == Assignment.assignment_id)
            .where(Assignment.plan_id == plan_id)
        )
        return {assignment_id: path or {} for assignment_id, path in result.all()}

    async def list_route_legs(self, plan_id: int) -> dict[int, tuple[int | None, dict]]:
        """request_id → (engineer_id, участок до визита) — поля `routes` для копии в новую версию."""
        result = await self._session.exec(
            select(
                Assignment.request_id,
                Assignment.engineer_id,
                Route.start_point_id,
                Route.end_point_id,
                Route.transport_id,
                Route.start_time,
                Route.end_time,
                Route.path,
            )
            .join(Assignment, Route.assignment_id == Assignment.assignment_id)
            .where(Assignment.plan_id == plan_id)
        )
        return {
            request_id: (
                engineer_id,
                {
                    "start_point_id": start_point_id,
                    "end_point_id": end_point_id,
                    "transport_id": transport_id,
                    "start_time": start_time,
                    "end_time": end_time,
                    "path": path,
                },
            )
            for request_id, engineer_id, start_point_id, end_point_id, transport_id, start_time, end_time, path in result.all()
        }

    async def shift_request_window(self, request_id: int, minutes: float) -> None:
        """Сдвигает окно клиента заявки — без commit: сохраняется вместе с версией плана."""
        request = await self._session.get(Request, request_id)
        if request is None:
            return
        shift = timedelta(minutes=minutes)
        request.plan_start_time = request.plan_start_time + shift
        request.plan_end_time = request.plan_end_time + shift
        self._session.add(request)

    async def travel_totals(self, plan_id: int) -> tuple[float, float]:
        """Сумма минут в пути и километров по назначенным визитам плана."""
        result = await self._session.exec(
            select(
                func.coalesce(func.sum(Assignment.travel_minutes), 0.0),
                func.coalesce(func.sum(Assignment.distance_km), 0.0),
            ).where(
                Assignment.plan_id == plan_id,
                col(Assignment.engineer_id).is_not(None),
            )
        )
        minutes, km = result.one()
        return float(minutes or 0), float(km or 0)

    async def unavailable_cutoffs(self, day: date) -> dict[str, datetime]:
        """Самый ранний момент недоступности инженера в этот день. Ключ — id инженера строкой."""
        start = datetime.combine(day, time.min)
        result = await self._session.exec(
            select(ReplanEvent).where(
                ReplanEvent.event_type == "engineer_unavailable",
                ReplanEvent.event_time >= start,
                ReplanEvent.event_time < start + timedelta(days=1),
                col(ReplanEvent.engineer_id).is_not(None),
            )
        )
        cutoffs: dict[str, datetime] = {}
        for event in result.all():
            if event.engineer_id is None:
                continue
            key = str(event.engineer_id)
            moment = event.event_time
            previous = cutoffs.get(key)
            if previous is None or moment < previous:
                cutoffs[key] = moment
        return cutoffs

    async def cancel_request(self, request_id: int, at: datetime) -> None:
        request = (
            await self._session.exec(
                select(Request)
                .where(Request.request_id == request_id)
                .options(selectinload(Request.status))
            )
        ).first()
        if request is None:
            return
        status = request.status.value.strip().lower() if request.status else ""
        if status in {"cancelled", "отменена"}:
            return
        new_status_id = await self.ensure_dict(DictGroup.STATUS, "cancelled")
        self._session.add(
            StatusChange(
                prev_status_id=request.status_id,
                new_status_id=new_status_id,
                request_id=request_id,
                status_change_dt=at,
            )
        )
        request.status_id = new_status_id
        self._session.add(request)

    async def add_replan_event(
        self,
        *,
        event_type: str,
        event_time: datetime,
        request_id: int | None,
        engineer_id: int | None,
    ) -> None:
        self._session.add(
            ReplanEvent(
                event_type=event_type,
                event_time=event_time.replace(tzinfo=None),
                request_id=request_id,
                engineer_id=engineer_id,
            )
        )

    async def list_assignments(self, plan_id: int) -> list[Assignment]:
        result = await self._session.exec(
            select(Assignment)
            .where(Assignment.plan_id == plan_id)
            .options(selectinload(Assignment.unassigned_reason))
            .order_by(col(Assignment.engineer_id), col(Assignment.position))
        )
        return list(result.all())

    async def save_plan(
        self,
        *,
        region_id: int,
        day: date,
        version: int,
        reference_plan_id: int | None,
        rows: list[Assignment],
        legs: dict[int, dict] | None = None,
    ) -> Plan:
        plan = Plan(
            version=version,
            date=day,
            region_id=region_id,
            created_at=datetime.now(),
            reference_plan_id=reference_plan_id,
        )
        self._session.add(plan)
        await self._session.flush()
        for row in rows:
            row.plan_id = plan.plan_id or 0
            self._session.add(row)
        if legs:
            await self._session.flush()
            for row in rows:
                leg = legs.get(row.request_id)
                if leg is not None and row.engineer_id is not None and row.assignment_id is not None:
                    self._session.add(Route(assignment_id=row.assignment_id, is_active=True, **leg))
        await self._session.commit()
        await self._session.refresh(plan)
        return plan

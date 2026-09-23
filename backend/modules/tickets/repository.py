from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from modules.catalogs.enums import DictGroup
from modules.catalogs.models.address import Address
from modules.catalogs.models.area import Area
from modules.catalogs.models.dictionary import Dictionary
from modules.catalogs.models.region import Region
from modules.planning.models.assignment import Assignment
from modules.planning.models.plan import Plan
from modules.tickets.importer import ParsedTicket
from modules.tickets.models.request import Request
from modules.tickets.models.snapshot_item import SnapshotItem
from modules.tickets.models.upload_snapshot import UploadSnapshot


class TicketsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_plan(self, plan_id: int) -> Plan | None:
        return await self._session.get(Plan, plan_id)

    async def find_latest_plan_id(self, *, region_id: int, day: date) -> int | None:
        result = await self._session.exec(
            select(Plan.plan_id)
            .where(Plan.region_id == region_id, Plan.date == day)
            .order_by(col(Plan.version).desc(), col(Plan.created_at).desc())
            .limit(1)
        )
        return result.first()

    async def list_requests_for_day(
        self,
        *,
        region_id: int,
        day: date,
    ) -> list[Request]:
        result = await self._session.exec(
            select(Request)
            .where(Request.region_id == region_id, Request.date == day)
            .options(
                selectinload(Request.address_ref),
                selectinload(Request.request_type_vk),
                selectinload(Request.priority),
            )
            .order_by(col(Request.plan_start_time).asc(), col(Request.external_id).asc())
        )
        return list(result.all())

    async def list_assignments_for_plan(
        self,
        plan_id: int,
        request_ids: list[int],
    ) -> list[Assignment]:
        if not request_ids:
            return []
        result = await self._session.exec(
            select(Assignment)
            .where(
                Assignment.plan_id == plan_id,
                col(Assignment.request_id).in_(request_ids),
            )
            .options(
                selectinload(Assignment.unassigned_reason),
                selectinload(Assignment.engineer),
            )
        )
        return list(result.all())

    async def get_region(self, region_id: int) -> Region | None:
        return await self._session.get(Region, region_id)

    async def ensure_dict(self, group: DictGroup, value: str) -> int:
        label = value.strip() or "—"
        result = await self._session.exec(
            select(Dictionary).where(
                Dictionary.group == group,
                Dictionary.value == label,
            )
        )
        row = result.first()
        if row is not None and row.dict_id is not None:
            return row.dict_id
        row = Dictionary(value=label, group=group)
        self._session.add(row)
        await self._session.flush()
        return row.dict_id or 0

    async def ensure_address(
        self,
        *,
        region_id: int,
        district: str,
        address: str,
        latitude: float,
        longitude: float,
    ) -> int:
        area_name = district.strip() or "—"
        area_result = await self._session.exec(
            select(Area).where(Area.region_id == region_id, Area.area == area_name)
        )
        area = area_result.first()
        if area is None:
            area = Area(area=area_name, region_id=region_id)
            self._session.add(area)
            await self._session.flush()

        address_result = await self._session.exec(
            select(Address).where(
                Address.area_id == area.id,
                Address.address == address,
            )
        )
        found = address_result.first()
        if found is not None and found.address_id is not None:
            return found.address_id
        created = Address(
            area_id=area.id or 0,
            address=address,
            latitude=latitude,
            longitude=longitude,
        )
        self._session.add(created)
        await self._session.flush()
        return created.address_id or 0

    async def find_request(self, region_id: int, external_id: str) -> Request | None:
        result = await self._session.exec(
            select(Request).where(
                Request.region_id == region_id,
                Request.external_id == external_id,
            )
        )
        return result.first()

    async def save_upload(
        self,
        *,
        region_id: int,
        filename: str,
        file_type: str,
        tickets: list[ParsedTicket],
        skipped: int,
    ) -> tuple[int, int, int]:
        created = 0
        updated = 0
        upload_type_id = await self.ensure_dict(DictGroup.UPLOAD_TYPE, "request")
        file_type_id = await self.ensure_dict(DictGroup.FILE_TYPE, file_type)
        created_action_id = await self.ensure_dict(DictGroup.SNAPSHOT_ACTION, "created")
        updated_action_id = await self.ensure_dict(DictGroup.SNAPSHOT_ACTION, "updated")

        snapshot = UploadSnapshot(
            upload_dt=datetime.now(),
            upload_type_id=upload_type_id,
            filename=filename,
            file_type_id=file_type_id,
            region_id=region_id,
            created=0,
            updated=0,
            skipped=skipped,
        )
        self._session.add(snapshot)
        await self._session.flush()

        for ticket in tickets:
            address_id = await self.ensure_address(
                region_id=region_id,
                district=ticket.district,
                address=ticket.address,
                latitude=ticket.latitude,
                longitude=ticket.longitude,
            )
            priority_id = await self.ensure_dict(DictGroup.PRIORITY, ticket.priority)
            status_id = await self.ensure_dict(DictGroup.STATUS, ticket.status)
            skill_id = await self.ensure_dict(DictGroup.SKILL, ticket.skill)
            vk_id = await self.ensure_dict(DictGroup.REQUEST_TYPE_VK, ticket.category)
            hd_id = await self.ensure_dict(DictGroup.REQUEST_TYPE_HD, ticket.hd)

            ticket_day = ticket.window_start.date()
            existing = await self.find_request(region_id, ticket.external_id)
            if existing is None:
                request = Request(
                    external_id=ticket.external_id,
                    address_id=address_id,
                    date=ticket_day,
                    plan_start_time=ticket.window_start,
                    plan_end_time=ticket.window_end,
                    priority_id=priority_id,
                    status_id=status_id,
                    skill_id=skill_id,
                    region_id=region_id,
                    request_type_vk_id=vk_id,
                    request_type_hd_id=hd_id,
                )
                self._session.add(request)
                await self._session.flush()
                action_id = created_action_id
                request_id = request.request_id
                created += 1
            else:
                changed = (
                    existing.address_id != address_id
                    or existing.date != ticket_day
                    or existing.plan_start_time != ticket.window_start
                    or existing.plan_end_time != ticket.window_end
                    or existing.priority_id != priority_id
                    or existing.status_id != status_id
                    or existing.skill_id != skill_id
                    or existing.request_type_vk_id != vk_id
                    or existing.request_type_hd_id != hd_id
                )
                if not changed:
                    skipped += 1
                    continue
                existing.address_id = address_id
                existing.date = ticket_day
                existing.plan_start_time = ticket.window_start
                existing.plan_end_time = ticket.window_end
                existing.priority_id = priority_id
                existing.status_id = status_id
                existing.skill_id = skill_id
                existing.request_type_vk_id = vk_id
                existing.request_type_hd_id = hd_id
                action_id = updated_action_id
                request_id = existing.request_id
                updated += 1

            self._session.add(
                SnapshotItem(
                    snapshoot_id=snapshot.snapshoot_id or 0,
                    action_type_id=action_id,
                    request_id=request_id,
                )
            )

        snapshot.created = created
        snapshot.updated = updated
        snapshot.skipped = skipped
        await self._session.commit()
        return created, updated, skipped

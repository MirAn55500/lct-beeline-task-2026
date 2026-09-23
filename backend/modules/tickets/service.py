from __future__ import annotations

import json
from collections import Counter
from datetime import date, time

from sqlmodel.ext.asyncio.session import AsyncSession

from core.exceptions import AppError
from modules.planning.models.assignment import Assignment
from modules.planning.service import PlanningService
from modules.tickets.importer import parse_upload
from modules.tickets.models.request import Request
from modules.tickets.repository import TicketsRepository
from modules.tickets.schemas import (
    TicketAssignmentFilter,
    TicketResponse,
    TicketsQuery,
    UploadTicketsResult,
)


def _format_window(start, end) -> str:
    return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"


def _time_of(dt) -> time:
    return dt.time().replace(tzinfo=None) if dt.tzinfo else dt.time()


def _window_overlaps(
    start,
    end,
    time_from: time | None,
    time_to: time | None,
) -> bool:
    if time_from is None and time_to is None:
        return True
    start_t = _time_of(start)
    end_t = _time_of(end)
    from_t = time_from or time(0, 0)
    to_t = time_to or time(23, 59, 59)
    return start_t < to_t and end_t > from_t


def _matches_query(
    request: Request,
    reason: str | None,
    engineer: str | None,
    q: str,
) -> bool:
    needle = q.strip().lower()
    if not needle:
        return True
    haystacks = [
        request.external_id,
        request.address_ref.address if request.address_ref else "",
        request.request_type_vk.value if request.request_type_vk else "",
        reason or "",
        engineer or "",
    ]
    return any(needle in (item or "").lower() for item in haystacks)


class TicketsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TicketsRepository(session)

    def health(self) -> dict[str, str]:
        return {"module": "tickets", "status": "ok"}

    async def _plan_id(self, query: TicketsQuery) -> int | None:
        if query.plan_id is None:
            return await self._repo.find_latest_plan_id(
                region_id=query.region_id,
                day=query.date,
            )
        plan = await self._repo.get_plan(query.plan_id)
        if (
            plan is None
            or plan.region_id != query.region_id
            or plan.date != query.date
        ):
            raise AppError("План не найден", status_code=404)
        return plan.plan_id

    async def list_tickets(self, query: TicketsQuery) -> list[TicketResponse]:
        requests = await self._repo.list_requests_for_day(
            region_id=query.region_id,
            day=query.date,
        )
        if not requests:
            return []

        plan_id = await self._plan_id(query)
        assignment_by_request: dict[int, Assignment] = {}
        if plan_id is not None:
            request_ids = [item.request_id for item in requests if item.request_id is not None]
            assignments = await self._repo.list_assignments_for_plan(plan_id, request_ids)
            assignment_by_request = {
                item.request_id: item
                for item in assignments
                if item.request_id is not None
            }

        items: list[TicketResponse] = []
        for request in requests:
            assert request.request_id is not None
            assignment = assignment_by_request.get(request.request_id)
            assigned = assignment is not None and assignment.engineer_id is not None
            if query.assignment is TicketAssignmentFilter.ASSIGNED and not assigned:
                continue
            if query.assignment is TicketAssignmentFilter.UNASSIGNED and assigned:
                continue

            reason = None
            engineer = None
            if assigned and assignment is not None and assignment.engineer is not None:
                engineer = assignment.engineer.name
            elif assignment is not None and assignment.unassigned_reason is not None:
                reason = assignment.unassigned_reason.value

            category = request.request_type_vk.value if request.request_type_vk else ""
            address = request.address_ref.address if request.address_ref else ""

            if query.work_type and category not in query.work_type:
                continue
            if query.reason and (reason is None or reason not in query.reason):
                continue
            if not _window_overlaps(
                request.plan_start_time,
                request.plan_end_time,
                query.time_from,
                query.time_to,
            ):
                continue
            if query.q and not _matches_query(request, reason, engineer, query.q):
                continue

            items.append(
                TicketResponse(
                    id=request.request_id,
                    number=request.external_id,
                    category=category,
                    reason=reason,
                    engineer=engineer,
                    assigned=assigned,
                    window=_format_window(request.plan_start_time, request.plan_end_time),
                    window_start=request.plan_start_time,
                    window_end=request.plan_end_time,
                    address=address,
                )
            )

        def sort_key(item: TicketResponse) -> tuple:
            cat = item.category.lower()
            emergency = 0 if ("авар" in cat or "emergency" in cat) else 1
            pending = 0 if not item.assigned else 1
            return (pending, emergency, item.window_start, item.number)

        items.sort(key=sort_key)
        return items

    async def list_unassigned(self, query: TicketsQuery) -> list[TicketResponse]:
        return await self.list_tickets(
            query.model_copy(update={"assignment": TicketAssignmentFilter.UNASSIGNED})
        )

    async def upload(
        self,
        *,
        region_id: int,
        day: date,
        filename: str,
        raw: bytes,
    ) -> UploadTicketsResult:
        region = await self._repo.get_region(region_id)
        if region is None:
            raise AppError("Регион не найден", status_code=404)
        if not raw:
            raise AppError("Файл пустой")

        try:
            tickets, skipped = parse_upload(raw, filename, day)
        except (ValueError, json.JSONDecodeError) as exc:
            raise AppError(str(exc)) from exc

        file_type = "json" if filename.lower().endswith(".json") else "csv"
        created, updated, skipped = await self._repo.save_upload(
            region_id=region_id,
            filename=filename or "upload.csv",
            file_type=file_type,
            tickets=tickets,
            skipped=skipped,
        )

        counts = Counter(ticket.window_start.date() for ticket in tickets)
        primary = counts.most_common(1)[0][0] if counts else None
        plan_id = None
        plan_version = None
        if counts:
            planner = PlanningService(self._session)
            for ticket_day in sorted(counts):
                try:
                    planned = await planner.recalculate(region_id, ticket_day)
                except AppError:
                    continue
                if ticket_day == primary:
                    plan_id = planned.plan_id
                    plan_version = planned.version

        return UploadTicketsResult(
            created=created,
            updated=updated,
            skipped=skipped,
            date=primary,
            plan_id=plan_id,
            plan_version=plan_version,
        )

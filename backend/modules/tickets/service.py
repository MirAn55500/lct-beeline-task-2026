from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, time

from sqlmodel.ext.asyncio.session import AsyncSession

from core.config import get_settings
from core.exceptions import AppError
from modules.catalogs.seed_values import reason_code, reason_hint, reason_label
from modules.geocoding.anchors import district_anchors
from modules.geocoding.geocoder import DISTRICT, HOUSE, REGION_BBOX, SETTLED, AddressGeocoder, has_house
from modules.planning.models.assignment import Assignment
from modules.planning import background
from modules.planning.schemas import RemakeLevel
from modules.tickets.importer import WORK_TYPE_BK, ParsedTicket, manual_ticket, parse_upload
from modules.tickets.models.request import Request
from modules.tickets.repository import TicketsRepository
from modules.tickets.schemas import (
    CreateTicketRequest,
    CreateTicketResult,
    TicketAssignmentFilter,
    TicketResponse,
    TicketsQuery,
    UploadTicketsResult,
)


def _format_window(start, end) -> str:
    return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"


_STATUS_LABEL = {
    "pending": "Не отправлена",
    "en_route": "В пути",
    "in_progress": "В работе",
    "completed": "Выполнена",
    "cancelled": "Отменена",
}


def _status_label(value: str | None) -> str:
    if not value:
        return ""
    raw = value.strip()
    return _STATUS_LABEL.get(raw.lower(), raw)


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

            reason_raw = None
            engineer = None
            if assigned and assignment is not None and assignment.engineer is not None:
                engineer = assignment.engineer.name
            elif assignment is not None and assignment.unassigned_reason is not None:
                reason_raw = assignment.unassigned_reason.value

            reason = reason_label(reason_raw)
            hint = reason_hint(reason_raw)

            category = request.request_type_vk.value if request.request_type_vk else ""
            address = request.address_ref.address if request.address_ref else ""
            district = None
            if request.address_ref is not None and request.address_ref.area_ref is not None:
                district = request.address_ref.area_ref.area
            status = _status_label(request.status.value if request.status else None)
            hd = request.request_type_hd.value if request.request_type_hd else None

            if query.work_type and category not in query.work_type:
                continue
            if query.reason:
                wanted = {
                    reason_code(item) or item.strip().lower() for item in query.reason
                }
                actual = reason_code(reason_raw)
                if actual is None or actual not in wanted:
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
                    reason_hint=hint,
                    engineer=engineer,
                    assigned=assigned,
                    window=_format_window(request.plan_start_time, request.plan_end_time),
                    window_start=request.plan_start_time,
                    window_end=request.plan_end_time,
                    address=address,
                    status=status or None,
                    hd=hd,
                    district=district,
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
        remake_level: RemakeLevel = RemakeLevel.FREE,
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

        tickets = await self._geocode(region_id, tickets)

        file_type = "json" if filename.lower().endswith(".json") else "csv"
        created, updated, skipped, touched = await self._repo.save_upload(
            region_id=region_id,
            filename=filename or "upload.csv",
            file_type=file_type,
            tickets=tickets,
            skipped=skipped,
        )
        return UploadTicketsResult(
            created=created,
            updated=updated,
            skipped=skipped,
            **await self._plan_after(region_id, tickets, remake_level, touched),
        )

    async def create(self, body: CreateTicketRequest) -> CreateTicketResult:
        """Одна заявка из окна «Добавить заявку» и её постановка в план дня."""
        region = await self._repo.get_region(body.region_id)
        if region is None:
            raise AppError("Регион не найден", status_code=404)
        if body.work_type not in WORK_TYPE_BK:
            raise AppError("Неизвестный тип работ")
        if body.end <= body.start:
            raise AppError("Окончание окна должно быть позже начала")
        address = " ".join(body.address.split())
        if not address:
            raise AppError("Укажите адрес заявки")

        remake_level = body.remake_level
        if remake_level is None:
            emergency = body.work_type == "Аварийные работы"
            remake_level = RemakeLevel.FREE if emergency else RemakeLevel.FIX

        number = await self._repo.next_external_id()
        ticket = manual_ticket(
            external_id=number,
            address=address,
            start=datetime.combine(body.date, body.start),
            end=datetime.combine(body.date, body.end),
            work_type=body.work_type,
        )
        if body.lat is not None and body.lon is not None:
            # Как офис бригады: адрес из подсказок или точка на карте — геокодер не нужен
            south, west, north, east = REGION_BBOX
            if not (south <= body.lat <= north and west <= body.lon <= east):
                raise AppError("Адрес заявки должен быть в Москве или Московской области")
            if not has_house(address):
                raise AppError("Укажите адрес заявки с номером дома")
            ticket = replace(
                ticket,
                latitude=body.lat,
                longitude=body.lon,
                geo_precision=HOUSE,
                geo_source="map",
            )
        else:
            [ticket] = await self._geocode(body.region_id, [ticket])
            stored = (await self._repo.find_addresses(body.region_id)).get((ticket.district, address))
            if ticket.geo_precision not in SETTLED and (
                stored is None or stored.geo_precision not in SETTLED
            ):
                # Точка по району или городу увела бы инженера не туда — лучше уточнить адрес
                raise AppError("Не удалось найти адрес на карте — уточните улицу и дом")

        created, updated, skipped, touched = await self._repo.save_upload(
            region_id=body.region_id,
            filename="Добавлена вручную",
            file_type="manual",
            tickets=[ticket],
            skipped=0,
        )
        return CreateTicketResult(
            number=number,
            created=created,
            updated=updated,
            skipped=skipped,
            **await self._plan_after(body.region_id, [ticket], remake_level, touched),
        )

    async def _plan_after(
        self,
        region_id: int,
        tickets: list[ParsedTicket],
        remake_level: RemakeLevel,
        touched: list[int],
    ) -> dict:
        """Расчёт плана на дни записанных заявок — в фоне: с сотней новых адресов это минуты."""
        counts = Counter(ticket.window_start.date() for ticket in tickets)
        primary = counts.most_common(1)[0][0] if counts else None
        days = sorted(counts)
        background.schedule(
            region_id,
            days,
            await background.estimate(self._session, region_id, days),
            remake_level=remake_level,
            fresh=touched,
        )
        return dict(
            date=primary,
            planning=bool(counts),
            planning_eta_seconds=background.status(region_id, primary)[2] if primary else None,
        )

    async def _geocode(self, region_id: int, tickets: list[ParsedTicket]) -> list[ParsedTicket]:
        """Координаты новых адресов и тех, что записаны без точности или по району.

        Адрес, уже найденный с точностью до дома или улицы, повторно не геокодируется.
        """
        known = await self._repo.find_addresses(region_id)

        def key(ticket: ParsedTicket) -> tuple[str, str]:
            return (ticket.district.strip() or "—", ticket.address)

        pending = [
            key(t)
            for t in tickets
            if key(t) not in known or known[key(t)].geo_precision not in SETTLED
        ]
        if not pending:
            return tickets

        anchors = await district_anchors(self._session, region_id)
        async with AddressGeocoder(get_settings(), anchors) as geocoder:
            hits = await geocoder.locate_many(pending)
            result: list[ParsedTicket] = []
            for ticket in tickets:
                hit = hits.get(key(ticket))
                stored = known.get(key(ticket))
                if hit is None:
                    result.append(ticket)
                    continue
                if (
                    stored is not None
                    and hit.precision == DISTRICT
                    and geocoder.plausible(
                        stored.latitude, stored.longitude, stored.address, key(ticket)[0]
                    )
                ):
                    result.append(ticket)  # лучше не нашлось, записанная точка правдоподобна
                    continue
                result.append(
                    replace(
                        ticket,
                        latitude=hit.lat,
                        longitude=hit.lon,
                        geo_precision=hit.precision,
                        geo_source=hit.source,
                    )
                )
        return result

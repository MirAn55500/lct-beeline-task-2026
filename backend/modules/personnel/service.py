from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from core.config import get_settings
from core.exceptions import AppError, NotFoundError
from modules.catalogs.enums import DictGroup
from modules.catalogs.models.address import Address
from modules.geocoding import suggest as address_suggest
from modules.geocoding.geocoder import (
    HOUSE,
    MOSCOW_CENTRE,
    AddressGeocoder,
    distance_km,
    has_house,
)
from modules.personnel.models.brigade import Brigade
from modules.personnel.models.engineer import Engineer
from modules.personnel.qualification import (
    QUALIFICATION_LABELS,
    normalize_qualification,
    qualification_hint,
    qualification_label,
)
from modules.personnel.repository import PersonnelRepository
from modules.personnel.schemas import (
    AddressSuggestionResponse,
    AreaResponse,
    BrigadeResponse,
    CreateEngineerRequest,
    EngineerResponse,
    EngineersQuery,
    PersonnelFilterOptions,
    ReverseGeocodeResponse,
    UpdateBrigadeRequest,
    UpdateBrigadeResponse,
)
from modules.personnel.skills import SKILL_LABELS, map_skill, skill_code
from modules.personnel.transport import map_transport


def short_name(name: str) -> str:
    """«Саша Белый» → «Белый С.» — подпись бригадира в списке бригад."""
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[-1]} {parts[0][0]}."
    return name


# Коды транспорта UI → значение для словаря (канон: bicycle, не bike).
_TRANSPORT_STORE: dict[str, str] = {
    "car": "car",
    "bike": "bicycle",
    "bicycle": "bicycle",
    "public": "public_transport",
    "public_transport": "public_transport",
    "walking": "walking",
}

# Лейблы транспорта страницы «Персонал».
_TRANSPORT_UI_LABEL: dict[str, str] = {
    "car": "Автомобиль",
    "public": "Общ. транспорт",
    "bike": "Велосипед",
    "walking": "Пешеход",
}


OFFICE_FALLBACK_KM = 120.0
"""Без DaData: офис не дальше этого от центра Москвы. Область тянется примерно на
120–150 км, Тверь, Рязань и Калуга — дальше 150."""


class PersonnelService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PersonnelRepository(session)

    def health(self) -> dict[str, str]:
        return {"module": "personnel", "status": "ok"}

    def filter_options(self) -> PersonnelFilterOptions:
        return PersonnelFilterOptions(
            skills=list(SKILL_LABELS.values()),
            transports=list(_TRANSPORT_UI_LABEL.values()),
            qualifications=list(QUALIFICATION_LABELS.values()),
        )

    async def list_brigades(self, region_id: int | None = None) -> list[BrigadeResponse]:
        brigades = await self._repo.list_brigades(region_id)
        return [self._brigade_response(brigade) for brigade in brigades]

    async def list_areas(self, region_id: int) -> list[AreaResponse]:
        areas = await self._repo.list_areas(region_id)
        return [AreaResponse(id=area.id or 0, name=area.area) for area in areas]

    async def update_brigade(
        self, brigade_id: int, body: UpdateBrigadeRequest
    ) -> UpdateBrigadeResponse:
        """Сохранить карточку «Управление бригадой».

        Новый адрес офиса геокодируется — это точка старта инженеров. Рабочий день
        переставляется тем инженерам, у кого он совпадал с прежним днём бригады;
        свою смену инженера не трогаем. План сам не пересчитывается.
        """
        brigade = await self._repo.get_brigade_full(brigade_id)
        if brigade is None:
            raise NotFoundError("Бригада не найдена")

        name = body.name.strip()
        if not name:
            raise AppError("Укажите название бригады")
        if body.end_work <= body.start_work:
            raise AppError("Конец рабочего дня должен быть позже начала")
        days = sorted(set(body.work_days))
        if not days or any(day < 1 or day > 7 for day in days):
            raise AppError("Выберите хотя бы один рабочий день")

        areas = {area.id: area for area in await self._repo.list_areas(brigade.region_id)}
        if any(area_id not in areas for area_id in body.area_ids):
            raise AppError("Район не из региона бригады")

        address = " ".join(body.office_address.split())
        office = brigade.office_address
        point = (
            (body.office_lat, body.office_lon)
            if body.office_lat is not None and body.office_lon is not None
            else None
        )
        renamed = office is None or address != " ".join(office.address.split())
        moved = point is not None and (
            office is None
            or abs(point[0] - office.latitude) > 1e-6
            or abs(point[1] - office.longitude) > 1e-6
        )
        office_moved = moved
        if moved or renamed:
            # Свободный текст геокодер путает (Невский проспект находился в Москве):
            # новый офис — только адрес из подсказок или точка на карте, оба с точкой
            if point is None:
                raise AppError("Выберите адрес офиса из подсказок или укажите его на карте")
            if not has_house(address):
                raise AppError("Укажите адрес офиса с номером дома")
            previous = brigade.office_address
            office = await self._place_office(brigade, address, point)
            brigade.office_address_id = office.address_id or 0
            self._session.add(brigade)
            await self._session.flush()
            # Прежний офис, поставленный здесь же с карты, больше никому не нужен
            if (
                previous is not None
                and previous.address_id != office.address_id
                and previous.geo_source == "map"
                and not await self._repo.address_in_use(previous.address_id or 0)
            ):
                await self._repo.delete_address(previous)

        rescheduled = 0
        old_day = (brigade.start_work, brigade.end_work)
        if (body.start_work, body.end_work) != old_day:
            for engineer in brigade.engineers or []:
                if (engineer.start_work, engineer.end_work) == old_day:
                    engineer.start_work = body.start_work
                    engineer.end_work = body.end_work
                    self._session.add(engineer)
                    rescheduled += 1

        brigade.name = name
        brigade.start_work = body.start_work
        brigade.end_work = body.end_work
        brigade.work_days = "".join(str(day) for day in days)
        brigade.in_planning = body.in_planning
        brigade.areas = [areas[area_id] for area_id in dict.fromkeys(body.area_ids)]
        self._session.add(brigade)
        await self._repo.commit()

        saved = await self._repo.get_brigade_full(brigade_id)
        assert saved is not None
        return UpdateBrigadeResponse(
            **self._brigade_response(saved).model_dump(),
            rescheduled_engineers=rescheduled,
            office_moved=office_moved,
        )

    async def suggest_addresses(self, query: str) -> list[AddressSuggestionResponse]:
        items = await address_suggest.suggest(query)
        return [
            AddressSuggestionResponse(
                address=item.address, lat=item.lat, lon=item.lon, has_house=item.house
            )
            for item in items
        ]

    async def reverse_geocode(self, lat: float, lon: float) -> ReverseGeocodeResponse:
        """Адрес точки под булавкой. DaData знает дома и регион точно и отвечает за
        десятки миллисекунд; «здесь ничего нет» от неё — тоже ответ. OpenStreetMap —
        только когда DaData недоступна: он медленный и дом находит редко."""
        try:
            near = await self._check_office_region(lat, lon)
        except address_suggest.DadataUnavailable:
            async with AddressGeocoder(get_settings()) as geocoder:
                text = await geocoder.reverse(lat, lon, dadata=False)
            return ReverseGeocodeResponse(address=text, has_house=bool(text and has_house(text)))
        if near is None:
            return ReverseGeocodeResponse()
        return ReverseGeocodeResponse(address=near.address, has_house=near.house)

    async def _check_office_region(
        self, lat: float, lon: float
    ) -> address_suggest.PointAddress | None:
        """Офис — только в Москве и области. Прямоугольник вокруг них захватывает Тверь,
        Рязань и Калугу, поэтому регион уточняем у DaData.

        Возвращает ближайший адрес DaData в 100 м (None — адресов рядом нет).
        DadataUnavailable — DaData нет, проверен только прямоугольник.
        """
        async with AddressGeocoder(get_settings()) as geocoder:
            if not geocoder.in_region(lat, lon):
                raise AppError("Офис должен быть в Москве или Московской области")
        try:
            near = await address_suggest.locate_point(lat, lon)
            region = near if near is not None else await address_suggest.locate_point(lat, lon, 1000)
        except address_suggest.DadataUnavailable:
            # Без DaData регион не узнать — хотя бы не дальше, чем тянется область
            if distance_km((lat, lon), MOSCOW_CENTRE) > OFFICE_FALLBACK_KM:
                raise AppError("Офис должен быть в Москве или Московской области") from None
            raise
        if region is not None and region.region not in address_suggest.MOSCOW_REGIONS:
            raise AppError("Офис должен быть в Москве или Московской области")
        return near

    async def _place_office(
        self, brigade: Brigade, address: str, point: tuple[float, float]
    ) -> Address:
        """Офис в выбранной точке (подсказка или карта); адрес — подпись к ней."""
        if brigade.office_address is None:
            raise AppError("У бригады нет офиса, к району которого привязать новый адрес")
        try:
            await self._check_office_region(*point)
        except address_suggest.DadataUnavailable:
            pass  # регион не уточнить — прямоугольник Москвы и области уже проверен
        area_id = brigade.office_address.area_id
        same = await self._repo.find_address(area_id, address, *point)
        if same is not None:
            return same
        return await self._repo.add_address(
            Address(
                area_id=area_id,
                address=address,
                latitude=point[0],
                longitude=point[1],
                geo_precision=HOUSE,
                geo_source="map",
            )
        )

    def _brigade_response(self, brigade: Brigade) -> BrigadeResponse:
        assert brigade.brigade_id is not None
        engineers = brigade.engineers or []
        lead = next((item for item in engineers if item.is_lead), None)
        if lead is None and engineers:
            lead = min(engineers, key=lambda item: item.engineer_id or 0)
        leader_name = lead.name if lead else None
        office = brigade.office_address
        return BrigadeResponse(
            id=brigade.brigade_id,
            name=brigade.name,
            number=brigade.number,
            region_id=brigade.region_id,
            engineers_count=len(engineers),
            leader_name=leader_name,
            leader_short_name=short_name(leader_name) if leader_name else None,
            office_address=office.address if office else None,
            office_lat=office.latitude if office else None,
            office_lon=office.longitude if office else None,
            start_work=brigade.start_work,
            end_work=brigade.end_work,
            work_days=brigade.weekdays,
            in_planning=brigade.in_planning,
            area_ids=sorted(area.id for area in brigade.areas or [] if area.id is not None),
        )

    async def list_engineers(self, query: EngineersQuery) -> list[EngineerResponse]:
        if query.region_id is None and query.brigade_id is None:
            raise AppError("Укажите region_id или brigade_id")

        engineers = await self._repo.list_engineers(
            region_id=query.region_id,
            brigade_id=query.brigade_id,
        )
        items = [self._to_response(engineer) for engineer in engineers]
        return [item for item in items if self._matches(item, query)]

    async def create_engineer(self, body: CreateEngineerRequest) -> EngineerResponse:
        brigade = await self._repo.get_brigade(body.brigade_id)
        if brigade is None:
            raise NotFoundError("Бригада не найдена")

        transport_code, _ = map_transport(body.transport)
        if transport_code == "unknown":
            raise AppError("Неизвестный транспорт")
        store_transport = _TRANSPORT_STORE.get(transport_code, transport_code)
        transport_id = await self._repo.ensure_dict(DictGroup.TRANSPORT, store_transport)

        skill_codes: list[str] = []
        for raw in body.skills:
            code = skill_code(raw)
            if code is None or code not in SKILL_LABELS:
                raise AppError(f"Неизвестный навык: {raw}")
            skill_codes.append(code)
        skill_codes = list(dict.fromkeys(skill_codes))

        qualification: str | None = None
        if body.qualification is not None:
            qualification = normalize_qualification(body.qualification.value)
            if qualification is None:
                raise AppError("Неизвестная квалификация")

        if body.end_work <= body.start_work:
            raise AppError("Конец смены должен быть позже начала")

        engineer = Engineer(
            name=body.name.strip(),
            start_work=body.start_work,
            end_work=body.end_work,
            transport_id=transport_id,
            brigade_id=body.brigade_id,
            qualification=qualification,
            is_lead=body.is_lead,
        )
        engineer = await self._repo.add_engineer(engineer)
        assert engineer.engineer_id is not None

        for code in skill_codes:
            skill_id = await self._repo.ensure_dict(DictGroup.SKILL, code)
            await self._repo.add_skill(engineer.engineer_id, skill_id)

        refreshed = await self._repo.refresh_engineer(engineer.engineer_id)
        if refreshed is None:
            raise AppError("Не удалось сохранить инженера", status_code=500)
        return self._to_response(refreshed)

    async def delete_engineer(self, engineer_id: int) -> None:
        engineer = await self._repo.get_engineer(engineer_id)
        if engineer is None:
            raise NotFoundError("Инженер не найден")
        await self._repo.delete_engineer(engineer)
        await self._repo.commit()

    def _to_response(self, engineer: Engineer) -> EngineerResponse:
        transport_code, transport_label = map_transport(
            engineer.transport.value if engineer.transport else None
        )
        ui_transport_label = _TRANSPORT_UI_LABEL.get(transport_code, transport_label)

        skills: list[str] = []
        skill_labels: list[str] = []
        for link in engineer.skills or []:
            value = link.skill.value if link.skill is not None else None
            mapped = map_skill(value)
            if mapped is None:
                continue
            code, label = mapped
            if code not in skills:
                skills.append(code)
                skill_labels.append(label)

        qualification = normalize_qualification(engineer.qualification)
        position = qualification_label(qualification)
        brigade_name = engineer.brigade.name if engineer.brigade is not None else None

        return EngineerResponse(
            id=engineer.engineer_id or 0,
            name=engineer.name,
            brigade_id=engineer.brigade_id,
            transport=transport_code,
            transport_label=ui_transport_label,
            skill=skill_labels[0] if skill_labels else None,
            skills=skills,
            skill_labels=skill_labels,
            qualification=qualification,
            position=position,
            qualification_hint=qualification_hint(qualification),
            is_lead=bool(engineer.is_lead),
            start_work=engineer.start_work,
            end_work=engineer.end_work,
            brigade_name=brigade_name,
        )

    def _matches(self, item: EngineerResponse, query: EngineersQuery) -> bool:
        if query.q:
            needle = query.q.strip().lower()
            if needle and needle not in item.name.lower():
                return False

        if query.qualification:
            wanted = {
                normalize_qualification(value) or value.strip().lower()
                for value in query.qualification
            }
            # Фильтр принимает код или русскую подпись.
            wanted |= {
                code
                for value in query.qualification
                for code, label in QUALIFICATION_LABELS.items()
                if value.strip().lower() in {code, label.lower()}
            }
            if item.qualification not in wanted:
                return False

        if query.skill:
            wanted_codes: set[str] = set()
            wanted_labels: set[str] = set()
            for raw in query.skill:
                code = skill_code(raw)
                if code:
                    wanted_codes.add(code)
                wanted_labels.add(raw.strip().lower())
            if not (
                any(code in wanted_codes for code in item.skills)
                or any(label.lower() in wanted_labels for label in item.skill_labels)
            ):
                return False

        if query.transport:
            wanted: set[str] = set()
            for raw in query.transport:
                code, label = map_transport(raw)
                wanted.add(code)
                wanted.add(label.lower())
                wanted.add(raw.strip().lower())
                ui = _TRANSPORT_UI_LABEL.get(code)
                if ui:
                    wanted.add(ui.lower())
            haystack = {
                item.transport,
                item.transport_label.lower(),
            }
            if not haystack.intersection(wanted):
                return False

        return True

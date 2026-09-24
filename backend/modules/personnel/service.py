from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from core.exceptions import AppError, NotFoundError
from modules.catalogs.enums import DictGroup
from modules.personnel.models.engineer import Engineer
from modules.personnel.qualification import (
    QUALIFICATION_LABELS,
    normalize_qualification,
    qualification_hint,
    qualification_label,
)
from modules.personnel.repository import PersonnelRepository
from modules.personnel.schemas import (
    BrigadeResponse,
    CreateEngineerRequest,
    EngineerResponse,
    EngineersQuery,
    PersonnelFilterOptions,
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


class PersonnelService:
    def __init__(self, session: AsyncSession) -> None:
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
        items: list[BrigadeResponse] = []
        for brigade in brigades:
            assert brigade.brigade_id is not None
            engineers = brigade.engineers or []
            lead = next((item for item in engineers if item.is_lead), None)
            if lead is None and engineers:
                lead = min(engineers, key=lambda item: item.engineer_id or 0)
            leader_name = lead.name if lead else None
            items.append(
                BrigadeResponse(
                    id=brigade.brigade_id,
                    name=brigade.name,
                    number=brigade.number,
                    region_id=brigade.region_id,
                    engineers_count=len(engineers),
                    leader_name=leader_name,
                    leader_short_name=short_name(leader_name) if leader_name else None,
                )
            )
        return items

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

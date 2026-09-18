"""Объяснения решений на языке диспетчера.

Принципиально собираются **из тех же данных, что использовал алгоритм**: причина отказа —
это код, который вернула единая функция проверки ограничений, а не отдельно сочинённый
текст. Поэтому объяснение нельзя рассинхронизировать с решением, и на защите его можно
показать «по коду»: вот проверка, вот её результат, вот фраза.

Генерация текста языковой моделью здесь была бы хуже по трём причинам: недетерминирована,
непроверяема и способна уверенно описать ограничение, которого алгоритм не проверял.
"""

from __future__ import annotations

from datetime import datetime

from .enums import SKILL_TITLES, TRANSPORT_TITLES, EventType, ReasonCode
from .models import Request
from .result import PlanDiff, RouteResult, Visit
from .textutil import hhmm as _hhmm
from .textutil import plural as _plural

__all__ = [
    "explain_assignment",
    "explain_unassigned",
    "explain_route",
    "explain_replan",
    "REASON_TITLES",
]

REASON_TITLES: dict[ReasonCode, str] = {
    ReasonCode.NO_ENGINEERS: "нет ни одного исполнителя",
    ReasonCode.NO_REGION: "нет исполнителя нужного региона",
    ReasonCode.NO_SKILL: "нет исполнителя с требуемым навыком",
    ReasonCode.NO_TRANSPORT: "нет исполнителя с требуемым транспортом",
    ReasonCode.NO_EQUIPMENT: "ни у кого нет требуемого снаряжения",
    ReasonCode.NO_WORK_TIME: "у подходящих исполнителей нет рабочего времени",
    ReasonCode.TIME_CONFLICT: "работа не помещается во временное окно или смену",
    ReasonCode.NOT_FOUND: "подходящий вариант не найден в отведённое время",
    ReasonCode.MANUAL: "снята с исполнителя вручную диспетчером",
}


# --------------------------------------------------------------------------------------


def explain_assignment(
    request: Request,
    engineer_name: str,
    visit: Visit,
    shift_end: datetime | None,
    *,
    alternatives: int = 0,
    added_distance_km: float | None = None,
) -> str:
    """Почему эта заявка досталась именно этому инженеру."""
    skill = SKILL_TITLES.get(request.required_skill, str(request.required_skill))
    parts = [
        f"Заявка {request.id} назначена инженеру {engineer_name}: "
        f"у него есть навык «{skill}»"
    ]
    if request.required_transport is not None:
        parts.append(
            f"и требуемый транспорт «{TRANSPORT_TITLES.get(request.required_transport, '')}»"
        )
    parts.append(
        f". Приезжает в {_hhmm(visit.arrival_at)} "
        f"(окно {_hhmm(request.window_start)}–{_hhmm(request.window_end)})"
    )
    if visit.waiting_minutes > 0.5:
        parts.append(f", ждёт {round(visit.waiting_minutes)} мин до начала окна")
    parts.append(
        f", работает с {_hhmm(visit.service_start_at)} до {_hhmm(visit.service_end_at)}"
    )
    if shift_end is not None:
        parts.append(f" и укладывается в смену до {_hhmm(shift_end)}")
    parts.append(".")

    if added_distance_km is not None:
        parts.append(f" Маршрут удлиняется на {added_distance_km:.1f} км")
        if alternatives > 0:
            parts.append(
                f" — это минимум среди {alternatives} "
                f"{_plural(alternatives, 'подходящего исполнителя', 'подходящих исполнителей', 'подходящих исполнителей')}"
            )
        parts.append(".")
    elif alternatives > 0:
        parts.append(
            f" Всего подходящих исполнителей: {alternatives}; выбран дающий наименьший прирост маршрута."
        )
    return "".join(parts)


def explain_unassigned(request: Request, reason: ReasonCode, details: list[str]) -> str:
    """Почему заявку не удалось назначить. Причина — код проверки, а не догадка."""
    skill = SKILL_TITLES.get(request.required_skill, str(request.required_skill))
    window = f"{_hhmm(request.window_start)}–{_hhmm(request.window_end)}"
    head = f"Заявка {request.id} не назначена"

    if reason is ReasonCode.NO_ENGINEERS:
        return f"{head}: во входных данных нет ни одного инженера."
    if reason is ReasonCode.MANUAL:
        return f"{head}: снята с исполнителя вручную диспетчером и ожидает нового назначения."
    if reason is ReasonCode.NO_REGION:
        body = f"нет ни одного инженера региона «{request.region_key}»"
    elif reason is ReasonCode.NO_SKILL:
        body = f"ни у одного доступного инженера нет навыка «{skill}»"
    elif reason is ReasonCode.NO_TRANSPORT:
        transport = TRANSPORT_TITLES.get(request.required_transport, "требуемый")
        body = f"нет инженера с транспортом «{transport}»"
    elif reason is ReasonCode.NO_EQUIPMENT:
        body = "ни у одного подходящего инженера нет требуемого снаряжения на этот день"
    elif reason is ReasonCode.NO_WORK_TIME:
        body = "у подходящих инженеров нет рабочего времени на дату плана"
    elif reason is ReasonCode.TIME_CONFLICT:
        body = (
            f"ни один инженер с навыком «{skill}» не успевает в окно {window} "
            f"с учётом уже запланированных работ и времени в пути"
        )
    else:
        body = "подходящий вариант не найден за отведённое время поиска; невозможность не доказана"

    text = f"{head}: {body}."
    if details:
        shown = details[:3]
        text += " Проверено: " + "; ".join(shown) + "."
        if len(details) > len(shown):
            text += f" И ещё {len(details) - len(shown)}."
    return text


def explain_route(route: RouteResult) -> str:
    """Краткое описание маршрута целиком."""
    if not route.visits:
        return f"{route.engineer_name}: заявок не назначено."
    count = len(route.visits)
    return (
        f"{route.engineer_name} ({TRANSPORT_TITLES.get(route.transport_mode, '')}): "
        f"{count} {_plural(count, 'заявка', 'заявки', 'заявок')}, "
        f"с {_hhmm(route.start_at)} до {_hhmm(route.end_at)}, "
        f"пробег {route.distance_km:.1f} км, в пути {round(route.travel_minutes)} мин, "
        f"ожидание {round(route.waiting_minutes)} мин, "
        f"загрузка {route.utilization * 100:.0f}% от смены. "
        f"Порядок объезда выбран так, чтобы каждая заявка попадала в своё окно "
        f"при наименьшем приросте времени в пути."
    )


def explain_replan(event_type: EventType, diff: PlanDiff, total_routes: int) -> str:
    """Что изменилось после события. Главное здесь — сколько всего НЕ изменилось."""
    touched = len(diff.changed_route_engineer_ids)
    # Маршрутов после события может стать больше, чем было: «затронуто 2 из 1» — бессмыслица.
    total_routes = max(total_routes, touched + len(diff.unchanged_route_engineer_ids))
    titles = {
        EventType.URGENT_REQUEST: "Поступила срочная заявка",
        EventType.CANCEL_REQUEST: "Заявка отменена",
        EventType.ENGINEER_UNAVAILABLE: "Инженер стал недоступен",
        EventType.CLIENT_REFUSAL: "Клиент отказался на адресе",
    }
    head = titles.get(event_type, "План пересчитан")

    parts = [f"{head}. "]
    if diff.newly_assigned_request_ids:
        ids = ", ".join(diff.newly_assigned_request_ids)
        parts.append(f"Назначено заново: {ids}. ")
    if diff.newly_unassigned_request_ids:
        ids = ", ".join(diff.newly_unassigned_request_ids)
        parts.append(f"Осталось без исполнителя: {ids}. ")
    if diff.removed_route_engineer_ids:
        parts.append(f"Маршрутов снято: {len(diff.removed_route_engineer_ids)}. ")
    parts.append(
        f"Изменения затронули {touched} "
        f"{_plural(touched, 'маршрут', 'маршрута', 'маршрутов')} из {total_routes}"
    )
    if diff.unchanged_route_engineer_ids:
        parts.append(
            f"; остальные {len(diff.unchanged_route_engineer_ids)} остались без изменений"
        )
    parts.append(".")
    return "".join(parts)

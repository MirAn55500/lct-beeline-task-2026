"""Перечисления предметной области.

Коды соответствуют справочникам ТЗ (п. 2.4.1) и базы знаний
(`Навык`, `Способ передвижения`, `Назначение на работу`).
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "Skill",
    "TransportMode",
    "Priority",
    "AssignmentStatus",
    "Algorithm",
    "EventType",
    "ReasonCode",
]


class _StrEnum(str, Enum):
    """Строковый Enum: сериализуется как обычная строка, сравнивается со строками."""

    def __str__(self) -> str:  # pragma: no cover - тривиально
        return str(self.value)


class Skill(_StrEnum):
    """Требуемый навык. Справочник ТЗ п. 2.4.1."""

    LOCAL = "local"
    CONNECTION = "connection"
    EMERGENCY = "emergency"


SKILL_TITLES: dict[Skill, str] = {
    Skill.LOCAL: "Локальные работы",
    Skill.CONNECTION: "Работы на подключение и дозаказы",
    Skill.EMERGENCY: "Аварийные работы",
}


class TransportMode(_StrEnum):
    """Способ передвижения инженера. Справочник ТЗ п. 2.4.1."""

    CAR = "car"
    WALKING = "walking"
    BICYCLE = "bicycle"
    PUBLIC_TRANSPORT = "public_transport"


TRANSPORT_TITLES: dict[TransportMode, str] = {
    TransportMode.CAR: "автомобиль",
    TransportMode.WALKING: "пешком",
    TransportMode.BICYCLE: "велосипед",
    TransportMode.PUBLIC_TRANSPORT: "общественный транспорт",
}


class Priority(_StrEnum):
    """Приоритет заявки. Срочные размещаются раньше обычных."""

    NORMAL = "normal"
    URGENT = "urgent"

    @property
    def rank(self) -> int:
        """Чем больше, тем важнее. Используется как первый ключ отбора."""
        return 1 if self is Priority.URGENT else 0


class AssignmentStatus(_StrEnum):
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"


class Algorithm(_StrEnum):
    """Базовый вариант обязателен по ТЗ п. 2.3 как точка сравнения."""

    BASELINE = "baseline"
    OPTIMIZED = "optimized"


class EventType(_StrEnum):
    """Сценарии перепланирования (ТЗ п. 2.1.6, БЗ «Перераспределение заявок»)."""

    URGENT_REQUEST = "urgent_request"
    CANCEL_REQUEST = "cancel_request"
    ENGINEER_UNAVAILABLE = "engineer_unavailable"
    CLIENT_REFUSAL = "client_refusal"


class ReasonCode(_StrEnum):
    """Причина неназначения заявки.

    Коды упорядочены по «глубине пройденной проверки»: итоговая причина заявки —
    код с максимальным ``rank`` среди всех рассмотренных инженеров. Если хоть один
    инженер дошёл до проверки времени, значит навык и транспорт в наличии есть,
    и честная причина — время, а не навык.
    """

    NO_ENGINEERS = "no_engineers"
    NO_REGION = "no_region"
    NO_SKILL = "no_skill"
    NO_TRANSPORT = "no_transport"
    NO_EQUIPMENT = "no_equipment"
    NO_WORK_TIME = "no_work_time"
    TIME_CONFLICT = "time_conflict"
    NOT_FOUND = "not_found"
    MANUAL = "manual"

    @property
    def rank(self) -> int:
        return _REASON_RANK[self]


_REASON_RANK: dict[ReasonCode, int] = {
    ReasonCode.NO_ENGINEERS: 0,
    ReasonCode.NO_REGION: 1,
    ReasonCode.NO_SKILL: 2,
    ReasonCode.NO_TRANSPORT: 3,
    ReasonCode.NO_EQUIPMENT: 4,
    ReasonCode.NO_WORK_TIME: 5,
    ReasonCode.TIME_CONFLICT: 6,
    ReasonCode.NOT_FOUND: 7,
    # Ручное решение диспетчера — самый высокий ранг: пересчёт причин по общему правилу
    # «максимальный ранг» не имеет права затереть его машинной догадкой.
    ReasonCode.MANUAL: 8,
}

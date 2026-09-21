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
    "ExecutionStatus",
    "AssignmentStatus",
    "Algorithm",
    "EventType",
    "ReplanScope",
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
    """Приоритет заявки при нехватке ресурсов: авария → подключение → ремонт / дозаказ.

    Коды совпадают со словарём модели (`priority`). Навык и приоритет — разные оси:
    дозаказ требует навык `connection`, но по важности равен ремонту.
    """

    REPAIR = "repair_or_addon"
    CONNECTION = "connection"
    EMERGENCY = "emergency"

    @property
    def rank(self) -> int:
        """Чем больше, тем важнее. Используется как первый ключ отбора."""
        return _PRIORITY_RANK[self]


_PRIORITY_RANK: dict["Priority", int] = {
    Priority.REPAIR: 0,
    Priority.CONNECTION: 1,
    Priority.EMERGENCY: 2,
}

PRIORITY_TITLES: dict[Priority, str] = {
    Priority.EMERGENCY: "авария",
    Priority.CONNECTION: "подключение",
    Priority.REPAIR: "ремонт / дозаказ",
}


class ExecutionStatus(_StrEnum):
    """Статус выполнения заявки. Закрытые (completed, cancelled) в новый план не входят."""

    UNKNOWN = "unknown"
    PENDING = "pending"
    EN_ROUTE = "en_route"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    @property
    def is_closed(self) -> bool:
        return self in (ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED)


class AssignmentStatus(_StrEnum):
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"


class Algorithm(_StrEnum):
    """Базовый вариант обязателен по ТЗ п. 2.3 как точка сравнения."""

    BASELINE = "baseline"
    OPTIMIZED = "optimized"


class EventType(_StrEnum):
    """Сценарии перепланирования (ТЗ п. 2.1.6, БЗ «Перераспределение заявок»).

    Первые четыре меняют состав работы: появилась авария, заявка снята, человек выбыл,
    клиент отказался. Последние два ничего не меняют по составу — они приносят **факт**
    исполнения: инженер на месте, работы завершены. Факт важен не сам по себе, а потому
    что план после него перестаёт быть догадкой: отсюда считается остаток дня.

    Последнее значение стоит особняком: событием оно не является и во вход `replan()`
    не допускается — см. `MANUAL_REASSIGN`.
    """

    URGENT_REQUEST = "urgent_request"
    CANCEL_REQUEST = "cancel_request"
    ENGINEER_UNAVAILABLE = "engineer_unavailable"
    CLIENT_REFUSAL = "client_refusal"
    VISIT_ARRIVED = "visit_arrived"
    VISIT_COMPLETED = "visit_completed"

    MANUAL_REASSIGN = "manual_reassign"
    """Причина пересчёта «диспетчер передвинул заявку руками».

    Это **метка `PlanDiff`, а не вход `replan()`**: ручной ход выполняет `reassign()`,
    и `ReplanEvent` с этим типом создать нельзя. Значение нужно потому, что `diff`
    обязан честно отвечать на вопрос «почему план изменился», а до него ручной ход
    подписывался чужим типом — и в журнале выглядел как поступившая авария.
    """

    @property
    def is_status(self) -> bool:
        """Событие-статус: приносит факт исполнения, а не меняет состав заявок."""
        return self in (EventType.VISIT_ARRIVED, EventType.VISIT_COMPLETED)

    @property
    def is_event(self) -> bool:
        """Настоящее событие перепланирования, а не метка ручного вмешательства."""
        return self is not EventType.MANUAL_REASSIGN


class ReplanScope(_StrEnum):
    """Степень изменения плана — потолок лестницы ремонта.

    Лестница **всегда** начинается с самой дешёвой ступени; степень задаёт лишь то,
    до какой ступени разрешено подняться, если дешёвые не справились. Диспетчеру это
    читается как ответ на вопрос «насколько сильно можно перетряхнуть день».

    * `LOW` — только свободные окна существующих маршрутов: заявка либо вставляется,
      никого не сдвигая с места, либо честно уходит в отказ;
    * `MEDIUM` — плюс перестроение затронутых маршрутов: вытеснение менее приоритетных
      работ и перестановки внутри маршрута;
    * `HIGH` — плюс пересчёт остатка дня по всем инженерам.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return _SCOPE_RANK[self]

    @property
    def allows_ejection(self) -> bool:
        """Можно ли двигать уже назначенные работы в пределах маршрута."""
        return self.rank >= ReplanScope.MEDIUM.rank

    @property
    def allows_rebuild(self) -> bool:
        """Можно ли пересобирать остаток дня по всем инженерам."""
        return self is ReplanScope.HIGH


_SCOPE_RANK: dict["ReplanScope", int] = {
    ReplanScope.LOW: 0,
    ReplanScope.MEDIUM: 1,
    ReplanScope.HIGH: 2,
}

REPLAN_SCOPE_TITLES: dict[ReplanScope, str] = {
    ReplanScope.LOW: "низкая",
    ReplanScope.MEDIUM: "средняя",
    ReplanScope.HIGH: "высокая",
}


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

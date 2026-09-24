"""Канонические значения словаря (`dicts`).

Коды совпадают с docs/03 Требования/Словари модели.md.
Подписи — для UI; в таблице храним `value` = код.
"""

from __future__ import annotations

# (group, value/code)
TRANSPORT_SEED: tuple[tuple[str, str], ...] = (
    ("transport", "car"),
    ("transport", "walking"),
    ("transport", "bicycle"),
    ("transport", "public_transport"),
)

SKILL_SEED: tuple[tuple[str, str], ...] = (
    ("skill", "local"),
    ("skill", "connection"),
    ("skill", "emergency"),
)

PRIORITY_SEED: tuple[tuple[str, str], ...] = (
    ("priority", "emergency"),
    ("priority", "connection"),
    ("priority", "repair_or_addon"),
)

UNASSIGNED_REASON_SEED: tuple[tuple[str, str], ...] = (
    ("unassigned_reason", "no_engineers"),
    ("unassigned_reason", "no_region"),
    ("unassigned_reason", "no_skill"),
    ("unassigned_reason", "no_transport"),
    ("unassigned_reason", "no_equipment"),
    ("unassigned_reason", "no_work_time"),
    ("unassigned_reason", "time_conflict"),
    ("unassigned_reason", "not_found"),
    ("unassigned_reason", "manual"),
)

# Краткие подписи тега / фильтра (как в макете).
REASON_LABELS: dict[str, str] = {
    "no_engineers": "Нет инженеров",
    "no_region": "Нет инженера в регионе",
    "no_skill": "Нет нужного навыка",
    "no_transport": "Нет подходящего транспорта",
    "no_equipment": "Нет нужного снаряжения",
    "no_work_time": "Нет рабочего времени",
    "time_conflict": "Конфликт времени",
    "not_found": "Не найдено",
    "manual": "Вручную",
}

# Текст тултипа при наведении на тег причины.
REASON_HINTS: dict[str, str] = {
    "no_engineers": "Инженеры региона отсутствуют или недоступны на нужное время",
    "no_region": "В выбранном регионе нет инженера, которому можно отдать заявку",
    "no_skill": "Нет инженера с нужным навыком для этого вида работ",
    "no_transport": "Нет инженера с транспортом, который требует заявка",
    "no_equipment": "Ни у кого из доступных инженеров нет нужного снаряжения",
    "no_work_time": "У подходящих инженеров нет свободного рабочего времени",
    "time_conflict": "Работа не помещается во временное окно или в смену",
    "not_found": "Подходящий вариант назначения не найден",
    "manual": "Заявка снята с исполнителя вручную диспетчером",
}

# Старые/русские value из seed_east → код.
_REASON_ALIASES: dict[str, str] = {
    **{code: code for code in REASON_LABELS},
    **{label.lower(): code for code, label in REASON_LABELS.items()},
    "нет нужного навыка": "no_skill",
    "нет нужного снаряжения": "no_equipment",
    "нет рабочего времени": "no_work_time",
    "конфликт времени": "time_conflict",
    "нет инженера в регионе": "no_region",
    "нет инженеров": "no_engineers",
    "нет подходящего транспорта": "no_transport",
    "не найдено": "not_found",
    "вручную": "manual",
    # Подписи с карточек макета.
    "нет инженера с нужным навыком": "no_skill",
    "работа не помещается в смену": "time_conflict",
    "нет свободного инженера": "no_engineers",
}


def reason_code(value: str | None) -> str | None:
    if not value:
        return None
    return _REASON_ALIASES.get(value.strip().lower())


def reason_label(value: str | None) -> str | None:
    code = reason_code(value)
    if code is None:
        return value
    return REASON_LABELS.get(code, value)


def reason_hint(value: str | None) -> str | None:
    code = reason_code(value)
    if code is None:
        return None
    return REASON_HINTS.get(code)


ALL_SEED_ROWS: tuple[tuple[str, str], ...] = (
    *TRANSPORT_SEED,
    *SKILL_SEED,
    *PRIORITY_SEED,
    *UNASSIGNED_REASON_SEED,
)

"""Маппинг навыков словаря → код/лейбл для UI страницы «Персонал»."""

from __future__ import annotations

# Канонические коды совпадают с docs/03 Требования/Навык.md
SKILL_LABELS: dict[str, str] = {
    "connection": "Работы на подключение и дозаказы",
    "local": "Локальные работы",
    "emergency": "Аварийные работы",
}

_SKILL_BY_VALUE: dict[str, str] = {
    "connection": "connection",
    "подключение": "connection",
    "работы на подключение и дозаказы": "connection",
    "local": "local",
    "локальные работы": "local",
    "локальная заявка": "local",
    "emergency": "emergency",
    "аварийные работы": "emergency",
    "глобальная проблема": "emergency",
}


def map_skill(dict_value: str | None) -> tuple[str, str] | None:
    """Возвращает (code, label) или None, если значение пустое/неизвестное."""
    if not dict_value:
        return None
    raw = dict_value.strip()
    code = _SKILL_BY_VALUE.get(raw.lower())
    if code is None:
        # Неизвестный навык — отдаём как есть, чтобы UI не терял данные.
        return (raw, raw)
    return (code, SKILL_LABELS[code])


def skill_code(dict_value: str | None) -> str | None:
    mapped = map_skill(dict_value)
    return mapped[0] if mapped else None


def skill_label(dict_value: str | None) -> str | None:
    mapped = map_skill(dict_value)
    return mapped[1] if mapped else None

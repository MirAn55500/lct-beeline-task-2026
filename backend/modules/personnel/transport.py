"""Маппинг транспорта словаря → код/лейбл для UI обзора дня."""

from __future__ import annotations

# dict.value может быть кодом или русской подписью — нормализуем оба варианта.
_TRANSPORT_BY_VALUE: dict[str, tuple[str, str]] = {
    "car": ("car", "Машина"),
    "automobile": ("car", "Машина"),
    "автомобиль": ("car", "Машина"),
    "машина": ("car", "Машина"),
    "bicycle": ("bike", "Велосипед"),
    "bike": ("bike", "Велосипед"),
    "велосипед": ("bike", "Велосипед"),
    "public_transport": ("public", "Общ. транспорт"),
    "public": ("public", "Общ. транспорт"),
    "общественный транспорт": ("public", "Общ. транспорт"),
    "общ. транспорт": ("public", "Общ. транспорт"),
    "walking": ("walking", "Пешком"),
    "пешком": ("walking", "Пешком"),
}


def map_transport(dict_value: str | None) -> tuple[str, str]:
    if not dict_value:
        return ("unknown", "—")
    mapped = _TRANSPORT_BY_VALUE.get(dict_value.strip().lower())
    if mapped:
        return mapped
    return (dict_value, dict_value)

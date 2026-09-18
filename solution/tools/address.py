"""Разбор адресов выгрузки в вид, пригодный для геокодера.

В выгрузках соседствуют четыре разных формата записи, и различаются они не мелочами:

    Город Москва, ул.Грайвороновская, д. 10 к 2        тип улицы ПЕРЕД названием
    МО, г. Кашира Кржижановского ул. д. 5/1            город и улица в одном поле, тип ПОСЛЕ
    обл.Московская область, г.Домодедово, пгт.Вост…    регион, город, посёлок, улица, дом
    Москва Бирюлевская ул. д. 44                       вообще без запятых

Поэтому разбор идёт не по позициям («первое поле — город, второе — улица»), а по признакам:
кусок с маркером дома — это дом, кусок с типом улицы — улица, остальное — населённый пункт.

Функция возвращает не один запрос, а **лестницу запросов** от точного к грубому: дом →
улица → населённый пункт. Если дома нет в OSM, лучше попасть на его улицу (промах порядка
сотен метров), чем свалиться в центр района (промах порядка километров).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from planner.io_csv import normalize_address  # noqa: E402

__all__ = ["ParsedAddress", "parse_address", "build_queries"]

STREET_TYPES = {
    "ул": "улица",
    "улица": "улица",
    "пр-кт": "проспект",
    "проспект": "проспект",
    "пр-зд": "проезд",
    "проезд": "проезд",
    "пер": "переулок",
    "переулок": "переулок",
    "б-р": "бульвар",
    "бульвар": "бульвар",
    "наб": "набережная",
    "набережная": "набережная",
    "ш": "шоссе",
    "шоссе": "шоссе",
    "пл": "площадь",
    "площадь": "площадь",
    "туп": "тупик",
    "аллея": "аллея",
}

CITY_PREFIXES = ("город", "г", "гор")
SETTLEMENT_PREFIXES = ("пгт", "мкр", "рп", "дп", "п", "с", "д")
REGION_PREFIXES = ("обл", "область", "мо", "московская область", "респ", "край")

# После маркера «д.» должен идти номер: цифра либо корпус/строение/владение с цифрой
# («д. к5» встречается в выгрузках). Требование цифры обязательно — иначе «д» в начале
# слова «Домодедово» опознаётся как маркер дома и съедает весь адрес.
_HOUSE_MARKER = re.compile(
    r"(?:^|[,\s])д\.?\s*(?=(?:\d|[кк]\.?\s*\d|стр\.?\s*\d|вл\.?\s*\d))",
    re.IGNORECASE,
)
_TYPE_PREFIX = re.compile(r"^([А-Яа-яё\-]+)\.\s*(.+)$")
_TYPE_SUFFIX = re.compile(r"^(.+?)\s+([А-Яа-яё\-]+)\.?$")


@dataclass(frozen=True, slots=True)
class ParsedAddress:
    city: str = ""
    street: str = ""
    house: str = ""
    settlement: str = ""

    @property
    def is_usable(self) -> bool:
        return bool(self.city or self.street)


def _strip_prefix(value: str, prefixes: tuple[str, ...]) -> tuple[str, bool]:
    """Снимает ведущий маркер вида «г.», «пгт.», «обл.» вместе с точкой или пробелом."""
    lowered = value.lower().lstrip()
    for prefix in sorted(prefixes, key=len, reverse=True):
        for form in (f"{prefix}.", f"{prefix} "):
            if lowered.startswith(form):
                return value.lstrip()[len(form):].strip(), True
    return value.strip(), False


def _normalize_house(raw: str) -> str:
    """«128 к 5» → «128к5»; «13 стр. 1» → «13с1»; «5/1» и «6к1» остаются как есть."""
    value = re.sub(r"^д\.?\s*", "", raw.strip(), flags=re.IGNORECASE)
    value = re.sub(r"\s*к\.?\s*(?=\d)", "к", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*стр\.?\s*(?=\d)", "с", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*вл\.?\s*(?=\d)", "", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", "", value)


def _as_street(chunk: str) -> str:
    """Приводит «ул.Грайвороновская» и «Кржижановского ул.» к «Грайвороновская улица»."""
    chunk = chunk.strip()
    match = _TYPE_PREFIX.match(chunk)
    if match and match.group(1).lower() in STREET_TYPES:
        return f"{match.group(2).strip()} {STREET_TYPES[match.group(1).lower()]}"
    match = _TYPE_SUFFIX.match(chunk)
    if match and match.group(2).lower().rstrip(".") in STREET_TYPES:
        return f"{match.group(1).strip()} {STREET_TYPES[match.group(2).lower().rstrip('.')]}"
    return ""


def _split_city_street(chunk: str) -> tuple[str, str]:
    """Разделяет «Кашира Кржижановского ул.» на населённый пункт и улицу.

    В части выгрузок город и улица записаны одним полем. Признак — после отделения
    первого слова остаток всё ещё разбирается как улица.
    """
    street = _as_street(chunk)
    if not street:
        return "", ""
    words = chunk.split()
    if len(words) >= 3:
        inner = _as_street(" ".join(words[1:]))
        if inner:
            return words[0], inner
    return "", street


def parse_address(address: str) -> ParsedAddress:
    """Разбирает адрес по признакам, а не по позициям полей.

    Номер квартиры снимается здесь же: геокодеру нужен дом, а не квартира, и полагаться
    на то, что вызывающий не забудет нормализовать адрес заранее, нельзя — забудет.
    """
    text = normalize_address(address)

    # Дом отделяется по маркеру «д.» — он единственный надёжный якорь во всех форматах.
    house = ""
    marker = _HOUSE_MARKER.search(text)
    if marker:
        house = _normalize_house(text[marker.end():])
        text = text[: marker.start()]

    chunks = [c.strip(" ,") for c in text.split(",") if c.strip(" ,")]

    city = settlement = street = ""
    leftovers: list[str] = []

    for chunk in chunks:
        stripped, was_region = _strip_prefix(chunk, REGION_PREFIXES)
        if was_region or chunk.strip().lower() in REGION_PREFIXES:
            continue  # регион геокодеру не нужен, город его определяет

        # Маркер города проверяется РАНЬШЕ улицы: иначе «г. Кашира Кржижановского ул.»
        # целиком опознаётся как название улицы.
        stripped_city, was_city = _strip_prefix(chunk, CITY_PREFIXES)
        if was_city:
            inner_city, inner_street = _split_city_street(stripped_city)
            city = inner_city or stripped_city
            if inner_street:
                street = inner_street
            continue

        stripped_settlement, was_settlement = _strip_prefix(chunk, SETTLEMENT_PREFIXES)
        if was_settlement:
            settlement = stripped_settlement
            continue

        inner_city, inner_street = _split_city_street(chunk)
        if inner_street:
            street = inner_street
            if inner_city and not city:
                city = inner_city
            continue

        leftovers.append(chunk)

    for chunk in leftovers:
        if not city:
            city = chunk
        elif not street:
            street = chunk

    city = re.sub(r"^город\s+", "", city, flags=re.IGNORECASE).strip()
    return ParsedAddress(city=city, street=street, house=house, settlement=settlement)


def build_queries(address: str) -> list[str]:
    """Лестница запросов от точного к грубому: дом → улица → населённый пункт."""
    parsed = parse_address(address)
    if not parsed.is_usable:
        return []

    place = [p for p in (parsed.settlement, parsed.city) if p]
    queries: list[str] = []

    def add(*parts: str) -> None:
        pieces = [p for p in parts if p]
        if not pieces:
            return
        query = ", ".join(pieces + ["Россия"])
        if query not in queries:
            queries.append(query)

    if parsed.street and parsed.house:
        add(parsed.street, parsed.house, *place)
    if parsed.street:
        add(parsed.street, *place)
    if parsed.settlement and parsed.city:
        add(parsed.settlement, parsed.city)
    add(*place)
    return queries

"""Геокодирование адресов выгрузок через Nominatim (OpenStreetMap).

Зачем отдельный инструмент, а не шаг расчёта: геокодирование — разовая операция с
внешним сервисом и лимитом «не чаще раза в секунду». Её результат коммитится в
`data/geocache.json` вместе с набором, после чего планировщик работает без сети и
полностью воспроизводимо.

Запуск:
    python tools/geocode.py --dry-run     # показать запросы, никуда не ходить
    python tools/geocode.py               # геокодировать недостающие адреса
    python tools/geocode.py --limit 20    # первые 20 (для проверки)

Использование Nominatim ограничено правилами OSM: один запрос в секунду и осмысленный
User-Agent. Оба требования соблюдены; результат кэшируется, чтобы не обращаться повторно.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner.io_csv import _read_rows, normalize_address  # noqa: E402

DATASET_DIR = ROOT.parent / "Обезличивание"
CACHE_PATH = ROOT / "data" / "geocache.json"
ENDPOINT = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "LCT2026-BeelineRoutePlanner/1.0 (hackathon prototype; contact via repo)"
DELAY_SECONDS = 1.1

# Тип улицы в выгрузках стоит ПЕРЕД названием и сокращён: «ул.Грайвороновская».
# Nominatim ожидает обычный порядок и полное слово: «Грайвороновская улица».
STREET_TYPES = {
    "ул.": "улица",
    "пр-кт.": "проспект",
    "пр-зд.": "проезд",
    "проезд.": "проезд",
    "пер.": "переулок",
    "б-р.": "бульвар",
    "наб.": "набережная",
    "ш.": "шоссе",
    "пл.": "площадь",
    "туп.": "тупик",
    "аллея.": "аллея",
}

CITY_PREFIXES = ("город ", "г.", "г ")
REGION_MARKERS = ("мо", "обл.московская область", "московская область")


def _clean_city(raw: str) -> str:
    value = raw.strip()
    lowered = value.lower()
    for prefix in CITY_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix):].strip()
            lowered = value.lower()
    if lowered.startswith("город "):
        value = value[6:].strip()
    return value


def _clean_house(raw: str) -> str:
    """«д. 128 к 5» → «128к5»; «д. 1А» → «1А»; строение и владение сохраняются."""
    value = raw.strip()
    value = re.sub(r"^д\.?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*к\.?\s*", "к", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*стр\.?\s*", "с", value, flags=re.IGNORECASE)
    return value.strip()


def _clean_street(raw: str) -> str:
    value = raw.strip()
    match = re.match(r"^([А-Яа-яё\-]+\.)\s*(.+)$", value)
    if match and match.group(1).lower() in STREET_TYPES:
        return f"{match.group(2).strip()} {STREET_TYPES[match.group(1).lower()]}"
    return value


def build_query(address: str) -> str:
    """Приводит адрес выгрузки к виду, который понимает Nominatim."""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if not parts:
        return ""

    # Ведущий маркер региона («МО», «обл.Московская область») city не задаёт.
    while parts and parts[0].lower().strip(".") in REGION_MARKERS:
        parts.pop(0)
    if not parts:
        return ""

    city = _clean_city(parts[0])
    rest = parts[1:]

    # Единичный случай без запятых: «Москва Бирюлевская ул. д. 44».
    if not rest:
        return f"{city}, Россия"

    street = _clean_street(rest[0])
    house = _clean_house(rest[1]) if len(rest) > 1 else ""
    pieces = [p for p in (street, house, city, "Россия") if p]
    return ", ".join(pieces)


def collect_addresses() -> tuple[list[str], list[str]]:
    """Уникальные адреса заявок и адреса офисов из всех выгрузок."""
    addresses: set[str] = set()
    offices: set[str] = set()
    for path in sorted(DATASET_DIR.glob("*.csv")):
        for row in _read_rows(path):
            first = row.get("Заявка", "").lower()
            if "адрес офиса" in first:
                values = [v for k, v in row.items() if k != "Заявка" and v]
                if values:
                    offices.add(values[0].strip())
                continue
            value = row.get("Адрес", "").strip()
            if value:
                addresses.add(normalize_address(value))
    return sorted(addresses), sorted(offices)


def geocode(query: str) -> tuple[float, float] | None:
    params = urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "ru"}
    )
    request = urllib.request.Request(
        f"{ENDPOINT}?{params}", headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload:
        return None
    return float(payload[0]["lat"]), float(payload[0]["lon"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="показать запросы и выйти")
    parser.add_argument("--limit", type=int, help="ограничить число адресов")
    parser.add_argument("--retry-missed", action="store_true", help="повторить ранее не найденные")
    args = parser.parse_args()

    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    cache.setdefault("addresses", {})
    cache.setdefault("not_found", [])

    addresses, offices = collect_addresses()
    targets = offices + addresses
    known = set(cache["addresses"])
    missed = set() if args.retry_missed else set(cache["not_found"])
    pending = [a for a in targets if a not in known and a not in missed]
    if args.limit:
        pending = pending[: args.limit]

    print(f"Всего адресов: {len(targets)} (из них офисов: {len(offices)})")
    print(f"Уже в кэше: {len(known)} | пропускаем как ненайденные ранее: {len(missed)}")
    print(f"К геокодированию: {len(pending)}")

    if args.dry_run:
        for address in pending[:25]:
            print(f"  {address}\n      -> {build_query(address)}")
        if len(pending) > 25:
            print(f"  ... ещё {len(pending) - 25}")
        return 0

    found = 0
    not_found: list[str] = []
    started = time.monotonic()

    for index, address in enumerate(pending, 1):
        query = build_query(address)
        try:
            result = geocode(query) if query else None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"  [{index}/{len(pending)}] ОШИБКА СЕТИ: {exc} — прерываю, кэш сохранён")
            break

        if result is None:
            not_found.append(address)
            print(f"  [{index}/{len(pending)}] не найден: {query}")
        else:
            cache["addresses"][address] = {"lat": round(result[0], 6), "lon": round(result[1], 6)}
            found += 1
            if index % 20 == 0 or index == len(pending):
                print(f"  [{index}/{len(pending)}] найдено {found}, не найдено {len(not_found)}")

        if index % 10 == 0:
            _save(cache, not_found)
        time.sleep(DELAY_SECONDS)

    _save(cache, not_found)
    elapsed = time.monotonic() - started
    print(f"\nГотово за {elapsed:.0f} с. Найдено: {found}. Не найдено: {len(not_found)}.")
    print(f"Всего в кэше адресов: {len(cache['addresses'])}")
    if not_found:
        print("Не найдены (останутся на координате района):")
        for address in not_found[:15]:
            print(f"  · {address}")
        if len(not_found) > 15:
            print(f"  ... ещё {len(not_found) - 15}")
    return 0


def _save(cache: dict, not_found: list[str]) -> None:
    merged = sorted(set(cache.get("not_found", [])) | set(not_found))
    cache["not_found"] = merged
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())

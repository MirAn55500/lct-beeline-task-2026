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

from planner.io_csv import _read_rows, find_dataset_dir, normalize_address  # noqa: E402
from tools.address import build_queries  # noqa: E402

DATASET_DIR = find_dataset_dir() or (ROOT.parent / "Обезличивание")
CACHE_PATH = ROOT / "data" / "geocache.json"
ENDPOINT = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "LCT2026-BeelineRoutePlanner/1.0 (hackathon prototype; contact via repo)"
DELAY_SECONDS = 1.1

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


PRECISION = ("дом", "улица", "населённый пункт", "населённый пункт")


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
    if args.retry_missed:
        cache["not_found"] = []
    pending = [a for a in targets if a not in known and a not in missed]
    if args.limit:
        pending = pending[: args.limit]

    print(f"Всего адресов: {len(targets)} (из них офисов: {len(offices)})")
    print(f"Уже в кэше: {len(known)} | пропускаем как ненайденные ранее: {len(missed)}")
    print(f"К геокодированию: {len(pending)}")

    if args.dry_run:
        for address in pending[:25]:
            ladder = " | ".join(build_queries(address)) or "— не разобран —"
            print(f"  {address}\n      -> {ladder}")
        if len(pending) > 25:
            print(f"  ... ещё {len(pending) - 25}")
        return 0

    found = 0
    not_found: list[str] = []
    started = time.monotonic()

    for index, address in enumerate(pending, 1):
        queries = build_queries(address)
        result = None
        level = 0
        failed = False

        # Лестница запросов: сначала дом, при промахе — улица, затем населённый пункт.
        # Улица промахивается на сотни метров, центр района — на километры.
        for level, query in enumerate(queries):
            try:
                result = geocode(query)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                print(f"  [{index}/{len(pending)}] ОШИБКА СЕТИ: {exc} — прерываю, кэш сохранён")
                failed = True
                break
            time.sleep(DELAY_SECONDS)
            if result is not None:
                break

        if failed:
            break

        if result is None:
            not_found.append(address)
            print(f"  [{index}/{len(pending)}] не найден: {address}")
        else:
            precision = PRECISION[min(level, len(PRECISION) - 1)]
            cache["addresses"][address] = {
                "lat": round(result[0], 6),
                "lon": round(result[1], 6),
                "precision": precision,
            }
            found += 1
            if precision != "дом":
                print(f"  [{index}/{len(pending)}] {address} — точность: {precision}")
            elif index % 20 == 0 or index == len(pending):
                print(f"  [{index}/{len(pending)}] найдено {found}, не найдено {len(not_found)}")

        if index % 10 == 0:
            _save(cache, not_found)

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

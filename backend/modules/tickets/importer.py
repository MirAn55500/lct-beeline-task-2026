"""Разбор CSV/JSON выгрузки заявок в строки для записи в БД."""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

_SOLUTION = Path(__file__).resolve().parents[3] / "solution"
if str(_SOLUTION) not in sys.path:
    sys.path.insert(0, str(_SOLUTION))

from planner.io_csv import WorkTypeCatalog  # noqa: E402

_OFFICE_MARKERS = ("адрес офиса",)
_CLOSED = {"выполнена", "отменена", "completed", "cancelled"}
_STATUS = {
    "не отправлена": "pending",
    "отправлена": "pending",
    "в пути": "en_route",
    "в работе": "in_progress",
    "выполнена": "completed",
    "отменена": "cancelled",
}
_CATEGORY = {
    "подключение": "Подключение",
    "дозаказ": "Дозаказ",
    "локальная заявка": "Ремонт",
    "ремонт": "Ремонт",
    "глобальная проблема": "Аварийные работы",
    "авария": "Аварийные работы",
    "аварийные работы": "Аварийные работы",
}


@dataclass(frozen=True, slots=True)
class ParsedTicket:
    external_id: str
    address: str
    district: str
    window_start: datetime
    window_end: datetime
    category: str
    hd: str
    status: str
    skill: str
    priority: str
    # Заполняются геокодером в TicketsService.upload
    latitude: float | None = None
    longitude: float | None = None
    geo_precision: str | None = None
    geo_source: str | None = None


def _category(bk: str) -> str:
    key = bk.strip().rstrip(".").strip().lower()
    return _CATEGORY.get(key, bk.strip() or "Подключение")


def _parse_moment(value: str, fallback_day: date) -> datetime:
    """Дата из файла сохраняется. Без даты окно вешается на выбранный день."""
    text = value.strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            clock = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return datetime.combine(fallback_day, clock.time())
    raise ValueError(f"Не удалось разобрать дату и время: {text}")


def _rows_from_csv(raw: bytes) -> list[dict[str, str]]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        reader = csv.DictReader(text.splitlines(), delimiter=";")
        return [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    raise ValueError(f"Не удалось прочитать CSV: {last_error}")


def _rows_from_json(raw: bytes) -> list[dict[str, str]]:
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("JSON должен быть списком заявок")
    rows: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        rows.append({str(k): "" if v is None else str(v) for k, v in item.items()})
    return rows


def parse_upload(raw: bytes, filename: str, day: date) -> tuple[list[ParsedTicket], int]:
    """Возвращает заявки и число пропущенных строк (пустые, офис, закрытые)."""
    name = filename.lower()
    if name.endswith(".json"):
        rows = _rows_from_json(raw)
    else:
        rows = _rows_from_csv(raw)

    catalog = WorkTypeCatalog.load()
    tickets: list[ParsedTicket] = []
    skipped = 0

    for row in rows:
        external_id = row.get("Заявка", "").strip()
        if any(marker in external_id.lower() for marker in _OFFICE_MARKERS):
            skipped += 1
            continue
        if not external_id or not row.get("Начало") or not row.get("Окончание"):
            skipped += 1
            continue

        status_raw = row.get("Статус BK", "").strip()
        if status_raw.lower() in _CLOSED:
            skipped += 1
            continue

        bk = row.get("Тип заявки BK", "")
        hd = row.get("Тип заявки HD", "").strip() or "—"
        spec = catalog.resolve(bk, hd)
        address = row.get("Адрес", "").strip() or "—"
        district = row.get("Район", "").strip() or "—"

        start = _parse_moment(row["Начало"], day)
        end = _parse_moment(row["Окончание"], start.date())
        if end <= start:
            end = datetime.combine(start.date(), time(23, 59))

        tickets.append(
            ParsedTicket(
                external_id=external_id,
                address=address,
                district=district,
                window_start=start,
                window_end=end,
                category=_category(bk),
                hd=hd,
                status=_STATUS.get(status_raw.lower(), "pending"),
                skill=str(spec.get("skill", "connection")),
                priority=str(spec.get("priority", "connection")),
            )
        )

    return tickets, skipped

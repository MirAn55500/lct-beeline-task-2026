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


_REQUIRED = ("Заявка", "Начало", "Окончание", "Адрес")
"""Без этих колонок строка не заявка: номер, окно клиента и куда ехать."""


def _check_columns(columns: list[str]) -> None:
    """Файл другого вида (не тот разделитель, чужая выгрузка) — ошибка, а не «0 заявок»."""
    missing = [name for name in _REQUIRED if name not in columns]
    if missing:
        raise ValueError(
            "В файле нет колонок " + ", ".join(f"«{name}»" for name in missing)
            + ". Нужна выгрузка заявок: CSV с разделителем «;» и строкой заголовков"
        )


def _rows_from_csv(raw: bytes) -> list[dict[str, str]]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        reader = csv.DictReader(text.splitlines(), delimiter=";")
        _check_columns([(name or "").strip() for name in reader.fieldnames or []])
        # Лишние «;» в строке (значения без заголовка) DictReader кладёт списком под ключ
        # None — они не нужны, а раньше роняли загрузку ошибкой 500
        return [
            {k.strip(): (v or "").strip() for k, v in row.items() if k is not None}
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
        rows.append({str(k).strip(): "" if v is None else str(v).strip() for k, v in item.items()})
    if rows:
        _check_columns(list(rows[0]))
    return rows


MAX_NOTES = 5
"""Сколько строк с ошибками перечислять в уведомлении: остальные — одним «и ещё N»."""


@dataclass(slots=True)
class ParsedUpload:
    tickets: list[ParsedTicket]
    skipped: int
    """Пустые строки, офис, строки с ошибками."""
    notes: list[str]
    """Что не так со строками файла — для уведомления о загрузке."""


class _Notes:
    """Ошибки строк по видам: в уведомлении первые несколько, а не простыня на сотню строк."""

    def __init__(self) -> None:
        self._items: list[str] = []
        self.count = 0

    def add(self, text: str) -> None:
        self.count += 1
        if len(self._items) < MAX_NOTES:
            self._items.append(text)

    def lines(self) -> list[str]:
        more = self.count - len(self._items)
        return self._items + ([f"…и ещё {more} {_rows(more)} с ошибками"] if more > 0 else [])


def _rows(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "строка"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "строки"
    return "строк"


def parse_upload(raw: bytes, filename: str, day: date) -> ParsedUpload:
    """Строки файла → заявки. Строка с ошибкой пропускается и попадает в `notes`:
    повтор номера, окно «конец раньше начала», неразборчивая дата, нет адреса.

    «Статус BK» не учитывается: каждая строка выгрузки — открытая заявка дня. В выгрузках
    прошедших дней почти все строки «Выполнена» или «Отменена», и из файла на 74 заявки
    в план попадали 3.
    """
    name = filename.lower()
    json_file = name.endswith(".json")
    rows = _rows_from_json(raw) if json_file else _rows_from_csv(raw)

    catalog = WorkTypeCatalog.load()
    tickets: list[ParsedTicket] = []
    seen: dict[str, int] = {}
    notes = _Notes()
    unknown_types: dict[str, int] = {}
    skipped = 0

    for index, row in enumerate(rows):
        # Номер строки, как в Excel: заголовок — первая строка файла
        line = f"запись {index + 1}" if json_file else f"строка {index + 2}"
        external_id = row.get("Заявка", "").strip()
        if any(marker in external_id.lower() for marker in _OFFICE_MARKERS):
            skipped += 1
            continue
        if not external_id or not row.get("Начало") or not row.get("Окончание"):
            skipped += 1
            continue
        if external_id in seen:
            # Какая из строк верная, по файлу не понять — берём первую и говорим об этом
            notes.add(f"{line}: заявка {external_id} уже была в {seen[external_id]}-й — повтор пропущен")
            skipped += 1
            continue
        seen[external_id] = index + 1 if json_file else index + 2

        address = row.get("Адрес", "").strip()
        if not address or address in {"—", "-"}:
            # Без адреса точка нашлась бы только по району — инженер поехал бы наугад
            notes.add(f"{line}: у заявки {external_id} нет адреса — пропущена")
            skipped += 1
            continue

        try:
            start = _parse_moment(row["Начало"], day)
            end = _parse_moment(row["Окончание"], start.date())
        except ValueError as exc:
            notes.add(f"{line}: заявка {external_id} — {str(exc)[0].lower()}{str(exc)[1:]}, пропущена")
            skipped += 1
            continue
        if end <= start and end.time() == time(0, 0):
            end = datetime.combine(start.date(), time(23, 59))  # «до 00:00» — до конца дня
        if end <= start:
            notes.add(
                f"{line}: у заявки {external_id} окно {start:%H:%M}–{end:%H:%M} "
                "заканчивается раньше начала — пропущена"
            )
            skipped += 1
            continue

        bk = row.get("Тип заявки BK", "")
        if bk.strip() and bk.strip().rstrip(".").strip().lower() not in _CATEGORY:
            unknown_types[bk.strip()] = unknown_types.get(bk.strip(), 0) + 1
        hd = row.get("Тип заявки HD", "").strip() or "—"
        spec = catalog.resolve(bk, hd)
        district = row.get("Район", "").strip() or "—"

        tickets.append(
            ParsedTicket(
                external_id=external_id,
                address=address,
                district=district,
                window_start=start,
                window_end=end,
                category=_category(bk),
                hd=hd,
                status="pending",
                skill=str(spec.get("skill", "connection")),
                priority=str(spec.get("priority", "connection")),
            )
        )

    lines = notes.lines()
    for bk, count in list(unknown_types.items())[:MAX_NOTES]:
        lines.append(
            f"тип заявки BK «{bk}» не из справочника ({count} {_rows(count)}) — "
            "норматив и навык как у подключения"
        )
    return ParsedUpload(tickets, skipped, lines)


WORK_TYPE_BK = {
    "Подключение": "Подключение",
    "Дозаказ": "Дозаказ",
    "Ремонт": "Локальная заявка",
    "Аварийные работы": "Глобальная проблема",
}
"""Тип работ из окна «Добавить заявку» → «Тип заявки BK» выгрузки: по нему норматив и навык."""


def manual_ticket(
    *, external_id: str, address: str, start: datetime, end: datetime, work_type: str
) -> ParsedTicket:
    """Одна заявка из окна «Добавить заявку» — как строка выгрузки без района и HD."""
    bk = WORK_TYPE_BK[work_type]
    spec = WorkTypeCatalog.load().resolve(bk, "—")
    return ParsedTicket(
        external_id=external_id,
        address=address,
        district="—",
        window_start=start,
        window_end=end,
        category=_category(bk),
        hd="—",
        status="pending",
        skill=str(spec.get("skill", "connection")),
        priority=str(spec.get("priority", "connection")),
    )

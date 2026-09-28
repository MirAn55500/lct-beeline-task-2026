"""Разбор CSV/JSON профилей инженеров для загрузки в бригаду."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, time


@dataclass(frozen=True, slots=True)
class ParsedEngineer:
    name: str
    transport: str
    skills: tuple[str, ...]
    qualification: str | None
    start_work: time | None
    end_work: time | None
    home_address: str | None


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
        raise ValueError("JSON должен быть списком инженеров")
    rows: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        rows.append({str(k): "" if v is None else str(v) for k, v in item.items()})
    return rows


def _cell(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key, "").strip()
        if value:
            return value
    # Регистронезависимый поиск по ключам файла экспорта / шаблона
    lower = {k.lower(): v for k, v in row.items()}
    for key in keys:
        value = lower.get(key.lower(), "").strip()
        if value:
            return value
    return ""


def _parse_time(value: str) -> time | None:
    text = value.strip()
    if not text:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Не удалось разобрать время: {text}")


def _skills(raw: str) -> tuple[str, ...]:
    if not raw.strip():
        return ()
    parts = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    return tuple(dict.fromkeys(parts))


def parse_engineers_upload(raw: bytes, filename: str) -> tuple[list[ParsedEngineer], int]:
    """Возвращает инженеров и число пропущенных пустых/битых строк."""
    name = filename.lower()
    rows = _rows_from_json(raw) if name.endswith(".json") else _rows_from_csv(raw)

    engineers: list[ParsedEngineer] = []
    skipped = 0
    for row in rows:
        fio = _cell(row, "ФИО", "fio", "name", "Имя")
        if not fio:
            skipped += 1
            continue
        transport = _cell(row, "Транспорт", "transport")
        skills_raw = _cell(row, "Навыки", "skills", "skill")
        if not transport or not skills_raw:
            skipped += 1
            continue
        try:
            start = _parse_time(_cell(row, "Начало смены", "start_work", "Начало"))
            end = _parse_time(_cell(row, "Конец смены", "end_work", "Окончание"))
        except ValueError:
            skipped += 1
            continue
        if (start is None) != (end is None):
            skipped += 1
            continue
        if start is not None and end is not None and end <= start:
            skipped += 1
            continue

        qualification = _cell(row, "Квалификация", "qualification", "position") or None
        home = _cell(row, "Домашний адрес", "home_address") or None

        engineers.append(
            ParsedEngineer(
                name=fio,
                transport=transport,
                skills=_skills(skills_raw),
                qualification=qualification,
                start_work=start,
                end_work=end,
                home_address=home,
            )
        )
    return engineers, skipped

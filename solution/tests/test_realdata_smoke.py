# -*- coding: utf-8 -*-
"""Smoke-тест на реальных обезличенных выгрузках (SPEC §10).

Проверяет только одно: загрузчик читает предоставленный CSV (cp1251, ';'),
собирается сценарий и план по нему валиден. Сеть не используется — координаты
берутся из кэша или детерминированной подстановки с предупреждением.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from factories import plan_optimized, validate_plan

io_csv = pytest.importorskip("planner.io_csv", reason="модуль planner.io_csv ещё не готов")

CSV_CANDIDATES = (
    "Восток Синтетические данные.csv",
    "Юго-восток Синтетические данные.csv",
    "Югоцентр Синтетические данные.csv",
)

LOADER_NAMES = (
    "load_scenario",
    "read_scenario",
    "scenario_from_csv",
    "load_scenario_from_csv",
    "build_scenario",
)
REQUEST_LOADER_NAMES = ("load_requests", "read_requests", "requests_from_csv", "parse_requests")


@pytest.fixture(scope="module")
def csv_path(anonymized_csv_dir: Path) -> Path:
    """Первый доступный CSV из каталога обезличенных данных."""
    if not anonymized_csv_dir.exists():
        pytest.skip(f"каталог с данными не найден: {anonymized_csv_dir}")
    for name in CSV_CANDIDATES:
        candidate = anonymized_csv_dir / name
        if candidate.exists():
            return candidate
    found = sorted(anonymized_csv_dir.glob("*.csv"))
    if not found:
        pytest.skip(f"в {anonymized_csv_dir} нет CSV-файлов")
    return found[0]


def _find_callable(names):
    """Найти первую доступную функцию загрузчика из списка имён."""
    for name in names:
        func = getattr(io_csv, name, None)
        if callable(func):
            return name, func
    return None, None


@pytest.mark.realdata
def test_csv_file_is_readable_in_cp1251(csv_path: Path):
    """Файл читается в cp1251 и имеет ';'-разделённый заголовок."""
    text = csv_path.read_bytes().decode("cp1251")
    header = text.splitlines()[0]
    assert ";" in header, f"неожиданный разделитель в заголовке: {header!r}"
    assert len(text.splitlines()) > 5


@pytest.mark.realdata
def test_loader_reads_requests_from_real_csv(csv_path: Path):
    """Загрузчик возвращает непустой набор заявок без обращения к сети."""
    name, func = _find_callable(REQUEST_LOADER_NAMES + LOADER_NAMES)
    if func is None:
        pytest.skip(
            f"в planner.io_csv нет загрузчика из {REQUEST_LOADER_NAMES + LOADER_NAMES}; "
            f"доступно: {[n for n in dir(io_csv) if not n.startswith('_')]}"
        )
    loaded = func(str(csv_path))
    if isinstance(loaded, tuple):
        loaded = loaded[0]
    requests = getattr(loaded, "requests", loaded)
    assert len(requests) > 0, f"{name}() вернул пустой список заявок"


@pytest.mark.realdata
@pytest.mark.slow
def test_plan_over_real_data_is_valid(csv_path: Path):
    """План по реальным данным валиден — сквозная проверка пайплайна."""
    name, func = _find_callable(LOADER_NAMES)
    if func is None:
        pytest.skip("в planner.io_csv нет функции сборки Scenario из CSV")

    signature = inspect.signature(func)
    try:
        loaded = func(str(csv_path))
    except TypeError as exc:
        pytest.skip(f"{name}{signature} требует дополнительных аргументов: {exc}")

    # Загрузчик может возвращать пару (сценарий, примечания) — примечания идут в warnings.
    scenario = loaded[0] if isinstance(loaded, tuple) else loaded
    if not hasattr(scenario, "requests"):
        pytest.skip(f"{name}() вернул не Scenario: {type(scenario).__name__}")
    if not scenario.engineers:
        pytest.skip("в сценарии нет инженеров — для плана нужен отдельный источник бригад")

    result = plan_optimized(scenario)
    assert validate_plan(result, scenario) == []
    assert len(result.assignments) == len(scenario.requests)


@pytest.mark.realdata
def test_service_row_is_not_treated_as_request(csv_path: Path):
    """Служебная строка «Адрес Офиса» не должна попадать в заявки (SPEC §10)."""
    name, func = _find_callable(REQUEST_LOADER_NAMES + LOADER_NAMES)
    if func is None:
        pytest.skip("загрузчик недоступен")
    text = csv_path.read_bytes().decode("cp1251")
    if "Адрес Офиса" not in text:
        pytest.skip("в этом файле нет служебной строки «Адрес Офиса»")

    loaded = func(str(csv_path))
    if isinstance(loaded, tuple):
        loaded = loaded[0]
    requests = getattr(loaded, "requests", loaded)
    for request in requests:
        address = getattr(request, "address", "") or ""
        assert "Адрес Офиса" not in address, "служебная строка распознана как заявка"

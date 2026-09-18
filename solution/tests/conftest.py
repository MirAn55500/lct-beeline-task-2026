# -*- coding: utf-8 -*-
"""Общая настройка сьюта: путь до пакета ``planner`` и переиспользуемые фикстуры.

Тесты написаны строго по ``solution/SPEC.md``. Реализация пишется параллельно,
поэтому все обращения к пакету идут через :mod:`factories`, который умеет
корректно скипнуть модуль целиком, если пакет ещё не готов.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# solution/ должен быть на sys.path, чтобы работал `import planner`
# при запуске `python -m pytest solution/tests` из корня репозитория.
_SOLUTION_DIR = Path(__file__).resolve().parent.parent
if str(_SOLUTION_DIR) not in sys.path:
    sys.path.insert(0, str(_SOLUTION_DIR))

# Каталог самих тестов — чтобы `import factories` работал при любом rootdir.
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


@pytest.fixture(scope="session")
def solution_dir() -> Path:
    """Каталог solution/ — корень пакета planner и данных."""
    return _SOLUTION_DIR


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Корень репозитория (на уровень выше solution/)."""
    return _SOLUTION_DIR.parent


@pytest.fixture(scope="session")
def anonymized_csv_dir(repo_root: Path) -> Path:
    """Каталог с обезличенными выгрузками (cp1251, разделитель ';')."""
    try:
        from planner.io_csv import find_dataset_dir
    except Exception:
        return repo_root / "Обезличивание"
    return find_dataset_dir() or (repo_root / "Обезличивание")


@pytest.fixture
def tz():
    """Часовой пояс сценариев — Europe/Moscow как фиксированный UTC+3."""
    from factories import TZ

    return TZ


@pytest.fixture
def scenario_date():
    """Дата по умолчанию для всех сценариев тестов."""
    from factories import DATE

    return DATE

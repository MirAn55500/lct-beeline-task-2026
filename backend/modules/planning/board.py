"""Планы, открытые для ручной правки на Ганте: доска планировщика в памяти процесса.

Доска держит маршруты и модель поездок (ORS, rRAPTOR) — собрать её стоит секунды, а
проверка хода после этого — миллисекунды. Поэтому доска живёт между запросами: окна
постановки и ходы одного плана считаются на одной и той же. После сохранённого хода
она переезжает на новую версию плана. Через `TTL` собирается заново: «сейчас»
(какие визиты уже начаты) и данные в БД за это время могли измениться.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date

from modules.planning import scenario_builder as _builder  # noqa: F401 - sys.path к planner

from planner.dispatch import Board  # noqa: E402
from planner.models import Scenario  # noqa: E402
from planner.ors import Routing  # noqa: E402

TTL_SECONDS = 300.0
LIMIT = 16


@dataclass
class OpenBoard:
    board: Board
    scenario: Scenario
    routing: Routing
    travel: object
    region_id: int
    day: date
    transport_of: dict[int, int]
    address_of: dict[int, int]
    office_of: dict[int, int]
    lock: threading.Lock = field(default_factory=threading.Lock)
    opened: float = field(default_factory=time.monotonic)


_boards: dict[int, OpenBoard] = {}
_guard = threading.Lock()


def get(plan_id: int) -> OpenBoard | None:
    with _guard:
        entry = _boards.get(plan_id)
        if entry is not None and time.monotonic() - entry.opened > TTL_SECONDS:
            del _boards[plan_id]
            return None
        return entry


def put(plan_id: int, entry: OpenBoard) -> None:
    with _guard:
        _boards[plan_id] = entry
        while len(_boards) > LIMIT:
            oldest = min(_boards, key=lambda key: _boards[key].opened)
            del _boards[oldest]


def rename(old_plan_id: int, new_plan_id: int) -> None:
    with _guard:
        entry = _boards.pop(old_plan_id, None)
        if entry is not None:
            _boards[new_plan_id] = entry


def drop(plan_id: int) -> None:
    with _guard:
        _boards.pop(plan_id, None)

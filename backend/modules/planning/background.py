"""Расчёт плана после загрузки заявок — в фоне, чтобы запрос загрузки не ждал минутами.

Файл с сотней новых адресов считается полторы-три минуты (время в пути между новыми
точками: матрицы ORS и RAPTOR), а nginx фронта ждёт ответа не дольше 180 с. Поэтому
загрузка только записывает заявки и ставит расчёт в очередь, а обзор дня показывает,
что план считается (`status`), пока очередь не дойдёт до конца.

Расчёты идут по одному: на стенде два ядра и памяти впритык, а файл на несколько дат
иначе запустил бы несколько тяжёлых расчётов разом. Состояние — в памяти процесса
(uvicorn запускается одним процессом); после перезапуска план досчитывается пересчётом.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from core.database import async_session_factory
from core.exceptions import AppError

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_pending: dict[tuple[int, date], int] = {}
"""(регион, день) → расчётов в очереди, включая идущий."""
_failed: dict[tuple[int, date], str] = {}
"""(регион, день) → почему последний фоновый расчёт не удался."""
_tasks: set[asyncio.Task] = set()


def schedule(region_id: int, days: list[date]) -> None:
    """Поставить в очередь расчёт плана на каждый день."""
    for day in days:
        key = (region_id, day)
        _failed.pop(key, None)
        _pending[key] = _pending.get(key, 0) + 1
        task = asyncio.create_task(_run(key))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


def status(region_id: int, day: date) -> tuple[bool, str | None]:
    """(план ещё считается, причина неудачи последнего расчёта)."""
    key = (region_id, day)
    return key in _pending, _failed.get(key)


async def _run(key: tuple[int, date]) -> None:
    from modules.planning.service import PlanningService

    try:
        async with _lock:
            try:
                async with async_session_factory() as session:
                    planned = await PlanningService(session).recalculate(*key)
                _failed.pop(key, None)
                logger.info("План на %s, регион %d: версия %d", key[1], key[0], planned.version)
            except AppError as exc:
                _failed[key] = exc.message
            except Exception:  # noqa: BLE001
                logger.exception("Фоновый расчёт плана на %s, регион %d", key[1], key[0])
                _failed[key] = "Не удалось рассчитать план — попробуйте пересчитать"
    finally:
        left = _pending.get(key, 1) - 1
        if left > 0:
            _pending[key] = left
        else:
            _pending.pop(key, None)

"""Расчёт плана после загрузки заявок — в фоне, чтобы запрос загрузки не ждал минутами.

Файл с сотней новых адресов считается полторы-три минуты (время в пути между новыми
точками: матрицы ORS и RAPTOR), а nginx фронта ждёт ответа не дольше 180 с. Поэтому
загрузка только записывает заявки и ставит расчёт в очередь, а обзор дня показывает,
что план считается (`status`), пока очередь не дойдёт до конца.

Расчёты идут по одному: на стенде два ядра и памяти впритык, а файл на несколько дат
иначе запустил бы несколько тяжёлых расчётов разом. Состояние — в памяти процесса
(uvicorn запускается одним процессом); после перезапуска план досчитывается пересчётом.

Сколько ждать (`estimate`): почти всё время уходит на адреса, которых ещё нет в кэше
маршрутов, — по ним идут в ORS и RAPTOR. Известные адреса считаются секунды. Поэтому
оценка — «база + секунды на новый адрес», и обе величины подстраиваются по тому, сколько
на деле шли прошлые расчёты.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from datetime import date

from sqlmodel.ext.asyncio.session import AsyncSession

from core.database import async_session_factory
from core.exceptions import AppError
from modules.planning.schemas import RemakeLevel
from modules.planning import routing_cache  # и sys.path к planner

from planner.models import Scenario  # noqa: E402
from planner.ors import (  # noqa: E402
    DEFAULT_PROFILES,
    NO_MATRIX_PROFILES,
    collect_points,
    point_key,
    scenario_modes,
)

logger = logging.getLogger(__name__)

Key = tuple[int, date]

_lock = asyncio.Lock()
_pending: dict[Key, int] = {}
"""(регион, день) → расчётов в очереди, включая идущий."""
_failed: dict[Key, str] = {}
"""(регион, день) → почему последний фоновый расчёт не удался."""
_tasks: set[asyncio.Task] = set()

_queued: dict[Key, int] = {}
"""(регион, день) → номер в очереди: чьи расчёты идут раньше."""
_sequence = 0
_estimate: dict[Key, tuple[float, int]] = {}
"""(регион, день) → (ожидаемые секунды, новых адресов)."""
_started: dict[Key, float] = {}
"""(регион, день) → когда начался идущий расчёт (monotonic)."""

_rate = {"base": 10.0, "point": 1.2}
"""Секунды на расчёт без новых адресов и на каждый новый адрес — стартовые, по замерам
на стенде (известные адреса ~8 с, сотня новых — полторы-три минуты), дальше по факту."""
_LEARN = 0.5
"""Вес последнего замера: план с тем же набором адресов считается почти одинаково."""


def new_points(scenario: Scenario) -> int:
    """Сколько точек сценария ещё не посчитано: нет в кэше ни одного участка из них."""
    points = collect_points(scenario)
    profiles = [
        DEFAULT_PROFILES[mode]
        for mode in scenario_modes(scenario)
        if DEFAULT_PROFILES.get(mode) not in (None, *NO_MATRIX_PROFILES)
    ]
    if not profiles or len(points) < 2:
        return 0
    cache = routing_cache.shared()
    keys = [point_key(p) for p in points]
    fresh = 0
    for profile in profiles:
        known = {a for a, _ in cache.legs_of(profile)}
        fresh = max(fresh, sum(key not in known for key in keys))
    return fresh


async def estimate(session: AsyncSession, region_id: int, days: list[date]) -> dict[date, tuple[float, int]]:
    """Ожидаемое время расчёта каждого дня, секунды, и число новых адресов."""
    from modules.planning.service import PlanningService

    planner = PlanningService(session)
    estimates: dict[date, tuple[float, int]] = {}
    for day in days:
        try:
            scenario, _ = await planner._scenario(region_id, day)
            fresh = await asyncio.to_thread(new_points, scenario)
        except AppError:
            fresh = 0  # считать нечего — об этом скажет сам расчёт
        except Exception:  # noqa: BLE001 — оценка не должна ломать загрузку
            logger.warning("Не удалось оценить время расчёта на %s, регион %d", day, region_id, exc_info=True)
            fresh = 0
        estimates[day] = (_rate["base"] + _rate["point"] * fresh, fresh)
    return estimates


def schedule(
    region_id: int,
    days: list[date],
    estimates: dict[date, tuple[float, int]] | None = None,
    *,
    remake_level: RemakeLevel = RemakeLevel.FREE,
    fresh: Iterable[int] = (),
) -> None:
    """Поставить в очередь расчёт плана на каждый день.

    `remake_level` — уровень перестроения из окна загрузки: «Фикс» и «Инженерный» ставят
    новые заявки в последнюю версию плана, «Свободный» считает день заново.
    `fresh` — id добавленных и изменённых заявок: их прежние визиты не сохраняются.
    """
    fresh = frozenset(fresh)
    global _sequence
    for day in days:
        key = (region_id, day)
        _failed.pop(key, None)
        _pending[key] = _pending.get(key, 0) + 1
        _sequence += 1
        _queued[key] = _sequence
        _estimate[key] = (estimates or {}).get(day) or (_rate["base"], 0)
        task = asyncio.create_task(_run(key, remake_level, fresh))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


def _left(key: Key, now: float) -> float:
    seconds, _ = _estimate.get(key, (_rate["base"], 0))
    started = _started.get(key)
    return seconds - (now - started) if started is not None else seconds


def status(region_id: int, day: date) -> tuple[bool, str | None, int | None]:
    """(план ещё считается, причина неудачи последнего расчёта, примерно секунд до готовности)."""
    key = (region_id, day)
    if key not in _pending:
        return False, _failed.get(key), None
    now = time.monotonic()
    # Сначала досчитываются дни, поставленные раньше, — их остаток тоже ждать
    ahead = sum(_left(other, now) for other in _pending if other != key and _queued[other] < _queued[key])
    return True, _failed.get(key), max(0, round(ahead + _left(key, now)))


def _learn(key: Key, elapsed: float) -> None:
    """Подстроить оценку под то, сколько расчёт шёл на деле."""
    _, fresh = _estimate.get(key, (0.0, 0))
    if fresh > 0:
        per_point = (elapsed - _rate["base"]) / fresh
        _rate["point"] = (1 - _LEARN) * _rate["point"] + _LEARN * min(max(per_point, 0.2), 10.0)
    else:
        _rate["base"] = (1 - _LEARN) * _rate["base"] + _LEARN * min(max(elapsed, 2.0), 120.0)


_rebuild_seconds: float | None = None
"""Сколько шёл последний пересчёт по «Обновить план» — для индикатора в шапке."""


def rebuild_estimate() -> int:
    """Примерно секунд на «Обновить план»: адреса дня уже в кэше, поэтому без новых точек."""
    return round(_rebuild_seconds if _rebuild_seconds is not None else _rate["base"])


def learn_rebuild(elapsed: float) -> None:
    global _rebuild_seconds
    last = _rebuild_seconds if _rebuild_seconds is not None else _rate["base"]
    _rebuild_seconds = (1 - _LEARN) * last + _LEARN * min(max(elapsed, 1.0), 120.0)


async def _run(key: Key, remake_level: RemakeLevel, fresh: frozenset[int]) -> None:
    from modules.planning.service import PlanningService

    try:
        async with _lock:
            _started[key] = time.monotonic()
            try:
                async with async_session_factory() as session:
                    planned = await PlanningService(session).recalculate(
                        *key, remake_level=remake_level, fresh=fresh
                    )
                _failed.pop(key, None)
                elapsed = time.monotonic() - _started[key]
                _learn(key, elapsed)
                logger.info(
                    "План на %s, регион %d: версия %d за %.0f с (ждали %.0f с, новых адресов %d)",
                    key[1], key[0], planned.version, elapsed, *_estimate.get(key, (0.0, 0)),
                )
            except AppError as exc:
                _failed[key] = exc.message
            except Exception:  # noqa: BLE001
                logger.exception("Фоновый расчёт плана на %s, регион %d", key[1], key[0])
                _failed[key] = "Не удалось рассчитать план — попробуйте пересчитать"
            finally:
                _started.pop(key, None)
    finally:
        left = _pending.get(key, 1) - 1
        if left > 0:
            _pending[key] = left
        else:
            _pending.pop(key, None)
            _queued.pop(key, None)
            _estimate.pop(key, None)

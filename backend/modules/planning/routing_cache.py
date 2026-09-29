"""Кэш маршрутов (матрицы ORS, RAPTOR на 10:00, линии по улицам) — один на процесс.

Файл кэша — JSON на 15 МБ. На стенде его разбор стоит 0,7–1,9 с, запись — ещё полсекунды,
и всё это время поток держит GIL, то есть стоят и остальные запросы. Раньше файл читали
заново каждый расчёт и каждый сохранённый ход на Ганте (с базовым планом — до пяти раз
за ход) и тут же писали обратно, а каждая открытая доска держала свою копию (~60 МБ).

Теперь файл читается один раз, пополняется в памяти, а на диск уходит в фоне: не чаще
раза в `SAVE_DELAY` секунд и при остановке сервиса. Uvicorn запущен одним процессом,
поэтому писатель у файла один. Файл, поменянный снаружи (прогрев `tools/ors_prefetch.py`
в контейнере), видно по времени изменения: чистый кэш перечитывается, а несохранённое
перед записью доливается к прочитанному.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from modules.planning import scenario_builder as _builder  # noqa: F401 - sys.path к planner

from core.config import get_settings
from planner.ors import DEFAULT_CACHE_PATH, RoutingCache  # noqa: E402

logger = logging.getLogger(__name__)

SAVE_DELAY = 20.0
"""Через сколько секунд после пополнения кэш уходит на диск. Все пополнения за это
время — одной записью: ходы на Ганте идут сериями."""

lock = threading.RLock()
"""Загрузка, запись и долив в общий кэш. Чтение и пополнение участков идут без него:
операции со словарями кэша атомарны под GIL."""

_cache: RoutingCache | None = None
_stamp: tuple[int, int] | None = None
"""(mtime_ns, размер) файла, с которым совпадает кэш в памяти."""
_timer: threading.Timer | None = None


def path() -> Path:
    return Path(get_settings().routing_cache_path or DEFAULT_CACHE_PATH)


def _stamp_of(file: Path) -> tuple[int, int] | None:
    try:
        stat = file.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def shared() -> RoutingCache:
    """Общий кэш процесса; при первом обращении — с диска."""
    global _cache, _stamp
    with lock:
        file = path()
        stamp = _stamp_of(file)
        if _cache is None or _cache.path != file or (stamp != _stamp and not _cache.dirty):
            _cache = RoutingCache(file)
            _stamp = stamp
        return _cache


def merge(fresh: RoutingCache) -> int:
    """Долить посчитанное отдельно (RAPTOR новых адресов) в общий кэш. Возвращает число новых пар."""
    with lock:
        added = shared().merge(fresh)
    if added:
        changed()
    return added


def changed() -> None:
    """Кэш пополнился: запись на диск через `SAVE_DELAY` секунд, одна на все пополнения."""
    global _timer
    with lock:
        if _timer is not None:
            return
        _timer = threading.Timer(SAVE_DELAY, flush)
        _timer.daemon = True
        _timer.start()


def flush() -> None:
    """Несохранённое — на диск. Если файл за это время поменяли снаружи — сначала долить его."""
    global _stamp, _timer
    with lock:
        _timer = None
        cache = _cache
        if cache is None or not cache.dirty:
            return
        file = path()
        try:
            stamp = _stamp_of(file)
            if stamp is not None and stamp != _stamp:
                cache.merge(RoutingCache(file))
            cache.save(file)
        except OSError:
            logger.warning("Кэш маршрутов не сохранён в %s", file, exc_info=True)
            return
        _stamp = _stamp_of(file)


def close() -> None:
    """Остановка сервиса: отложенная запись — сейчас."""
    with lock:
        if _timer is not None:
            _timer.cancel()
    flush()

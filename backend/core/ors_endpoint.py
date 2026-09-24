"""Какой ORS спрашивать: основной (отдельная машина) или запасной (на самом стенде).

Основной — `ORS_URL`: все профили, включая общественный транспорт. Запасной —
`ORS_FALLBACK_URL`: экономный ORS стенда, только авто, пешком и велосипед. Если
основной не отвечает, матрицы новых адресов считаются по запасному, а не по
координатам. Проверка — `/v2/health` с коротким таймаутом, её ответ запоминается на
HEALTH_TTL, чтобы не тратить секунды на каждый расчёт.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.request

from core.config import Settings

logger = logging.getLogger(__name__)

HEALTH_TIMEOUT = 3.0
HEALTH_TTL = 30.0

_health: dict[str, tuple[float, bool]] = {}
_lock = threading.Lock()


def is_healthy(url: str) -> bool:
    now = time.monotonic()
    with _lock:
        cached = _health.get(url)
        if cached is not None and now - cached[0] < HEALTH_TTL:
            return cached[1]
    try:
        # health у nginx на отдельной машине открыт без токена
        with urllib.request.urlopen(f"{url.rstrip('/')}/v2/health", timeout=HEALTH_TIMEOUT) as r:
            ok = b"ready" in r.read()
    except OSError:
        ok = False
    with _lock:
        _health[url] = (now, ok)
    return ok


def pick(settings: Settings) -> tuple[str | None, str | None]:
    """(адрес, токен) ORS для расчёта матриц; (None, None) — без сервиса, по кэшу."""
    primary = settings.ors_url or None
    fallback = settings.ors_fallback_url or None
    if primary is None:
        return None, None
    if fallback is None or fallback == primary or is_healthy(primary):
        return primary, settings.ors_api_key or None
    if is_healthy(fallback):
        logger.warning("ORS %s не отвечает — матрицы считаются по запасному %s", primary, fallback)
        return fallback, None
    return primary, settings.ors_api_key or None  # оба лежат — planner сам откатится

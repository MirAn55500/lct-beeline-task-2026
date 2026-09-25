"""Загрузить заранее посчитанные профили rRAPTOR в Postgres (при старте контейнера).

Файл `solution/data/transit_profiles.bin` считается `solution/tools/raptor_prefetch.py`
и едет в образе. Грузится один раз на содержимое файла: если в базе уже лежит этот же
файл (тот же хэш), скрипт ничего не делает. Иначе — новый фид, пересчитанный файл того
же фида или прерванная прошлая загрузка — таблица перезаливается целиком в одной
транзакции.

    python -m core.load_transit_profiles /solution/data/transit_profiles.bin
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
import time
from pathlib import Path

_SOLUTION = Path(__file__).resolve().parents[2] / "solution"
for candidate in (_SOLUTION, Path("/solution")):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from planner import transit_profiles  # noqa: E402
from sqlalchemy import text  # noqa: E402

from core.database import engine  # noqa: E402

logger = logging.getLogger("load_transit_profiles")


async def load(path: Path) -> int:
    """Возвращает число загруженных строк (0 — уже были или загружать нечего)."""
    if not path.exists():
        logger.warning("Профилей %s нет — общественный транспорт по расписанию на 10:00", path)
        return 0
    started = time.perf_counter()
    source = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    async with engine.begin() as conn:
        loaded = await conn.scalar(text("SELECT source FROM transit_feed LIMIT 1"))
        if loaded == source:
            return 0
        profiles = transit_profiles.read_file(path)
        # Всё сразу и в одной транзакции: частичной загрузки не остаётся ни при каком сбое
        await conn.execute(text("DELETE FROM transit_profile"))
        await conn.execute(text("DELETE FROM transit_feed"))
        rows = [(profiles.feed, weekday, a, b, blob) for weekday, a, b, blob in profiles.rows()]
        raw = await conn.get_raw_connection()
        await raw.driver_connection.copy_records_to_table(
            "transit_profile",
            records=rows,
            columns=["feed_version", "weekday", "origin", "dest", "data"],
        )
        await conn.execute(
            text(
                "INSERT INTO transit_feed (feed_version, first_second, last_second, pairs, source) "
                "VALUES (:f, :first, :last, :n, :source)"
            ),
            {
                "f": profiles.feed, "first": profiles.first, "last": profiles.last,
                "n": len(rows), "source": source,
            },
        )
    logger.info(
        "Профили rRAPTOR: %d строк (фид %s) загружены за %.1f с",
        len(rows), profiles.feed, time.perf_counter() - started,
    )
    return len(rows)


async def _main(path: Path) -> None:
    try:
        await load(path)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
    asyncio.run(_main(Path(sys.argv[1])))

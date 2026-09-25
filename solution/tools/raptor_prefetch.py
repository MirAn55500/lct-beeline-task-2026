"""Посчитать профили rRAPTOR для всех известных пар точек на каждый день недели.

Известные пары — все, что есть в кэше маршрутов (`data/routing_cache.json`): это точки
всех загруженных сценариев. Результат — `data/transit_profiles.bin`, который backend
при старте загружает в Postgres (`backend/core/load_transit_profiles.py`), а planner
может читать напрямую (`planner.transit_profiles.read_file`).

Дни недели с одинаковым набором действующих сервисов фида считаются один раз: в
московском фиде понедельник — четверг совпадают, так что вместо семи прогонов — четыре.

Один поиск — ~15 с на точку в чистом Python, поэтому точки раскладываются по
процессам; каждый процесс держит своё расписание дня (~350 МБ).

Запуск:
    python tools/raptor_prefetch.py                     # все ядра, неделя с 17.08.2026
    python tools/raptor_prefetch.py --workers 8 --origins 5   # проба
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner import raptor, transit_profiles  # noqa: E402
from planner.models import GeoPoint  # noqa: E402

FIRST = 7 * 3600
LAST = 22 * 3600
"""Окно выезда. Смены инженеров на стенде — 09:00–22:00, профиль берётся с запасом."""

_router: raptor.TransitRouter | None = None


def _point(key: str) -> GeoPoint:
    lat, lon = key.split(",")
    return GeoPoint(float(lat), float(lon))


def _init(gtfs: str, day: date) -> None:
    global _router
    horizon = (LAST - FIRST) / 60 + 60 + raptor.HORIZON_MINUTES
    _router = raptor.TransitRouter(
        raptor.load_timetable(gtfs, day, FIRST, horizon_minutes=horizon)
    )


def _one(job: tuple[str, list[str], list[float | None]]) -> tuple[str, dict[str, bytes], float]:
    origin, targets, walks = job
    started = time.perf_counter()
    profiles = _router.profiles(_point(origin), [_point(b) for b in targets], FIRST, LAST, walks)
    blobs = {
        b: transit_profiles.encode(p) for b, p in zip(targets, profiles) if p is not None
    }
    return origin, blobs, time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gtfs", default=ROOT / "deploy/ors/files/gtfs.zip", type=Path)
    parser.add_argument("--cache", default=ROOT / "data/routing_cache.json", type=Path)
    parser.add_argument("--out", default=ROOT / "data/transit_profiles.bin", type=Path)
    parser.add_argument("--week", default="2026-08-17", help="понедельник недели, по которой берутся дни")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--origins", type=int, default=0, help="только N точек (проба)")
    args = parser.parse_args()

    cache = json.loads(args.cache.read_text(encoding="utf-8"))
    foot = cache["legs"].get("foot-walking", {})
    targets: dict[str, set[str]] = defaultdict(set)
    for section, legs in cache["legs"].items():
        # Все пары сценариев: и те, что ORS связал по расписанию, и те, где отказал
        if section.startswith("public-transport@") or section == "foot-walking":
            for key in legs:
                a, b = key.split(">")
                targets[a].add(b)
    origins = sorted(targets)
    if args.origins:
        origins = origins[:: max(1, len(origins) // args.origins)][: args.origins]  # вразброс
    jobs = [
        (a, sorted(targets[a]), [foot.get(f"{a}>{b}", [None, None])[1] for b in sorted(targets[a])])
        for a in origins
    ]
    print(f"{len(origins)} точек, {sum(len(j[1]) for j in jobs)} пар; процессов {args.workers}")

    monday = date.fromisoformat(args.week)
    groups: dict[str, list[int]] = defaultdict(list)
    sample: dict[str, date] = {}
    for weekday in range(7):
        day = monday + timedelta(days=weekday)
        signature = transit_profiles.service_signature(args.gtfs, day)
        groups[signature].append(weekday)
        sample.setdefault(signature, day)
    print("группы дней:", [[("пн", "вт", "ср", "чт", "пт", "сб", "вс")[d] for d in g] for g in groups.values()])

    weekdays: dict[int, int] = {}
    pairs: dict[int, dict[tuple[str, str], bytes]] = {}
    started = time.perf_counter()
    for g, (signature, days) in enumerate(groups.items()):
        for weekday in days:
            weekdays[weekday] = g
        day = sample[signature]
        t0 = time.perf_counter()
        found: dict[tuple[str, str], bytes] = {}
        with mp.Pool(args.workers, initializer=_init, initargs=(str(args.gtfs), day)) as pool:
            for n, (origin, blobs, _) in enumerate(pool.imap_unordered(_one, jobs), start=1):
                for b, blob in blobs.items():
                    found[(origin, b)] = blob
                print(f"\r  {day}: {n}/{len(jobs)} точек", end="", flush=True)
        pairs[g] = found
        print(f"\r  {day} ({len(days)} дн.): {len(found)} пар за {time.perf_counter() - t0:.0f} с")

    profiles = transit_profiles.ProfileSet(
        feed=transit_profiles.feed_version(args.gtfs),
        first=FIRST, last=LAST, weekdays=weekdays, pairs=pairs,
    )
    size = transit_profiles.write_file(args.out, profiles)
    print(
        f"{args.out}: {size / 2**20:.1f} МБ, версия фида {profiles.feed}, "
        f"всего {time.perf_counter() - started:.0f} с"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

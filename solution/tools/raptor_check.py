"""Сверка RAPTOR (`planner/raptor.py`) с временами ORS из кэша маршрутов.

В `data/routing_cache.json` лежат тысячи пар, посчитанных ORS по расписанию на
10:00 каждого дня недели (разделы `public-transport@<дата>T07:00:00`, время в UTC).
Скрипт считает те же пары своим поиском и печатает, насколько они расходятся.

Запуск:
    python tools/raptor_check.py                       # 17.08, параметры по умолчанию
    python tools/raptor_check.py --date 2026-08-22     # суббота
    python tools/raptor_check.py --detour 1.35 --transfer-km 0.3 --worst 20
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import tracemalloc
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner import raptor  # noqa: E402
from planner.models import GeoPoint  # noqa: E402
from planner.travel import haversine_km  # noqa: E402

MSK = timezone(timedelta(hours=3))


def _point(key: str) -> GeoPoint:
    lat, lon = key.split(",")
    return GeoPoint(float(lat), float(lon))


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gtfs", default=ROOT / "deploy/ors/files/gtfs.zip", type=Path)
    parser.add_argument("--cache", default=ROOT / "data/routing_cache.json", type=Path)
    parser.add_argument("--date", default="2026-08-17")
    parser.add_argument("--detour", type=float, default=raptor.WALK_DETOUR)
    parser.add_argument("--transfer-km", type=float, default=raptor.TRANSFER_KM)
    parser.add_argument("--transfer-penalty", type=int, default=raptor.TRANSFER_PENALTY)
    parser.add_argument("--access-minutes", type=float, default=raptor.ACCESS_MINUTES)
    parser.add_argument("--rounds", type=int, default=raptor.MAX_ROUNDS)
    parser.add_argument("--origins", type=int, default=0, help="взять только N точек отправления")
    parser.add_argument(
        "--straight-walk", dest="street_walk", action="store_false",
        help="пешком целиком — по прямой, а не по матрице foot-walking из кэша",
    )
    parser.add_argument("--worst", type=int, default=10)
    parser.add_argument("--json", type=Path, help="сохранить попарное сравнение")
    parser.add_argument("--memory", action="store_true", help="замерить память (загрузка в разы дольше)")
    args = parser.parse_args()

    cache = json.loads(args.cache.read_text(encoding="utf-8"))
    section = f"public-transport@{args.date}T07:00:00"
    legs = cache["legs"].get(section)
    if not legs:
        print(f"в кэше нет раздела {section}", file=sys.stderr)
        return 1
    moment = datetime.fromisoformat(f"{args.date}T07:00:00+00:00").astimezone(MSK)
    start = moment.hour * 3600 + moment.minute * 60
    foot = cache["legs"].get("foot-walking", {})

    by_origin: dict[str, list[str]] = defaultdict(list)
    for key in legs:
        a, b = key.split(">")
        by_origin[a].append(b)
    origins = sorted(by_origin)
    if args.origins:
        origins = random.Random(1).sample(origins, min(args.origins, len(origins)))

    if args.memory:
        tracemalloc.start()
    t0 = time.perf_counter()
    tt = raptor.load_timetable(
        args.gtfs, date.fromisoformat(args.date), start,
        transfer_km=args.transfer_km, transfer_penalty=args.transfer_penalty, detour=args.detour,
    )
    load_s = time.perf_counter() - t0
    memory_mb = tracemalloc.get_traced_memory()[0] / 2**20 if args.memory else float("nan")
    tracemalloc.stop()
    print(
        f"{args.date} с {moment:%H:%M} МСК: {tt.trips} рейсов, {len(tt.routes)} маршрутов, "
        f"{sum(map(len, tt.transfers))} пересадок; загрузка {load_s:.1f} с, память ~{memory_mb:.0f} МБ"
    )

    router = raptor.TransitRouter(
        tt, access_minutes=args.access_minutes, detour=args.detour, rounds=args.rounds
    )
    rows = []
    timings = []
    outside = 0
    for a in origins:
        targets = by_origin[a]
        t1 = time.perf_counter()
        walks = [foot.get(f"{a}>{b}", [None, None])[1] for b in targets] if args.street_walk else None
        ours = router.travel_minutes(_point(a), [_point(b) for b in targets], walks)
        timings.append(time.perf_counter() - t1)
        for b, mine in zip(targets, ours):
            km, ors_min = legs[f"{a}>{b}"]
            if mine is None:
                outside += 1
                continue
            walk = foot.get(f"{a}>{b}", [None, None])[1]
            rows.append({
                "pair": f"{a}>{b}", "ors": ors_min, "raptor": round(mine, 2),
                "straight_km": round(haversine_km(_point(a), _point(b)), 2),
                "ors_walk": walk,
            })

    diffs = [r["raptor"] - r["ors"] for r in rows]
    absd = [abs(d) for d in diffs]
    rel = [abs(r["raptor"] - r["ors"]) / r["ors"] for r in rows if r["ors"] > 0]
    print(
        f"пар: {len(rows)} (ещё {outside} — у RAPTOR вне фида); поиск из точки: "
        f"медиана {statistics.median(timings):.2f} с, максимум {max(timings):.2f} с, "
        f"всего {sum(timings):.0f} с на {len(origins)} точек"
    )
    print(
        f"RAPTOR − ORS, мин: среднее {statistics.mean(diffs):+.1f}, медиана "
        f"{statistics.median(diffs):+.1f}; |Δ| медиана {statistics.median(absd):.1f}, "
        f"p90 {_quantile(absd, 0.9):.1f}, p99 {_quantile(absd, 0.99):.1f}"
    )
    print(
        f"|Δ| ≤ 5 мин: {sum(d <= 5 for d in absd) / len(absd):.0%}; ≤ 10 мин: "
        f"{sum(d <= 10 for d in absd) / len(absd):.0%}; относительная |Δ| медиана "
        f"{statistics.median(rel):.0%}, p90 {_quantile(rel, 0.9):.0%}"
    )
    for lo, hi in ((0, 30), (30, 60), (60, 1000)):
        part = [r["raptor"] - r["ors"] for r in rows if lo <= r["ors"] < hi]
        if part:
            print(
                f"  ORS {lo}-{hi} мин: {len(part)} пар, среднее {statistics.mean(part):+.1f}, "
                f"|Δ| медиана {statistics.median(map(abs, part)):.1f}"
            )
    if args.worst:
        print("худшие пары:")
        for r in sorted(rows, key=lambda r: -abs(r["raptor"] - r["ors"]))[: args.worst]:
            print(
                f"  {r['pair']}  ORS {r['ors']:.1f}  RAPTOR {r['raptor']:.1f}  "
                f"прямая {r['straight_km']} км  ORS пешком {r['ors_walk']}"
            )
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

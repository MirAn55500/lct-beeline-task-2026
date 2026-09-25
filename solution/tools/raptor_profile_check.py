"""Время выезда в течение дня: часовые слоты RAPTOR против rRAPTOR, и оба — против ORS.

Отвечает на четыре вопроса:

1. Сколько стоит каждый способ: время на точку отправления, память на расписание дня.
2. Верен ли rRAPTOR: его профиль на любой момент обязан совпасть с обычным поиском
   на этот же момент (секунда в секунду).
3. Сколько теряется, если вместо точного момента выезда взять слот — начало часа,
   ближайший час, или одно значение на весь день (10:00, как сейчас в кэше ORS).
4. Насколько RAPTOR расходится с ORS в разные часы (нужен поднятый локальный ORS).

Запуск:
    python tools/raptor_profile_check.py                         # 30 точек, 17.08
    python tools/raptor_profile_check.py --origins 60 --ors 150  # + сверка со 150 парами ORS
    python tools/raptor_profile_check.py --json results.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner import raptor  # noqa: E402
from planner.models import GeoPoint  # noqa: E402

MSK = timezone(timedelta(hours=3))


def _point(key: str) -> GeoPoint:
    lat, lon = key.split(",")
    return GeoPoint(float(lat), float(lon))


def _hhmm(value: str) -> int:
    h, m = value.split(":")
    return int(h) * 3600 + int(m) * 60


def _q(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else float("nan")


def _stats(values: list[float]) -> dict:
    if not values:
        return {}
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "p90": round(_q(values, 0.9), 2),
        "p99": round(_q(values, 0.99), 2),
        "max": round(max(values), 2),
    }


def _rss_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process(os.getpid()).memory_info().rss / 2**20


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gtfs", default=ROOT / "deploy/ors/files/gtfs.zip", type=Path)
    parser.add_argument("--cache", default=ROOT / "data/routing_cache.json", type=Path)
    parser.add_argument("--date", default="2026-08-17")
    parser.add_argument("--first", default="08:00", help="самый ранний выезд")
    parser.add_argument("--last", default="20:00", help="самый поздний выезд")
    parser.add_argument("--origins", type=int, default=30)
    parser.add_argument("--samples", type=int, default=20, help="случайных моментов на точку")
    parser.add_argument("--ors", type=int, default=0, help="сверить N пар с ORS")
    parser.add_argument("--ors-url", default="http://127.0.0.1:8080/ors")
    parser.add_argument("--ors-hours", default="8,11,14,17,20")
    parser.add_argument("--ors-workers", type=int, default=4)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    rng = random.Random(7)
    day = date.fromisoformat(args.date)
    first, last = _hhmm(args.first), _hhmm(args.last)
    report: dict = {"date": args.date, "window": [args.first, args.last]}

    cache = json.loads(args.cache.read_text(encoding="utf-8"))
    legs = cache["legs"][f"public-transport@{args.date}T07:00:00"]
    foot = cache["legs"].get("foot-walking", {})
    by_origin: dict[str, list[str]] = defaultdict(list)
    for key in legs:
        a, b = key.split(">")
        by_origin[a].append(b)
    origins = rng.sample(sorted(by_origin), min(args.origins, len(by_origin)))

    # --- 1. расписание на весь рабочий день
    rss0 = _rss_mb()
    t0 = time.perf_counter()
    horizon = (last - first) / 60 + 60 + raptor.HORIZON_MINUTES
    tt = raptor.load_timetable(args.gtfs, day, first, horizon_minutes=horizon)
    load_s = time.perf_counter() - t0
    rss1 = _rss_mb()
    report["timetable"] = {
        "trips": tt.trips, "routes": len(tt.routes), "load_s": round(load_s, 1),
        "rss_mb": round(rss1 - rss0, 0) if rss0 is not None else None,
    }
    print(
        f"{args.date}, выезд {args.first}–{args.last}: {tt.trips} рейсов, {len(tt.routes)} маршрутов; "
        f"загрузка {load_s:.1f} с, память +{report['timetable']['rss_mb']} МБ"
    )
    router = raptor.TransitRouter(tt)
    hours = list(range(first, last + 1, 3600))

    cost = defaultdict(list)
    exact_vs_plain: list[float] = []
    grid_vs_plain: list[float] = []
    err = defaultdict(list)  # способ → |Δ| мин против точного
    rel = defaultdict(list)
    by_hour = defaultdict(list)  # час → |Δ| против 10:00, %
    entries: list[int] = []
    profiles_of: dict[str, list] = {}

    for n, a in enumerate(origins, start=1):
        targets = by_origin[a]
        pts = [_point(b) for b in targets]
        walks = [foot.get(f"{a}>{b}", [None, None])[1] for b in targets]
        origin = _point(a)

        t1 = time.perf_counter()
        exact = router.profiles(origin, pts, first, last, walks)
        cost["rraptor_exact"].append(time.perf_counter() - t1)
        t1 = time.perf_counter()
        grid = router.profiles(origin, pts, first, last, walks, step=300)
        cost["rraptor_grid5"].append(time.perf_counter() - t1)
        t1 = time.perf_counter()
        slots = {h: router.travel_minutes(origin, pts, walks, depart=h) for h in hours}
        cost["hourly_slots"].append(time.perf_counter() - t1)
        t1 = time.perf_counter()
        router.travel_minutes(origin, pts, walks, depart=first)
        cost["single_search"].append(time.perf_counter() - t1)
        profiles_of[a] = list(zip(targets, exact))
        entries.extend(len(p.deps) for p in exact if p is not None)

        # --- 2. точность rRAPTOR: сверка с обычным поиском на тот же момент
        for _ in range(3):
            t = rng.randrange(first, last)
            plain = router.travel_minutes(origin, pts, walks, depart=t)
            for p, g, v in zip(exact, grid, plain):
                if p is None or v is None:
                    continue
                exact_vs_plain.append(abs(p.minutes_at(t) - v))
                grid_vs_plain.append(g.minutes_at(t) - v)

        # --- 3. потери слотов против точного момента
        for _ in range(args.samples):
            t = rng.randrange(first, last)
            floor_h = first + (t - first) // 3600 * 3600
            near_h = min(hours, key=lambda h: abs(h - t))
            for i, p in enumerate(exact):
                if p is None or slots[floor_h][i] is None:
                    continue
                truth = p.minutes_at(t)
                if truth <= 0:
                    continue
                for name, value in (
                    ("slot_hour_floor", slots[floor_h][i]),
                    ("slot_hour_nearest", slots[near_h][i]),
                    ("fixed_10", slots[36000][i] if 36000 in slots else None),
                    ("grid5", grid[i].minutes_at(t)),
                ):
                    if value is None:
                        continue
                    err[name].append(abs(value - truth))
                    rel[name].append(abs(value - truth) / truth)
        if 36000 in slots:
            for h in hours:
                for v10, v in zip(slots[36000], slots[h]):
                    if v10 and v is not None:
                        by_hour[h].append(abs(v - v10) / v10 * 100)
        print(f"\r  точек {n}/{len(origins)}", end="", flush=True)
    print()

    report["cost_per_origin_s"] = {k: _stats(v) for k, v in cost.items()}
    report["targets_per_origin"] = round(statistics.mean(len(by_origin[a]) for a in origins), 1)
    report["profile_entries_per_pair"] = _stats([float(e) for e in entries])
    report["rraptor_exact_vs_plain_min"] = _stats(exact_vs_plain)
    report["rraptor_grid5_minus_plain_min"] = _stats(grid_vs_plain)
    report["error_vs_exact_min"] = {k: _stats(v) for k, v in err.items()}
    report["error_vs_exact_rel"] = {k: _stats(v) for k, v in rel.items()}
    report["share_within"] = {
        k: {f"<={m}": round(sum(x <= m for x in v) / len(v), 3) for m in (2, 5, 10)}
        for k, v in err.items()
    }
    report["change_vs_10_by_hour_pct"] = {
        f"{h // 3600:02d}:00": _stats(v) for h, v in sorted(by_hour.items())
    }

    c = report["cost_per_origin_s"]
    print(
        f"на точку ({report['targets_per_origin']} целей): один поиск {c['single_search']['median']} с; "
        f"{len(hours)} часовых слотов {c['hourly_slots']['median']} с; rRAPTOR точный "
        f"{c['rraptor_exact']['median']} с (макс {c['rraptor_exact']['max']}); сетка 5 мин "
        f"{c['rraptor_grid5']['median']} с"
    )
    print(
        f"rRAPTOR против обычного поиска на тот же момент: max |Δ| "
        f"{report['rraptor_exact_vs_plain_min'].get('max')} мин на {len(exact_vs_plain)} сравнениях; "
        f"сетка 5 мин − точный: среднее {report['rraptor_grid5_minus_plain_min'].get('mean')}, "
        f"мин {min(grid_vs_plain):.2f}, макс {max(grid_vs_plain):.2f}"
    )
    print(f"записей в профиле пары: медиана {report['profile_entries_per_pair']['median']}")
    print("ошибка против точного момента выезда, мин (|Δ| медиана / p90 / доля ≤5 мин):")
    for name, title in (
        ("fixed_10", "одно значение на 10:00 (как сейчас)"),
        ("slot_hour_floor", "слот: начало часа"),
        ("slot_hour_nearest", "слот: ближайший час"),
        ("grid5", "rRAPTOR сетка 5 мин"),
    ):
        s, share = report["error_vs_exact_min"].get(name), report["share_within"].get(name)
        if s:
            print(f"  {title:<38} {s['median']:>5} / {s['p90']:>5}   {share['<=5']:.0%}")
    print("насколько время в пути отличается от 10:00, % (медиана / p90):")
    for h, s in report["change_vs_10_by_hour_pct"].items():
        print(f"  {h}  {s['median']:>5} / {s['p90']:>5}")

    # --- 4. сверка с ORS в разные часы
    if args.ors:
        from planner import ors

        client = ors.OrsClient(args.ors_url, timeout=600)
        pairs = [(a, b, p) for a, lst in profiles_of.items() for b, p in lst if p is not None]
        pairs = rng.sample(pairs, min(args.ors, len(pairs)))
        ors_hours = [int(h) * 3600 for h in args.ors_hours.split(",")]
        jobs = [(a, b, p, h) for a, b, p in pairs for h in ors_hours]

        def one(job):
            a, b, p, h = job
            when = (datetime.combine(day, datetime.min.time(), MSK) + timedelta(seconds=h))
            when = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            try:
                _, minutes, _, _ = ors._fetch_leg(client, "public-transport", _point(a), _point(b), when=when)
            except Exception:  # noqa: BLE001 — вне фида / не построилось: пару пропускаем
                return None
            return h, minutes, p.minutes_at(h)

        t1 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(args.ors_workers) as pool:
            answers = [x for x in pool.map(one, jobs) if x and x[1] is not None]
        ors_s = time.perf_counter() - t1
        per_hour = defaultdict(list)
        for h, o, r in answers:
            per_hour[h].append(r - o)
        allv = [r - o for _, o, r in answers]
        report["vs_ors"] = {
            "pairs": len(pairs), "answers": len(answers), "ors_seconds": round(ors_s),
            "all": _stats(allv) | {
                "abs_median": round(statistics.median(map(abs, allv)), 2),
                "within5": round(sum(abs(x) <= 5 for x in allv) / len(allv), 3),
                "within10": round(sum(abs(x) <= 10 for x in allv) / len(allv), 3),
                "raptor_slower_gt10": round(sum(x > 10 for x in allv) / len(allv), 3),
                "raptor_faster_gt10": round(sum(x < -10 for x in allv) / len(allv), 3),
            },
            "by_hour": {
                f"{h // 3600:02d}:00": {
                    "n": len(v), "mean": round(statistics.mean(v), 2),
                    "abs_median": round(statistics.median(map(abs, v)), 2),
                    "within5": round(sum(abs(x) <= 5 for x in v) / len(v), 3),
                }
                for h, v in sorted(per_hour.items())
            },
        }
        s = report["vs_ors"]["all"]
        print(
            f"против ORS: {len(answers)} ответов ({len(pairs)} пар × {len(ors_hours)} часов, "
            f"ORS считал {ors_s:.0f} с); RAPTOR − ORS среднее {s['mean']:+}, |Δ| медиана "
            f"{s['abs_median']}, ≤5 мин {s['within5']:.0%}, ≤10 мин {s['within10']:.0%}"
        )
        for h, v in report["vs_ors"]["by_hour"].items():
            print(f"  {h}: {v['n']} пар, среднее {v['mean']:+}, |Δ| медиана {v['abs_median']}, ≤5 мин {v['within5']:.0%}")

    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

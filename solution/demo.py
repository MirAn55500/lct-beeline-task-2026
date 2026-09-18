"""Демонстрационный сценарий: расчёт дня, сравнение с базовым планом, перепланирование.

Запуск:
    python demo.py                      # встроенный набор (Восток)
    python demo.py --region southeast   # другой регион
    python demo.py --json plan.json     # выгрузить план целиком в JSON

Скрипт ничего не рисует: он показывает ровно то, что отдаёт алгоритм, — чтобы было видно,
что интерфейсу остаётся только отобразить готовые поля.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from planner import Algorithm, EventType, Priority, ReplanEvent, compare, plan, replan, validate_plan
from planner.io_csv import build_scenario

SOURCES = {
    "east": ("Восток", "Восток Синтетические данные.csv", "Восток Контрольное распределение..csv"),
    "southeast": (
        "Юго-восток",
        "Юго-восток Синтетические данные.csv",
        "Юго-восток Контрольное распределение.csv",
    ),
    "southcentral": (
        "Югоцентр",
        "Югоцентр Синтетические данные.csv",
        "Югоцентр Контрольное распределение..csv",
    ),
}

DATASET_DIR = ROOT.parent / "Обезличивание"
LINE = "─" * 92


def _head(text: str) -> None:
    print(f"\n{LINE}\n{text}\n{LINE}")


def _plan_summary(tag: str, result) -> None:
    m = result.metrics
    print(
        f"  {tag:<12} назначено {m.assigned_count:>3} | без исполнителя {m.unassigned_count:>3} "
        f"(срочных {m.urgent_unassigned_count}) | инженеров {m.used_engineer_count:>2} | "
        f"пробег {m.total_distance_km:>7.1f} км | в пути {m.total_travel_minutes:>6.0f} мин | "
        f"{m.computation_ms:>6.0f} мс"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=sorted(SOURCES), default="east")
    parser.add_argument("--shift", default="09:00-21:00", help="смена, формат ЧЧ:ММ-ЧЧ:ММ")
    parser.add_argument("--lunch", default="13:00-14:00", help="перерыв или 'нет'")
    parser.add_argument("--limit", type=float, default=5.0, help="лимит поиска, секунд")
    parser.add_argument("--json", type=Path, help="куда сохранить план целиком")
    args = parser.parse_args()

    title, synthetic, control = SOURCES[args.region]
    shift = tuple(args.shift.split("-"))
    lunch = None if args.lunch.lower() in {"нет", "no", "none"} else tuple(args.lunch.split("-"))

    _head(f"1. ИСХОДНЫЕ ДАННЫЕ — {title}")
    scenario, notes = build_scenario(
        DATASET_DIR / synthetic,
        control_csv=DATASET_DIR / control,
        region_key=args.region,
        shift=shift,
        lunch=lunch,
        name=title,
    )
    scenario.settings.time_limit_seconds = args.limit
    print(f"  Заявок: {len(scenario.requests)} | инженеров: {len(scenario.engineers)} | дата: {scenario.date}")
    for note in notes:
        print(f"  · {note}")

    _head("2. РАСЧЁТ И СРАВНЕНИЕ С БАЗОВЫМ ВАРИАНТОМ")
    baseline = plan(scenario, Algorithm.BASELINE)
    optimized = plan(scenario, Algorithm.OPTIMIZED)
    _plan_summary("базовый", baseline)
    _plan_summary("оптимизир.", optimized)
    print(f"\n  {compare(baseline, optimized)['summary']}")

    problems = validate_plan(optimized, scenario)
    print(f"  Независимая проверка плана: {'нарушений нет' if not problems else problems[:3]}")

    _head("3. МАРШРУТЫ")
    for route in optimized.routes[:4]:
        print(
            f"  {route.engineer_name:<24} {len(route.visits):>2} заявок | "
            f"{route.start_at:%H:%M}–{route.end_at:%H:%M} | {route.distance_km:>5.1f} км | "
            f"загрузка {route.utilization * 100:>3.0f}%"
        )
        for visit in route.visits[:3]:
            print(
                f"      {visit.position}. заявка {visit.request_id} — выезд {visit.departure_at:%H:%M}, "
                f"прибытие {visit.arrival_at:%H:%M}, работа {visit.service_start_at:%H:%M}–"
                f"{visit.service_end_at:%H:%M}"
            )
        if len(route.visits) > 3:
            print(f"      … ещё {len(route.visits) - 3}")
    if len(optimized.routes) > 4:
        print(f"  … ещё маршрутов: {len(optimized.routes) - 4}")

    _head("4. ОБЪЯСНЕНИЯ")
    assigned = optimized.assigned
    if assigned:
        print("  Почему назначено:")
        print(f"    {assigned[0].explanation}")
    if optimized.unassigned:
        print("\n  Почему не назначено:")
        for item in optimized.unassigned[:2]:
            print(f"    {item.explanation}")
    else:
        print("  Все заявки распределены.")

    _head("5. ПЕРЕПЛАНИРОВАНИЕ: СРОЧНАЯ ЗАЯВКА В СЕРЕДИНЕ ДНЯ")
    sample = optimized.routes[0].visits[-1]
    source = scenario.request_by_id[sample.request_id]
    from dataclasses import replace as _replace

    urgent = _replace(
        source,
        id="URGENT-1",
        priority=Priority.URGENT,
        window_start=source.window_start + timedelta(hours=1),
        window_end=source.window_end + timedelta(hours=1),
        input_order=10_000,
    )
    event = ReplanEvent(type=EventType.URGENT_REQUEST, at=sample.departure_at, request=urgent)
    updated = replan(optimized, scenario, event)

    _plan_summary("после", updated)
    print(f"\n  {updated.diff.summary}")
    print(
        f"  Затронуто маршрутов: {len(updated.diff.changed_route_engineer_ids)} | "
        f"без изменений: {len(updated.diff.unchanged_route_engineer_ids)}"
    )
    placed = updated.assignment_of("URGENT-1")
    if placed is not None:
        print(f"  {placed.explanation}")

    if args.json:
        args.json.write_text(
            json.dumps(optimized.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nПлан сохранён: {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

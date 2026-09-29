"""Базовый и оптимизированный план на трёх выгрузках — таблица «Результаты» из README.

Смена 09:00–22:00, обед 60 минут в окне 12:00–16:00 (время обеда выбирает планировщик),
лимит поиска 5 с, расстояния из кэша маршрутов data/routing_cache.json.

    python tools/bench_compare.py
"""

from __future__ import annotations

import dataclasses
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "viz"))

from export import SOURCES, _build_real_scenario  # noqa: E402
from planner import Algorithm, plan, validate_plan  # noqa: E402
from planner.models import Lunch  # noqa: E402
from planner.ors import setup_routing  # noqa: E402


def with_lunch(scenario):
    day = scenario.engineers[0].work_intervals[0].start
    lunch = Lunch(
        window_start=day.replace(hour=12, minute=0),
        window_end=day.replace(hour=16, minute=0),
        minutes=60,
    )
    engineers = tuple(dataclasses.replace(e, lunch=lunch) for e in scenario.engineers)
    return dataclasses.replace(scenario, engineers=engineers)


def main() -> None:
    print("| Набор | Заявок | Алгоритм | Назначено | Инженеров | Пробег, км | км на заявку | В пути, мин | Расчёт, с | Нарушений |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for region, (title, *_files) in SOURCES.items():
        built = _build_real_scenario(region, "09:00-22:00", "нет", 5.0)
        if built is None:
            print(f"{title}: выгрузка не найдена")
            continue
        scenario = with_lunch(built[0])
        routing = setup_routing(scenario, url=None)
        for algorithm in (Algorithm.BASELINE, Algorithm.OPTIMIZED):
            started = time.perf_counter()
            result = plan(scenario, algorithm, travel=routing.travel)
            seconds = time.perf_counter() - started
            m = result.metrics
            per_ticket = m.total_distance_km / max(1, m.assigned_count)
            problems = validate_plan(result, scenario, routing.travel)
            print(
                f"| {title} | {len(scenario.requests)} | {algorithm.name.lower()} | {m.assigned_count} "
                f"| {m.used_engineer_count} | {m.total_distance_km:.1f} | {per_ticket:.2f} "
                f"| {m.total_travel_minutes:.0f} | {seconds:.2f} | {len(problems)} |"
            )


if __name__ == "__main__":
    main()

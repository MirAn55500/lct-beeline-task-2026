"""Сравнение планов между собой.

ТЗ (п. 4.7, п. 8.1) прямо требует сравнения с базовым вариантом по двум обязательным
метрикам. Эта функция готовит данные ровно в том виде, в каком их показывают диспетчеру:
что было, что стало, на сколько и в какую сторону.
"""

from __future__ import annotations

from typing import Any

from .result import PlanResult

__all__ = ["compare"]


def _delta(better_when_lower: bool, base: float, other: float) -> dict[str, Any]:
    change = other - base
    if abs(change) < 1e-9:
        verdict = "без изменений"
    elif (change < 0) == better_when_lower:
        verdict = "лучше"
    else:
        verdict = "хуже"
    percent = (change / base * 100.0) if base else None
    return {
        "baseline": round(base, 3),
        "optimized": round(other, 3),
        "delta": round(change, 3),
        "delta_percent": round(percent, 1) if percent is not None else None,
        "verdict": verdict,
    }


def compare(baseline: PlanResult, optimized: PlanResult) -> dict[str, Any]:
    """Сравнивает базовый и оптимизированный планы на одних и тех же входных данных."""
    b, o = baseline.metrics, optimized.metrics

    comparison = {
        "assigned_count": _delta(False, b.assigned_count, o.assigned_count),
        "unassigned_count": _delta(True, b.unassigned_count, o.unassigned_count),
        "urgent_unassigned_count": _delta(True, b.urgent_unassigned_count, o.urgent_unassigned_count),
        "used_engineer_count": _delta(True, b.used_engineer_count, o.used_engineer_count),
        "total_distance_km": _delta(True, b.total_distance_km, o.total_distance_km),
        "total_travel_minutes": _delta(True, b.total_travel_minutes, o.total_travel_minutes),
        "total_waiting_minutes": _delta(True, b.total_waiting_minutes, o.total_waiting_minutes),
        "avg_utilization": _delta(False, b.avg_utilization, o.avg_utilization),
    }

    better = o.quality_key() < b.quality_key()
    same = o.quality_key() == b.quality_key()

    return {
        "baseline_plan_id": baseline.plan_id,
        "optimized_plan_id": optimized.plan_id,
        "metrics": comparison,
        "optimized_is_better": better,
        "optimized_is_equal": same,
        "summary": _summary(b, o, better, same),
        "per_engineer": {
            "baseline": [m.to_dict() for m in b.per_engineer],
            "optimized": [m.to_dict() for m in o.per_engineer],
        },
    }


def _summary(b, o, better: bool, same: bool) -> str:
    parts: list[str] = []
    if o.assigned_count != b.assigned_count:
        parts.append(
            f"назначено заявок {o.assigned_count} против {b.assigned_count} у базового варианта"
        )
    if o.used_engineer_count != b.used_engineer_count:
        parts.append(
            f"задействовано инженеров {o.used_engineer_count} вместо {b.used_engineer_count}"
        )
    if abs(o.total_distance_km - b.total_distance_km) > 0.05:
        saved = b.total_distance_km - o.total_distance_km
        word = "меньше" if saved > 0 else "больше"
        parts.append(f"пробег на {abs(saved):.1f} км {word} ({o.total_distance_km:.1f} км)")
    if abs(o.total_travel_minutes - b.total_travel_minutes) > 1.0:
        saved = b.total_travel_minutes - o.total_travel_minutes
        word = "меньше" if saved > 0 else "больше"
        parts.append(f"время в пути на {abs(saved):.0f} мин {word}")

    if not parts:
        return "Планы совпадают по обязательным метрикам."
    head = "Оптимизированный план лучше" if better else ("Планы равноценны" if same else "Базовый план не хуже")
    return f"{head}: " + ", ".join(parts) + "."

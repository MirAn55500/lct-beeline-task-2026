"""Минимизация числа задействованных исполнителей.

Первая обязательная метрика ТЗ (п. 2.3) — «выполнение всех заявок наименьшим количеством
персонала». Regret-вставка сама по себе её не обеспечивает: она оптимизирует стоимость
каждой отдельной вставки и легко «размазывает» день по всем инженерам.

Приём — **route elimination**, стандартный для задач минимизации парка: берём самый лёгкий
маршрут, распускаем его и пробуем разложить заявки по остальным, **не открывая никого
нового**. Получилось у всех — инженер свободен на весь день, повторяем. Не получилось —
откатываемся целиком, будто ничего не было.

Двa свойства, ради которых это сделано именно так:

* число назначенных заявок не имеет права уменьшиться — освободить человека ценой
  потерянной заявки запрещено, заявки в порядке критериев стоят выше людей;
* результат легко объяснить: «инженер N освобождён, его три заявки забрали M и K».
"""

from __future__ import annotations

import time as _time

from .construct import insert_regret
from .context import PlanContext
from .solution import Solution

__all__ = ["minimize_fleet", "EliminationLog"]


class EliminationLog(list):
    """Протокол освобождений: (инженер, чьи заявки разошлись, куда именно)."""


def minimize_fleet(
    ctx: PlanContext,
    solution: Solution,
    *,
    deadline: float | None = None,
) -> EliminationLog:
    """Пытается распустить маршруты по одному. Возвращает протокол освобождений."""
    log = EliminationLog()

    while True:
        if deadline is not None and _time.monotonic() > deadline:
            break

        candidates = [r for r in solution.used_routes() if r.locked_count == 0]
        # Сначала самые лёгкие: их проще разложить, и выигрыш достигается быстрее.
        candidates.sort(key=lambda r: (r.size, r.service_minutes, r.engineer.input_order, r.engineer.id))
        # Дальше работаем по идентификаторам: откат пересоздаёт объекты маршрутов,
        # и ссылки, взятые до отката, указывали бы в никуда.
        candidate_ids = [r.engineer.id for r in candidates]

        progressed = False
        for engineer_id in candidate_ids:
            if deadline is not None and _time.monotonic() > deadline:
                break
            target = solution.routes.get(engineer_id)
            if target is None or target.is_empty or target.locked_count:
                continue

            snapshot = solution.clone()
            assigned_before = solution.assigned_count()
            emergency_before = solution.emergency_start_minutes
            moved = list(target.stops)
            engineer_name = target.engineer.name

            if not target.try_sequence([]):
                continue

            rejected = insert_regret(
                ctx,
                solution,
                moved,
                allow_new_engineers=False,
                deadline=deadline,
                record_failures=False,
            )

            if (
                rejected
                or solution.assigned_count() != assigned_before
                # Освободить человека ценой более поздней аварии нельзя
                or solution.emergency_start_minutes > emergency_before + 0.5
            ):
                solution.restore_from(snapshot)
                continue

            destinations = sorted(
                {
                    solution.route_of(r.id).engineer.name
                    for r in moved
                    if solution.route_of(r.id) is not None
                }
            )
            log.append(
                {
                    "engineer_id": target.engineer.id,
                    "engineer_name": engineer_name,
                    "moved_request_ids": [r.id for r in moved],
                    "destinations": destinations,
                }
            )
            progressed = True
            break

        if not progressed:
            break

    return log

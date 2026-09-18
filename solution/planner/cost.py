"""Стоимость вставки и качество плана — строго лексикографически.

Почему не взвешенная сумма. Типовой приём («штраф за нового инженера = 100000»)
работает, но держится на подобранной константе: стоит пробегу вырасти на порядок,
и приоритеты молча меняются местами. Здесь порядок критериев выражен структурой
данных, а не величиной весов, поэтому его нельзя нарушить случайно и легко объяснить
диспетчеру: «сначала не открываем нового человека, потом экономим время, потом — километры».

Порядок соответствует базе знаний («Правила расчёта»): число исполнителей важнее,
время перемещения важнее пробега.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

__all__ = ["InsertionCost", "BEST_POSSIBLE", "WORST_POSSIBLE"]

_ROUND = 6
"""Округление перед сравнением: иначе шум float делает порядок недетерминированным."""


@dataclass(frozen=True, slots=True, order=False)
class InsertionCost:
    """Во сколько обходится размещение заявки в конкретное место конкретного маршрута."""

    opens_new_engineer: int = 0
    delta_travel_minutes: float = 0.0
    delta_distance_km: float = 0.0
    delta_waiting_minutes: float = 0.0

    @property
    def key(self) -> tuple[int, float, float, float]:
        return (
            self.opens_new_engineer,
            round(self.delta_travel_minutes, _ROUND),
            round(self.delta_distance_km, _ROUND),
            round(self.delta_waiting_minutes, _ROUND),
        )

    def __lt__(self, other: "InsertionCost") -> bool:
        return self.key < other.key

    def __le__(self, other: "InsertionCost") -> bool:
        return self.key <= other.key

    def __gt__(self, other: "InsertionCost") -> bool:
        return self.key > other.key

    def __ge__(self, other: "InsertionCost") -> bool:
        return self.key >= other.key

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, InsertionCost) and self.key == other.key

    def __hash__(self) -> int:
        return hash(self.key)

    def __sub__(self, other: "InsertionCost") -> "InsertionCost":
        """Покомпонентная разность. Используется как мера «сожаления» (regret)."""
        return InsertionCost(
            self.opens_new_engineer - other.opens_new_engineer,
            self.delta_travel_minutes - other.delta_travel_minutes,
            self.delta_distance_km - other.delta_distance_km,
            self.delta_waiting_minutes - other.delta_waiting_minutes,
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "opens_new_engineer": self.opens_new_engineer,
            "delta_travel_minutes": round(self.delta_travel_minutes, 3),
            "delta_distance_km": round(self.delta_distance_km, 3),
            "delta_waiting_minutes": round(self.delta_waiting_minutes, 3),
        }


BEST_POSSIBLE = InsertionCost(-1, -math.inf, -math.inf, -math.inf)
"""Нижняя граница: ничего не может быть дешевле."""

WORST_POSSIBLE = InsertionCost(1 << 30, math.inf, math.inf, math.inf)
"""Верхняя граница. Также играет роль «бесконечного сожаления»: если допустимая
позиция ровно одна, отложить заявку — значит с большой вероятностью потерять её."""

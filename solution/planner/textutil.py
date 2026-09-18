"""Мелкие помощники для текста объяснений.

Вынесены отдельно, потому что нужны и диагностике маршрута, и блоку объяснений, а
согласование по числу в русском тексте — ровно то место, где «и так сойдёт» бросается
в глаза диспетчеру на защите.
"""

from __future__ import annotations

from datetime import datetime

__all__ = ["plural", "hhmm"]


def plural(count: int, one: str, few: str, many: str) -> str:
    """Форма слова при числе: 1 заявка, 2 заявки, 5 заявок."""
    tail = count % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def hhmm(moment: datetime | None) -> str:
    return f"{moment:%H:%M}" if moment is not None else "—"

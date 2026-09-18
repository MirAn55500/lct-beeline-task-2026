"""Единая проверка жёстких ограничений.

Одна и та же функция используется в базовом алгоритме, в конструктивной фазе,
в локальном поиске и при перепланировании. Дублировать её нельзя: расхождение
проверок — самый дорогой класс ошибок в планировщике, потому что план внешне
выглядит корректным.

Функция возвращает не `bool`, а структуру с кодом и человекочитаемой причиной —
блок объяснений (`explain.py`) строится ровно из этих данных, а не сочиняется отдельно.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import SKILL_TITLES, TRANSPORT_TITLES, ReasonCode, Skill, TransportMode
from .models import Engineer, Request, Settings

__all__ = ["FeasibilityResult", "OK", "check_static", "ReasonAccumulator", "EQUIPMENT_TITLES"]

EQUIPMENT_TITLES: dict[str, str] = {
    "router": "роутер",
    "set_top_box": "ТВ-приставка",
}


@dataclass(frozen=True, slots=True)
class FeasibilityResult:
    """Результат проверки. `detail` уже пригоден для показа диспетчеру."""

    ok: bool
    reason: ReasonCode | None = None
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


OK = FeasibilityResult(ok=True)


def _equipment_names(codes: frozenset[str]) -> str:
    return ", ".join(EQUIPMENT_TITLES.get(c, c) for c in sorted(codes))


def check_static(engineer: Engineer, request: Request, settings: Settings) -> FeasibilityResult:
    """Проверки, не зависящие от текущего маршрута инженера.

    Порядок фиксирован и совпадает с порядком `ReasonCode.rank`: сначала территория,
    затем квалификация, затем ресурс, затем наличие рабочего времени вообще.
    """
    if not engineer.active:
        return FeasibilityResult(
            False,
            ReasonCode.NO_WORK_TIME,
            f"{engineer.name} не участвует в планировании на эту дату",
        )

    if settings.check_region and engineer.region_key != request.region_key:
        return FeasibilityResult(
            False,
            ReasonCode.NO_REGION,
            f"{engineer.name} работает в регионе «{engineer.region_key}», "
            f"а заявка относится к региону «{request.region_key}»",
        )

    if request.required_skill not in engineer.skills:
        return FeasibilityResult(
            False,
            ReasonCode.NO_SKILL,
            f"у {engineer.name} нет навыка «{SKILL_TITLES.get(request.required_skill, request.required_skill)}»",
        )

    if request.required_transport is not None and request.required_transport != engineer.transport_mode:
        return FeasibilityResult(
            False,
            ReasonCode.NO_TRANSPORT,
            f"заявка требует транспорт «{TRANSPORT_TITLES.get(request.required_transport, request.required_transport)}», "
            f"у {engineer.name} — «{TRANSPORT_TITLES.get(engineer.transport_mode, engineer.transport_mode)}»",
        )

    if settings.check_equipment and not request.required_equipment <= engineer.equipment:
        missing = request.required_equipment - engineer.equipment
        return FeasibilityResult(
            False,
            ReasonCode.NO_EQUIPMENT,
            f"у {engineer.name} на день не выдано: {_equipment_names(missing)}",
        )

    if not engineer.work_intervals:
        return FeasibilityResult(
            False,
            ReasonCode.NO_WORK_TIME,
            f"у {engineer.name} нет рабочих интервалов на дату плана",
        )

    return OK


class ReasonAccumulator:
    """Собирает причины отказа по всем инженерам и выбирает самую содержательную.

    Правило: побеждает код с **максимальным** рангом. Если кто-то из инженеров дошёл
    до проверки времени, значит навык и транспорт в организации есть, и честный ответ
    диспетчеру — «не помещается по времени», а не «нет навыка». Обратный порядок
    (первая сработавшая проверка) регулярно даёт ложную диагностику.
    """

    __slots__ = ("_reason", "_details", "_seen")

    def __init__(self) -> None:
        self._reason: ReasonCode | None = None
        self._details: list[str] = []
        self._seen: set[str] = set()

    def add(self, result: FeasibilityResult) -> None:
        if result.ok or result.reason is None:
            return
        current = self._reason
        if current is None or result.reason.rank > current.rank:
            self._reason = result.reason
            self._details = []
            self._seen = set()
        if result.reason is self._reason and result.detail and result.detail not in self._seen:
            self._seen.add(result.detail)
            self._details.append(result.detail)

    @property
    def reason(self) -> ReasonCode | None:
        return self._reason

    @property
    def details(self) -> list[str]:
        return list(self._details)

    def resolve(self, has_engineers: bool) -> tuple[ReasonCode, list[str]]:
        if not has_engineers:
            return ReasonCode.NO_ENGINEERS, ["во входных данных нет ни одного инженера"]
        if self._reason is None:
            return ReasonCode.NOT_FOUND, []
        return self._reason, list(self._details)

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlgorithmResult:
    assignments: list[dict]
    unassigned: list[dict]


class AlgorithmService:
    """Алгоритм автораспределения. Вход/выход — DTO, без доступа к БД."""

    def run(
        self,
        *,
        tickets: list[dict],
        engineers: list[dict],
    ) -> AlgorithmResult:
        del tickets, engineers
        return AlgorithmResult(assignments=[], unassigned=[])

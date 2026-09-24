"""Квалификация инженера для UI страницы «Персонал»."""

from __future__ import annotations

from enum import StrEnum


class QualificationCode(StrEnum):
    MASTER = "master"
    WORKER = "worker"
    NOVICE = "novice"


QUALIFICATION_LABELS: dict[str, str] = {
    QualificationCode.MASTER: "Мастер",
    QualificationCode.WORKER: "Бывалый",
    QualificationCode.NOVICE: "Новичек",
}

_BY_LABEL: dict[str, str] = {
    label.lower(): code for code, label in QUALIFICATION_LABELS.items()
}
_BY_LABEL.update({code: code for code in QUALIFICATION_LABELS})
# Старое имя из ранних макетов.
_BY_LABEL["работяга"] = QualificationCode.WORKER


def normalize_qualification(value: str | None) -> str | None:
    if not value:
        return None
    return _BY_LABEL.get(value.strip().lower())


def qualification_label(code: str | None) -> str | None:
    if not code:
        return None
    normalized = normalize_qualification(code)
    if normalized is None:
        return code
    return QUALIFICATION_LABELS[normalized]

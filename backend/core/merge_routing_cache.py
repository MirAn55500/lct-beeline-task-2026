"""Слить кэш маршрутов из образа с кэшем в volume (запускается из entrypoint.sh).

Volume переживает деплои и копит ответы ORS, а кэш в репозитории пополняется прогревом
на машине разработчика. Копировать только в пустой volume мало — новые участки из
репозитория до стенда тогда не доходят. Поэтому при старте берётся объединение; при
совпадении ключей побеждает volume: там самые свежие ответы сервиса.

    python -m core.merge_routing_cache <кэш из образа> <кэш в volume>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SECTIONS = ("legs", "geometry", "transit")


def merge(source: Path, target: Path) -> str:
    bundled = json.loads(source.read_text(encoding="utf-8"))
    if not target.exists():
        current: dict = {}
    else:
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}  # недописанный файл — пересобираем из образа
    if current.get("version") != bundled.get("version"):
        current = {}  # другой формат кэша — берём из образа целиком

    added = 0
    merged: dict = {"version": bundled.get("version")}
    for section in SECTIONS:
        out: dict = {}
        profiles = set(bundled.get(section, {})) | set(current.get(section, {}))
        for profile in sorted(profiles):
            ours = current.get(section, {}).get(profile, {})
            theirs = bundled.get(section, {}).get(profile, {})
            added += sum(1 for key in theirs if key not in ours)
            out[profile] = {**theirs, **ours}
        merged[section] = out

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, target)  # атомарно: backend не прочитает полуфайл
    return f"Routing cache: {target}, добавлено из образа {added}"


if __name__ == "__main__":
    print(merge(Path(sys.argv[1]), Path(sys.argv[2])))

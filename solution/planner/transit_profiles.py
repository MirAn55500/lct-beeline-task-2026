"""Хранение профилей rRAPTOR: время в пути на общественном транспорте на любой момент выезда.

Профиль пары (`raptor.Profile`) — ~200-300 записей «выезд → прибытие» на рабочий день.
На имеющиеся точки это десятки тысяч пар на каждый день недели, поэтому хранятся они
компактно:

* одна пара — `encode`: число записей, время пешком, первый выезд, дальше приращения
  выездов и время в пути, всё целыми секундами (uint16/uint32) — ~0.9 КБ без сжатия;
* набор пар — файл `data/transit_profiles.bin` (`write_file` / `read_file`): заголовок
  JSON и записи, всё под zlib. Дни недели с одинаковым расписанием (в фиде понедельник
  — четверг совпадают) лежат в файле один раз.

В backend профили живут в Postgres (таблица `transit_profile`), файл — только способ
привезти заранее посчитанное на стенд. Считает их `tools/raptor_prefetch.py`.

Профиль привязан к версии фида (`feed_version`): после обновления `gtfs.zip` старые
профили не должны подмешиваться к новому расписанию.
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zipfile
from array import array
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .raptor import Profile, _active_services

__all__ = [
    "ProfileSet",
    "decode",
    "encode",
    "feed_version",
    "read_file",
    "service_signature",
    "write_file",
]

MAGIC = b"RRP1"
_HEAD = struct.Struct("<HII")  # записей, пешком (с), первый выезд (с)
_RECORD = struct.Struct("<BHHH")  # группа дней, откуда, куда, длина записи


def feed_version(gtfs: str | Path) -> str:
    """Короткий хэш содержимого фида: меняется вместе с расписанием."""
    digest = hashlib.sha256()
    with open(gtfs, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def service_signature(gtfs: str | Path, day: date) -> str:
    """Какие сервисы фида действуют в этот день. Одинаковая подпись — одинаковое расписание."""
    with zipfile.ZipFile(gtfs) as archive:
        services = sorted(_active_services(archive, day))
    return hashlib.sha256("\n".join(services).encode()).hexdigest()[:16]


def encode(profile: Profile) -> bytes:
    # Запись, по которой ехать не быстрее, чем идти, ответа не меняет: `seconds_at`
    # берёт минимум с пешком, а следующие записи прибывают ещё позже. Выбрасываются —
    # заодно время в пути гарантированно влезает в uint16 (18 часов).
    cap = min(profile.walk, 0xFFFF)
    kept = [(d, a) for d, a in zip(profile.deps, profile.arrs) if a - d < cap]
    n = len(kept)
    if n > 0xFFFF:
        raise ValueError(f"профиль из {n} записей не помещается в формат")
    first = kept[0][0] if n else 0
    gaps = array("H", (b[0] - a[0] for a, b in zip(kept, kept[1:])))
    rides = array("H", (a - d for d, a in kept))
    return _HEAD.pack(n, min(profile.walk, 0xFFFFFFFF), first) + gaps.tobytes() + rides.tobytes()


def decode(blob: bytes) -> Profile:
    n, walk, first = _HEAD.unpack_from(blob)
    offset = _HEAD.size
    gaps = array("H")
    gaps.frombytes(blob[offset : offset + 2 * max(0, n - 1)])
    offset += 2 * max(0, n - 1)
    rides = array("H")
    rides.frombytes(blob[offset : offset + 2 * n])
    deps = [first] * n
    for i, gap in enumerate(gaps, start=1):
        deps[i] = deps[i - 1] + gap
    return Profile(deps, [d + r for d, r in zip(deps, rides)], walk)


@dataclass
class ProfileSet:
    """Профили всех пар на все дни недели одной версии фида."""

    feed: str
    first: int
    last: int
    weekdays: dict[int, int]
    """День недели (0 — понедельник) → номер группы дней с одинаковым расписанием."""
    pairs: dict[int, dict[tuple[str, str], bytes]]
    """Группа → (точка, точка) → `encode(profile)`."""

    def rows(self) -> Iterator[tuple[int, str, str, bytes]]:
        """(день недели, откуда, куда, профиль) — по строке на каждый день недели."""
        for weekday, group in sorted(self.weekdays.items()):
            for (a, b), blob in self.pairs.get(group, {}).items():
                yield weekday, a, b, blob

    def for_weekday(self, weekday: int, keys: Iterable[str] | None = None) -> dict[tuple[str, str], Profile]:
        group = self.weekdays.get(weekday)
        if group is None:
            return {}
        wanted = set(keys) if keys is not None else None
        return {
            (a, b): decode(blob)
            for (a, b), blob in self.pairs.get(group, {}).items()
            if wanted is None or (a in wanted and b in wanted)
        }


def write_file(path: str | Path, profiles: ProfileSet) -> int:
    """Записать набор в файл. Возвращает размер файла в байтах."""
    import zlib

    points = sorted({k for group in profiles.pairs.values() for pair in group for k in pair})
    index = {key: i for i, key in enumerate(points)}
    groups = sorted(profiles.pairs)
    header = json.dumps({
        "feed": profiles.feed,
        "first": profiles.first,
        "last": profiles.last,
        "weekdays": {str(d): groups.index(g) for d, g in profiles.weekdays.items()},
        "points": points,
    }).encode()
    body = io.BytesIO()
    body.write(MAGIC)
    body.write(struct.pack("<I", len(header)))
    body.write(header)
    for g, group in enumerate(groups):
        for (a, b), blob in sorted(profiles.pairs[group].items()):
            body.write(_RECORD.pack(g, index[a], index[b], len(blob)))
            body.write(blob)
    data = zlib.compress(body.getvalue(), 9)
    Path(path).write_bytes(data)
    return len(data)


def read_file(path: str | Path) -> ProfileSet:
    import zlib

    data = zlib.decompress(Path(path).read_bytes())
    if data[:4] != MAGIC:
        raise ValueError(f"{path}: не файл профилей rRAPTOR")
    (size,) = struct.unpack_from("<I", data, 4)
    header = json.loads(data[8 : 8 + size])
    points = header["points"]
    pairs: dict[int, dict[tuple[str, str], bytes]] = {}
    offset = 8 + size
    while offset < len(data):
        g, a, b, length = _RECORD.unpack_from(data, offset)
        offset += _RECORD.size
        pairs.setdefault(g, {})[(points[a], points[b])] = data[offset : offset + length]
        offset += length
    return ProfileSet(
        feed=header["feed"],
        first=header["first"],
        last=header["last"],
        weekdays={int(d): g for d, g in header["weekdays"].items()},
        pairs=pairs,
    )


def profiles_by_pair(
    rows: Iterable[tuple[str, str, bytes]]
) -> Mapping[tuple[str, str], Profile]:
    """Строки хранилища (откуда, куда, профиль) → словарь для модели перемещения."""
    return {(a, b): decode(bytes(blob)) for a, b, blob in rows}

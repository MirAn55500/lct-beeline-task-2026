"""Загрузка предоставленных выгрузок и сборка сценария.

Модуль вспомогательный: алгоритм работает с координатами и минутами и ничего не знает
про CSV. Здесь собрано всё, что нужно, чтобы довести реальный файл до этого вида, —
и, главное, всё, чего в файле **нет** и что приходится достраивать:

* координат нет → геокодирование (кэш + честная детерминированная заглушка);
* длительности нет → норматив по виду работ (`data/work_types.json`);
* навыка нет → только из «Тип заявки BK» (HD описывает работу и навык не подменяет);
* профилей инженеров нет вовсе → синтезируются по колонке «Бригада» контрольной выгрузки
  либо генерируются по заданным долям.

Каждое достроенное значение либо помечено в предупреждениях сценария, либо выводится по
явно записанному правилу. Выдавать сгенерированное за данные организатора нельзя.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .enums import Priority, Skill, TransportMode
from .models import MSK, Engineer, GeoPoint, Request, Scenario, Settings, WorkInterval

__all__ = [
    "WorkTypeCatalog",
    "Geocoder",
    "normalize_address",
    "LoadedRequests",
    "load_requests",
    "engineers_from_control",
    "generate_engineers",
    "build_scenario",
    "DATA_DIR",
]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_ENCODINGS = ("utf-8-sig", "cp1251")
_OFFICE_MARKERS = ("адрес офиса",)


# --------------------------------------------------------------------------------------
# Справочник видов работ
# --------------------------------------------------------------------------------------


class WorkTypeCatalog:
    """«Тип заявки BK» + «Тип заявки HD» → длительность, снаряжение; навык — только из BK."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._default = raw["default"]
        self._by_hd = raw.get("by_hd", {})
        self._by_bk = raw.get("by_bk", {})

    @classmethod
    def load(cls, path: Path | None = None) -> "WorkTypeCatalog":
        path = path or (DATA_DIR / "work_types.json")
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip().rstrip(".").strip()

    def resolve(self, bk: str, hd: str) -> dict[str, Any]:
        """Норматив: точная пара → HD → BK → default. Навык: только BK, если категория известна.

        HD описывает работу и может задать длительность и снаряжение, но не подменяет
        требуемый навык: он берётся из BK по таблице базы знаний «Навык».
        """
        bk_key, hd_key = self._normalize(bk), self._normalize(hd)
        exact = self._by_hd.get(f"{bk_key}|{hd_key}")
        found = exact or self._by_hd.get(hd_key) or self._by_bk.get(bk_key) or self._default
        result = dict(found)
        bk_spec = self._by_bk.get(bk_key)
        if bk_spec is not None and "skill" in bk_spec:
            result["skill"] = bk_spec["skill"]
        return result


# --------------------------------------------------------------------------------------
# Координаты
# --------------------------------------------------------------------------------------

_APARTMENT_RE = re.compile(r",\s*кв\.?\s*\S+\s*$", re.IGNORECASE)
_SPACES_RE = re.compile(r"\s+")


def normalize_address(address: str) -> str:
    """Канонический ключ адреса для кэша координат.

    Синтетическая и контрольная выгрузки описывают одни и те же дома, но в контрольной
    дописан номер квартиры. Геокодировать нужно дом, а не квартиру, поэтому ключ от неё
    очищается — иначе кэш раздувается вдвое и половина адресов всё равно не находится.
    """
    cleaned = _APARTMENT_RE.sub("", address.strip())
    return _SPACES_RE.sub(" ", cleaned).strip(" ,")


class Geocoder:
    """Координаты по адресу: кэш, затем детерминированная заглушка по району.

    Заглушка нужна, чтобы прототип запускался без сети и без ключей, и она **не выдаёт
    себя за геокодирование**: каждый такой адрес попадает в `warnings`. Разброс точек
    внутри района псевдослучайный, но детерминированный (хеш адреса), поэтому расчёт
    полностью воспроизводим.
    """

    def __init__(self, cache: dict[str, Any] | None = None) -> None:
        cache = cache or {}
        self.addresses: dict[str, GeoPoint] = {
            key: GeoPoint(value["lat"], value["lon"])
            for key, value in cache.get("addresses", {}).items()
        }
        self.districts: dict[str, GeoPoint] = {
            key: GeoPoint(value["lat"], value["lon"])
            for key, value in cache.get("districts", {}).items()
        }
        self.approximated: list[str] = []

    @classmethod
    def load(cls, path: Path | None = None) -> "Geocoder":
        path = path or (DATA_DIR / "geocache.json")
        if not path.exists():
            return cls()
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _jitter(seed_text: str, spread: float) -> tuple[float, float]:
        digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
        a = int.from_bytes(digest[0:4], "big") / 0xFFFFFFFF - 0.5
        b = int.from_bytes(digest[4:8], "big") / 0xFFFFFFFF - 0.5
        return a * spread, b * spread * 1.7

    def locate(self, address: str, district: str = "", anchor: GeoPoint | None = None) -> GeoPoint:
        key = normalize_address(address)
        exact = self.addresses.get(key) or self.addresses.get(address.strip())
        if exact is not None:
            return exact

        centre = self.districts.get(district.strip()) or anchor
        if centre is None:
            centre = GeoPoint(55.7522, 37.6156)  # центр Москвы как последняя опора
        dlat, dlon = self._jitter(key or district, 0.020)
        self.approximated.append(key or district)
        return GeoPoint(centre.lat + dlat, centre.lon + dlon)


# --------------------------------------------------------------------------------------
# Чтение выгрузки
# --------------------------------------------------------------------------------------


@dataclass
class LoadedRequests:
    requests: tuple[Request, ...]
    office_address: str = ""
    office_point: GeoPoint | None = None
    source_brigades: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _read_rows(path: Path) -> list[dict[str, str]]:
    last_error: Exception | None = None
    for encoding in _ENCODINGS:
        try:
            text = path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError) as exc:  # pragma: no cover - редкий путь
            last_error = exc
            continue
        reader = csv.DictReader(text.splitlines(), delimiter=";")
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    raise ValueError(f"Не удалось прочитать {path.name}: {last_error}")


def _parse_moment(value: str) -> datetime:
    """Формат выгрузок: ДД.ММ.ГГГГ ЧЧ:ММ, московское время (пояс в колонке отсутствует)."""
    return datetime.strptime(value.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=MSK)


def load_requests(
    path: str | Path,
    *,
    region_key: str = "default",
    catalog: WorkTypeCatalog | None = None,
    geocoder: Geocoder | None = None,
    urgent_statuses: Sequence[str] = (),
) -> LoadedRequests:
    """Читает файл заявок. Служебная строка с адресом офиса заявкой не считается."""
    path = Path(path)
    catalog = catalog or WorkTypeCatalog.load()
    geocoder = geocoder or Geocoder.load()

    rows = _read_rows(path)
    result = LoadedRequests(requests=())
    requests: list[Request] = []
    brigades: dict[str, list[str]] = {}
    skipped = 0

    for index, row in enumerate(rows):
        external_id = row.get("Заявка", "")
        first_cell = external_id.lower()

        if any(marker in first_cell for marker in _OFFICE_MARKERS):
            values = [v for k, v in row.items() if k != "Заявка" and v]
            result.office_address = values[0] if values else ""
            skipped += 1
            continue
        if not external_id or not row.get("Начало"):
            skipped += 1
            continue

        spec = catalog.resolve(row.get("Тип заявки BK", ""), row.get("Тип заявки HD", ""))
        address = row.get("Адрес", "")
        district = row.get("Район", "")
        status = row.get("Статус BK", "")

        requests.append(
            Request(
                id=external_id,
                point=geocoder.locate(address, district),
                window_start=_parse_moment(row["Начало"]),
                window_end=_parse_moment(row["Окончание"]),
                duration_minutes=int(spec["duration_minutes"]),
                required_skill=Skill(spec["skill"]),
                region_key=region_key,
                priority=Priority.URGENT if status in urgent_statuses else Priority.NORMAL,
                required_equipment=frozenset(spec.get("equipment", ())),
                address=address,
                district=district,
                input_order=index,
            )
        )
        brigade = row.get("Бригада", "")
        if brigade:
            brigades.setdefault(brigade, []).append(external_id)

    if result.office_address:
        result.office_point = geocoder.locate(result.office_address)

    if geocoder.approximated:
        unique = len(set(geocoder.approximated))
        result.warnings.append(
            f"Координаты {unique} адресов не найдены в кэше геокодирования и заменены "
            f"детерминированной оценкой по району: пробег и время в пути ориентировочные"
        )
    if skipped:
        result.warnings.append(f"Пропущено служебных и пустых строк: {skipped}")

    result.requests = tuple(requests)
    result.source_brigades = brigades
    return result


# --------------------------------------------------------------------------------------
# Профили инженеров
# --------------------------------------------------------------------------------------

_TRANSPORT_SHARES: tuple[tuple[TransportMode, float], ...] = (
    # База знаний: пешие исполнители и пользователи общественного транспорта преобладают.
    (TransportMode.WALKING, 0.35),
    (TransportMode.PUBLIC_TRANSPORT, 0.35),
    (TransportMode.CAR, 0.20),
    (TransportMode.BICYCLE, 0.10),
)

_LEVELS = ("junior", "middle", "senior")
"""Шкала квалификации — предложение набора. В выгрузках уровней нет, база знаний просит
достроить их синтетически. Правило влияния уровня на назначение не определено, поэтому
уровень сохраняется и показывается, но исполнителя не отбирает."""

_SKILL_SETS: tuple[tuple[Skill, ...], ...] = (
    (Skill.CONNECTION,),
    (Skill.LOCAL,),
    (Skill.CONNECTION, Skill.LOCAL),
    (Skill.CONNECTION, Skill.EMERGENCY),
    (Skill.LOCAL, Skill.EMERGENCY),
    (Skill.CONNECTION, Skill.LOCAL, Skill.EMERGENCY),
)


def _transport_for(index: int, total: int) -> TransportMode:
    """Раскладка по долям без случайности: доли соблюдаются точно и воспроизводимо."""
    position = (index + 0.5) / max(1, total)
    cumulative = 0.0
    for mode, share in _TRANSPORT_SHARES:
        cumulative += share
        if position <= cumulative:
            return mode
    return _TRANSPORT_SHARES[-1][0]


def generate_engineers(
    count: int,
    office: GeoPoint,
    day: Date,
    *,
    region_key: str = "default",
    shift: tuple[str, str] = ("09:00", "18:00"),
    lunch: tuple[str, str] | None = None,
    seed: int = 2026,
    names: Sequence[str] | None = None,
) -> tuple[Engineer, ...]:
    """Синтезирует состав бригады: профилей инженеров в выгрузках нет.

    Навыки распределяются так, чтобы каждый из трёх встречался и встречались разные
    комбинации — это требование ТЗ к тестовому набору (п. 6).
    """
    rnd = random.Random(seed)
    intervals = _build_intervals(day, shift, lunch)
    engineers: list[Engineer] = []

    for index in range(count):
        skills = _SKILL_SETS[index % len(_SKILL_SETS)]
        if index >= len(_SKILL_SETS):
            skills = rnd.choice(_SKILL_SETS)
        name = names[index] if names and index < len(names) else f"Инженер {index + 1}"
        levels = tuple(
            (skill, _LEVELS[(index + offset) % len(_LEVELS)])
            for offset, skill in enumerate(sorted(skills, key=lambda s: s.value))
        )
        engineers.append(
            Engineer(
                id=f"E{index + 1:03d}",
                name=name,
                start_point=office,
                work_intervals=intervals,
                skills=frozenset(skills),
                skill_levels=levels,
                transport_mode=_transport_for(index, count),
                region_key=region_key,
                equipment=frozenset({"router", "set_top_box"}),
                input_order=index,
            )
        )
    return tuple(engineers)


def engineers_from_control(
    brigades: Iterable[str],
    office: GeoPoint,
    day: Date,
    *,
    region_key: str = "default",
    shift: tuple[str, str] = ("09:00", "18:00"),
    lunch: tuple[str, str] | None = None,
    seed: int = 2026,
) -> tuple[Engineer, ...]:
    """Строит профили по колонке «Бригада» контрольной выгрузки.

    Каждое непустое значение колонки — отдельный исполнитель (а не бригада сервиса).
    Имя берётся из файла, всё остальное — навыки, транспорт, график — достраивается:
    этих данных в выгрузках нет.
    """
    names = sorted({b.strip() for b in brigades if b and b.strip()})
    engineers = generate_engineers(
        len(names),
        office,
        day,
        region_key=region_key,
        shift=shift,
        lunch=lunch,
        seed=seed,
        names=names,
    )
    return engineers


def _build_intervals(
    day: Date, shift: tuple[str, str], lunch: tuple[str, str] | None
) -> tuple[WorkInterval, ...]:
    def at(text: str) -> datetime:
        hour, minute = (int(part) for part in text.split(":"))
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK)

    start, end = at(shift[0]), at(shift[1])
    if lunch is None:
        return (WorkInterval(start, end),)
    lunch_start, lunch_end = at(lunch[0]), at(lunch[1])
    return (WorkInterval(start, lunch_start), WorkInterval(lunch_end, end))


# --------------------------------------------------------------------------------------
# Сборка сценария
# --------------------------------------------------------------------------------------


def build_scenario(
    requests_csv: str | Path,
    *,
    control_csv: str | Path | None = None,
    region_key: str = "default",
    engineer_count: int | None = None,
    shift: tuple[str, str] = ("09:00", "18:00"),
    lunch: tuple[str, str] | None = None,
    settings: Settings | None = None,
    name: str = "",
) -> tuple[Scenario, list[str]]:
    """Готовый сценарий из файла заявок. Возвращает сценарий и список примечаний.

    Если передан контрольный файл, состав исполнителей берётся из его колонки «Бригада»
    (имена реальные, остальные свойства достраиваются). Иначе команда генерируется
    заданного размера.
    """
    geocoder = Geocoder.load()
    catalog = WorkTypeCatalog.load()
    loaded = load_requests(
        requests_csv, region_key=region_key, catalog=catalog, geocoder=geocoder
    )
    notes = list(loaded.warnings)

    if not loaded.requests:
        raise ValueError(f"В файле {Path(requests_csv).name} не найдено ни одной заявки")

    day = loaded.requests[0].window_start.date()
    office = loaded.office_point or geocoder.locate("", "", None)
    if loaded.office_point is None:
        notes.append("Адрес офиса в файле не найден: старт инженеров взят как центр области")

    if control_csv is not None:
        control = load_requests(
            control_csv, region_key=region_key, catalog=catalog, geocoder=geocoder
        )
        engineers = engineers_from_control(
            control.source_brigades.keys(),
            office,
            day,
            region_key=region_key,
            shift=shift,
            lunch=lunch,
        )
        notes.append(
            f"Состав исполнителей ({len(engineers)}) взят из колонки «Бригада» контрольной "
            f"выгрузки; навыки, транспорт и график достроены синтетически"
        )
    else:
        count = engineer_count or max(1, round(len(loaded.requests) / 6))
        engineers = generate_engineers(
            count, office, day, region_key=region_key, shift=shift, lunch=lunch
        )
        notes.append(f"Профилей инженеров в данных нет: сгенерирована команда из {count} человек")

    scenario = Scenario(
        date=day,
        requests=loaded.requests,
        engineers=engineers,
        settings=settings or Settings(),
        name=name or Path(requests_csv).stem,
    )
    return scenario, notes

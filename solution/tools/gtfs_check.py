"""Проверка GTFS-архива до того, как отдавать его openrouteservice.

Профиль `public-transport` собирается вместе с графом: ORS принимает архив молча, а
непригодность выясняется через двадцать минут пересборки — либо не выясняется вовсе,
и сервис начинает отвечать пешей доступностью вместо расписаний. Дешевле посмотреть
в архив заранее.

Скрипт отвечает на три вопроса:

1. Это вообще GTFS? Выгрузки «остановки и маршруты» с порталов открытых данных часто
   называют GTFS, хотя времён в них нет. Без `stop_times.txt` профиль бесполезен.
2. Расписание ещё действует? Календарь с истёкшим сроком даёт пустую выдачу.
3. Покрывает ли фид наши адреса? Городской фид закрывает малую часть области, и на
   остальном линия маршрута просто не построится. Времени и расстояния это не
   затрагивает: матрица у этого профиля не берётся в любом случае (planner/ors.py).

Запуск:
    python tools/gtfs_check.py deploy/ors/files/gtfs.zip
    python tools/gtfs_check.py a.zip b.zip        # несколько фидов сразу

Код возврата 0, если архив пригоден к загрузке (пункты 1 и 2); покрытие влияет только
на печать, потому что несколько фидов дополняют друг друга.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner.io_csv import build_scenario, find_dataset_dir  # noqa: E402

# Минимальный состав по спецификации GTFS. calendar.txt и calendar_dates.txt
# взаимозаменяемы, поэтому проверяются отдельно.
REQUIRED = ("agency.txt", "routes.txt", "trips.txt", "stops.txt", "stop_times.txt")
CALENDARS = ("calendar.txt", "calendar_dates.txt")


def _rows(archive: zipfile.ZipFile, name: str):
    """Строки CSV из архива. GTFS допускает BOM, и csv без utf-8-sig ломается на первом поле."""
    with archive.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        yield from csv.DictReader(text)


def _service_dates(archive: zipfile.ZipFile, names: set[str]) -> tuple[str, str] | None:
    """Границы календаря в формате ГГГГММДД."""
    dates: list[str] = []
    if "calendar.txt" in names:
        for row in _rows(archive, "calendar.txt"):
            for key in ("start_date", "end_date"):
                value = (row.get(key) or "").strip()
                if len(value) == 8 and value.isdigit():
                    dates.append(value)
    if "calendar_dates.txt" in names:
        for row in _rows(archive, "calendar_dates.txt"):
            value = (row.get("date") or "").strip()
            if len(value) == 8 and value.isdigit():
                dates.append(value)
    return (min(dates), max(dates)) if dates else None


def _bbox(archive: zipfile.ZipFile) -> tuple[float, float, float, float] | None:
    lats: list[float] = []
    lons: list[float] = []
    for row in _rows(archive, "stops.txt"):
        try:
            lat = float((row.get("stop_lat") or "").strip())
            lon = float((row.get("stop_lon") or "").strip())
        except ValueError:
            continue
        lats.append(lat)
        lons.append(lon)
    return (min(lats), max(lats), min(lons), max(lons)) if lats else None


def _scenario_bbox() -> tuple[float, float, float, float] | None:
    """Границы наших адресов — чтобы сравнивать фид с задачей, а не с картой вообще."""
    dataset_dir = find_dataset_dir()
    if dataset_dir is None:
        return None
    lats: list[float] = []
    lons: list[float] = []
    for source in sorted(dataset_dir.glob("*.csv")):
        try:
            scenario, _ = build_scenario(source)
        except Exception:  # noqa: BLE001 - выгрузки бывают служебными, это не ошибка проверки
            continue
        for request in scenario.requests:
            lats.append(request.point.lat)
            lons.append(request.point.lon)
    return (min(lats), max(lats), min(lons), max(lons)) if lats else None


def _fmt_date(value: str) -> str:
    return f"{value[6:8]}.{value[4:6]}.{value[0:4]}"


def check(path: Path, wanted: tuple[float, float, float, float] | None) -> bool:
    print(f"\n· {path}")
    if not path.exists():
        print("    файла нет")
        return False

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        print("    это не zip-архив")
        return False

    with archive:
        # GTFS допускает вложенную папку внутри архива; берём только имена файлов.
        names = {Path(n).name for n in archive.namelist() if not n.endswith("/")}
        missing = [n for n in REQUIRED if n not in names]
        has_calendar = any(n in names for n in CALENDARS)
        if missing or not has_calendar:
            if missing:
                print(f"    не GTFS: нет {', '.join(missing)}")
            if not has_calendar:
                print(f"    не GTFS: нет ни {CALENDARS[0]}, ни {CALENDARS[1]}")
            if "stop_times.txt" in missing:
                print("    это выгрузка остановок и трасс без времён — для ORS бесполезна")
            return False

        stops = sum(1 for _ in _rows(archive, "stops.txt"))
        trips = sum(1 for _ in _rows(archive, "trips.txt"))
        routes = sum(1 for _ in _rows(archive, "routes.txt"))
        agencies = [(r.get("agency_name") or "?").strip() for r in _rows(archive, "agency.txt")]
        print(f"    состав: {routes} маршрутов, {trips} рейсов, {stops} остановок")
        print(f"    перевозчики: {', '.join(agencies[:5])}{'…' if len(agencies) > 5 else ''}")

        usable = True
        span = _service_dates(archive, names)
        if span is None:
            print("    календарь пуст — расписаний нет")
            usable = False
        else:
            today = date.today().strftime("%Y%m%d")
            mark = "действует" if span[0] <= today <= span[1] else "НЕ ДЕЙСТВУЕТ СЕГОДНЯ"
            print(f"    календарь: {_fmt_date(span[0])} — {_fmt_date(span[1])} ({mark})")
            if span[1] < today:
                usable = False

        box = _bbox(archive)
        if box is None:
            print("    у остановок нет координат")
            usable = False
        else:
            print(f"    покрытие: {box[0]:.2f}–{box[1]:.2f} с.ш., {box[2]:.2f}–{box[3]:.2f} в.д.")
            if wanted is not None:
                inside = (
                    box[0] <= wanted[0] and box[1] >= wanted[1]
                    and box[2] <= wanted[2] and box[3] >= wanted[3]
                )
                if inside:
                    print("    адреса выгрузок укладываются в фид целиком")
                else:
                    print(
                        f"    адреса выгрузок шире фида ({wanted[0]:.2f}–{wanted[1]:.2f} с.ш., "
                        f"{wanted[2]:.2f}–{wanted[3]:.2f} в.д.): вне покрытия линия "
                        "маршрута не построится, нужен ещё областной фид"
                    )
        return usable


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка GTFS-архива перед загрузкой в ORS")
    parser.add_argument("paths", nargs="+", type=Path, help="путь к gtfs.zip")
    args = parser.parse_args()

    wanted = _scenario_bbox()
    if wanted is None:
        print("Выгрузки не найдены — покрытие проверить не с чем, остальное проверяется.")
    else:
        print(
            f"Адреса выгрузок: {wanted[0]:.2f}–{wanted[1]:.2f} с.ш., "
            f"{wanted[2]:.2f}–{wanted[3]:.2f} в.д."
        )

    results = [check(path, wanted) for path in args.paths]
    good = [p for p, ok in zip(args.paths, results) if ok]
    print()
    if good:
        print(f"Пригодны к загрузке: {', '.join(str(p) for p in good)}")
        print("Дальше: положить архив в deploy/ors/files/gtfs.zip и пересобрать граф")
        print("профиля public-transport (см. deploy/ors/README.md) — блок в ors-config.yml")
        print("уже включён.")
        return 0
    print("Пригодных архивов нет.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

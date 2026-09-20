"""Сборка GTFS-фида из выгрузок data.mos.ru.

Портал отдаёт расписания наземного транспорта Москвы шестью отдельными CSV, каждый
со своим ключом. Состав ровно соответствует минимальному GTFS, только разложен иначе:

    маршруты.csv                  -> routes.txt
    рейсы маршрутов.csv           -> trips.txt
    расписание рейсов.csv         -> stop_times.txt
    календарь маршрутов.csv       -> calendar.txt
    остановки.csv                 -> stops.txt
    Транспортные предприятия.csv  -> agency.txt

Ничего не досочиняется: все поля переносятся как есть, кроме трёх мест, каждое
помечено в коде — вид транспорта (нумерация портала не совпадает с GTFS для
троллейбуса), пункт назначения (в выгрузке пуст у всех 203 791 рейса) и адрес сайта
перевозчика (GTFS требует непустой, у четырёх из пяти предприятий его нет).

Запуск:
    python tools/mosdata_to_gtfs.py
    python tools/mosdata_to_gtfs.py --data data --out deploy/ors/files/gtfs.zip

После сборки архив стоит прогнать через `tools/gtfs_check.py` — он проверит то, чего
конвертер по построению проверить не может: действует ли календарь сегодня и
накрывает ли фид адреса выгрузок.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SOURCES = {
    "routes": "маршруты.csv",
    "trips": "рейсы маршрутов.csv",
    "stop_times": "расписание рейсов.csv",
    "calendar": "календарь маршрутов.csv",
    "stops": "остановки.csv",
    "agency": "Транспортные предприятия.csv",
}

# Нумерация видов транспорта на портале совпадает с GTFS для автобуса (3) и трамвая (0),
# но не для троллейбуса: у портала 5, в GTFS 5 — это фуникулёр, а троллейбус 11.
ROUTE_TYPE = {"3": "3", "0": "0", "5": "11"}

# GTFS требует непустой agency_url, а в выгрузке он заполнен только у Мосгортранса.
# Общий портал городского транспорта — единственный честный вариант: он относится
# ко всем пяти предприятиям и никого не выдаёт за кого-то другого.
FALLBACK_AGENCY_URL = "https://transport.mos.ru"

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# Наибольший правдоподобный разрыв между соседними отметками рейса. Нужен, чтобы
# отличить переход через полночь от ошибки в данных: см. `_normalize_times`.
MAX_GAP = 12 * 3600


def read(path: Path):
    """Строки выгрузки. У файлов портала две строки заголовка — английская и русская."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        next(reader)  # русские названия тех же колонок
        for row in reader:
            yield dict(zip(header, row))


def _point(row: dict) -> tuple[float, float] | None:
    """Координата остановки из поля «Центроид»: {type=Point, coordinates=[lon, lat]}."""
    raw = row.get("Centroid") or row.get("Geodata") or ""
    start = raw.find("coordinates=[")
    if start < 0:
        return None
    end = raw.find("]", start)
    try:
        lon, lat = (float(v) for v in raw[start + 13:end].split(","))
    except ValueError:
        return None
    return lat, lon


def _headsign(long_name: str, direction: str) -> str:
    """Пункт назначения из названия маршрута «А - Б».

    В выгрузке поле пусто у всех рейсов, а в GTFS оно показывается пассажиру и на
    расчёт не влияет. Берём конец названия для прямого направления и начало для
    обратного; если название не разбирается — оставляем пустым, а не гадаем.
    """
    parts = long_name.split(" - ")
    if len(parts) < 2:
        return ""
    return parts[-1].strip() if direction == "0" else parts[0].strip()


def _seconds(value: str) -> int | None:
    try:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _clock(value: int) -> str:
    return f"{value // 3600:02d}:{value // 60 % 60:02d}:{value % 60:02d}"


def _normalize_times(rows: list[tuple[int, str, str, str]]) -> list[tuple[int, str, str, str]] | None:
    """Времена рейса в непрерывной шкале GTFS. None, если рейс починить нельзя.

    Бо́льшая часть ночных рейсов в выгрузке уже записана как 24:55 или 26:59 — ровно
    по соглашению GTFS, где отсчёт идёт от начала служебных суток и после 23:59 идёт
    24:00. Но у 155 рейсов полночь записана обычным 00:02, и время «идёт назад».

    Отличить это от ошибки можно по величине отката: если прибавка суток даёт разрыв
    в считанные минуты — это полночь; если разрыв остаётся почти суточным, значит в
    данных ошибка, и такой рейс отбрасывается, а не подгоняется.
    """
    result: list[tuple[int, str, str, str]] = []
    offset = 0
    previous: int | None = None
    for order, arrival, departure, stop in rows:
        pair = []
        for raw in (arrival, departure):
            value = _seconds(raw)
            if value is None:
                return None
            value += offset
            if previous is not None and value < previous:
                if value + 86400 - previous > MAX_GAP:
                    return None
                offset += 86400
                value += 86400
            previous = value
            pair.append(value)
        result.append((order, _clock(pair[0]), _clock(pair[1]), stop))
    return result


def _write(archive: zipfile.ZipFile, name: str, columns: list[str], rows) -> int:
    """Запись таблицы в архив. Возвращает число строк."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    count = 0
    for row in rows:
        writer.writerow(row)
        count += 1
    archive.writestr(name, buffer.getvalue().encode("utf-8"))
    return count


def build(data_dir: Path, out: Path) -> int:
    missing = [n for n in SOURCES.values() if not (data_dir / n).exists()]
    if missing:
        print(f"Не хватает выгрузок в {data_dir}:")
        for name in missing:
            print(f"    {name}")
        return 1

    print(f"Источник: {data_dir}")

    # --- остановки ---------------------------------------------------------------
    stops: dict[str, tuple[str, float, float]] = {}
    for row in read(data_dir / SOURCES["stops"]):
        point = _point(row)
        if point is None:
            continue
        stops[row["Stop code"]] = (row["Stop name"].strip(), point[0], point[1])
    print(f"    остановок в справочнике: {len(stops)}")

    # --- предприятия -------------------------------------------------------------
    agencies = []
    for row in read(data_dir / SOURCES["agency"]):
        agencies.append((
            row["Agency code"],
            row["Name of transport company"].strip(),
            (row.get("Website") or "").strip() or FALLBACK_AGENCY_URL,
            (row.get("Time zone") or "").strip() or "Europe/Moscow",
        ))

    # --- маршруты ----------------------------------------------------------------
    routes = {}
    unknown_types: set[str] = set()
    for row in read(data_dir / SOURCES["routes"]):
        kind = row["Type of route"].strip()
        if kind not in ROUTE_TYPE:
            unknown_types.add(kind)
            continue
        routes[row["Route code"]] = (
            row["Agency code"],
            row["Number of the route"].strip(),
            row["Full name route"].strip(),
            ROUTE_TYPE[kind],
        )
    if unknown_types:
        print(f"    ! неизвестный вид транспорта, маршруты пропущены: {sorted(unknown_types)}")

    # --- календарь ---------------------------------------------------------------
    calendar = []
    services: set[str] = set()
    for row in read(data_dir / SOURCES["calendar"]):
        service = row["Code list of dates"]
        services.add(service)
        calendar.append([service, *(row[d] for d in DAYS),
                         row["Start date of trip"], row["End date of trip"]])

    # --- рейсы -------------------------------------------------------------------
    trips: dict[str, tuple[str, str, str]] = {}
    orphan_route = orphan_service = 0
    for row in read(data_dir / SOURCES["trips"]):
        route, service = row["Route code"], row["Code list of dates"]
        if route not in routes:
            orphan_route += 1
            continue
        if service not in services:
            orphan_service += 1
            continue
        trips[row["Trip code"]] = (route, service, row["Direction of trip"].strip() or "0")
    print(f"    маршрутов: {len(routes)}, рейсов: {len(trips)}, перечней дат: {len(calendar)}")
    if orphan_route or orphan_service:
        print(f"    ! отброшено рейсов: {orphan_route} без маршрута, {orphan_service} без календаря")

    # --- расписание --------------------------------------------------------------
    # Файл отсортирован по остановкам, а не по рейсам, поэтому собирается целиком в
    # память и сортируется: GTFS ожидает строки по возрастанию stop_sequence внутри
    # рейса. Пять с лишним миллионов строк — около гигабайта, разовая операция.
    print("    чтение расписания (5+ млн строк, минуты)…")
    by_trip: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
    no_stop: set[str] = set()
    skipped = 0
    for row in read(data_dir / SOURCES["stop_times"]):
        trip = row["Trip code"]
        if trip not in trips:
            skipped += 1
            continue
        stop = row["Stop code"]
        if stop not in stops:
            no_stop.add(trip)
            continue
        try:
            order = int(row["Number stop"])
        except ValueError:
            skipped += 1
            continue
        by_trip[trip].append((order, row["Arrival time"], row["Departure time"], stop))

    # Рейс, у которого потерялась остановка, нельзя чинить пропуском строки: маршрут
    # поедет мимо неё по прямой. Такие рейсы выбрасываются целиком.
    for trip in no_stop:
        by_trip.pop(trip, None)
    if no_stop:
        print(f"    ! отброшено рейсов с остановкой без координат: {len(no_stop)}")
    if skipped:
        print(f"    ! пропущено строк расписания без рейса: {skipped}")

    # Рейс из одной точки в GTFS бессмыслен и валидаторами отвергается.
    short = [t for t, rows in by_trip.items() if len(rows) < 2]
    for trip in short:
        by_trip.pop(trip)
    if short:
        print(f"    ! отброшено рейсов короче двух остановок: {len(short)}")

    # Сортировка здесь, а не при записи: нормализация времён требует порядка остановок.
    broken = []
    midnight = 0
    for trip, rows in list(by_trip.items()):
        ordered = sorted(rows)
        fixed = _normalize_times(ordered)
        if fixed is None:
            broken.append(trip)
            by_trip.pop(trip)
            continue
        if fixed != ordered:
            midnight += 1
        by_trip[trip] = fixed
    if midnight:
        print(f"    переведено на шкалу служебных суток (полночь в пути): {midnight} рейсов")
    if broken:
        print(f"    ! отброшено рейсов с временем назад по ходу движения: {len(broken)}")

    used_stops = {row[3] for rows in by_trip.values() for row in rows}
    used_services = {trips[t][1] for t in by_trip}
    used_routes = {trips[t][0] for t in by_trip}

    # --- запись ------------------------------------------------------------------
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        n_agency = _write(archive, "agency.txt",
                          ["agency_id", "agency_name", "agency_url", "agency_timezone"],
                          agencies)
        n_stops = _write(archive, "stops.txt",
                         ["stop_id", "stop_name", "stop_lat", "stop_lon"],
                         ((code, stops[code][0], f"{stops[code][1]:.6f}", f"{stops[code][2]:.6f}")
                          for code in sorted(used_stops)))
        n_routes = _write(archive, "routes.txt",
                          ["route_id", "agency_id", "route_short_name",
                           "route_long_name", "route_type"],
                          ((code, *routes[code]) for code in sorted(used_routes)))
        n_cal = _write(archive, "calendar.txt",
                       ["service_id", "monday", "tuesday", "wednesday", "thursday",
                        "friday", "saturday", "sunday", "start_date", "end_date"],
                       (row for row in calendar if row[0] in used_services))
        n_trips = _write(archive, "trips.txt",
                         ["route_id", "service_id", "trip_id", "direction_id", "trip_headsign"],
                         ((trips[t][0], trips[t][1], t, trips[t][2],
                           _headsign(routes[trips[t][0]][2], trips[t][2]))
                          for t in sorted(by_trip)))

        def stop_time_rows():
            for trip in sorted(by_trip):
                for order, arrival, departure, stop in by_trip[trip]:
                    yield trip, arrival, departure, stop, order

        n_times = _write(archive, "stop_times.txt",
                         ["trip_id", "arrival_time", "departure_time",
                          "stop_id", "stop_sequence"],
                         stop_time_rows())

    size = out.stat().st_size / 1024 / 1024
    print(f"\nСобрано: {out} ({size:.1f} МБ)")
    print(f"    agency.txt     {n_agency}")
    print(f"    stops.txt      {n_stops}")
    print(f"    routes.txt     {n_routes}")
    print(f"    calendar.txt   {n_cal}")
    print(f"    trips.txt      {n_trips}")
    print(f"    stop_times.txt {n_times}")
    print(f"\nДальше: python tools/gtfs_check.py {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Сборка GTFS из выгрузок data.mos.ru")
    parser.add_argument("--data", type=Path, default=ROOT / "data",
                        help="каталог с выгрузками портала")
    parser.add_argument("--out", type=Path, default=ROOT / "deploy" / "ors" / "files" / "gtfs.zip",
                        help="куда положить архив")
    args = parser.parse_args()
    return build(args.data, args.out)


if __name__ == "__main__":
    raise SystemExit(main())

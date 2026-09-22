# -*- coding: utf-8 -*-
"""Синтез расписания метро, МЦК и МЦД (`tools/metro_gtfs.py`).

Расписаний рельсового транспорта Москвы в машиночитаемом виде не существует, поэтому
эта часть фида не переносится из выгрузки, а строится по интервалам движения. Раз она
строится, её и проверять надо иначе, чем перенос: важно не «совпало ли с источником»,
а выполняются ли свойства, без которых маршрут по расписанию посчитается неправильно.

Проверяется восемь вещей:

* время внутри рейса не идёт назад и перегон занимает правдоподобное время;
* интервал движения зависит от часа и от дня недели;
* пересадочный узел — это разные остановки разных линий плюс явная пересадка;
* ответвление линии не заводит вторых платформ на тех же станциях;
* кольцевой рейс позволяет доехать с конца цепочки в её начало;
* оба хода линии останавливаются на одних и тех же станциях;
* координата остановки принадлежит её собственной линии, а не станции-однофамильцу;
* цвет линии доезжает до фида в обеих записях, которыми его задаёт OSM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from metro_gtfs import (  # noqa: E402
    DWELL_SECONDS,
    HEADWAY_SECONDS,
    SPEED_KMH,
    TRANSFER_NEARBY_KM,
    TRANSFER_NEARBY_SECONDS,
    TRANSFER_SAME_NAME_KM,
    TRANSFER_SAME_NAME_SECONDS,
    TRANSFER_WALK_MAX_KM,
    build_metro,
    haversine_km,
    headway,
    line_group,
    normalize,
    route_color,
    slug,
    transfer_seconds,
)
from metro_gtfs import _mirror_missing_stations  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def feed():
    built = build_metro(DATA, "20240916", "20301231")
    if built is None:
        pytest.skip(f"нет {DATA / 'метро.json'} — соберите: python tools/osm_metro.py")
    return built


def _seconds(clock: str) -> int:
    hours, minutes, seconds = (int(part) for part in clock.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _by_trip(feed):
    trips: dict[str, list[tuple]] = {}
    for row in feed.stop_times:
        trips.setdefault(row[0], []).append(row)
    return trips


# --------------------------------------------------------------------------
# Ход рейса
# --------------------------------------------------------------------------


def test_time_never_goes_backwards_inside_a_trip(feed):
    """Время назад по ходу рейса — самая дешёвая ошибка синтеза и самая незаметная.

    Загрузчик GTFS такой рейс либо отбросит, либо построит по нему маршрут в прошлое;
    и то и другое выяснится только через двадцать минут пересборки графа.
    """
    for trip, rows in _by_trip(feed).items():
        previous = -1
        for _trip, arrival, departure, _stop, order in rows:
            assert _seconds(arrival) >= previous, f"{trip}: прибытие раньше предыдущего"
            assert _seconds(departure) >= _seconds(arrival), f"{trip}: отправление до прибытия"
            previous = _seconds(departure)


def test_stop_sequence_is_dense_and_starts_at_one(feed):
    """GTFS требует возрастающий `stop_sequence`; дыра в нём ломает порядок остановок."""
    for trip, rows in _by_trip(feed).items():
        orders = [int(row[4]) for row in rows]
        assert orders == list(range(1, len(orders) + 1)), trip


def test_run_time_between_stations_is_plausible(feed):
    """Перегон должен занимать минуты, а не секунды и не полчаса.

    Проверка грубая нарочно: точного времени хода нам взять неоткуда, но порядок
    величины ловит перепутанные единицы (секунды вместо минут) и потерянную стоянку.
    """
    gaps = []
    for rows in _by_trip(feed).values():
        for first, second in zip(rows, rows[1:]):
            gaps.append(_seconds(second[1]) - _seconds(first[2]))
    assert gaps
    average = sum(gaps) / len(gaps)
    assert 60 <= average <= 240, f"средний перегон {average:.0f} с неправдоподобен"
    assert max(gaps) <= 900


def test_commercial_speed_matches_the_official_one():
    """Скорость перегона и стоянка вместе обязаны давать эксплуатационную ~41 км/ч.

    Это единственная проверяемая величина во всей модели: метрополитен публикует
    эксплуатационную скорость, а средний перегон известен из данных. Если кто-то
    поднимет `SPEED_KMH`, забыв про стоянку, расхождение вылезет здесь.
    """
    average_hop_km = 1.72  # замер по data/метро.json
    seconds = average_hop_km / SPEED_KMH["metro"] * 3600 + DWELL_SECONDS["metro"]
    assert average_hop_km / seconds * 3600 == pytest.approx(41.6, abs=1.5)


# --------------------------------------------------------------------------
# Интервалы
# --------------------------------------------------------------------------


def test_headway_depends_on_hour_and_weekday():
    """Час пик, межпик и раннее утро — три разных интервала, и в выходные пика нет."""
    peak, day, quiet = HEADWAY_SECONDS["metro"]
    assert headway("metro", True, 8 * 3600) == peak
    assert headway("metro", True, 13 * 3600) == day
    assert headway("metro", True, 6 * 3600) == quiet
    assert headway("metro", True, 23 * 3600) == quiet
    assert headway("metro", False, 8 * 3600) == day, "в выходные часа пик нет"
    assert peak < day < quiet


def test_weekday_has_more_trips_than_weekend(feed):
    """Следствие интервалов: будний день должен давать больше рейсов, чем выходной."""
    weekday = sum(1 for trip in feed.trips if trip[1] == "m_weekday")
    weekend = sum(1 for trip in feed.trips if trip[1] == "m_weekend")
    assert weekday > weekend > 0


def test_service_covers_the_whole_working_day(feed):
    """Первый поезд до начала смены, последний — заполночь по шкале служебных суток."""
    starts = [_seconds(row[2]) for row in feed.stop_times]
    assert min(starts) <= 6 * 3600
    assert max(starts) > 24 * 3600, "ночные рейсы должны идти по шкале 24:00+"


# --------------------------------------------------------------------------
# Узлы и пересадки
# --------------------------------------------------------------------------


def test_interchange_is_separate_stops_plus_an_explicit_transfer(feed):
    """«Китай-город» шестой и седьмой линии — разные платформы и переход между ними.

    Одной остановкой их делать нельзя: пересадка стала бы бесплатной. Оставлять без
    `transfers.txt` — тоже: переход идёт под землёй, и на карте улиц его нет.
    """
    china = {row[0] for row in feed.stops if normalize(row[1]) == "китай-город"}
    assert len(china) >= 2, "пересадочный узел должен давать остановку на каждой линии"

    pairs = {(row[0], row[1]) for row in feed.transfers}
    assert any(a in china and b in china for a, b in pairs)

    coordinates = {row[0]: (float(row[2]), float(row[3])) for row in feed.stops}
    for a, b, kind, seconds in feed.transfers:
        assert kind == "2"
        # Нижняя граница — переход внутри узла, верхняя — пеший километр по
        # `TRANSFER_WALK_MAX_KM`: дальше записи вообще не заводятся.
        assert TRANSFER_SAME_NAME_SECONDS <= int(seconds) <= _walk_limit()
        assert haversine_km(coordinates[a], coordinates[b]) <= TRANSFER_WALK_MAX_KM


def _walk_limit() -> int:
    """Самая долгая пересадка, которую правила вообще разрешают записать."""
    return transfer_seconds(TRANSFER_WALK_MAX_KM, same_name=True)


def test_same_name_does_not_make_a_node_out_of_two_kilometres(feed):
    """«Перово» восьмой линии и «Перово» МЦД-3 стоят в 2.2 км друг от друга.

    Правило «то же имя — 180 секунд» дарило пассажиру двадцать минут ходьбы поверху, и
    это опаснее, чем отсутствие пересадки: маршрутизатор выбирает по времени и охотно
    строит поездку через переход, которого нет. Без записи в `transfers.txt` он ищет
    путь между платформами по уличному графу и считает его честно.
    """
    stops = {row[0]: (normalize(row[1]), float(row[2]), float(row[3])) for row in feed.stops}
    pairs = {(row[0], row[1]) for row in feed.transfers}

    far = [
        (a, b) for a in stops for b in stops
        if a < b
        and a.split("_")[1] != b.split("_")[1]
        and stops[a][0] == stops[b][0]
        and haversine_km(stops[a][1:], stops[b][1:]) > TRANSFER_WALK_MAX_KM
    ]
    assert far, "в сети должны быть одноимённые станции, разнесённые дальше километра"
    assert "перово" in {stops[a][0] for a, _b in far}, "проверять надо на известном случае"
    assert not any(pair in pairs or pair[::-1] in pairs for pair in far)


def test_transfer_time_follows_the_distance():
    """Три правила, и расстояние в каждом решает первым: имя только смягчает порог."""
    assert transfer_seconds(0.1, same_name=True) == TRANSFER_SAME_NAME_SECONDS
    assert transfer_seconds(TRANSFER_SAME_NAME_KM, same_name=True) == TRANSFER_SAME_NAME_SECONDS
    assert transfer_seconds(0.2, same_name=False) == TRANSFER_NEARBY_SECONDS
    assert transfer_seconds(TRANSFER_NEARBY_KM + 0.01, same_name=False) is None

    # Между порогом узла и километром — пешком, и чем дальше, тем дольше.
    near = transfer_seconds(TRANSFER_SAME_NAME_KM + 0.1, same_name=True)
    far = transfer_seconds(TRANSFER_WALK_MAX_KM, same_name=True)
    assert near is not None and far is not None and far > near > TRANSFER_NEARBY_SECONDS
    assert transfer_seconds(TRANSFER_WALK_MAX_KM + 0.01, same_name=True) is None


def test_transfers_are_symmetric(feed):
    """Пересадка в обе стороны: GTFS не выводит обратную запись сам."""
    pairs = {(row[0], row[1]) for row in feed.transfers}
    assert all((b, a) in pairs for a, b in pairs)


def test_transfers_never_join_one_line_with_itself(feed):
    """Пересадка внутри линии — это остановка, а не переход, и платить за неё нельзя."""
    for a, b, _kind, _seconds in feed.transfers:
        assert a.split("_")[1] != b.split("_")[1]


# --------------------------------------------------------------------------
# Ответвления и кольца
# --------------------------------------------------------------------------


def test_branch_shares_platforms_with_its_line():
    """Филёвская 4А идёт теми же платформами, что и 4, — остановки обязаны совпадать."""
    assert line_group("4А") == "4"
    assert line_group("D4А") == "D4"
    assert line_group("D1") == "D1", "цифра в конце — это номер, а не ответвление"
    assert line_group("11") == "11"


def test_branch_does_not_duplicate_stops(feed):
    """Следствие: у «Киевской» не должно быть отдельной остановки для 4А."""
    kiev = {row[0] for row in feed.stops if normalize(row[1]) == "киевская"}
    assert not any(stop.startswith("m_4a_") for stop in kiev)


def test_line_colour_survives_both_notations(feed):
    """В OSM цвет линии записан то кодом, то словом; GTFS принимает только код.

    У МЦК тег `colour` — это слово `red`, и без перевода линия осталась бы на карте
    бесцветной при том, что цвет в данных есть.
    """
    assert route_color("red") == "FF0000"
    assert route_color("#1EBCEF") == "1EBCEF"
    assert route_color("#abc") == "AABBCC"
    assert route_color("не цвет") == ""
    assert route_color("") == ""
    assert all(row[5] for row in feed.routes), "у каждой линии должен быть цвет"


def test_circular_trip_lets_you_ride_past_the_start(feed):
    """У кольца конечной нет, и рейс обязан это отражать.

    Иначе пассажиру с конца цепочки недоступно её начало: по данным поезд там уже
    закончил ход. На Кольцевой это каждая десятая пара станций.
    """
    circle = [row for row in feed.routes if row[0] == "m_metro_5"]
    assert circle, "Кольцевая линия должна быть в фиде"
    trips = [trip[2] for trip in feed.trips if trip[0] == "m_metro_5"]
    rows = _by_trip(feed)[trips[0]]
    stops = [row[3] for row in rows]
    assert stops[0] == stops[-1], "рейс кольца должен возвращаться на ту же станцию"
    assert len(stops) > len(set(stops)) + 1, "круг должен проезжаться дважды"


# --------------------------------------------------------------------------
# Ходы линии
# --------------------------------------------------------------------------


def test_both_directions_of_a_line_stop_at_the_same_stations(feed):
    """Ход туда и ход обратно обязаны знать одни и те же станции.

    В отношениях OSM станция иногда попадает только в одно направление: «Перерва» была
    лишь в ходе МЦД-2 на Подольск, «Левобережная» — лишь в ходе МЦД-3 на Ипподром.
    Остановка у нас одна на пару «линия + станция», поэтому дыра не отрезает станцию, а
    разворачивает поездку: маршрутизатор сажает пассажира на встречный поезд, везёт до
    станции, где есть оба хода, и там меняет направление. «Перерва» → «Люблино» стоила
    12.9 минуты против 10 в обратную сторону — маршрут построен, время правдоподобное,
    неправдой он выглядит только рядом с зеркальным.
    """
    directions: dict[tuple[str, str], set[str]] = {}
    trip_direction = {trip[2]: (trip[0], trip[3]) for trip in feed.trips}
    for trip, _arrival, _departure, stop, _order in feed.stop_times:
        directions.setdefault(trip_direction[trip], set()).add(stop)

    for route, _agency, ref, *_rest in feed.routes:
        here = directions.get((route, "0"), set())
        back = directions.get((route, "1"), set())
        if not back:
            continue                      # односторонних линий в сети нет, но мало ли
        assert here == back, (
            f"{ref}: ходы расходятся составом станций — "
            f"{sorted(here ^ back)}"
        )


def test_missing_station_is_taken_from_the_opposite_direction():
    """Потерянная в OSM остановка встаёт на зеркальное место, а не в конец хода."""
    line = {
        "ref": "D2",
        "directions": [
            {"headsign": "туда", "stations": [
                {"name": "А", "lat": 55.0, "lon": 37.0},
                {"name": "Б", "lat": 55.1, "lon": 37.0},
                {"name": "В", "lat": 55.2, "lon": 37.0},
            ]},
            {"headsign": "обратно", "stations": [
                {"name": "В", "lat": 55.2, "lon": 37.01},
                {"name": "А", "lat": 55.0, "lon": 37.01},
            ]},
        ],
    }
    notes = _mirror_missing_stations(line)
    assert [s["name"] for s in line["directions"][1]["stations"]] == ["В", "Б", "А"]
    assert [s["lon"] for s in line["directions"][1]["stations"]] == [37.01, 37.0, 37.01], (
        "своя платформа остаётся своей, достраивается только потерянная"
    )
    assert notes and "Б" in notes[0]


def test_a_different_route_is_not_mirrored():
    """Ход, идущий другим порядком, — это другой маршрут, и зеркалить его нечем."""
    line = {
        "ref": "D4",
        "directions": [
            {"headsign": "туда", "stations": [
                {"name": "А", "lat": 55.0, "lon": 37.0},
                {"name": "Б", "lat": 55.1, "lon": 37.0},
                {"name": "В", "lat": 55.2, "lon": 37.0},
            ]},
            {"headsign": "обратно", "stations": [
                {"name": "А", "lat": 55.0, "lon": 37.01},
                {"name": "В", "lat": 55.2, "lon": 37.01},
            ]},
        ],
    }
    before = [s["name"] for s in line["directions"][1]["stations"]]
    notes = _mirror_missing_stations(line)
    assert [s["name"] for s in line["directions"][1]["stations"]] == before
    assert notes and notes[0].startswith("!")


# --------------------------------------------------------------------------
# Связность таблиц
# --------------------------------------------------------------------------


def test_every_reference_resolves(feed):
    """Рейс без маршрута, остановка без координат, расписание без рейса — фид мёртв."""
    stops = {row[0] for row in feed.stops}
    routes = {row[0] for row in feed.routes}
    services = {row[0] for row in feed.calendar}
    agencies = {row[0] for row in feed.agency}

    assert {row[1] for row in feed.routes} <= agencies
    assert {trip[0] for trip in feed.trips} <= routes
    assert {trip[1] for trip in feed.trips} <= services
    assert {row[3] for row in feed.stop_times} <= stops
    assert {row[0] for row in feed.stop_times} == {trip[2] for trip in feed.trips}
    assert {row[0] for row in feed.transfers} | {row[1] for row in feed.transfers} <= stops


def test_stops_are_inside_the_moscow_region(feed):
    """Координата не на месте — единственная ошибка, которую не ловит ни одна ссылка."""
    for stop_id, name, lat, lon in feed.stops:
        assert 54.5 <= float(lat) <= 57.0, f"{name} ({stop_id})"
        assert 35.5 <= float(lon) <= 39.5, f"{name} ({stop_id})"


def test_every_stop_sits_on_its_own_line(feed):
    """Координата остановки обязана быть рядом с путями ИМЕННО своей линии.

    Проверка ловит один конкретный класс ошибки: станцию с координатами однофамильца.
    «Дубровка» есть на Люблинско-Дмитровской и на МЦК, «Новогиреево» — на восьмой линии
    и на МЦД-4; сличение с выгрузкой вестибюлей по одному названию уводило тридцать
    платформ к чужим входам, и у МЦД-2 «Люблино» промах составлял два километра. Ничем
    другим такая ошибка не видна: координата остаётся правдоподобной, все ссылки целы,
    маршрут строится — просто не оттуда.
    """
    lines = json.loads((DATA / "метро.json").read_text(encoding="utf-8"))["lines"]
    tracks: dict[str, list[tuple[float, float]]] = {}
    for line in lines:
        for direction in line["directions"]:
            for station in direction["stations"]:
                stop_id = f"m_{slug(line_group(line['ref']))}_{slug(station['name'])}"
                tracks.setdefault(stop_id, []).append((station["lat"], station["lon"]))

    for stop_id, name, lat, lon in feed.stops:
        points = tracks[stop_id]
        nearest = min(haversine_km((float(lat), float(lon)), p) for p in points)
        assert nearest <= 0.35, f"{name} ({stop_id}): {nearest * 1000:.0f} м до своих путей"

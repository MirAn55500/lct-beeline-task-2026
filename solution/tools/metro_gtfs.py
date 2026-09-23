"""Таблицы GTFS для метро, МЦК и МЦД.

Почему расписание синтезируется
-------------------------------
Расписаний рельсового транспорта Москвы в машиночитаемом виде нет: портал data.mos.ru
отдаёт справочник станций, вестибюли и рейтинг пассажиропотока, но ни одного времени
отправления. Наземный транспорт (`tools/mosdata_to_gtfs.py`) собирается из настоящих
расписаний, метро — нет, и делать вид, что это одно и то же, нельзя.

Зато метро — это ровно тот вид транспорта, который расписанием и не описывают.
Пассажир его не знает и не смотрит: поезда идут с интервалом, и время поездки
складывается из половины интервала (ожидание) и хода по перегонам. Именно это здесь и
моделируется — тактовое расписание по официальным интервалам метрополитена. Ошибка
такой модели — единицы минут на поездку, против десятков минут у расчёта по прямой,
который был до неё.

Все допущения собраны в константах ниже и ни одно не спрятано в коде.

Что откуда берётся
------------------
* порядок станций на линии      — `data/метро.json` (из OSM, см. `tools/osm_metro.py`);
* координаты станции            — центроид вестибюлей, «Входы и выходы вестибюлей
                                  станций метро.csv», по паре «линия + станция»;
                                  если станции там нет (платформы МЦД) — среднее
                                  координат путевых точек OSM;
* состав хода                   — из того же отношения, но сверенный со встречным:
                                  станция, потерянная OSM в одном направлении,
                                  достраивается на зеркальное место
                                  (см. `_mirror_missing_stations`);
* длина перегона                — по координатам соседних станций;
* время хода, интервалы         — константы ниже;
* пересадки                     — по расстоянию между платформами, с поправкой на
                                  совпадение названия станции.

Модуль вызывается из `tools/mosdata_to_gtfs.py` и отдельного запуска не имеет.
"""

from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

__all__ = ["MetroFeed", "build_metro", "transfer_seconds", "LINES_JSON", "ENTRANCES_CSV"]

LINES_JSON = "метро.json"
ENTRANCES_CSV = "Входы и выходы вестибюлей станций метро.csv"
STATIONS_CSV = "Станции метро.csv"

EARTH_RADIUS_KM = 6371.0088

# --------------------------------------------------------------------------------------
# Допущения модели. Все до одного — здесь.
# --------------------------------------------------------------------------------------

SPEED_KMH = {"metro": 50.0, "mcc": 48.0, "mcd": 55.0}
"""Скорость хода между станциями (не эксплуатационная!).

Эксплуатационная скорость метро — 41.6 км/ч — уже включает стоянки. Здесь задана
скорость именно перегона, стоянка добавляется отдельно (`DWELL_SECONDS`), иначе она
учлась бы дважды. Проверка: средний перегон метро 1.72 км даёт 124 с хода плюс 25 с
стоянки = 149 с, то есть 41.5 км/ч эксплуатационной — сходится с официальной.

МЦК: 53 км кольца за 32 остановки — 82 минуты круга против 84–90 фактических.
"""

DWELL_SECONDS = {"metro": 25, "mcc": 30, "mcd": 45}
"""Стоянка на станции. У МЦД длиннее: платформы длиннее и посадка медленнее."""

PEAK_HOURS = ((7, 10), (16, 20))
"""Часы пик по будням. В выходные пика нет — интервал дневной весь день."""

QUIET_BEFORE, QUIET_AFTER = 7, 21
"""Раннее утро и поздний вечер: интервал разрежен независимо от дня недели."""

HEADWAY_SECONDS = {
    # вид: (час пик, день, раннее утро и поздний вечер)
    "metro": (150, 240, 360),
    "mcc": (240, 480, 600),
    "mcd": (360, 900, 1200),
}
"""Интервалы движения. Метро — 2.5 мин в пик и 4 мин в межпик по данным
метрополитена; МЦК — 4 и 8 минут; МЦД — 6 и 15 минут."""

SERVICE_WINDOW = {
    # вид: (первый поезд, последний поезд) в секундах от начала служебных суток
    "metro": (5 * 3600 + 30 * 60, 25 * 3600),
    "mcc": (5 * 3600 + 45 * 60, 25 * 3600),
    "mcd": (5 * 3600 + 30 * 60, 24 * 3600 + 30 * 60),
}
"""Часы работы. 25:00 — это 01:00 следующих суток по шкале служебных суток GTFS."""

TRANSFER_SAME_NAME_SECONDS = 180
TRANSFER_SAME_NAME_KM = 0.4
TRANSFER_NEARBY_SECONDS = 300
TRANSFER_NEARBY_KM = 0.35
TRANSFER_WALK_MAX_KM = 1.0
TRANSFER_WALK_KMH = 4.5
TRANSFER_WALK_DETOUR = 1.3
"""Пересадка между линиями. Внутри узла — 3 минуты, между разноимёнными соседями —
5 минут, дальше — пешком по расстоянию, а совсем далеко — не пересадка вовсе.

Пересадки заданы явно, а не оставлены уличному графу, по простой причине: переход
между «Китай-городом» шестой и седьмой линии идёт под землёй, и на карте улиц его нет.
Сервис считал бы такой переход выходом на поверхность и обратно либо не находил вовсе.

Почему одного совпадения названий мало. Одноимённость в московской сети означает узел
не всегда: МЦД-3 «Перово» стоит в 2.2 км от станции восьмой линии, МЦД-2 «Люблино» —
в 2.0 км от станции десятой. Пассажир идёт туда двадцать минут поверху, а правило «то
же имя — 180 секунд» дарило ему их обе. Дарёные минуты опаснее отсутствующей пересадки:
маршрутизатор выбирает по времени и охотно строит поездку через несуществующий переход.

Поэтому решает расстояние, а имя только смягчает порог:

* до 0.4 км при совпадении названия — это узел, переход внутри него, 3 минуты. Порог
  взят по данным: из 123 одноимённых пар 114 укладываются в 0.5 км, а самые длинные
  настоящие переходы узла («ЗИЛ» МЦК ↔ БКЛ, «Дубровка» 10 ↔ 14) дают 0.47–0.63 км;
* до 0.35 км при разных названиях — «Тверская» / «Пушкинская», 5 минут;
* до 1 км — переход поверху, время считается по расстоянию (см. `transfer_seconds`);
* дальше — записи нет. Это не запрет пересадки: без записи в `transfers.txt`
  маршрутизатор ищет путь между платформами по уличному графу и посчитает его честно.
"""

CALENDAR = {
    # service_id: (пн, вт, ср, чт, пт, сб, вс)
    "m_weekday": (1, 1, 1, 1, 1, 0, 0),
    "m_weekend": (0, 0, 0, 0, 0, 1, 1),
}

AGENCIES = {
    "metro": ("m_metro", "Московский метрополитен", "https://mosmetro.ru"),
    "mcc": ("m_metro", "Московский метрополитен", "https://mosmetro.ru"),
    "mcd": ("m_mcd", "Московские центральные диаметры", "https://mcd.mosmetro.ru"),
}
"""МЦК отнесено к метрополитену намеренно: по тарифу и по пересадкам это его часть,
а перевозчик (РЖД) на расчёт маршрута не влияет."""

KIND_TITLES = {"metro": "метро", "mcc": "МЦК", "mcd": "МЦД"}


# --------------------------------------------------------------------------------------
# Вспомогательное
# --------------------------------------------------------------------------------------


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = lat2 - lat1
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def normalize(name: str) -> str:
    """Название станции в виде, пригодном для сличения OSM с выгрузкой портала.

    Расходятся ровно три вещи: «ё» против «е» («Чёрная речка»), кавычки-ёлочки вокруг
    имён собственных («Улица Академика Янгеля» против «Метро «Янгеля»») и регистр.
    Больше ничего не трогаем: «Арбатская» шестой и третьей линии — разные станции, и
    склеивать их по названию нельзя, поэтому сличение всегда идёт в паре с линией.
    """
    text = unicodedata.normalize("NFC", name).lower().replace("ё", "е")
    text = re.sub(r"[«»\"'`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def slug(name: str) -> str:
    """Идентификатор остановки из названия: только латиница, цифры и подчёркивание."""
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
        "и": "i", "й": "j", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
        "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch",
        "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    text = "".join(table.get(ch, ch) for ch in normalize(name))
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "x"


_BRANCH_SUFFIX = re.compile(r"^(.*\d)[А-Яа-яA-Za-z]$")


def line_group(ref: str) -> str:
    """Номер линии без буквы ответвления: «4А» -> «4», «D4А» -> «D4».

    Ответвление в OSM — отдельное отношение, но платформы у него общие с основным
    ходом: Филёвская 4А идёт от «Александровского сада» теми же станциями до «Киевской»
    и только дальше уходит в «Москва-Сити». Если дать ответвлению собственные остановки,
    те же самые платформы удвоятся, а между их половинами появится пересадка — и
    поездка по Филёвской подорожает на три минуты из ничего.
    """
    match = _BRANCH_SUFFIX.match(ref)
    return match.group(1) if match else ref


CSS_COLOURS = {
    "red": "FF0000", "green": "008000", "blue": "0000FF", "yellow": "FFFF00",
    "orange": "FFA500", "purple": "800080", "brown": "A52A2A", "grey": "808080",
    "gray": "808080", "black": "000000", "white": "FFFFFF", "pink": "FFC0CB",
    "cyan": "00FFFF", "lime": "00FF00", "teal": "008080", "navy": "000080",
}
"""Названия цветов CSS в шестнадцатеричный код.

В OSM тег `colour` допускает и то и другое, и у МЦК он записан словом `red`. GTFS
принимает только шестнадцатеричный код, поэтому слово без перевода просто потерялось бы —
линия на карте осталась бы бесцветной, хотя цвет в данных есть.
"""


def route_color(raw: str) -> str:
    """Цвет линии в формате GTFS: шесть шестнадцатеричных цифр без решётки."""
    value = (raw or "").strip().lstrip("#")
    if value.lower() in CSS_COLOURS:
        return CSS_COLOURS[value.lower()]
    if len(value) == 3 and all(c in "0123456789abcdefABCDEF" for c in value):
        return "".join(c * 2 for c in value).upper()   # #abc -> AABBCC
    if len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value):
        return value.upper()
    return ""


def clock(seconds: int) -> str:
    """Время по шкале служебных суток GTFS: после 23:59 идёт 24:00, а не 00:00."""
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def headway(kind: str, weekday: bool, seconds: int) -> int:
    """Интервал движения в момент `seconds` от начала служебных суток."""
    peak, day, quiet = HEADWAY_SECONDS[kind]
    hour = seconds // 3600 % 24
    if hour < QUIET_BEFORE or hour >= QUIET_AFTER:
        return quiet
    if weekday and any(start <= hour < end for start, end in PEAK_HOURS):
        return peak
    return day


# --------------------------------------------------------------------------------------
# Координаты станций из выгрузки портала
# --------------------------------------------------------------------------------------


def read_portal(path: Path):
    """Строки выгрузки портала. У файлов две строки заголовка — английская и русская."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        next(reader)
        for row in reader:
            yield dict(zip(header, row))


def _portal_station_names(path: Path) -> set[str]:
    """Действующие станции из справочника портала — чтобы сверить полноту фида.

    Справочник не участвует в сборке: порядка станций в нём нет, координат тоже.
    Зато он отвечает на вопрос, который иначе никто не задаёт: не потерялась ли
    станция при разборе OSM.
    """
    if not path.exists():
        return set()
    names: set[str] = set()
    for row in read_portal(path):
        if (row.get("Object status") or "").strip() != "действует":
            continue
        name = (row.get("Station name") or "").strip()
        if name:
            names.add(normalize(name))
    return names


def entrance_points(path: Path) -> dict[tuple[str, str], tuple[float, float]]:
    """Центроид вестибюлей по каждой станции. Ключ — пара «линия, станция».

    Координата станции берётся по вестибюлям, а не по путевой точке, потому что в
    маршруте важна не платформа, а место, куда человек приходит с улицы: сервис считает
    подход по уличному графу именно до координаты остановки. У станции в среднем четыре
    вестибюля, и центроид — компромисс между ними; ошибка против ближайшего входа
    (сотни метров у длинных станций) заведомо меньше, чем ошибка против платформы,
    которая может оказаться под парком или под рекой.

    Линия в ключе обязательна. «Дубровка» есть на Люблинско-Дмитровской и на МЦК, и это
    две разные станции в полукилометре друг от друга; «Новогиреево» — на восьмой линии и
    на МЦД-4, и там уже километр. Сличение по одному названию увело бы три десятка
    платформ к чужим вестибюлям — молча, потому что координата остаётся правдоподобной.

    Все 17 линий выгрузки совпадают по названию с линиями в OSM, так что ключ сходится
    без единого исключения; платформ МЦД в выгрузке нет вовсе — они и не метро.
    """
    groups: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for row in read_portal(path):
        if (row.get("Object status") or "").strip() != "действует":
            continue
        try:
            lat = float(row["Latitude in WGS-84"])
            lon = float(row["Longitude in WGS-84"])
        except (KeyError, ValueError):
            continue
        key = (normalize(row["Line name"]), normalize(row["Metro station name"]))
        groups[key].append((lat, lon))
    return {
        key: (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        for key, pts in groups.items()
    }


# --------------------------------------------------------------------------------------
# Сборка
# --------------------------------------------------------------------------------------


class MetroFeed:
    """Готовые таблицы GTFS и сводка по ним."""

    __slots__ = ("agency", "stops", "routes", "calendar", "trips", "stop_times",
                 "transfers", "notes")

    def __init__(self) -> None:
        self.agency: list[tuple] = []
        self.stops: list[tuple] = []
        self.routes: list[tuple] = []
        self.calendar: list[list] = []
        self.trips: list[tuple] = []
        self.stop_times: list[tuple] = []
        self.transfers: list[tuple] = []
        self.notes: list[str] = []


def _station_stops(lines: list[dict], points: dict[str, tuple[float, float]]) -> tuple[
    dict[tuple[str, str], str], list[tuple], int
]:
    """Остановки GTFS: по одной на пару «линия + станция».

    Не по одной на станцию: у пересадочного узла платформы разных линий — разные места,
    и время перехода между ними отлично от нуля (см. `transfers`). Не по одной на
    путевую точку OSM: у каждого направления она своя, и пассажир на «Медведково»
    оказался бы сразу на двух остановках, между которыми нет связи.
    """
    collected: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    titles: dict[tuple[str, str], str] = {}
    line_names: dict[tuple[str, str], str] = {}
    for line in lines:
        for direction in line["directions"]:
            for station in direction["stations"]:
                key = (line_group(line["ref"]), normalize(station["name"]))
                collected[key].append((station["lat"], station["lon"]))
                titles.setdefault(key, station["name"])
                line_names.setdefault(key, normalize(line["name"]))

    ids: dict[tuple[str, str], str] = {}
    rows: list[tuple] = []
    from_portal = 0
    for key in sorted(collected):
        ref, name = key
        point = points.get((line_names[key], name))
        if point is not None:
            from_portal += 1
        else:
            # Портал этой станции не знает: платформы МЦД, станции новых линий, а
            # также «Театральная» и «Улица Старокачаловская» — у них нет собственных
            # вестибюлей, вход через соседнюю станцию узла. Берём середину путевых
            # точек OSM.
            pts = collected[key]
            point = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        stop_id = f"m_{slug(ref)}_{slug(name)}"
        ids[key] = stop_id
        rows.append((stop_id, titles[key], f"{point[0]:.6f}", f"{point[1]:.6f}"))
    return ids, rows, from_portal


def transfer_seconds(km: float, same_name: bool) -> int | None:
    """Время перехода между платформами по расстоянию между ними. `None` — не пересадка.

    Расстояние решает, имя — только смягчает порог (см. `TRANSFER_SAME_NAME_KM`):
    одноимённость в московской сети не гарантирует узла, а двухкилометровый переход,
    записанный как трёхминутный, уводит маршрут в поездку, которой не существует.
    """
    if same_name and km <= TRANSFER_SAME_NAME_KM:
        return TRANSFER_SAME_NAME_SECONDS
    if km <= TRANSFER_NEARBY_KM:
        return TRANSFER_NEARBY_SECONDS
    if same_name and km <= TRANSFER_WALK_MAX_KM:
        # Переход поверху: идти столько, сколько идётся. Коэффициент извилистости тот
        # же, что у расчёта по координатам, — по прямой между платформами не ходят.
        walk = km * TRANSFER_WALK_DETOUR / TRANSFER_WALK_KMH * 3600
        return max(TRANSFER_NEARBY_SECONDS, round(walk))
    return None


def _transfers(stop_rows: list[tuple]) -> list[tuple]:
    """Пересадки между линиями: по близости платформ, с поправкой на совпадение названия.

    Оба признака нужны, но по-разному. Близость закрывает узлы с разными названиями —
    «Тверская» / «Пушкинская» / «Чеховская», «Библиотека имени Ленина» / «Боровицкая», —
    которых в Москве большинство. Совпадение названия закрывает узлы вроде «Китай-города»,
    где платформы разнесены дальше обычного порога, но переход внутри узла существует.

    Чего совпадение названия не делает — не заменяет расстояния. «Перово» восьмой линии
    и «Перово» МЦД-3 называются одинаково и стоят в 2.2 км друг от друга; см.
    `TRANSFER_SAME_NAME_KM`.
    """
    index = [(sid, name, float(lat), float(lon)) for sid, name, lat, lon in stop_rows]
    rows: list[tuple] = []
    for i, (sid_a, name_a, lat_a, lon_a) in enumerate(index):
        for sid_b, name_b, lat_b, lon_b in index[i + 1:]:
            if sid_a.split("_")[1] == sid_b.split("_")[1]:
                continue  # одна линия — это не пересадка
            km = haversine_km((lat_a, lon_a), (lat_b, lon_b))
            seconds = transfer_seconds(km, normalize(name_a) == normalize(name_b))
            if seconds is None:
                continue
            # GTFS требует обе стороны: переход A→B и B→A — разные записи.
            rows.append((sid_a, sid_b, "2", str(seconds)))
            rows.append((sid_b, sid_a, "2", str(seconds)))
    return rows


def _is_subsequence(part: list[str], whole: list[str]) -> bool:
    """Все элементы `part` встречаются в `whole` в том же порядке."""
    rest = iter(whole)
    return all(name in rest for name in part)


def _mirror_missing_stations(line: dict) -> list[str]:
    """Достроить ход по составу встречного: платформа есть, а в отношении OSM её нет.

    На диаметрах станция иногда попадает только в одно отношение: «Перерва» есть в
    ходе на Подольск и отсутствует в ходе на Нахабино, «Левобережная» — только в ходе
    на Ипподром. На земле платформы обе и поезд останавливается в обе стороны; потерян
    участник отношения, а не остановка.

    Для расписания это дороже, чем кажется. Остановка у нас одна на пару «линия +
    станция», поэтому сесть на «Перерве» можно, а уехать в нужную сторону — нельзя:
    маршрутизатор сажает пассажира на встречный поезд, везёт до ближайшей станции, где
    есть оба хода, и там разворачивает. «Перерва» → «Люблино» выходит 12.9 минуты
    против 10 в обратную сторону, «Левобережная» → «Химки» — 17.5 минуты и 4.4 км
    вместо одного перегона в 1.3 минуты. Ошибка молчаливая: маршрут построен, время
    правдоподобное, и неправдой он выглядит только рядом с обратным.

    Поэтому составы двух ходов сверяются, и недостающая остановка встаёт на зеркальное
    место — туда, где она стоит во встречном ходе. Координата берётся от платформы
    встречного пути: другой у нас нет, а платформы одной станции разнесены на десятки
    метров — это меньше ошибки самой модели.

    Зеркалится только ход, который беднее встречного и не спорит с ним порядком. Если
    порядок другой (укороченный маршрут, ответвление), достраивать нечего: такой случай
    отмечается в сводке и остаётся как есть.
    """
    directions = line["directions"]
    if len(directions) != 2:
        return []
    notes: list[str] = []
    for index in (0, 1):
        target, source = directions[index], directions[1 - index]
        have = [normalize(s["name"]) for s in target["stations"]]
        # Встречный ход, развёрнутый: так он идёт теми же станциями, что и наш.
        mirror_rows = list(reversed(source["stations"]))
        mirror = [normalize(s["name"]) for s in mirror_rows]
        missing = {name for name in mirror if name not in set(have)}
        if not missing:
            continue
        if not _is_subsequence(have, mirror):
            notes.append(
                f"! {line['ref']}: ход «{target['headsign']}» идёт не тем порядком, что "
                f"встречный, и остановок в нём меньше на {len(missing)} — не зеркалим"
            )
            continue
        merged: list[dict] = []
        position = 0
        for name, row in zip(mirror, mirror_rows):
            if position < len(have) and have[position] == name:
                merged.append(target["stations"][position])
                position += 1
            else:
                merged.append(dict(row))
        if position != len(have):        # своих остановок в зеркало не уложилось
            notes.append(
                f"! {line['ref']}: ход «{target['headsign']}» не лёг на встречный — не зеркалим"
            )
            continue
        added = [row["name"] for row, name in zip(merged, mirror) if name in missing]
        target["stations"] = merged
        notes.append(
            f"{line['ref']}: в ход «{target['headsign']}» добавлены остановки из встречного "
            f"хода ({len(added)}): {', '.join(added)} — в отношении OSM их нет, "
            "а платформы есть"
        )
    return notes


def _ring_runs(stations: list[dict], kind: str) -> list[tuple[list[dict], int]]:
    """Кольцевой ход как два рейса по кругу со сдвигом на полкруга.

    Круг в GTFS задаётся рейсом, который начинается и кончается на одной станции. Но
    рейс — это цепочка «сел не раньше, вышел не позже», и пассажиру, севшему у конца
    цепочки, ни одна станция у её начала недоступна: по данным поезд там уже закончил
    ход. На Кольцевой это каждая десятая пара станций.

    Раньше цепочка продлевалась на второй круг, и каждая станция встречалась в рейсе
    дважды. GTFS это допускает, а маршрутизатор ORS (GraphHopper) — нет: у поездки по
    такому рейсу ломаная проходит перегон дважды с прыжком назад между проходами, а
    расстояние втрое больше настоящего. На карте бригада «уезжала» в дальнюю точку и
    возвращалась, а километраж участков по кольцам (Кольцевая, БКЛ, МЦК) был завышен.

    Поэтому станции в рейсе теперь не повторяются: на каждый поезд два рейса, по кругу
    от первой станции и от станции напротив, второй — ровно тогда, когда тот же поезд
    там проходит. Любая поездка до полукруга включительно укладывается целиком в один
    из них, а длиннее полукруга по кольцу ехать незачем: встречный ход короче.

    Возвращает пары «станции рейса, сдвиг его отправления от первого, секунды».
    """
    circle = stations[:-1]                      # без повтора первой станции в конце
    half = len(circle) // 2
    _arrival, shift = _offsets(circle, kind)[half]
    return [(circle, 0), (circle[half:] + circle[:half], shift)]


def _offsets(stations: list[dict], kind: str) -> list[tuple[int, int]]:
    """Смещения прибытия и отправления от начала рейса, секунды."""
    speed = SPEED_KMH[kind]
    dwell = DWELL_SECONDS[kind]
    result = [(0, 0)]
    moment = 0
    for previous, station in zip(stations, stations[1:]):
        km = haversine_km((previous["lat"], previous["lon"]), (station["lat"], station["lon"]))
        moment += round(km / speed * 3600)
        result.append((moment, moment + dwell))
        moment += dwell
    # На конечной стоянки нет: отправление равно прибытию.
    arrival, _ = result[-1]
    result[-1] = (arrival, arrival)
    return result


def build_metro(data_dir: Path, start_date: str, end_date: str) -> MetroFeed | None:
    """Собрать таблицы метро. `None`, если нет `data/метро.json`."""
    source = data_dir / LINES_JSON
    if not source.exists():
        return None
    payload = json.loads(source.read_text(encoding="utf-8"))
    lines = payload.get("lines") or []
    if not lines:
        return None

    feed = MetroFeed()

    entrances = data_dir / ENTRANCES_CSV
    points = entrance_points(entrances) if entrances.exists() else {}
    if not points:
        feed.notes.append(
            f"! нет выгрузки «{ENTRANCES_CSV}» — координаты станций взяты по путевым "
            "точкам OSM, подход к станции считается до платформы, а не до вестибюля"
        )

    # Сверка ходов идёт до всего остального: она меняет состав станций, а от него
    # зависят и остановки, и расписание.
    repairs: list[str] = []
    for line in lines:
        repairs.extend(_mirror_missing_stations(line))

    stop_ids, feed.stops, from_portal = _station_stops(lines, points)
    feed.transfers = _transfers(feed.stops)
    feed.notes.extend(repairs)

    seen_agency: set[str] = set()
    for service_id, days in CALENDAR.items():
        feed.calendar.append([service_id, *days, start_date, end_date])

    counts: dict[str, int] = defaultdict(int)
    for line in lines:
        kind = line["kind"]
        agency_id, agency_name, agency_url = AGENCIES[kind]
        if agency_id not in seen_agency:
            seen_agency.add(agency_id)
            feed.agency.append((agency_id, agency_name, agency_url, "Europe/Moscow"))

        route_id = f"m_{slug(kind)}_{slug(line['ref'])}"
        feed.routes.append((
            route_id, agency_id, line["ref"], line["name"],
            str(line["route_type"]), route_color(line.get("colour", "")),
        ))
        counts[kind] += 1

        window_start, window_end = SERVICE_WINDOW[kind]
        for direction_id, direction in enumerate(line["directions"]):
            stations = direction["stations"]
            if line["circular"]:
                runs = _ring_runs(stations, kind)
            else:
                runs = [(stations, 0)]
            group = line_group(line["ref"])
            plans = [
                (
                    [stop_ids[(group, normalize(s["name"]))] for s in run],
                    _offsets(run, kind),
                    shift,
                )
                for run, shift in runs
            ]
            for service_id, days in CALENDAR.items():
                weekday = days[0] == 1
                moment = window_start
                index = 0
                while moment <= window_end:
                    for part, (sequence, offsets, shift) in enumerate(plans):
                        trip_id = f"{route_id}_{direction_id}_{service_id}_{index}"
                        if part:
                            trip_id += f"_{part}"
                        feed.trips.append((
                            route_id, service_id, trip_id, str(direction_id),
                            direction["headsign"],
                        ))
                        start = moment + shift
                        for order, (stop_id, (arrival, departure)) in enumerate(
                            zip(sequence, offsets), start=1
                        ):
                            feed.stop_times.append((
                                trip_id, clock(start + arrival), clock(start + departure),
                                stop_id, str(order),
                            ))
                    moment += headway(kind, weekday, moment)
                    index += 1

    total = len(feed.stops)
    feed.notes.append(
        f"остановок (линия × станция): {total}, координата по вестибюлям портала "
        f"у {from_portal}, по путевым точкам OSM у {total - from_portal} "
        "(платформы МЦД, которых в выгрузке вестибюлей нет)"
    )
    known = _portal_station_names(data_dir / STATIONS_CSV)
    if known:
        ours = {normalize(name) for _, name, _, _ in feed.stops}
        missing = sorted(known - ours)
        feed.notes.append(
            f"станций в справочнике портала {len(known)}, из них нет в фиде "
            f"{len(missing)}" + (f": {', '.join(missing[:5])}" if missing else "")
        )
    feed.notes.append(
        "линий: " + ", ".join(
            f"{KIND_TITLES[kind]} {count}" for kind, count in sorted(counts.items())
        )
        + f"; рейсов {len(feed.trips)}, строк расписания {len(feed.stop_times)}, "
        f"пересадок {len(feed.transfers) // 2}"
    )
    return feed

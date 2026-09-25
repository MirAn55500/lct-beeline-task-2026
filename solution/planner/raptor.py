"""Время в пути на общественном транспорте по расписанию GTFS — без ORS (RAPTOR).

Зачем. ORS считает общественный транспорт только через `directions`, по запросу на
пару точек, и держит расписания в памяти (~4 ГБ на Москву), поэтому новые адреса
досчитываются на отдельной машине (см. `ors.fetch_transit_legs`). Здесь то же самое
считается прямо из `gtfs.zip`: один поиск из точки даёт время прибытия сразу на все
остановки, а значит, и во все точки назначения — сколько бы их ни было.

Алгоритм — RAPTOR (Delling, Pajor, Werneck, «Round-Based Public Transit Routing», 2012).
Рейсы с одинаковой последовательностью остановок собираются в «маршруты»; поиск идёт
раундами, раунд = ещё одна поездка. В раунде просматриваются маршруты через остановки,
улучшенные прошлым раундом: садимся на ближайший рейс, обновляем прибытие на
следующие остановки, затем пешие пересадки на соседние остановки.

Допущения — те же, что у ORS там, где их можно повторить, и явные там, где нельзя:

* пешком 5 км/ч (как профиль `foot-walking` ORS, замерено по кэшу);
* пеший участок = расстояние по прямой × `WALK_DETOUR`. ORS идёт по улицам; медиана
  отношения «по улицам / по прямой» в кэше `foot-walking` — 1.29 (p10 1.15, p90 1.50).
  Это главный источник расхождения с ORS;
* до остановки и от неё — не дольше `ACCESS_MINUTES`, как `PT_WALKING_TIME` у ORS;
* пересадка — либо на той же остановке, либо из `transfers.txt`, либо пешком до
  остановки в радиусе `TRANSFER_KM` плюс `TRANSFER_PENALTY` (перейти улицу,
  спуститься в метро);
* если пешком целиком быстрее — идём пешком (ORS поступает так же); время пешком
  по улицам берётся из матрицы `foot-walking`, если она передана;
* время в пути = прибытие − момент выхода, то есть с ожиданием первого рейса.

Сверка с ORS (`tools/raptor_check.py`, 9.5 тыс. пар кэша, будни 10:00, штраф 120 с):
среднее RAPTOR − ORS −1.2 мин, |Δ| медиана 1.3 мин, 84 % пар в пределах 5 мин, 97 % —
10 мин. Медленнее ORS больше чем на 10 мин — 0.2 % пар; быстрее — 2.8 %, и это в
основном недосмотр самого ORS: из 12 таких маршрутов 11 ORS подтвердил по участкам
(каждый рейс в его графе есть, но сквозным поиском он их не нашёл). Поиск из точки —
0.07 с, загрузка дня — ~17 с, память ~80 МБ (30 тыс. рейсов в окне 10:00–14:00).

Только стандартная библиотека: модуль едет в образ backend, где numpy нет.
"""

from __future__ import annotations

import csv
import heapq
import io
import math
import zipfile
from array import array
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .models import GeoPoint
from .travel import haversine_km

__all__ = [
    "Profile",
    "Timetable",
    "TransitRouter",
    "load_timetable",
    "WALK_KMH",
    "WALK_DETOUR",
    "ACCESS_MINUTES",
    "TRANSFER_KM",
    "TRANSFER_PENALTY",
    "MAX_ROUNDS",
]

WALK_KMH = 5.0
WALK_DETOUR = 1.29
ACCESS_MINUTES = 30.0
TRANSFER_KM = 0.25
TRANSFER_PENALTY = 120
"""Секунды сверх ходьбы на пешую пересадку между разными остановками."""
MAX_ROUNDS = 6
HORIZON_MINUTES = 240.0
"""Сколько после момента выхода держать рейсы. Самая долгая пара кэша ORS — 99 мин."""

INF = 1 << 30

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def walk_seconds(km: float, detour: float = WALK_DETOUR, kmh: float = WALK_KMH) -> int:
    return int(round(km * detour / kmh * 3600))


def _seconds(value: str) -> int:
    """«HH:MM:SS» GTFS в секунды от начала служебных суток; часы могут быть > 24."""
    h, m, s = value.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _rows(archive: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with archive.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


@dataclass
class Route:
    """Рейсы с одной последовательностью остановок, без обгонов: j-й рейс не раньше j-1-го."""

    stops: list[int]
    dep: list[list[int]]  # dep[позиция][рейс]
    arr: list[list[int]]
    route_id: str = ""
    """Маршрут GTFS — для подписи поездки («автобус 123»), см. `Timetable.route_info`."""
    headsigns: list[str] = field(default_factory=list)
    """Направление каждого рейса (trip_headsign) — то, что написано на табло."""


@dataclass(frozen=True)
class RouteInfo:
    short_name: str
    long_name: str
    kind: str
    """Вид транспорта словом, как у ORS: bus, tram, subway, rail, trolleybus…"""


_KINDS = {
    0: "tram", 1: "subway", 2: "rail", 3: "bus", 4: "ferry", 5: "cable",
    6: "gondola", 7: "funicular", 11: "trolleybus", 12: "monorail",
}


def _kind(route_type: str) -> str:
    """`route_type` GTFS (и расширенные коды 100–1700) → вид транспорта словом."""
    try:
        code = int(route_type)
    except ValueError:
        return "bus"
    if code in _KINDS:
        return _KINDS[code]
    extended = {1: "rail", 2: "rail", 4: "subway", 7: "bus", 8: "trolleybus", 9: "tram", 10: "ferry"}
    return extended.get(code // 100, "bus")


@dataclass
class Timetable:
    """Расписание одного дня в окне [start, start + horizon], готовое к поиску."""

    day: date
    start: int  # секунды от начала служебных суток
    stop_ids: list[str]
    lat: list[float]
    lon: list[float]
    routes: list[Route]
    stop_routes: list[list[tuple[int, int]]]  # остановка → (маршрут, позиция)
    transfers: list[list[tuple[int, int]]]  # остановка → (остановка, секунды)
    stop_names: list[str] = field(default_factory=list)
    route_info: dict[str, RouteInfo] = field(default_factory=dict)
    _grid: dict[tuple[int, int], list[int]] = field(default_factory=dict, repr=False)

    @property
    def trips(self) -> int:
        return sum(len(r.dep[0]) for r in self.routes if r.dep)

    def stops_near(self, point: GeoPoint, km: float) -> list[tuple[int, float]]:
        """Остановки в радиусе `km` по прямой: (индекс, км)."""
        lat_step, lon_step = _cell_size(point.lat)
        radius_lat = math.ceil(km / (lat_step * 111.2))
        radius_lon = math.ceil(km / (lon_step * 111.2 * math.cos(math.radians(point.lat))))
        cy, cx = int(point.lat // lat_step), int(point.lon // lon_step)
        found = []
        for y in range(cy - radius_lat, cy + radius_lat + 1):
            for x in range(cx - radius_lon, cx + radius_lon + 1):
                for s in self._grid.get((y, x), ()):
                    d = haversine_km(point, GeoPoint(self.lat[s], self.lon[s]))
                    if d <= km:
                        found.append((s, d))
        return found


def _cell_size(lat: float) -> tuple[float, float]:
    return 0.01, 0.01 / max(0.2, math.cos(math.radians(lat)))


def _active_services(archive: zipfile.ZipFile, day: date) -> set[str]:
    names = set(archive.namelist())
    stamp = day.strftime("%Y%m%d")
    weekday = _WEEKDAYS[day.weekday()]
    active: set[str] = set()
    if "calendar.txt" in names:
        for row in _rows(archive, "calendar.txt"):
            if row[weekday] == "1" and row["start_date"] <= stamp <= row["end_date"]:
                active.add(row["service_id"])
    if "calendar_dates.txt" in names:
        for row in _rows(archive, "calendar_dates.txt"):
            if row["date"] != stamp:
                continue
            if row["exception_type"] == "1":
                active.add(row["service_id"])
            elif row["exception_type"] == "2":
                active.discard(row["service_id"])
    return active


def load_timetable(
    gtfs: str | Path,
    day: date,
    start_seconds: int,
    *,
    horizon_minutes: float = HORIZON_MINUTES,
    transfer_km: float = TRANSFER_KM,
    transfer_penalty: int = TRANSFER_PENALTY,
    detour: float = WALK_DETOUR,
) -> Timetable:
    """Разобрать `gtfs.zip` на один день.

    Держатся только рейсы, которые идут внутри окна: для поиска с выходом в 10:00
    ночные и вечерние рейсы бесполезны, а память и время на них ушли бы целиком.
    Рейсы после полуночи предыдущих суток (время > 24:00 вчерашнего дня) не учтены:
    для дневного окна их нет.
    """
    end = start_seconds + int(horizon_minutes * 60)
    with zipfile.ZipFile(gtfs) as archive:
        services = _active_services(archive, day)
        trip_meta: dict[str, tuple[str, str]] = {}
        headsigns: dict[str, str] = {}
        for row in _rows(archive, "trips.txt"):
            if row["service_id"] in services:
                sign = row.get("trip_headsign") or ""
                trip_meta[row["trip_id"]] = (row["route_id"], headsigns.setdefault(sign, sign))
        trip_ok = trip_meta
        route_info = {
            row["route_id"]: RouteInfo(
                row.get("route_short_name") or "", row.get("route_long_name") or "",
                _kind(row.get("route_type") or "3"),
            )
            for row in _rows(archive, "routes.txt")
        }

        stop_index: dict[str, int] = {}
        stop_ids: list[str] = []
        stop_names: list[str] = []
        lat: list[float] = []
        lon: list[float] = []
        for row in _rows(archive, "stops.txt"):
            stop_index[row["stop_id"]] = len(stop_ids)
            stop_ids.append(row["stop_id"])
            stop_names.append(row.get("stop_name") or "")
            lat.append(float(row["stop_lat"]))
            lon.append(float(row["stop_lon"]))

        # По рейсу — плоский array: sequence, stop, arr, dep. Компактно и не зависит
        # от того, отсортирован ли stop_times.txt по рейсам.
        raw: dict[str, array] = defaultdict(lambda: array("i"))
        for row in _rows(archive, "stop_times.txt"):
            trip = row["trip_id"]
            if trip not in trip_ok:
                continue
            stop = stop_index.get(row["stop_id"])
            if stop is None:
                continue
            raw[trip].extend((
                int(row["stop_sequence"]), stop,
                _seconds(row["arrival_time"]), _seconds(row["departure_time"]),
            ))

        explicit: list[tuple[int, int, int]] = []
        if "transfers.txt" in archive.namelist():
            for row in _rows(archive, "transfers.txt"):
                a, b = stop_index.get(row["from_stop_id"]), stop_index.get(row["to_stop_id"])
                if a is None or b is None or row.get("transfer_type") == "3":
                    continue
                explicit.append((a, b, int(float(row.get("min_transfer_time") or 0))))

    # Рейсы группируются по маршруту GTFS и последовательности остановок: так у поездки
    # есть подпись («автобус 123»), а на ответ поиска группировка не влияет.
    by_pattern: dict[tuple[str, tuple[int, ...]], list[tuple[list[int], list[int], str]]] = defaultdict(list)
    for trip, data in raw.items():
        rows = sorted(zip(data[0::4], data[1::4], data[2::4], data[3::4]))
        if len(rows) < 2 or rows[-1][2] < start_seconds or rows[0][3] > end:
            continue
        stops = tuple(r[1] for r in rows)
        route_id, sign = trip_meta[trip]
        by_pattern[(route_id, stops)].append(([r[2] for r in rows], [r[3] for r in rows], sign))
    del raw

    routes: list[Route] = []
    for (route_id, stops), trips in by_pattern.items():
        trips.sort(key=lambda t: (t[1][0], t[0][-1]))
        # Обгон (экспресс догоняет обычный рейс) ломает бинарный поиск рейса, поэтому
        # такие рейсы уходят в отдельный маршрут с той же последовательностью.
        lanes: list[list[tuple[list[int], list[int], str]]] = []
        for trip in trips:
            for lane in lanes:
                last = lane[-1]
                if all(a >= b for a, b in zip(trip[0], last[0])) and all(
                    a >= b for a, b in zip(trip[1], last[1])
                ):
                    lane.append(trip)
                    break
            else:
                lanes.append([trip])
        for lane in lanes:
            n = len(stops)
            routes.append(Route(
                stops=list(stops),
                arr=[[t[0][i] for t in lane] for i in range(n)],
                dep=[[t[1][i] for t in lane] for i in range(n)],
                route_id=route_id,
                headsigns=[t[2] for t in lane],
            ))

    stop_routes: list[list[tuple[int, int]]] = [[] for _ in stop_ids]
    for r, route in enumerate(routes):
        for pos, s in enumerate(route.stops):
            stop_routes[s].append((r, pos))

    timetable = Timetable(
        day=day, start=start_seconds, stop_ids=stop_ids, lat=lat, lon=lon,
        routes=routes, stop_routes=stop_routes, transfers=[[] for _ in stop_ids],
        stop_names=stop_names, route_info=route_info,
    )
    used = [s for s, rs in enumerate(stop_routes) if rs]
    for s in used:
        lat_step, lon_step = _cell_size(lat[s])
        timetable._grid.setdefault((int(lat[s] // lat_step), int(lon[s] // lon_step)), []).append(s)

    links: dict[tuple[int, int], int] = {}
    if transfer_km > 0:
        for s in used:
            for t, km in timetable.stops_near(GeoPoint(lat[s], lon[s]), transfer_km):
                if t != s:
                    links[(s, t)] = walk_seconds(km, detour) + transfer_penalty
    for a, b, seconds in explicit:
        if a != b:
            links[(a, b)] = seconds  # время из фида важнее расстояния по прямой
    for (a, b), seconds in links.items():
        timetable.transfers[a].append((b, seconds))
    return timetable


@dataclass
class Profile:
    """Время в пути до одной цели в зависимости от момента выхода (итог rRAPTOR).

    `deps` и `arrs` по возрастанию: выйти в `deps[i]` — прибыть в `arrs[i]`. Для
    выхода в момент t берётся ближайшая запись с deps ≥ t (выйти раньше можно, но
    ждать придётся на остановке), и сравнивается с дорогой пешком.
    """

    deps: list[int]
    arrs: list[int]
    walk: int

    def seconds_at(self, t: float) -> int:
        # Момент — до целой секунды, как в профиле: минуты планировщика — float, и
        # 1037.9 мин × 60 даёт 62273.99999…, а с таким моментом рейс ровно в 62274
        # то находится, то нет — в зависимости от того, как момент посчитан.
        t = round(t)
        i = bisect_left(self.deps, t)
        ride = self.arrs[i] - t if i < len(self.deps) else INF
        return min(ride, self.walk)

    def minutes_at(self, t: int) -> float:
        return self.seconds_at(t) / 60

    def latest_departure(self, arrive_by: float) -> float:
        """Самый поздний выход, при котором успеваем к `arrive_by` (секунды суток)."""
        arrive_by = round(arrive_by)
        i = bisect_right(self.arrs, arrive_by) - 1
        ride = self.deps[i] if i >= 0 else -INF
        walk = arrive_by - self.walk
        return ride if ride > walk else walk


class TransitRouter:
    """Поиск по расписанию: из одной точки во много."""

    def __init__(
        self,
        timetable: Timetable,
        *,
        access_minutes: float = ACCESS_MINUTES,
        detour: float = WALK_DETOUR,
        rounds: int = MAX_ROUNDS,
    ) -> None:
        self.tt = timetable
        self.detour = detour
        self.rounds = rounds
        self.access_km = access_minutes / 60 * WALK_KMH / detour
        self._near: dict[tuple[float, float], list[tuple[int, int]]] = {}

    def access(self, point: GeoPoint) -> list[tuple[int, int]]:
        """Остановки, до которых можно дойти: (остановка, секунды пешком)."""
        key = (point.lat, point.lon)
        near = self._near.get(key)
        if near is None:
            near = [(s, walk_seconds(km, self.detour)) for s, km in self.tt.stops_near(point, self.access_km)]
            self._near[key] = near
        return near

    def _search(
        self,
        best: list[int],
        ride: list[int],
        marked: set[int],
        limit: int,
        parents: list | None = None,
    ) -> set[int]:
        """Раунды RAPTOR от уже выставленных меток. Возвращает остановки, где улучшилось `ride`.

        Две метки на остановку: `best` — когда здесь можно быть (в том числе просто
        дойдя пешком от точки выхода), по ней садятся; `ride` — когда сюда можно
        приехать, по ней выходят к цели. Раздельно потому, что «дойти до остановки у
        цели и выйти» — не поездка, а прогулка по прямой, и она обходила бы время
        пешком по улицам.

        Метки не сбрасываются между вызовами — на этом держится rRAPTOR: всё, что
        достижимо при выходе позже, достижимо и при выходе раньше (можно подождать).
        """
        tt = self.tt
        routes, stop_routes, transfers = tt.routes, tt.stop_routes, tt.transfers
        changed: set[int] = set()
        for _ in range(self.rounds):
            queue: dict[int, int] = {}
            for s in marked:
                for r, pos in stop_routes[s]:
                    if pos < queue.get(r, INF):
                        queue[r] = pos
            improved: set[int] = set()
            rode: set[int] = set()
            for r, pos0 in queue.items():
                route = routes[r]
                stops, dep, arr = route.stops, route.dep, route.arr
                trip = -1
                board = -1
                board_pos = -1
                for pos in range(pos0, len(stops)):
                    s = stops[pos]
                    if trip >= 0:
                        a = arr[pos][trip]
                        if a < ride[s] and a <= limit:
                            ride[s] = a
                            rode.add(s)
                            if parents is not None:
                                parents[s] = ("ride", r, trip, board, board_pos, pos)
                            if a < best[s]:
                                best[s] = a
                                improved.add(s)
                    b = best[s]
                    if b < INF and (trip < 0 or b < dep[pos][trip]):
                        column = dep[pos]
                        j = bisect_left(column, b)
                        if j < len(column) and (trip < 0 or j < trip):
                            trip = j
                            board = s
                            board_pos = pos
            # Пешие пересадки — кратчайшим путём (Dijkstra) от всех, куда приехали: так
            # «линия 14 → линия 2 → автобус у выхода» складывается из двух связей, а
            # ответ не зависит от порядка обхода множества (раньше зависел).
            walked: set[int] = set()
            heap = [(ride[s], s) for s in rode]
            heapq.heapify(heap)
            while heap:
                base, s = heapq.heappop(heap)
                if base > ride[s]:
                    continue
                for t, seconds in transfers[s]:
                    if base + seconds < ride[t]:
                        ride[t] = base + seconds
                        walked.add(t)
                        heapq.heappush(heap, (base + seconds, t))
                        if parents is not None:
                            parents[t] = ("walk", s)
                        if base + seconds < best[t]:
                            best[t] = base + seconds
                            improved.add(t)
            changed |= rode
            changed |= walked
            marked = improved
            if not marked:
                break
        return changed

    def arrivals(
        self,
        sources: Iterable[tuple[int, int]],
        parents: list | None = None,
        *,
        depart: int | None = None,
    ) -> list[int]:
        """Самое раннее прибытие транспортом на каждую остановку (секунды суток; INF — нет).

        `parents` — пустой список для отладки: в него ляжет, как достигнута каждая
        остановка: ("ride", маршрут, рейс, остановка посадки) или ("walk", откуда).
        """
        n = len(self.tt.stop_ids)
        best, ride = [INF] * n, [INF] * n
        if parents is not None:
            parents[:] = [None] * n
        marked: set[int] = set()
        for s, t in sources:
            if t < best[s]:
                best[s] = t
                marked.add(s)
        start = self.tt.start if depart is None else depart
        self._search(best, ride, marked, start + int(HORIZON_MINUTES * 60), parents)
        return ride

    def _walks(
        self, origin: GeoPoint, targets: Sequence[GeoPoint],
        walk_minutes: Sequence[float | None] | None,
    ) -> list[int]:
        out = []
        for index, target in enumerate(targets):
            known = walk_minutes[index] if walk_minutes is not None else None
            if known is not None:
                out.append(int(round(known * 60)))
            else:
                out.append(walk_seconds(haversine_km(origin, target), self.detour))
        return out

    def travel_minutes(
        self,
        origin: GeoPoint,
        targets: Sequence[GeoPoint],
        walk_minutes: Sequence[float | None] | None = None,
        *,
        depart: int | None = None,
    ) -> list[float | None]:
        """Минуты от `origin` до каждой цели при выходе в `depart` (по умолчанию `timetable.start`).

        None — у одной из точек нет в пешей доступности остановок, через которые в
        этот день идёт хоть один рейс (вне фида). Если пешком быстрее или транспортом
        не доехать за горизонт — время пешком.

        `walk_minutes` — время пешком по улицам до каждой цели (матрица `foot-walking`
        ORS), если оно известно. По прямой здесь ошибиться легче всего: река или
        железная дорога удваивают путь, а короткие пары почти все решаются пешком.
        """
        start = self.tt.start if depart is None else depart
        origin_access = self.access(origin)
        ride = (
            self.arrivals(((s, start + w) for s, w in origin_access), depart=start)
            if origin_access else None
        )
        out: list[float | None] = []
        for target, walk in zip(targets, self._walks(origin, targets, walk_minutes)):
            egress = self.access(target)
            if ride is None or not egress:
                out.append(None)
                continue
            arrival = min((ride[s] + w for s, w in egress if ride[s] < INF), default=INF)
            out.append(min(arrival - start, walk) / 60)
        return out

    def profiles(
        self,
        origin: GeoPoint,
        targets: Sequence[GeoPoint],
        first: int,
        last: int,
        walk_minutes: Sequence[float | None] | None = None,
        *,
        step: int = 0,
        tail_minutes: float = 60.0,
    ) -> list[Profile | None]:
        """rRAPTOR: время до каждой цели для любого выхода из [first, last] одним проходом.

        Моменты выхода перебираются от позднего к раннему, метки между ними не
        сбрасываются, поэтому каждый следующий прогон досчитывает только то, что
        стало лучше. `step = 0` — точный rRAPTOR: моменты выхода = моменты, когда от
        ближайших остановок отходит рейс (с поправкой на дорогу до остановки).
        `step > 0` — сетка с этим шагом в секундах: быстрее, а ответ на момент между
        узлами берётся по следующему узлу, то есть не оптимистичнее точного.

        Рейсы после `last` тоже перебираются (`tail_minutes`), иначе для выхода около
        `last` профиль не знал бы о поездках чуть позже.
        """
        access = self.access(origin)
        walks = self._walks(origin, targets, walk_minutes)
        egress = [self.access(t) for t in targets]
        if not access:
            return [None] * len(targets)
        tail = last + int(tail_minutes * 60)
        by_moment: dict[int, set[int] | None]
        if step > 0:
            by_moment = {t: None for t in range(first - first % step, tail + 1, step)}
        else:
            grouped: dict[int, set[int]] = defaultdict(set)
            routes = self.tt.routes
            for s, w in access:
                for r, pos in self.tt.stop_routes[s]:
                    column = routes[r].dep[pos]
                    lo, hi = bisect_left(column, first + w), bisect_left(column, tail + w + 1)
                    for d in column[lo:hi]:
                        grouped[d - w].add(s)
            by_moment = dict(grouped)
        users: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for i, stops in enumerate(egress):
            for s, w in stops:
                users[s].append((i, w))

        n = len(self.tt.stop_ids)
        best, ride = [INF] * n, [INF] * n
        limit = tail + int(HORIZON_MINUTES * 60)
        current = [INF] * len(targets)
        found: list[list[tuple[int, int]]] = [[] for _ in targets]
        for t in sorted(by_moment, reverse=True):
            boarding = by_moment[t]
            marked: set[int] = set()
            for s, w in access:
                if t + w < best[s]:
                    best[s] = t + w
                    # Метить имеет смысл только остановки, где в этот момент отходит
                    # рейс: на остальных более ранняя метка ничего нового не открывает.
                    if boarding is None or s in boarding:
                        marked.add(s)
            touched: set[int] = set()
            for s in self._search(best, ride, marked, limit):
                for i, w in users.get(s, ()):
                    if ride[s] + w < current[i]:
                        current[i] = ride[s] + w
                        touched.add(i)
            for i in touched:
                found[i].append((t, current[i]))

        out: list[Profile | None] = []
        for i in range(len(targets)):
            if not egress[i]:
                out.append(None)
                continue
            pairs = found[i][::-1]
            out.append(Profile([d for d, _ in pairs], [a for _, a in pairs], walks[i]))
        return out

    def _rounds(self, access: list[tuple[int, int]], depart: int):
        """RAPTOR с метками по раундам: tau[k][s] — прибытие не более чем за k поездок.

        Обычный поиск (`_search`) держит одну метку на остановку — для времени это
        точно, но путь по ней восстановить нельзя: метки разных раундов смешиваются, и
        выходят «пересадки» ради выигрыша в секунды. Здесь, как в статье, у каждого
        раунда свои метки и свои «откуда»: parent[k][s] — ("ride", маршрут, рейс,
        остановка посадки, позиция посадки, позиция высадки) или ("walk", откуда); None —
        метка перенесена из раунда k-1.
        """
        tt = self.tt
        n = len(tt.stop_ids)
        limit = depart + int(HORIZON_MINUTES * 60)
        tau = [[INF] * n]
        parent: list[list] = [[None] * n]
        best = [INF] * n
        marked: set[int] = set()
        for s, w in access:
            if depart + w < tau[0][s]:
                tau[0][s] = best[s] = depart + w
                marked.add(s)
        for k in range(1, self.rounds + 1):
            prev = tau[k - 1]
            cur = list(prev)
            par: list = [None] * n
            queue: dict[int, int] = {}
            for s in marked:
                for r, pos in tt.stop_routes[s]:
                    if pos < queue.get(r, INF):
                        queue[r] = pos
            improved: set[int] = set()
            for r, pos0 in queue.items():
                route = tt.routes[r]
                stops, dep, arr = route.stops, route.dep, route.arr
                trip = board = board_pos = -1
                for pos in range(pos0, len(stops)):
                    s = stops[pos]
                    if trip >= 0:
                        a = arr[pos][trip]
                        if a < best[s] and a <= limit:
                            cur[s] = best[s] = a
                            par[s] = ("ride", r, trip, board, board_pos, pos)
                            improved.add(s)
                    b = prev[s]
                    if b < INF and (trip < 0 or b < dep[pos][trip]):
                        column = dep[pos]
                        j = bisect_left(column, b)
                        if j < len(column) and (trip < 0 or j < trip):
                            trip, board, board_pos = j, s, pos
            heap = [(cur[s], s) for s in improved]
            heapq.heapify(heap)
            while heap:
                base, s = heapq.heappop(heap)
                if base > cur[s]:
                    continue
                for t, seconds in tt.transfers[s]:
                    if base + seconds < best[t]:
                        cur[t] = best[t] = base + seconds
                        par[t] = ("walk", s)
                        improved.add(t)
                        heapq.heappush(heap, (base + seconds, t))
            tau.append(cur)
            parent.append(par)
            marked = improved
            if not marked:
                break
        return tau, parent

    def itinerary(
        self,
        origin: GeoPoint,
        target: GeoPoint,
        depart: int,
        walk_minutes: float | None = None,
        *,
        slack: int = 120,
    ) -> dict | None:
        """Как именно доехать при выходе в `depart` (секунды суток): состав и линия.

        Возвращает {"arrival": секунды, "legs": [...], "line": [[lon, lat], ...]}; участок —
        словарь в том же виде, что состав поездки ORS (`planner.ors._apply_transit`):
        kind, route, line, headsign, from, to, departure, arrival (секунды), minutes,
        km, stops. Линия идёт по координатам остановок маршрута — формы рейсов в фиде
        нет, но от остановки к остановке это и есть путь транспорта.

        Из вариантов, прибывающих не позже самого раннего + `slack` секунд, берётся тот,
        где меньше поездок: человек не станет пересаживаться трижды ради минуты.

        None — одна из точек вне фида. Если пешком не дольше — один пеший участок.
        """
        tt = self.tt
        access, egress = self.access(origin), self.access(target)
        if not access or not egress:
            return None
        [walk] = self._walks(origin, [target], [walk_minutes])
        tau, parent = self._rounds(access, depart)

        def reached(k: int, s: int) -> bool:
            """Метка раунда k получена поездкой, а не пешком от точки выхода."""
            while k > 0 and parent[k][s] is None:
                k -= 1
            return k > 0

        options = []
        for k in range(1, len(tau)):
            got = min(
                ((tau[k][s] + w, s, w) for s, w in egress if tau[k][s] < INF and reached(k, s)),
                default=None,
            )
            if got is not None:
                options.append((k, *got))
        if not options or min(o[1] for o in options) - depart >= walk:
            return {
                "arrival": depart + walk,
                "legs": [_walk_leg(depart, depart + walk, haversine_km(origin, target) * self.detour)],
                "line": [[origin.lon, origin.lat], [target.lon, target.lat]],
            }
        earliest = min(o[1] for o in options)
        k, _, stop, last_walk = next(o for o in options if o[1] <= earliest + slack)

        chain: list[tuple] = []
        s = stop
        while k > 0:
            step = parent[k][s]
            if step is None:
                k -= 1
            elif step[0] == "ride":
                chain.append((*step, s))
                s = step[3]
                k -= 1
            else:
                chain.append(("walk", step[1], s))
                s = step[1]
        chain.reverse()
        first_stop = s
        first_walk = dict(access).get(first_stop, 0)

        def point(x: int) -> list[float]:
            return [tt.lon[x], tt.lat[x]]

        def geo(x: int) -> GeoPoint:
            return GeoPoint(tt.lat[x], tt.lon[x])

        cursor = depart + first_walk
        legs = [_walk_leg(depart, cursor, haversine_km(origin, geo(first_stop)) * self.detour)]
        line = [[origin.lon, origin.lat], point(first_stop)]
        here = first_stop
        for item in chain:
            if item[0] == "ride":
                _, r, trip, board, board_pos, alight_pos, alight = item
                route = tt.routes[r]
                info = tt.route_info.get(route.route_id) or RouteInfo("", "", "bus")
                leaving = route.dep[board_pos][trip]
                arriving = route.arr[alight_pos][trip]
                path = route.stops[board_pos : alight_pos + 1]
                km = sum(haversine_km(geo(a), geo(b)) for a, b in zip(path, path[1:]))
                legs.append({
                    "kind": info.kind, "route": info.short_name, "line": info.long_name,
                    "headsign": route.headsigns[trip] if trip < len(route.headsigns) else "",
                    "from": tt.stop_names[board] if tt.stop_names else "",
                    "to": tt.stop_names[alight] if tt.stop_names else "",
                    "departure": leaving, "arrival": arriving,
                    "minutes": round((arriving - leaving) / 60, 2), "km": round(km, 3),
                    "stops": alight_pos - board_pos,
                })
                line.extend(point(x) for x in path[1:])
                cursor, here = arriving, alight
            else:
                _, source, dest = item
                seconds = next((sec for t, sec in tt.transfers[source] if t == dest), 0)
                legs.append(_walk_leg(cursor, cursor + seconds, haversine_km(geo(source), geo(dest)) * self.detour))
                line.append(point(dest))
                cursor, here = cursor + seconds, dest
        legs.append(_walk_leg(cursor, cursor + last_walk, haversine_km(geo(here), target) * self.detour))
        line.append([target.lon, target.lat])
        return {"arrival": cursor + last_walk, "legs": legs, "line": line}


def _walk_leg(start: int, end: int, km: float) -> dict:
    return {
        "kind": "walk", "route": "", "line": "", "headsign": "", "from": "", "to": "",
        "departure": start, "arrival": end, "minutes": round((end - start) / 60, 2),
        "km": round(km, 3), "stops": 0,
    }


def transit_legs(router: "TransitRouter", walk=None):
    """Источник состава поездок для `planner.ors.attach_route_geometry`.

    `walk(a, b)` — минуты пешком по улицам (матрица foot-walking), если известны.
    Возвращает функцию (a, b, выезд) → (линия, участки с ISO-временами) или None.
    """
    from datetime import timedelta

    def legs(a: GeoPoint, b: GeoPoint, departure):
        base = departure.replace(hour=0, minute=0, second=0, microsecond=0)
        depart = round((departure - base).total_seconds())
        got = router.itinerary(a, b, depart, walk(a, b) if walk is not None else None)
        if got is None:
            return None
        steps = [
            dict(
                leg,
                departure=(base + timedelta(seconds=leg["departure"])).isoformat(),
                arrival=(base + timedelta(seconds=leg["arrival"])).isoformat(),
            )
            for leg in got["legs"]
        ]
        return got["line"], steps

    return legs

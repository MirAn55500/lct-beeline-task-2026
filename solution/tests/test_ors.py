# -*- coding: utf-8 -*-
"""Реальная маршрутизация через openrouteservice (`planner/ors.py`).

Сеть здесь не трогается ни разу: клиент принимает функцию доставки запроса
параметром, и тесты подставляют вместо неё заглушку. Это не «мок ради мока» —
сервис внешний, и главное требование к интеграции как раз в том, что расчёт
обязан пережить любой его отказ.

Проверяются четыре вещи:

* запрос к сервису формируется по спецификации ORS (порядок lon/lat, метрики, нарезка);
* ответ раскладывается в модель перемещения без потери направления;
* любой отказ сервиса откатывает режим на расчёт по координатам, а не роняет план;
* геометрия доезжает до результата в виде, который сразу рисует карта.
"""
from __future__ import annotations

import json
import tempfile
import urllib.error
from datetime import timedelta
from pathlib import Path

import pytest

from factories import Algorithm, TransportMode, eng, gp, plan, req, routes_by_engineer, sc, settings

from planner.models import GeoPoint
from planner.ors import (
    SEARCH_BLOCK_ROWS,
    DEFAULT_PROFILES,
    NO_MATRIX_PROFILES,
    OrsClient,
    OrsError,
    OrsTravelModel,
    RoutingCache,
    attach_route_geometry,
    collect_points,
    covers,
    departure_moment,
    fetch_matrix,
    fetch_missing,
    point_key,
    reach_groups,
    scenario_departure,
    scenario_modes,
    setup_routing,
    transit_profile,
)

A = gp((55.7000, 37.6000))
B = gp((55.7500, 37.6500))
C = gp((55.8000, 37.7000))


# --------------------------------------------------------------------------
# Заглушка сервиса
# --------------------------------------------------------------------------


def _km(i: int, j: int) -> float:
    """Асимметричная «дорожная сеть»: A->B и B->A специально не равны."""
    return 0.0 if i == j else 1.0 + i + 0.25 * j


class FakeOrs:
    """Ответы ORS без сети. Считает вызовы — нарезку матрицы иначе не проверить."""

    def __init__(
        self,
        *,
        holes: set[tuple[int, int]] = frozenset(),
        error: Exception | None = None,
        summary: dict | None = None,
        bad_geometry: bool = False,
        row_width: int | None = None,
        rows_dropped: int = 0,
    ):
        self.calls: list[tuple[str, dict]] = []
        self.holes = set(holes)
        self.error = error
        # Ответ 200 неожиданной формы — не выдумка: у ORS 10 поле summary приходит
        # пустым, когда маршрут построен, но не измерен, а нечисловое значение в нём
        # встречается на сборках с локализованными полями. Заглушка обязана уметь и то
        # и другое, иначе проверять откат на прямую не на чем.
        self.summary = summary
        self.bad_geometry = bad_geometry
        self.row_width = row_width
        self.rows_dropped = rows_dropped

    def __call__(self, url, body, headers, timeout):
        payload = json.loads(body.decode("utf-8"))
        self.calls.append((url, payload))
        if self.error is not None:
            raise self.error() if callable(self.error) else self.error
        if "/matrix/" in url:
            return json.dumps(self._matrix(payload)).encode("utf-8")
        return json.dumps(self._directions(payload)).encode("utf-8")

    def _matrix(self, payload):
        count = len(payload["locations"])
        sources = payload.get("sources") or list(range(count))
        distances, durations = [], []
        for i in sources:
            row_km, row_sec = [], []
            for j in range(count):
                if (i, j) in self.holes:
                    # ORS так помечает недостижимую или не легшую на граф точку.
                    row_km.append(None)
                    row_sec.append(None)
                    continue
                km = _km(i, j)
                row_km.append(km)
                row_sec.append(km * 60.0)  # 1 км = 1 минута, считать в уме проще
            if self.row_width is not None:
                row_km = row_km[: self.row_width]
                row_sec = row_sec[: self.row_width]
            distances.append(row_km)
            durations.append(row_sec)
        if self.rows_dropped:
            distances = distances[: -self.rows_dropped]
            durations = durations[: -self.rows_dropped]
        return {"distances": distances, "durations": durations}

    def _directions(self, payload):
        """Ломаная: между каждой парой опорных точек — одна промежуточная."""
        coordinates, way_points = [], [0]
        for index, (lon, lat) in enumerate(payload["coordinates"]):
            if index:
                previous = payload["coordinates"][index - 1]
                coordinates.append([(previous[0] + lon) / 2, (previous[1] + lat) / 2])
            coordinates.append([lon, lat])
            if index:
                way_points.append(len(coordinates) - 1)
        if self.bad_geometry:
            coordinates[-1] = ["нет", "нет"]
        properties = {
            "way_points": way_points,
            # Числа круглые нарочно: 30 минут и 12 км ни при каком коэффициенте
            # извилистости не совпадут с расчётом по прямой, поэтому в тестах сразу
            # видно, чей ответ попал в модель.
            "summary": {"distance": 12000.0, "duration": 1800.0}
            if self.summary is None else self.summary,
        }
        if "departure" in payload:
            properties["legs"] = self._transit_legs(payload["departure"])
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                    "properties": properties,
                }
            ],
        }

    @staticmethod
    def _transit_legs(departure: str):
        """Поездка «пешком — автобус — метро»: так же, как её отдаёт ORS с GTFS."""
        return [
            {"type": "walk", "departure_location": "Walk",
             "distance": 400.0, "duration": 300.0, "route_type": -1,
             "departure": departure, "arrival": departure},
            {"type": "pt", "departure_location": "Улица Лескова",
             "route_short_name": "903", "trip_headsign": "Метро «Проспект Мира»",
             "route_type": 3, "distance": 6500.0, "duration": 900.0,
             "departure": departure, "arrival": departure,
             "stops": [{"name": "Улица Лескова"}, {"name": "Медведково"},
                       {"name": "Метро «ВДНХ»"}]},
            {"type": "pt", "departure_location": "ВДНХ",
             "route_short_name": "6", "trip_headsign": "Новоясеневская",
             "route_type": 1, "distance": 5100.0, "duration": 600.0,
             "departure": departure, "arrival": departure,
             "stops": [{"name": "ВДНХ"}, {"name": "Алексеевская"},
                       {"name": "Рижская"}]},
        ]



def _body(text: str):
    """Тело HTTPError: urllib ждёт файловый объект, а не строку."""
    import io

    return io.BytesIO(text.encode("utf-8"))

def client(fake: FakeOrs | None = None, **kwargs) -> OrsClient:
    return OrsClient("http://ors.test/ors", transport=fake or FakeOrs(), retries=0, **kwargs)


# --------------------------------------------------------------------------
# Клиент: форма запроса
# --------------------------------------------------------------------------


def test_matrix_request_follows_ors_spec():
    """GeoJSON-порядок (lon, lat), обе метрики, километры — иначе ответ не про то."""
    fake = FakeOrs()
    client(fake).matrix("driving-car", [A, B])
    url, payload = fake.calls[0]

    assert url == "http://ors.test/ors/v2/matrix/driving-car"
    assert payload["locations"] == [[A.lon, A.lat], [B.lon, B.lat]]
    assert set(payload["metrics"]) == {"distance", "duration"}
    assert payload["units"] == "km"


def test_directions_request_uses_geojson_endpoint():
    """Карте нужна геометрия, поэтому запрашивается именно /geojson."""
    fake = FakeOrs()
    client(fake).directions("foot-walking", [A, B])
    url, payload = fake.calls[0]

    assert url.endswith("/v2/directions/foot-walking/geojson")
    assert payload["coordinates"] == [[A.lon, A.lat], [B.lon, B.lat]]


def test_directions_requires_two_points():
    with pytest.raises(OrsError):
        client().directions("driving-car", [A])


def test_profiles_cover_every_transport_mode():
    """Справочник ТЗ п. 2.4.1 должен отображаться в профили ORS целиком."""
    assert set(DEFAULT_PROFILES) == set(TransportMode)


def test_client_reports_service_failure_as_ors_error():
    fake = FakeOrs(error=urllib.error.URLError("connection refused"))
    with pytest.raises(OrsError):
        client(fake).matrix("driving-car", [A, B])


# --------------------------------------------------------------------------
# Матрица
# --------------------------------------------------------------------------


def test_fetch_matrix_keeps_direction():
    """Односторонние улицы: A->B и B->A обязаны остаться разными значениями."""
    table = fetch_matrix(client(), "driving-car", [A, B, C])
    forward = table[(point_key(A), point_key(B))]
    backward = table[(point_key(B), point_key(A))]

    assert forward[0] == pytest.approx(_km(0, 1))
    assert backward[0] == pytest.approx(_km(1, 0))
    assert forward != backward


def test_fetch_matrix_converts_seconds_to_minutes():
    """ORS отдаёт секунды, планировщик считает в минутах."""
    table = fetch_matrix(client(), "driving-car", [A, B])
    _km_value, minutes = table[(point_key(A), point_key(B))]
    assert minutes == pytest.approx(_km(0, 1) * 60.0 / 60.0)


def test_fetch_matrix_is_split_into_blocks_under_the_instance_limit():
    """Лимит maximum_routes: 4 точки = 16 пар, при лимите 8 нужно два запроса."""
    fake = FakeOrs()
    points = [A, B, C, gp((55.85, 37.75))]
    table = fetch_matrix(client(fake, max_routes_per_request=8), "driving-car", points)

    assert len(fake.calls) == 2, "матрица не нарезана на блоки"
    assert len(table) == 12  # 4x4 без диагонали
    assert table[(point_key(points[3]), point_key(A))][0] == pytest.approx(_km(3, 0))


def test_fetch_matrix_result_does_not_depend_on_block_size():
    points = [A, B, C, gp((55.85, 37.75))]
    whole = fetch_matrix(client(max_routes_per_request=10_000), "driving-car", points)
    sliced = fetch_matrix(client(max_routes_per_request=4), "driving-car", points)
    assert whole == sliced


def test_unreachable_pairs_are_left_out_of_the_matrix():
    """null в ответе — не ноль расстояния, а «нет данных»: пара просто отсутствует."""
    fake = FakeOrs(holes={(0, 1)})
    table = fetch_matrix(client(fake), "driving-car", [A, B])
    assert (point_key(A), point_key(B)) not in table
    assert (point_key(B), point_key(A)) in table


# --------------------------------------------------------------------------
# Модель перемещения
# --------------------------------------------------------------------------


def ors_model(fake: FakeOrs | None = None, cfg=None, points=(A, B, C)) -> OrsTravelModel:
    cfg = cfg or settings()
    legs = {"driving-car": fetch_matrix(client(fake), "driving-car", list(points))}
    return OrsTravelModel(cfg, legs)


def test_travel_minutes_add_configured_overhead():
    """Парковка и подход — наши, а не дорожного графа: ORS про них не знает."""
    cfg = settings()
    model = ors_model(cfg=cfg)
    road = _km(0, 1)  # 1 км = 1 минута в заглушке
    assert model.travel_minutes(A, B, TransportMode.CAR) == pytest.approx(
        road + cfg.overhead_minutes[TransportMode.CAR]
    )


def test_distance_comes_from_the_service_as_is():
    assert ors_model().distance_km(A, B, TransportMode.CAR) == pytest.approx(_km(0, 1))


def test_model_is_asymmetric_unlike_the_haversine_one():
    model = ors_model()
    assert model.distance_km(A, B, TransportMode.CAR) != pytest.approx(
        model.distance_km(B, A, TransportMode.CAR)
    )


def test_same_point_costs_nothing():
    model = ors_model()
    assert model.both(A, GeoPoint(A.lat, A.lon), TransportMode.CAR) == (0.0, 0.0)


def test_unknown_pair_falls_back_to_coordinates():
    """Точка вне запрошенной матрицы не должна давать ни нуля, ни исключения."""
    cfg = settings()
    model = ors_model(cfg=cfg, points=(A, B))
    far = gp((56.5, 38.5))

    from planner.travel import HaversineTravelModel

    expected = HaversineTravelModel(cfg).both(A, far, TransportMode.CAR)
    assert model.both(A, far, TransportMode.CAR) == pytest.approx(expected)
    assert model.fallback_hits == 1


def test_mode_without_matrix_falls_back_per_mode():
    """Матрица собрана для авто — пешеход считается по координатам, а не берёт чужое."""
    cfg = settings()
    model = ors_model(cfg=cfg)
    from planner.travel import HaversineTravelModel

    expected = HaversineTravelModel(cfg).travel_minutes(A, B, TransportMode.WALKING)
    assert model.travel_minutes(A, B, TransportMode.WALKING) == pytest.approx(expected)


def test_report_mentions_incomplete_coverage():
    model = ors_model(points=(A, B))
    model.both(A, B, TransportMode.CAR)
    model.both(A, gp((56.5, 38.5)), TransportMode.CAR)
    report = " ".join(model.report())
    assert "координатам" in report and "50" in report


# --------------------------------------------------------------------------
# Сборка под сценарий и отказ сервиса
# --------------------------------------------------------------------------


def two_point_scenario():
    home = (55.70, 37.60)
    far = (55.80, 37.75)
    return sc(
        [req("R1", window=("09:00", "17:00"), dur=30, at=far)],
        [eng("E1", shift=("09:00", "18:00"), at=home, transport="car")],
    )


def test_collect_points_and_modes_describe_the_scenario():
    scenario = two_point_scenario()
    assert collect_points(scenario) == (
        scenario.engineers[0].start_point,
        scenario.requests[0].point,
    )
    assert scenario_modes(scenario) == (TransportMode.CAR,)


def test_collect_points_include_the_lunch_place():
    """Дорога к обеду «в своей точке» — из матрицы, а не по координатам."""
    from dataclasses import replace

    from factories import t
    from planner import Lunch

    scenario = two_point_scenario()
    spot = gp((55.73, 37.62))
    engineer = replace(
        scenario.engineers[0],
        lunch=Lunch(window_start=t("12:00"), window_end=t("14:00"), point=spot, place="point"),
    )
    scenario = replace(scenario, engineers=(engineer,))
    assert collect_points(scenario) == (engineer.start_point, spot, scenario.requests[0].point)


MOSCOW = [gp((55.70 + i / 100, 37.60)) for i in range(6)]
KASHIRA = [gp((54.84, 38.19)), gp((54.843, 38.24))]


def test_walking_matrix_is_split_into_islands():
    """Кашира в 100 км от Москвы: пешком между ними ORS не ищет — лимит обхода графа
    кончался на одной строке, и матрица собиралась минутами."""
    points = MOSCOW[:3] + KASHIRA[:1] + MOSCOW[3:] + KASHIRA[1:]
    assert reach_groups("foot-walking", points) == [[0, 1, 2, 4, 5, 6], [3, 7]]
    assert reach_groups("driving-car", points) == [list(range(8))]

    fake = FakeOrs()
    table = fetch_missing(client(fake), "foot-walking", points, {})
    far = {point_key(p) for p in KASHIRA}
    for _url, payload in fake.calls:
        keys = {point_key(gp((lat, lon))) for lon, lat in payload["locations"]}
        assert not keys & far or keys <= far, "запрос смешал острова"
    assert len(table) == 6 * 5 + 2 * 1
    assert (point_key(MOSCOW[0]), point_key(KASHIRA[0])) not in table
    assert covers(table, points, "foot-walking")
    assert not covers(table, points, "driving-car")
    # Всё нужное уже в таблице — второго похода в сервис нет
    fake.calls.clear()
    assert fetch_missing(client(fake), "foot-walking", points, table) == {}
    assert fake.calls == []


def test_car_matrix_keeps_distant_points_together():
    fake = FakeOrs()
    table = fetch_missing(client(fake), "driving-car", MOSCOW[:2] + KASHIRA[:1], {})
    assert len(table) == 3 * 2


def test_for_scenario_requests_only_the_modes_in_use():
    """Лишний профиль — это лишние минуты сборки графа и мегабайты кэша."""
    fake = FakeOrs()
    OrsTravelModel.for_scenario(two_point_scenario(), client(fake))
    assert len(fake.calls) == 1
    assert fake.calls[0][0].endswith("/matrix/driving-car")


def test_public_transport_matrix_is_not_requested():
    """У /matrix нет времени отправления, и ORS отвечает на неё пешим временем.

    Взять такой ответ — значит подменить транспорт пешеходом, не заметив этого:
    числа приходят правдоподобные. Поэтому профиль в матрицу не запрашивается вовсе.
    """
    scenario = sc(
        [req("R1", window=("09:00", "17:00"), dur=30, at=(55.80, 37.75))],
        [eng("E1", shift=("09:00", "18:00"), at=(55.70, 37.60), transport="public_transport")],
    )
    fake = FakeOrs()
    travel = OrsTravelModel.for_scenario(scenario, client(fake))

    assert fake.calls == [], "матрица общественного транспорта не должна запрашиваться"
    assert any("расписания" in w for w in travel.warnings)

    from planner.travel import HaversineTravelModel

    expected = HaversineTravelModel(scenario.settings).travel_minutes(
        scenario.engineers[0].start_point,
        scenario.requests[0].point,
        TransportMode.PUBLIC_TRANSPORT,
    )
    assert travel.travel_minutes(
        scenario.engineers[0].start_point,
        scenario.requests[0].point,
        TransportMode.PUBLIC_TRANSPORT,
    ) == pytest.approx(expected)


def test_public_transport_legs_in_an_old_cache_are_ignored():
    """Кэш мог успеть набрать такие участки до того, как выяснилось, чего они стоят."""
    profile = DEFAULT_PROFILES[TransportMode.PUBLIC_TRANSPORT]
    assert profile in NO_MATRIX_PROFILES

    cache = RoutingCache()
    cache.put_leg(profile, A, B, km=1.0, minutes=999.0)
    cfg = settings()
    model = OrsTravelModel.from_cache(cfg, cache)

    from planner.travel import HaversineTravelModel

    expected = HaversineTravelModel(cfg).travel_minutes(A, B, TransportMode.PUBLIC_TRANSPORT)
    assert model.travel_minutes(A, B, TransportMode.PUBLIC_TRANSPORT) == pytest.approx(expected)


def _public_transport_scenario():
    return sc(
        [req("R1", window=("09:00", "17:00"), dur=30, at=(55.80, 37.75))],
        [eng("E1", shift=("09:00", "18:00"), at=(55.70, 37.60), transport="public_transport")],
    )


def test_public_transport_is_counted_by_schedule_when_asked():
    """Главное про общественный транспорт: с `transit=True` числа берутся из расписания.

    Матрица для него по-прежнему не запрашивается — вместо неё идут запросы
    `/directions` со временем отправления, по одному на пару точек.
    """
    scenario = _public_transport_scenario()
    fake = FakeOrs()
    travel = OrsTravelModel.for_scenario(scenario, client(fake), transit=True)

    urls = [url for url, _ in fake.calls]
    assert not any("/matrix/" in url for url in urls)
    assert all("/directions/public-transport" in url for url in urls)
    assert all("departure" in payload for _, payload in fake.calls)

    a = scenario.engineers[0].start_point
    b = scenario.requests[0].point
    overhead = scenario.settings.overhead_minutes[TransportMode.PUBLIC_TRANSPORT]
    assert travel.travel_minutes(a, b, TransportMode.PUBLIC_TRANSPORT) == pytest.approx(
        30.0 + overhead
    )
    assert travel.distance_km(a, b, TransportMode.PUBLIC_TRANSPORT) == pytest.approx(12.0)


def test_transit_cache_is_keyed_by_departure_time():
    """Одна и та же пара точек утром и вечером — разные автобусы и разное время.

    Если бы раздел кэша не включал время, вечерний расчёт молча взял бы утренние числа.
    """
    scenario = _public_transport_scenario()
    cache = RoutingCache()
    OrsTravelModel.for_scenario(scenario, client(), cache=cache, transit=True)

    morning = scenario_departure(scenario)
    assert cache.legs_of(transit_profile("public-transport", morning))
    assert not cache.legs_of("public-transport")
    assert not cache.legs_of(transit_profile("public-transport", "2026-01-01T21:00:00"))


def test_transit_legs_reach_the_visit():
    """Диспетчеру нужен не только итог в минутах, но и на чём ехать и где садиться."""
    scenario = _public_transport_scenario()
    api = client(FakeOrs())
    travel = OrsTravelModel.for_scenario(scenario, api, transit=True)
    result = attach_route_geometry(plan(scenario, Algorithm.OPTIMIZED, travel=travel), api)

    legs = routes_by_engineer(result)["E1"].visits[0].transit
    assert [leg.kind for leg in legs] == ["walk", "bus", "subway"]
    assert [leg.route for leg in legs] == ["", "903", "6"]
    assert legs[1].from_stop == "Улица Лескова"
    assert legs[1].to_stop == "Метро «ВДНХ»"
    assert legs[1].stops == 2
    assert "автобус 903" in legs[1].title
    assert legs[2].to_dict()["kind"] == "subway"


def _verdict(code: int, message: str):
    """Фабрика отказов ORS: 404 с кодом ORS в теле, свежий экземпляр на каждый вызов.

    Именно фабрика, а не готовое исключение: тело `HTTPError` — файловый объект, и
    разбор вычитывает его до конца. Один экземпляр на два запроса означал бы, что во
    второй раз код ORS потерян и отказ неотличим от обрыва связи.
    """
    def make() -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            "http://ors.test/ors", 404, message, {},
            _body(json.dumps({"error": {"code": code, "message": message}})),
        )

    return make


def test_transit_falls_back_to_straight_line_for_unreachable_pairs():
    """Адрес вне зоны действия фида не должен ни ломать прогон, ни врать числом."""
    scenario = _public_transport_scenario()
    fake = FakeOrs(error=_verdict(2010, "Point 1 was not found in the graph"))
    travel = OrsTravelModel.for_scenario(scenario, client(fake), transit=True)

    from planner.travel import HaversineTravelModel

    a = scenario.engineers[0].start_point
    b = scenario.requests[0].point
    expected = HaversineTravelModel(scenario.settings).travel_minutes(
        a, b, TransportMode.PUBLIC_TRANSPORT
    )
    assert travel.travel_minutes(a, b, TransportMode.PUBLIC_TRANSPORT) == pytest.approx(expected)
    assert any("вне зоны действия фида" in w for w in travel.warnings)


@pytest.mark.parametrize("code, message", [
    (2014, "PT exit point cannot be reached within given street time."),
    (2013, "PT entry point cannot be reached within given street time."),
    (7777, "неизвестный нам вердикт"),
])
def test_a_routing_verdict_is_a_boundary_of_the_feed(code, message):
    """Регрессия живого прогона: «до остановки не дойти» — вне фида, а не отказ сервиса.

    2014 — вне фида прибытие, 2013 — вне фида отправление. Сервис при этом жив и
    ответил. Пока список перечислял коды «про пару точек», каждый неучтённый код молча
    становился поломкой профиля: 2538 пар «Юго-востока» уехали в отчёт с советом
    пересчитать план, когда сервис поднимут, — а он и не падал.

    Поэтому третий случай в списке — заведомо незнакомый код: умолчание обязано быть
    безопасным, то есть «вердикт о паре точек», иначе история повторится на следующем
    типе местности.
    """
    scenario = _public_transport_scenario()
    fake = FakeOrs(error=_verdict(
        code, f"Route could not be found - Unable to find a route between points. {message}"
    ))
    travel = OrsTravelModel.for_scenario(scenario, client(fake), transit=True)

    text = " ".join(travel.warnings)
    assert "вне зоны действия фида" in text
    assert "отказа сервиса" not in text
    assert "отклонил" not in text


def test_a_routing_verdict_does_not_disable_the_profile():
    """То же самое в геометрии: вердикт о паре точек не выключает профиль целиком.

    Счётчик `PROFILE_STRIKES` считает только отказы про сам запрос. Пока 2014 в них
    попадал, трёх адресов вне фида подряд хватало, чтобы у всего набора перестала
    строиться линия общественного транспорта: на «Юго-востоке» из сотни участков
    построилось два.
    """
    scenario = sc(
        [req(f"R{i}", window=("09:00", "09:30"), dur=55, at=(55.70 + 0.002 * i, 37.60))
         for i in range(1, 6)],
        [eng(f"C{i}", shift=("09:00", "18:00"), at=(55.70, 37.60), transport="car")
         for i in range(1, 6)],
    )
    result = plan(scenario, Algorithm.OPTIMIZED)

    class OutOfFeed(FakeOrs):
        """Первые четыре участка вне фида, пятый — обычный."""

        def __call__(self, url, body, headers, timeout):
            if "/directions/" in url and len(self.calls) < 4:
                self.calls.append((url, None))
                raise _verdict(2014, "PT exit point cannot be reached")()
            return super().__call__(url, body, headers, timeout)

    enriched = attach_route_geometry(result, client(OutOfFeed()))

    assert any(r.geometry_source == "ors" for r in enriched.routes), (
        "после отказов по конкретным адресам профиль должен остаться рабочим"
    )


def test_a_request_level_verdict_is_its_own_case():
    """«Нет такого профиля» (2003) — не граница фида и не оборванная связь.

    Результат тот же (пары уходят на координаты), а вывод третий: сервис отвечает,
    пересчитывать план бесполезно, чинить надо конфигурацию инстанса. Совет «смиритесь,
    адрес вне зоны фида» увёл бы ровно от той строки в `ors-config.yml`, которой всё
    лечится.
    """
    scenario = _public_transport_scenario()
    fake = FakeOrs(error=_verdict(2003, "Unable to find an appropriate routing profile"))
    travel = OrsTravelModel.for_scenario(scenario, client(fake), transit=True)

    text = " ".join(travel.warnings)
    assert "отклонил" in text
    assert "routing profile" in text
    assert "вне зоны действия фида" not in text
    assert "отказа сервиса" not in text


def test_transit_outage_is_not_reported_as_a_boundary_of_the_feed():
    """Лежащий сервис и Кашира дают одинаковые числа и противоположный вывод.

    В первом случае план станет точным сам собой, стоит поднять контейнер, и его надо
    пересчитать. Во втором пересчитывать нечего: адрес вне зоны действия фида не
    свяжется никогда. Одна строка на оба случая — это ровно та подсказка, которой
    диспетчер не может воспользоваться.
    """
    scenario = _public_transport_scenario()
    fake = FakeOrs(error=urllib.error.URLError("connection refused"))
    travel = OrsTravelModel.for_scenario(scenario, client(fake), transit=True)

    text = " ".join(travel.warnings)
    assert "отказа сервиса" in text
    assert "connection refused" in text
    assert "вне зоны действия фида" not in text


def test_empty_summary_is_not_a_free_ride():
    """Ответ без summary — «сервис не сказал, сколько ехать», а не «ехать ноль».

    Нули попали бы в кэш, то есть навсегда, и пара точек стала бы бесплатным
    переездом через весь город — причём в плане это выглядело бы как удача.
    """
    scenario = _public_transport_scenario()
    cache = RoutingCache()
    fake = FakeOrs(summary={})
    travel = OrsTravelModel.for_scenario(
        scenario, client(fake), cache=cache, transit=True
    )

    departure = scenario_departure(scenario)
    assert not cache.legs_of(transit_profile("public-transport", departure))
    assert any("без расстояния" in w for w in travel.warnings)

    from planner.travel import HaversineTravelModel

    a = scenario.engineers[0].start_point
    b = scenario.requests[0].point
    expected = HaversineTravelModel(scenario.settings).travel_minutes(
        a, b, TransportMode.PUBLIC_TRANSPORT
    )
    assert travel.travel_minutes(a, b, TransportMode.PUBLIC_TRANSPORT) == pytest.approx(expected)


def test_public_transport_geometry_is_still_drawn():
    """Матрица не берётся, а линия на карте — берётся: /directions расписания учитывает."""
    scenario = sc(
        [req("R1", window=("09:00", "17:00"), dur=30, at=(55.80, 37.75))],
        [eng("E1", shift=("09:00", "18:00"), at=(55.70, 37.60), transport="public_transport")],
    )
    fake = FakeOrs()
    api = client(fake)
    result = plan(scenario, Algorithm.OPTIMIZED, travel=OrsTravelModel.for_scenario(scenario, api))
    result = attach_route_geometry(result, api)

    assert any("/directions/public-transport" in url for url, _ in fake.calls)
    assert routes_by_engineer(result)["E1"].geometry


def test_service_outage_does_not_break_planning():
    """Главное требование к интеграции: сервис лежит — план всё равно считается."""
    scenario = two_point_scenario()
    fake = FakeOrs(error=urllib.error.URLError("connection refused"))
    travel = OrsTravelModel.for_scenario(scenario, client(fake))

    assert travel.warnings, "отказ сервиса должен попасть в предупреждения"
    result = plan(scenario, Algorithm.OPTIMIZED, travel=travel)
    assert result.metrics.assigned_count == 1

    from planner.travel import HaversineTravelModel

    expected = HaversineTravelModel(scenario.settings).travel_minutes(
        scenario.engineers[0].start_point, scenario.requests[0].point, TransportMode.CAR
    )
    assert routes_by_engineer(result)["E1"].visits[0].travel_minutes == pytest.approx(expected)


def test_ors_distances_reach_the_plan():
    """Смысл интеграции: числа сервиса доезжают до расписания без правок алгоритма."""
    scenario = two_point_scenario()
    travel = OrsTravelModel.for_scenario(scenario, client())
    result = plan(scenario, Algorithm.OPTIMIZED, travel=travel)

    visit = routes_by_engineer(result)["E1"].visits[0]
    assert visit.distance_km == pytest.approx(_km(0, 1))
    assert visit.travel_minutes == pytest.approx(
        _km(0, 1) + scenario.settings.overhead_minutes[TransportMode.CAR]
    )


# --------------------------------------------------------------------------
# Кэш
# --------------------------------------------------------------------------


def test_cache_round_trip(tmp_path):
    path = tmp_path / "routing.json"
    cache = RoutingCache(path)
    cache.put_leg("driving-car", A, B, 12.5, 30.0)
    assert cache.dirty
    cache.save()

    reloaded = RoutingCache(path)
    assert reloaded.get_leg("driving-car", A, B) == (12.5, 30.0)
    assert reloaded.get_leg("driving-car", B, A) is None, "направление потеряно"
    assert not reloaded.dirty


def test_cache_is_filled_by_the_first_run_and_reused_by_the_second(tmp_path):
    """Второй расчёт в сервис не ходит — это и есть офлайн-воспроизводимость."""
    scenario = two_point_scenario()
    path = tmp_path / "routing.json"

    first = FakeOrs()
    cache = RoutingCache(path)
    OrsTravelModel.for_scenario(scenario, client(first), cache=cache)
    cache.save()
    assert len(first.calls) == 1

    second = FakeOrs()
    reloaded = RoutingCache(path)
    travel = OrsTravelModel.for_scenario(scenario, client(second), cache=reloaded)
    assert second.calls == [], "матрица перезапрошена, хотя она уже в кэше"
    assert travel.distance_km(
        scenario.engineers[0].start_point, scenario.requests[0].point, TransportMode.CAR
    ) == pytest.approx(_km(0, 1))


def test_setup_routing_works_offline_from_cache(tmp_path):
    scenario = two_point_scenario()
    path = tmp_path / "routing.json"
    cache = RoutingCache(path)
    OrsTravelModel.for_scenario(scenario, client(), cache=cache)
    cache.save()

    routing = setup_routing(scenario, url=None, cache_path=path)
    assert routing.enabled
    assert routing.client is None
    assert "кэш" in " ".join(routing.notes)


def test_setup_routing_without_service_and_cache_keeps_the_default_model(tmp_path):
    routing = setup_routing(two_point_scenario(), url=None, cache_path=tmp_path / "нет.json")
    assert routing.travel is None, "без сервиса и кэша расчёт должен идти по координатам"
    assert routing.save() is None


# --------------------------------------------------------------------------
# Геометрия маршрута
# --------------------------------------------------------------------------


def three_stop_plan(travel=None):
    scenario = sc(
        [
            req("R1", window=("09:00", "17:00"), dur=30, at=(55.75, 37.65)),
            req("R2", window=("09:00", "17:00"), dur=30, at=(55.80, 37.70)),
        ],
        [eng("E1", shift=("09:00", "18:00"), at=(55.70, 37.60), transport="car")],
    )
    return scenario, plan(scenario, Algorithm.OPTIMIZED, travel=travel)


def test_attach_geometry_fills_the_route_line():
    _scenario, result = three_stop_plan()
    enriched = attach_route_geometry(result, client())
    route = enriched.routes[0]

    assert route.geometry_source == "ors"
    # Заглушка добавляет по одной промежуточной точке на участок: 3 опорных -> 5 точек.
    assert len(route.geometry) == 5
    assert route.geometry[0] == route.start_point


def test_visit_geometry_ranges_slice_the_route_line():
    """Границы участков — индексы в общей линии, а не копия координат."""
    _scenario, result = three_stop_plan()
    route = attach_route_geometry(result, client()).routes[0]

    previous_end = 0
    for visit in route.visits:
        start, end = visit.geometry_range
        assert start == previous_end, "участки должны идти встык"
        assert route.geometry[end] == visit.to_point
        previous_end = end
    assert previous_end == len(route.geometry) - 1


def test_attach_geometry_survives_service_failure():
    _scenario, result = three_stop_plan()
    fake = FakeOrs(error=urllib.error.URLError("down"))
    enriched = attach_route_geometry(result, client(fake))

    route = enriched.routes[0]
    assert route.geometry == ()
    assert route.geometry_source == "straight"
    assert any("геометрия" in w for w in enriched.warnings)


def test_attach_geometry_uses_cache_without_the_service(tmp_path):
    _scenario, result = three_stop_plan()
    cache = RoutingCache(tmp_path / "routing.json")
    attach_route_geometry(result, client(), cache=cache)

    offline = attach_route_geometry(result, None, cache=cache)
    assert offline.routes[0].geometry_source == "ors"


def test_plan_json_carries_geometry_for_the_frontend():
    """Интерфейсу должно хватать одного `to_dict()` — без доработок на стороне фронта."""
    _scenario, result = three_stop_plan()
    payload = attach_route_geometry(result, client()).to_dict()
    route = payload["routes"][0]

    assert route["geometry_source"] == "ors"
    assert route["geometry"][0] == [route["start_point"]["lon"], route["start_point"]["lat"]]
    assert route["visits"][0]["geometry_range"] == [0, 2]
    json.dumps(payload, ensure_ascii=False)  # сериализуемо без кастомного энкодера


def test_geometry_is_absent_until_it_is_attached():
    """Ядро остаётся офлайновым: `plan()` сам в сеть не ходит."""
    _scenario, result = three_stop_plan()
    assert result.routes[0].geometry == ()
    assert result.routes[0].geometry_source == "straight"
    assert result.routes[0].visits[0].geometry_range is None


def test_broken_cache_file_is_treated_as_empty(tmp_path):
    """Недописанный кэш (прервали прогрев) — пустой кэш, а не падение расчёта."""
    path = tmp_path / "routing.json"
    path.write_text('{"version": 1, "legs": {"driving-car": {"55.7', encoding="utf-8")
    cache = RoutingCache(path)
    assert cache.stats()["legs"] == 0
    assert setup_routing(two_point_scenario(), url=None, cache_path=path).travel is None


def test_same_address_leg_is_not_asked_from_the_service():
    """Заявки по одному адресу дают участок нулевой длины, и сервис о нём не спрашивают.

    Регрессия живого прогона: три заявки в Кашире на Кржижановского, 5/1–5/3, геокодер
    положил в одну точку. Общественный транспорт отвечал на участок «из точки в неё же»
    HTTP 500, пеший и автомобильный профили — ответом без линии, и каждый такой отказ
    шёл в счётчик, выключающий линии профилю целиком.
    """
    scenario = sc(
        [
            req("R1", window=("09:00", "10:00"), dur=30, at=(55.75, 37.65)),
            req("R2", window=("11:00", "12:00"), dur=30, at=(55.75, 37.65)),
        ],
        [eng("E1", shift=("09:00", "18:00"), at=(55.70, 37.60), transport="car")],
    )
    result = plan(scenario, Algorithm.OPTIMIZED)
    fake = FakeOrs()
    route = attach_route_geometry(result, client(fake)).routes[0]

    assert [v.request_id for v in route.visits] == ["R1", "R2"]
    assert len(fake.calls) == 1, "участок между одинаковыми точками ушёл в сервис"
    assert route.geometry_source == "ors"
    start, end = route.visits[1].geometry_range
    assert all(point == route.visits[1].to_point for point in route.geometry[start:end + 1])


def test_geometry_failure_of_one_profile_does_not_disable_the_others():
    """Несобранный профиль гасит только свои маршруты. Регрессия живого прогона:
    общий счётчик отказов выключал геометрию всему плану из-за пеших инженеров."""
    # Окна узкие и одновременные: один инженер физически берёт одну заявку,
    # поэтому маршруты получают и пешеходы, и автомобилист.
    scenario = sc(
        [req(f"R{i}", window=("09:00", "09:30"), dur=55, at=(55.70 + 0.002 * i, 37.60))
         for i in range(1, 7)],
        [eng(f"W{i}", shift=("09:00", "18:00"), at=(55.70, 37.60), transport="walking")
         for i in range(1, 6)]
        + [eng("C1", shift=("09:00", "18:00"), at=(55.70, 37.60), transport="car")],
    )
    result = plan(scenario, Algorithm.OPTIMIZED)

    class OnlyCar(FakeOrs):
        def __call__(self, url, body, headers, timeout):
            if "foot-walking" in url:
                raise urllib.error.HTTPError(url, 404, "profile not found", {}, None)
            return super().__call__(url, body, headers, timeout)

    enriched = attach_route_geometry(result, client(OnlyCar()))
    by_mode = {r.transport_mode: r.geometry_source for r in enriched.routes if r.visits}
    assert by_mode.get(TransportMode.CAR) == "ors", "автомобильный маршрут остался без линии"
    assert by_mode.get(TransportMode.WALKING) == "straight"


def test_geometry_legs_are_reused_by_a_different_plan(tmp_path):
    """Ключ по участкам переживает перестановку визитов.

    Регрессия замысла: ключ по маршруту целиком делал кэш бесполезным ровно там, где он
    нужнее всего — базовый и оптимизированный планы отличаются порядком объезда, и ни
    одна линия между ними не переиспользовалась."""
    _scenario, result = three_stop_plan()
    cache = RoutingCache(tmp_path / "routing.json")
    attach_route_geometry(result, client(), cache=cache)

    # Тот же набор точек, но маршрут другой: инженер стартует из бывшей первой заявки.
    other = sc(
        [req("R2", window=("09:00", "17:00"), dur=30, at=(55.80, 37.70))],
        [eng("E2", shift=("09:00", "18:00"), at=(55.75, 37.65), transport="car")],
    )
    offline = attach_route_geometry(plan(other, Algorithm.OPTIMIZED), None, cache=cache)

    assert offline.routes[0].geometry_source == "ors", "участок из кэша не подошёл"


def test_one_broken_leg_leaves_the_rest_of_the_line_intact():
    """Непостроенный участок стоит участка, а не всего маршрута.

    Так ведёт себя адрес за границей покрытия фида (Кашира): пара точек не связывается
    никогда, но остальные участки того же маршрута строятся штатно."""
    _scenario, result = three_stop_plan()
    broken = (55.80, 37.70)

    class BrokenLeg(FakeOrs):
        def __call__(self, url, body, headers, timeout):
            payload = json.loads(body.decode("utf-8"))
            if "/directions/" in url and [broken[1], broken[0]] in payload["coordinates"]:
                self.calls.append((url, payload))
                raise urllib.error.HTTPError(
                    url, 404, "not found", {},
                    _body('{"error": {"code": 2015, "message": "Route could not be found"}}'),
                )
            return super().__call__(url, body, headers, timeout)

    route = attach_route_geometry(result, client(BrokenLeg())).routes[0]

    assert route.geometry_source == "mixed"
    first, second = route.visits
    # Первый участок настоящий (заглушка даёт промежуточную точку), второй — прямая.
    assert second.geometry_range[1] - second.geometry_range[0] == 1
    assert first.geometry_range[1] > first.geometry_range[0] + 1
    assert route.geometry[-1] == second.to_point, "линия должна доходить до последней точки"


def test_unroutable_pairs_do_not_disable_the_whole_profile():
    """Код 2015 — вердикт о паре точек, а не поломка профиля.

    Иначе несколько адресов вне покрытия подряд выключали бы геометрию всем остальным
    маршрутам того же профиля."""
    scenario = sc(
        [req(f"R{i}", window=("09:00", "09:30"), dur=55, at=(55.70 + 0.002 * i, 37.60))
         for i in range(1, 6)],
        [eng(f"C{i}", shift=("09:00", "18:00"), at=(55.70, 37.60), transport="car")
         for i in range(1, 6)],
    )
    result = plan(scenario, Algorithm.OPTIMIZED)

    class FarAway(FakeOrs):
        """Первые четыре участка не строятся, пятый — обычный."""

        def __call__(self, url, body, headers, timeout):
            if "/directions/" in url and len(self.calls) < 4:
                self.calls.append((url, None))
                raise urllib.error.HTTPError(
                    url, 404, "not found", {},
                    _body('{"error": {"code": 2015, "message": "Route could not be found"}}'),
                )
            return super().__call__(url, body, headers, timeout)

    fake = FarAway()
    enriched = attach_route_geometry(result, client(fake))
    built = [r for r in enriched.routes if r.geometry_source == "ors"]

    assert built, "после отказов по конкретным точкам профиль должен остаться рабочим"


def test_old_cache_keeps_the_matrix_and_forgets_the_geometry(tmp_path):
    """Смена формата геометрии не должна стоить пересчёта матрицы.

    Участков в живом кэше десятки тысяч, и повторный поход за ними — часы работы
    сервиса; геометрия же восстанавливается одним прогревом."""
    path = tmp_path / "routing.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "legs": {"driving-car": {f"{point_key(A)}>{point_key(B)}": [1.5, 3.0]}},
                "geometry": {"driving-car": {f"{point_key(A)}|{point_key(B)}": {"coordinates": []}}},
            }
        ),
        encoding="utf-8",
    )
    cache = RoutingCache(path)

    assert cache.get_leg("driving-car", A, B) == (1.5, 3.0)
    assert cache.stats()["geometry"] == 0
    assert cache.dirty, "кэш должен перезаписаться, чтобы мёртвая геометрия ушла из файла"


def test_matrix_block_is_halved_when_the_instance_refuses_the_request():
    """Регрессия живого прогона: бюджет обхода графа тратится на запрос целиком, и на
    пешем профиле он кончается на нескольких десятках точек. Размер блока не угадывается
    заранее — он нащупывается делением пополам."""

    class NodeBudget(FakeOrs):
        """Отвечает только на запросы не более чем с двумя источниками."""

        def __call__(self, url, body, headers, timeout):
            payload = json.loads(body.decode("utf-8"))
            if "/matrix/" in url and len(payload.get("sources") or payload["locations"]) > 2:
                self.calls.append((url, payload))
                raise urllib.error.HTTPError(
                    url, 500, "Internal Server Error", {},
                    _body('{"error": {"code": 6020, "message": "Search exceeds the limit of visited nodes."}}'),
                )
            return super().__call__(url, body, headers, timeout)

    points = [A, B, C, gp((55.85, 37.75)), gp((55.90, 37.80))]
    fake = NodeBudget()
    table = fetch_matrix(client(fake, max_routes_per_request=10_000), "driving-car", points)

    assert len(table) == 20, "матрица собралась не полностью"
    assert table[(point_key(C), point_key(A))][0] == pytest.approx(_km(2, 0))
    assert any(len(p.get("sources") or []) <= 2 for _u, p in fake.calls)


def test_learned_block_size_is_reused_by_the_next_matrix():
    """Нащупанный предел запоминается: следующая матрица не повторяет отказы, каждый из
    которых у пешего профиля ORS считает 13 с и держит в heap миллионы узлов."""

    class NodeBudget(FakeOrs):
        def __call__(self, url, body, headers, timeout):
            payload = json.loads(body.decode("utf-8"))
            if "/matrix/" in url and len(payload.get("sources") or payload["locations"]) > 2:
                self.calls.append((url, payload))
                raise urllib.error.HTTPError(
                    url, 500, "Internal Server Error", {},
                    _body('{"error": {"code": 6020, "message": "Search exceeds the limit of visited nodes."}}'),
                )
            return super().__call__(url, body, headers, timeout)

    points = [A, B, C, gp((55.85, 37.75)), gp((55.90, 37.80))]
    fake = NodeBudget()
    shared = client(fake, max_routes_per_request=10_000)
    fetch_matrix(shared, "driving-car", points)
    fake.calls.clear()
    again = fetch_matrix(shared, "driving-car", points)

    assert len(again) == 20
    assert all(len(p["sources"]) <= 2 for _u, p in fake.calls), "отказы повторились"


def test_search_profiles_start_with_a_small_block():
    """Пеший и велосипедный профили без contraction hierarchies: 250 источников в
    запросе ORS всё равно не примет, поэтому блок сразу маленький."""
    fake = FakeOrs()
    points = [gp((55.70 + i / 100, 37.60)) for i in range(12)]
    table = fetch_matrix(client(fake, max_routes_per_request=10_000), "foot-walking", points)

    assert len(table) == 12 * 11
    assert max(len(p["sources"]) for _u, p in fake.calls) == SEARCH_BLOCK_ROWS


def test_deterministic_service_verdict_is_not_retried():
    """Ошибка с кодом ORS — это вердикт по запросу, а не сбой связи. Повтор тех же
    данных даст тот же ответ, и три таймаута подряд здесь ничего не спасают."""

    class Verdict(FakeOrs):
        def __call__(self, url, body, headers, timeout):
            self.calls.append((url, json.loads(body.decode("utf-8"))))
            raise urllib.error.HTTPError(
                url, 500, "Internal Server Error", {},
                _body('{"error": {"code": 6020, "message": "nope"}}'),
            )

    fake = Verdict()
    with pytest.raises(OrsError) as exc:
        OrsClient("http://ors.test/ors", transport=fake, retries=3).matrix("driving-car", [A, B])
    assert exc.value.code == 6020
    assert len(fake.calls) == 1, "детерминированный отказ сервиса повторялся"


# --------------------------------------------------------------------------
# Ответ 200 неожиданной формы
#
# Контракт модуля обещает ровно две вещи: откат на расчёт по координатам (или на
# прямую линию) и предупреждение в плане. Ошибка сети его выполняет — а ответ с кодом
# 200, в котором сервис написал что-то своё, раньше выполнял иначе: `ValueError` и
# `IndexError` доходили до вызывающей стороны и роняли уже посчитанный план.
# --------------------------------------------------------------------------


def test_non_numeric_distance_does_not_break_the_plan():
    """`{"distance": "нет"}` приходит с кодом 200 — и это отказ участка, не падение."""
    _scenario, result = three_stop_plan()
    fake = FakeOrs(summary={"distance": "нет", "duration": "нет"})

    route = attach_route_geometry(result, client(fake)).routes[0]

    # Линия к summary отношения не имеет: она пришла и обязана доехать до карты.
    assert route.geometry_source == "ors"
    assert route.geometry[-1] == route.visits[-1].to_point


def test_unparsable_geometry_falls_back_to_a_straight_line():
    """Координата, которая не число, — это отсутствие линии, а не повод уронить план."""
    _scenario, result = three_stop_plan()
    enriched = attach_route_geometry(result, client(FakeOrs(bad_geometry=True)))
    route = enriched.routes[0]

    assert route.geometry_source == "straight"
    assert any("неразбираемая геометрия" in w for w in enriched.warnings)
    assert route.geometry == (), "прямую рисует сам фронт по polyline, подделывать её не надо"


def test_any_unexpected_shape_of_a_200_answer_is_still_only_a_failed_leg():
    """Разобрать все формы чужого JSON заранее нельзя — уронить план ими тоже нельзя.

    Поэтому у запроса участка стоит широкий перехват: ответ, на котором спотыкается
    сам разбор, кончается тем же, чем ошибка сети, — прямой и строкой в `warnings`.
    """
    _scenario, result = three_stop_plan()

    class Nonsense(FakeOrs):
        def __call__(self, url, body, headers, timeout):
            self.calls.append((url, json.loads(body.decode("utf-8"))))
            return json.dumps({"features": {"нет": "списка"}}).encode("utf-8")

    enriched = attach_route_geometry(result, client(Nonsense()))

    assert enriched.routes[0].geometry_source == "straight"
    assert any("неразбираемый ответ сервиса" in w for w in enriched.warnings)


def test_short_matrix_row_leaves_the_pair_to_the_coordinates():
    """Ряд короче матрицы — это несчитанные пары, а не `IndexError` посреди сборки."""
    points = [A, B, C]
    table = fetch_matrix(client(FakeOrs(row_width=1)), "driving-car", points)

    assert (point_key(B), point_key(A)) in table, "то, что пришло, должно попасть в матрицу"
    assert (point_key(A), point_key(B)) not in table
    assert (point_key(A), point_key(C)) not in table


def test_matrix_without_all_the_rows_is_a_service_failure():
    """Строк меньше, чем источников, — разложить такой ответ по парам невозможно.

    Какие именно источники пропущены, ответ не сообщает, поэтому раскладка стала бы
    угадыванием. Ошибка уходит наверх, где режим честно откатывается на координаты.
    """
    with pytest.raises(OrsError):
        fetch_matrix(client(FakeOrs(rows_dropped=1)), "driving-car", [A, B, C])


def test_broken_matrix_leaves_the_mode_on_coordinates_with_a_warning():
    """Тот же ответ, но на уровне сценария: план считается, предупреждение есть."""
    scenario = two_point_scenario()
    travel = OrsTravelModel.for_scenario(scenario, client(FakeOrs(rows_dropped=1)))

    assert travel.warnings
    assert not travel.has_matrix
    result = plan(scenario, Algorithm.OPTIMIZED, travel=travel)
    assert result.metrics.assigned_count == 1


# --------------------------------------------------------------------------
# Дата плана и раздел кэша расписаний
#
# Раздел кэша расписаний включает дату (иначе утренние числа выдавали бы себя за
# вечерние). Отсюда обратная беда: план на другой день не находит в кэше НИЧЕГО,
# внешне ничем не отличаясь — меняются только числа. Поэтому тихого исхода здесь нет
# ни одного, и это проверяется.
# --------------------------------------------------------------------------


def _warm_transit_cache(scenario, when: str) -> RoutingCache:
    """Кэш, прогретый расписаниями на произвольный момент."""
    cache = RoutingCache()
    OrsTravelModel.for_scenario(
        scenario, client(), cache=cache, transit=True, departure=when
    )
    assert cache.legs_of(transit_profile("public-transport", when))
    return cache


def test_same_weekday_and_hour_is_reused_as_a_stated_approximation():
    """17.08.2026 и 21.09.2026 — оба понедельника, и разница между ними несравнимо
    меньше, чем между поездкой по расписанию и расчётом по прямой.

    Но подмена, о которой не сказали, — это не приближение, а ошибка: обе даты обязаны
    быть названы в предупреждении.
    """
    scenario = _public_transport_scenario()          # план на 2026-09-21, понедельник
    other_monday = departure_moment(
        scenario.date - timedelta(days=35), scenario.settings.timezone_offset_hours
    )
    cache = _warm_transit_cache(scenario, other_monday)

    travel = OrsTravelModel.for_scenario(scenario, client(), cache=cache, transit=False)

    a = scenario.engineers[0].start_point
    b = scenario.requests[0].point
    overhead = scenario.settings.overhead_minutes[TransportMode.PUBLIC_TRANSPORT]
    assert travel.travel_minutes(a, b, TransportMode.PUBLIC_TRANSPORT) == pytest.approx(
        30.0 + overhead
    ), "числа должны остаться расписанием, а не съехать на прямую"

    text = " ".join(travel.warnings)
    assert "приближение" in text
    assert f"{scenario.date:%d.%m.%Y}" in text, "не названа дата плана"
    assert f"{(scenario.date - timedelta(days=35)):%d.%m.%Y}" in text, "не названа дата кэша"


def test_schedule_from_another_weekday_is_not_passed_off_as_this_one():
    """Вторник вместо понедельника — уже другое расписание, и брать его нельзя."""
    scenario = _public_transport_scenario()
    tuesday = departure_moment(
        scenario.date - timedelta(days=34), scenario.settings.timezone_offset_hours
    )
    cache = _warm_transit_cache(scenario, tuesday)

    travel = OrsTravelModel.for_scenario(scenario, client(), cache=cache, transit=False)

    from planner.travel import HaversineTravelModel

    a = scenario.engineers[0].start_point
    b = scenario.requests[0].point
    expected = HaversineTravelModel(scenario.settings).travel_minutes(
        a, b, TransportMode.PUBLIC_TRANSPORT
    )
    assert travel.travel_minutes(a, b, TransportMode.PUBLIC_TRANSPORT) == pytest.approx(expected)

    text = " ".join(travel.warnings)
    assert "другой день недели" in text
    assert f"{(scenario.date - timedelta(days=34)):%d.%m.%Y}" in text, "не сказано, что в кэше"
    assert "--date" in text, "совет по прогреву без даты бесполезен ровно в этом случае"


def test_offline_plan_on_another_date_never_stays_silent():
    """Тот же случай офлайн (`setup_routing` без адреса сервиса) — раньше молчал."""
    scenario = _public_transport_scenario()
    cache = _warm_transit_cache(
        scenario,
        departure_moment(
            scenario.date - timedelta(days=34), scenario.settings.timezone_offset_hours
        ),
    )
    path = Path(tempfile.mkdtemp()) / "routing.json"
    cache.save(path)

    routing = setup_routing(scenario, url=None, cache_path=path)
    result = routing.attach(plan(scenario, Algorithm.OPTIMIZED, travel=routing.travel))

    assert any("расписаний" in w for w in result.warnings)


def test_report_names_the_mode_and_the_moment_of_the_schedule():
    """«Посчитаны по координатам» без режима и без даты не отвечает ни на один вопрос."""
    scenario = _public_transport_scenario()
    travel = OrsTravelModel.for_scenario(scenario, client(), transit=False)
    travel.both(
        scenario.engineers[0].start_point,
        scenario.requests[0].point,
        TransportMode.PUBLIC_TRANSPORT,
    )
    report = " ".join(travel.report())

    assert "общественный транспорт" in report
    assert "по расписанию на" in report
    assert f"{scenario.date:%d.%m.%Y}" in report
    assert "понедельник" in report

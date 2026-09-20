# -*- coding: utf-8 -*-
"""Реальная маршрутизация по улицам: openrouteservice (OSM, self-hosted).

Зачем этот модуль
-----------------
Базовая модель перемещения (`travel.HaversineTravelModel`) считает расстояние по прямой
и умножает на коэффициент извилистости. ТЗ это разрешает, но у допущения есть цена:
коэффициент один на весь регион, а реальная сеть неоднородна — река, железная дорога,
МКАД и односторонние улицы дают промах в разы на отдельных парах точек. И главное:
по прямой нельзя нарисовать маршрут на карте, а интерфейсу нужна именно линия по улицам.

openrouteservice закрывает обе задачи одним сервисом:

* `POST /v2/matrix/{profile}`          — матрица расстояний и времён по УЛИЦАМ;
* `POST /v2/directions/{profile}/geojson` — геометрия маршрута (LineString) для карты.

Лицензия GPL-3.0/LGPL-3.0, разворачивается своим docker-compose (см. `deploy/ors/`),
ключей и внешней сети не требует, данные — OpenStreetMap. Профили передвижения
отображаются на справочник ТЗ один в один (см. `DEFAULT_PROFILES`).

Границы ответственности
-----------------------
Алгоритм планирования НЕ меняется. Модуль поставляет две вещи:

1. `OrsTravelModel` — реализация протокола `TravelModel`, то есть подстановка
   в `plan(scenario, travel=...)`. Всё остальное ядро её не отличает от расчёта
   по координатам;
2. `attach_route_geometry` — постобработка готового плана: дописывает в каждый
   маршрут настоящую линию по улицам, не трогая ни назначения, ни расписание.

Отказоустойчивость
------------------
Сервис внешний, значит он может быть выключен, перегружен или не знать нужного профиля.
Ни один такой случай не имеет права уронить расчёт: на неизвестной паре точек и на любой
ошибке сети модель молча откатывается на расчёт по координатам, а факт отката попадает
в `warnings`. План всегда строится — вопрос только в точности чисел.

Воспроизводимость
-----------------
`RoutingCache` хранит ответы сервиса в JSON рядом с `data/geocache.json`. Смысл тот же,
что у кэша геокодера: один раз сходили в сервис, закоммитили результат — дальше расчёт
идёт офлайн, детерминированно и без поднятого контейнера (см. `tools/ors_prefetch.py`).
"""

from __future__ import annotations

import json
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .enums import TransportMode
from .models import Engineer, GeoPoint, Scenario, Settings
from .result import PlanResult, RouteResult, Visit
from .travel import HaversineTravelModel, TravelModel

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_PROFILES",
    "DEFAULT_CACHE_PATH",
    "GEOMETRY_ONLY_PROFILES",
    "OrsError",
    "OrsClient",
    "RoutingCache",
    "OrsTravelModel",
    "Routing",
    "setup_routing",
    "attach_route_geometry",
    "collect_points",
    "scenario_modes",
]

DEFAULT_BASE_URL = "http://localhost:8080/ors"
"""Адрес локального контейнера из `deploy/ors/docker-compose.yml`."""

DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "routing_cache.json"
"""Кэш ответов сервиса рядом с кэшем геокодера — по той же причине и с той же ролью."""

DEFAULT_PROFILES: dict[TransportMode, str] = {
    TransportMode.CAR: "driving-car",
    TransportMode.WALKING: "foot-walking",
    TransportMode.BICYCLE: "cycling-regular",
    TransportMode.PUBLIC_TRANSPORT: "public-transport",
}
"""Справочник ТЗ п. 2.4.1 → профили openrouteservice.

`public-transport` в ORS требует отдельного графа, собранного из GTFS-фида города, и
на многих инстансах не отвечает на `/matrix`. Это не ломает расчёт: режим, по которому
сервис не ответил, целиком уходит в расчёт по координатам, о чём пишется предупреждение.
Проверить, что умеет конкретный инстанс, можно `python tools/ors_check.py`.
"""

GEOMETRY_ONLY_PROFILES: frozenset[str] = frozenset({"public-transport"})
"""Профили, чью матрицу брать нельзя, а геометрию — можно.

У `/v2/matrix` нет параметра времени отправления, поэтому расписания в матрицу не
попадают: ORS отвечает на неё пешей доступностью. Внешне это неотличимо от рабочего
ответа — приходят правдоподобные числа, просто не те. Замер на нашем инстансе, пара
Медведково — Ясенево: матрица 428 мин, пешком 427 мин, реальный маршрут по расписанию
150 мин.

На двенадцати парах реальных адресов средняя ошибка против маршрута по расписанию:
расчёт по координатам (18 км/ч + 10 мин) — 8 минут, матрица — 86 минут. Поэтому время
и расстояние для общественного транспорта остаются на расчёте по координатам.

`/v2/directions` расписания учитывает, так что линия на карте строится настоящая —
`attach_route_geometry` этот список не смотрит.
"""


class OrsError(RuntimeError):
    """Отказ маршрутного сервиса.

    Исключение всегда ловится на границе модуля: расчёт плана не должен падать
    из-за того, что контейнер не поднят.

    `code` — код ошибки самого ORS, если он был в теле ответа. Его наличие означает,
    что сервис жив и вынес вердикт по запросу; повторять такой запрос бессмысленно,
    а вот изменить его (например, уменьшить блок матрицы) — осмысленно.
    """

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def point_key(point: GeoPoint) -> str:
    """Ключ точки для матриц и кэша. Шесть знаков — это ~11 см, точнее геокодера."""
    return f"{point.lat:.6f},{point.lon:.6f}"


# --------------------------------------------------------------------------------------
# Клиент
# --------------------------------------------------------------------------------------

Transport = Callable[[str, bytes, Mapping[str, str], float], bytes]
"""Функция доставки запроса. Вынесена параметром, чтобы тесты работали без сети."""


def _urllib_transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class OrsClient:
    """Тонкий клиент openrouteservice на стандартной библиотеке.

    Зависимостей нет сознательно: `planner` обязан ставиться и работать на голом Python.
    """

    __slots__ = (
        "base_url",
        "api_key",
        "timeout",
        "retries",
        "profiles",
        "max_routes_per_request",
        "_transport",
    )

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        api_key: str | None = None,
        timeout: float = 60.0,
        retries: int = 2,
        profiles: Mapping[TransportMode, str] | None = None,
        max_routes_per_request: int = 2500,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retries = max(0, retries)
        self.profiles = dict(DEFAULT_PROFILES if profiles is None else profiles)
        self.max_routes_per_request = max(1, max_routes_per_request)
        """Предел `ors.endpoints.matrix.maximum_routes` инстанса (по умолчанию 2500).

        Больше этого числа пар в одном запросе сервис не примет, поэтому матрица
        режется на блоки по источникам. Для наших наборов (~100 точек = 10 000 пар)
        либо поднимается лимит в конфиге, либо работает нарезка — оба пути рабочие.
        """
        self._transport = transport or _urllib_transport

    # -- профили --

    def profile_of(self, mode: TransportMode) -> str:
        profile = self.profiles.get(mode)
        if profile is None:
            raise OrsError(f"для способа передвижения «{mode}» не задан профиль ORS")
        return profile

    # -- транспорт --

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, application/geo+json",
            "User-Agent": "LCT2026-BeelineRoutePlanner/1.0",
        }
        if self.api_key:
            headers["Authorization"] = self.api_key

        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                raw = self._transport(url, body, headers, self.timeout)
                return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                # 4xx — наша ошибка (нет профиля, превышен лимит): повтор не поможет.
                # 5xx с кодом ORS в теле — тоже вердикт сервиса, а не сбой связи:
                # «не смог посчитать матрицу» повторится слово в слово, и ждать
                # три таймаута ради этого незачем. Повторяем только «немые» 5xx.
                detail, code = _http_error_detail(exc)
                error = OrsError(f"{url}: HTTP {exc.code} — {detail}", code)
                if 400 <= exc.code < 500 or code is not None:
                    raise error from exc
                last = error
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = OrsError(f"{url}: сервис недоступен — {exc}")
            except json.JSONDecodeError as exc:
                last = OrsError(f"{url}: неразбираемый ответ — {exc}")
            if attempt < self.retries:
                _time.sleep(0.5 * (attempt + 1))
        raise last if last is not None else OrsError(f"{url}: неизвестная ошибка")

    # -- эндпойнты --

    def matrix(
        self,
        profile: str,
        locations: Sequence[GeoPoint],
        *,
        sources: Sequence[int] | None = None,
        destinations: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        """`POST /v2/matrix/{profile}`: расстояния (км) и времена (с) по улицам."""
        payload: dict[str, Any] = {
            "locations": [[p.lon, p.lat] for p in locations],
            "metrics": ["distance", "duration"],
            "units": "km",
        }
        if sources is not None:
            payload["sources"] = list(sources)
        if destinations is not None:
            payload["destinations"] = list(destinations)
        return self._post(f"/v2/matrix/{urllib.parse.quote(profile)}", payload)

    def directions(
        self, profile: str, coordinates: Sequence[GeoPoint], **options: Any
    ) -> dict[str, Any]:
        """`POST /v2/directions/{profile}/geojson`: геометрия маршрута для карты."""
        if len(coordinates) < 2:
            raise OrsError("для построения маршрута нужно минимум две точки")
        payload: dict[str, Any] = {
            "coordinates": [[p.lon, p.lat] for p in coordinates],
            # Текстовые подсказки («через 200 м направо») карте не нужны и весят больше
            # самой линии. Упрощение геометрии — тоже про вес: на городском масштабе
            # разница не видна, а JSON плана меньше в несколько раз.
            "instructions": False,
            "geometry": True,
            "geometry_simplify": True,
        }
        payload.update(options)
        return self._post(f"/v2/directions/{urllib.parse.quote(profile)}/geojson", payload)


def _http_error_detail(exc: urllib.error.HTTPError) -> tuple[str, int | None]:
    """Причина и код ошибки из тела ответа ORS (`{"error": {"code": …, "message": …}}`)."""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:  # pragma: no cover - тело может быть пустым или не JSON
        return (exc.reason if isinstance(exc.reason, str) else str(exc.reason)), None
    error = payload.get("error")
    if isinstance(error, Mapping):
        code = error.get("code")
        return str(error.get("message", error)), (int(code) if isinstance(code, int) else None)
    return str(error or payload), None


# --------------------------------------------------------------------------------------
# Кэш ответов
# --------------------------------------------------------------------------------------


class RoutingCache:
    """JSON-кэш ответов маршрутного сервиса: участки и геометрия.

    Хранится «сырое»: расстояние в км и ЧИСТОЕ время в пути в минутах, без парковки и
    подхода. Сопутствующие затраты — это параметр модели (`Settings.overhead_minutes`),
    и менять их нужно без похода в сервис заново.
    """

    __slots__ = ("path", "_legs", "_geometry", "_dirty")

    VERSION = 2
    """Версия 2 хранит геометрию участками, версия 1 хранила её маршрутом целиком.

    Формат матрицы (`legs`) при этом не менялся, поэтому кэш версии 1 читается
    частично: участки берутся как есть, геометрия отбрасывается. Иначе смена ключа
    стоила бы 38 тысяч заново посчитанных пар — а они дороже геометрии на порядок.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._legs: dict[str, dict[str, list[float]]] = {}
        self._geometry: dict[str, dict[str, list[list[float]]]] = {}
        self._dirty = False
        if self.path is not None and self.path.exists():
            self._load()

    def _load(self) -> None:
        assert self.path is not None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Битый или недописанный файл — это пустой кэш, а не отказ в расчёте.
            # Следующий прогон с сервисом перезапишет его целиком.
            return
        if not isinstance(payload, Mapping):
            return
        version = int(payload.get("version", 0))
        if version not in (1, self.VERSION):
            # Формат сменился непонятно как — кэш игнорируется, а не «чинится» догадками.
            return
        self._legs = payload.get("legs", {}) or {}
        if version == self.VERSION:
            self._geometry = payload.get("geometry", {}) or {}
        else:
            # Ключи старой геометрии несовместимы с новыми и просто не совпадут ни с
            # чем, поэтому их не переносим. Файл помечается на перезапись, чтобы мёртвые
            # мегабайты ушли при первом же сохранении.
            self._dirty = True

    # -- участки --

    @staticmethod
    def _leg_key(a: GeoPoint, b: GeoPoint) -> str:
        # Направление сохраняется: односторонние улицы делают A→B и B→A разными.
        return f"{point_key(a)}>{point_key(b)}"

    def get_leg(self, profile: str, a: GeoPoint, b: GeoPoint) -> tuple[float, float] | None:
        value = self._legs.get(profile, {}).get(self._leg_key(a, b))
        if value is None:
            return None
        return float(value[0]), float(value[1])

    def put_leg(self, profile: str, a: GeoPoint, b: GeoPoint, km: float, minutes: float) -> None:
        self._legs.setdefault(profile, {})[self._leg_key(a, b)] = [
            round(km, 4),
            round(minutes, 3),
        ]
        self._dirty = True

    def legs_of(self, profile: str) -> dict[tuple[str, str], tuple[float, float]]:
        """Все известные участки профиля в виде, готовом для `OrsTravelModel`."""
        table: dict[tuple[str, str], tuple[float, float]] = {}
        for key, value in self._legs.get(profile, {}).items():
            ka, _, kb = key.partition(">")
            table[(ka, kb)] = (float(value[0]), float(value[1]))
        return table

    # -- геометрия --
    #
    # Хранится по УЧАСТКАМ, тем же ключом «откуда>куда», что и матрица.
    #
    # Экономии на запросах это не даёт — наоборот: холодный прогрев трёх наших регионов
    # по двум планам стоил 55 запросов ключом по маршруту и 245 ключом по участкам.
    # Платим за другое.
    #
    # 1. Непостроенный участок теперь стоит участка, а не маршрута. Раньше `directions`
    #    получал все точки разом и отказывал целиком, если хоть одна пара не связывалась:
    #    линию теряли 4 маршрута из 55 из-за адресов в Кашире и Домодедово, хотя
    #    остальные их участки строились. Стало 2 из 55.
    # 2. Кэш перестал обнуляться от перестановки визитов. После снятия одной заявки и
    #    перепланирования ключ по маршруту переиспользовал 9 линий из 27 (33%), ключ по
    #    участкам — 84 участка из 159 (53%).
    #
    # Чего эта замена НЕ дала: базовый и оптимизированный планы по-прежнему почти не
    # делят между собой участков (замерено 2%) — они развозят разные заявки разными
    # инженерами, и совпадений там взяться неоткуда.

    @staticmethod
    def _geometry_key(a: GeoPoint, b: GeoPoint) -> str:
        return f"{point_key(a)}>{point_key(b)}"

    def get_geometry(self, profile: str, a: GeoPoint, b: GeoPoint) -> list[list[float]] | None:
        """Ломаная участка в порядке GeoJSON: `[[lon, lat], …]`."""
        return self._geometry.get(profile, {}).get(self._geometry_key(a, b))

    def put_geometry(
        self, profile: str, a: GeoPoint, b: GeoPoint, coordinates: Sequence[Sequence[float]]
    ) -> None:
        self._geometry.setdefault(profile, {})[self._geometry_key(a, b)] = [
            [float(c[0]), float(c[1])] for c in coordinates
        ]
        self._dirty = True

    # -- сохранение --

    @property
    def dirty(self) -> bool:
        return self._dirty

    def save(self, path: Path | str | None = None) -> Path:
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("не задан путь к файлу кэша")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.VERSION,
            "legs": {p: dict(sorted(v.items())) for p, v in sorted(self._legs.items())},
            "geometry": {p: dict(sorted(v.items())) for p, v in sorted(self._geometry.items())},
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False),
            encoding="utf-8",
        )
        self._dirty = False
        return target

    def stats(self) -> dict[str, int]:
        return {
            "legs": sum(len(v) for v in self._legs.values()),
            "geometry": sum(len(v) for v in self._geometry.values()),  # участков, не маршрутов
            "profiles": len(set(self._legs) | set(self._geometry)),
        }


# --------------------------------------------------------------------------------------
# Сбор точек сценария
# --------------------------------------------------------------------------------------


def collect_points(scenario: Scenario, *, include_inactive: bool = False) -> tuple[GeoPoint, ...]:
    """Все уникальные точки расчёта: старты инженеров и адреса заявок.

    Порядок стабилен (первое появление), потому что от него зависит и состав запроса
    к сервису, и содержимое кэша — а значит, воспроизводимость расчёта.
    """
    seen: dict[str, GeoPoint] = {}
    engineers: Iterable[Engineer] = (
        scenario.engineers if include_inactive else scenario.active_engineers()
    )
    for engineer in engineers:
        seen.setdefault(point_key(engineer.start_point), engineer.start_point)
    for request in scenario.planning_requests():
        seen.setdefault(point_key(request.point), request.point)
    return tuple(seen.values())


def scenario_modes(scenario: Scenario, *, include_inactive: bool = False) -> tuple[TransportMode, ...]:
    """Способы передвижения, реально встречающиеся в составе исполнителей.

    Матрица запрашивается только под них: лишний профиль — это лишние минуты сборки
    графа и лишние мегабайты кэша.
    """
    engineers: Iterable[Engineer] = (
        scenario.engineers if include_inactive else scenario.active_engineers()
    )
    modes = {e.transport_mode for e in engineers}
    return tuple(m for m in TransportMode if m in modes)


# --------------------------------------------------------------------------------------
# Модель перемещения поверх ORS
# --------------------------------------------------------------------------------------


class OrsTravelModel:
    """`TravelModel` на реальных расстояниях по улицам.

    В отличие от расчёта по координатам матрица НЕ симметрична: A→B и B→A различаются
    из-за односторонних улиц и разворотов. Алгоритму это безразлично — вставка считает
    конкретные участки маршрута, а не «расстояние между точками вообще».

    Время в пути = время сервиса + `Settings.overhead_minutes[mode]`. Накладные остаются
    нашими: парковка, подход к подъезду и подъём в квартиру — это требование базы знаний,
    а не часть дорожного графа, и ORS про них ничего не знает.
    """

    __slots__ = (
        "_settings",
        "_legs",
        "_profiles",
        "_fallback",
        "_add_overhead",
        "_cache",
        "warnings",
        "fallback_hits",
        "matrix_hits",
    )

    def __init__(
        self,
        settings: Settings,
        legs: Mapping[str, Mapping[tuple[str, str], tuple[float, float]]],
        *,
        profiles: Mapping[TransportMode, str] | None = None,
        fallback: TravelModel | None = None,
        add_overhead: bool = True,
        warnings: Sequence[str] = (),
    ) -> None:
        self._settings = settings
        self._legs = {p: dict(t) for p, t in legs.items()}
        self._profiles = dict(DEFAULT_PROFILES if profiles is None else profiles)
        self._fallback = fallback or HaversineTravelModel(settings)
        self._add_overhead = add_overhead
        self._cache: dict[tuple[str, str, TransportMode], tuple[float, float]] = {}
        self.warnings: tuple[str, ...] = tuple(warnings)
        self.fallback_hits = 0
        self.matrix_hits = 0

    # -- построение --

    @classmethod
    def for_scenario(
        cls,
        scenario: Scenario,
        client: OrsClient,
        *,
        cache: RoutingCache | None = None,
        modes: Sequence[TransportMode] | None = None,
        add_overhead: bool = True,
        refresh: bool = False,
    ) -> "OrsTravelModel":
        """Запросить матрицы под сценарий и собрать модель.

        Сеть трогается ровно столько раз, сколько профилей реально нужно; всё, что уже
        лежит в кэше, не перезапрашивается. Любая ошибка сервиса не поднимается выше:
        соответствующий режим просто останется на расчёте по координатам.
        """
        points = collect_points(scenario)
        wanted = tuple(modes) if modes is not None else scenario_modes(scenario)
        legs: dict[str, dict[tuple[str, str], tuple[float, float]]] = {}
        warnings: list[str] = []

        for mode in wanted:
            try:
                profile = client.profile_of(mode)
            except OrsError as exc:
                warnings.append(f"ORS: {exc}; режим «{mode}» считается по координатам")
                continue

            if profile in GEOMETRY_ONLY_PROFILES:
                # Матрица этого профиля вернула бы пешее время под видом транспортного,
                # см. GEOMETRY_ONLY_PROFILES. Лучше честный расчёт по координатам.
                warnings.append(
                    f"ORS: матрица профиля «{profile}» не учитывает расписания; "
                    f"режим «{mode}» считается по координатам"
                )
                continue

            table = {} if refresh else (cache.legs_of(profile) if cache else {})
            if not _covers(table, points):
                try:
                    fetched = fetch_matrix(client, profile, points)
                except OrsError as exc:
                    warnings.append(f"ORS: {exc}; режим «{mode}» считается по координатам")
                    if table:
                        legs[profile] = table
                    continue
                table.update(fetched)
                if cache is not None:
                    index = {point_key(p): p for p in points}
                    for (ka, kb), (km, minutes) in fetched.items():
                        cache.put_leg(profile, index[ka], index[kb], km, minutes)
            legs[profile] = table

        return cls(
            scenario.settings,
            legs,
            profiles=client.profiles,
            add_overhead=add_overhead,
            warnings=warnings,
        )

    @classmethod
    def from_cache(
        cls,
        settings: Settings,
        cache: RoutingCache,
        *,
        profiles: Mapping[TransportMode, str] | None = None,
        add_overhead: bool = True,
    ) -> "OrsTravelModel":
        """Модель целиком из файла кэша: офлайн, без поднятого контейнера."""
        table = dict(DEFAULT_PROFILES if profiles is None else profiles)
        # Тот же отбор, что и в for_scenario: в старом кэше такие участки могли осесть
        # до того, как выяснилось, чего стоит эта матрица.
        legs = {
            profile: cache.legs_of(profile)
            for profile in set(table.values()) - GEOMETRY_ONLY_PROFILES
        }
        return cls(
            settings,
            {p: t for p, t in legs.items() if t},
            profiles=table,
            add_overhead=add_overhead,
        )

    # -- протокол TravelModel --

    def _pair(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> tuple[float, float]:
        ka, kb = point_key(a), point_key(b)
        if ka == kb:
            # Инженер уже на месте: ни пробега, ни сопутствующих затрат.
            return 0.0, 0.0

        cached = self._cache.get((ka, kb, mode))
        if cached is not None:
            return cached

        profile = self._profiles.get(mode)
        value = self._legs.get(profile, {}).get((ka, kb)) if profile else None
        if value is None:
            self.fallback_hits += 1
            result = (
                self._fallback.distance_km(a, b, mode),
                self._fallback.travel_minutes(a, b, mode),
            )
        else:
            self.matrix_hits += 1
            km, minutes = value
            overhead = self._settings.overhead_minutes[mode] if self._add_overhead else 0.0
            result = (km, minutes + overhead)

        self._cache[(ka, kb, mode)] = result
        return result

    def distance_km(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> float:
        return self._pair(a, b, mode)[0]

    def travel_minutes(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> float:
        return self._pair(a, b, mode)[1]

    def both(self, a: GeoPoint, b: GeoPoint, mode: TransportMode) -> tuple[float, float]:
        return self._pair(a, b, mode)

    # -- отчётность --

    @property
    def has_matrix(self) -> bool:
        """Есть ли хоть одна непустая матрица. Пустая модель равносильна её отсутствию."""
        return any(self._legs.values())

    @property
    def coverage(self) -> float:
        """Доля обращений, закрытых реальной матрицей. Попадает в предупреждения плана."""
        total = self.matrix_hits + self.fallback_hits
        return self.matrix_hits / total if total else 0.0

    def report(self) -> tuple[str, ...]:
        """Предупреждения модели плюс итог по покрытию — для `PlanResult.warnings`."""
        lines = list(self.warnings)
        total = self.matrix_hits + self.fallback_hits
        if total and self.fallback_hits:
            lines.append(
                f"ORS: {self.fallback_hits} из {total} обращений к расстояниям "
                f"посчитаны по координатам (покрытие матрицей {self.coverage:.1%})"
            )
        return tuple(lines)


def _covers(table: Mapping[tuple[str, str], tuple[float, float]], points: Sequence[GeoPoint]) -> bool:
    """Есть ли в таблице все пары точек сценария. Одной дырки хватает, чтобы идти в сервис."""
    if not table:
        return not points
    keys = [point_key(p) for p in points]
    for ka in keys:
        for kb in keys:
            if ka != kb and (ka, kb) not in table:
                return False
    return True


def fetch_matrix(
    client: OrsClient, profile: str, points: Sequence[GeoPoint]
) -> dict[tuple[str, str], tuple[float, float]]:
    """Матрица «все со всеми» для профиля, при необходимости — блоками.

    Инстанс ограничивает запрос дважды: числом пар (`maximum_routes`, по умолчанию 2500)
    и бюджетом обхода графа (`maximum_visited_nodes`). Первый предел известен заранее и
    задаёт стартовый размер блока; второй зависит и от инстанса, и от самих точек, и
    проявляется только отказом — на него блок уменьшается по ходу дела.

    Результат от размера блока не зависит: это то же самое «все со всеми», просто
    собранное за несколько запросов.
    """
    count = len(points)
    if count < 2:
        return {}

    keys = [point_key(p) for p in points]
    rows_per_request = max(1, client.max_routes_per_request // count)
    table: dict[tuple[str, str], tuple[float, float]] = {}

    start = 0
    while start < count:
        block = list(range(start, min(start + rows_per_request, count)))
        try:
            payload = client.matrix(profile, points, sources=block)
        except OrsError as exc:
            # Инстанс ограничивает не только число пар, но и обход графа
            # (`maximum_visited_nodes`), причём бюджет тратится на запрос целиком.
            # Для профилей без contraction hierarchies (пеший, велосипедный) на
            # десятках точек он кончается, и сервис отвечает вердиктом 6020.
            # Величина предела зависит от инстанса и от самих точек, поэтому она не
            # угадывается, а нащупывается: блок делится пополам и запрос повторяется.
            if exc.code is None or rows_per_request <= 1:
                raise
            rows_per_request = max(1, rows_per_request // 2)
            continue

        distances = payload.get("distances")
        durations = payload.get("durations")
        if not isinstance(distances, list) or not isinstance(durations, list):
            raise OrsError(f"профиль {profile}: в ответе матрицы нет distances/durations")

        start = block[-1] + 1
        for row_index, source_index in enumerate(block):
            distance_row = distances[row_index]
            duration_row = durations[row_index]
            for column, key_b in enumerate(keys):
                if column == source_index:
                    continue  # диагональ: точка сама с собой, значение известно и так
                km = distance_row[column]
                seconds = duration_row[column]
                # null = точки нет в графе или она недостижима: пара остаётся
                # незаполненной и уходит в расчёт по координатам.
                if km is None or seconds is None:
                    continue
                table[(keys[source_index], key_b)] = (float(km), float(seconds) / 60.0)

    return table


# --------------------------------------------------------------------------------------
# Геометрия маршрутов для карты
# --------------------------------------------------------------------------------------


def attach_route_geometry(
    result: PlanResult,
    client: OrsClient | None = None,
    *,
    cache: RoutingCache | None = None,
    refresh: bool = False,
) -> PlanResult:
    """Дописать в план настоящие линии маршрутов по улицам.

    Назначения, расписание и метрики не трогаются — меняется только то, что рисует карта:

    * `RouteResult.geometry` — ломаная по улицам целиком, в порядке объезда;
    * `RouteResult.geometry_source` — `"ors"`, `"mixed"` или `"straight"`, чтобы
      интерфейс честно показывал, насколько линия настоящая;
    * `Visit.geometry_range` — срез общей ломаной, приходящийся на участок ДО этого
      визита. Индексы, а не копия точек: иначе JSON плана удваивается на ровном месте,
      а фронту всё равно нужен `slice` для подсветки одного участка.

    Линия собирается по участкам: на каждую пару соседних точек свой запрос и своя
    запись в кэше. Запросов при этом выходит в несколько раз больше, чем при одном
    `directions` на весь маршрут, — сознательный размен, см. комментарий у геометрии
    в `RoutingCache`.

    Участок, который сервис построить не смог, заменяется прямой, а маршрут помечается
    `"mixed"`: одна непригодная пара точек больше не лишает линии весь маршрут. Если не
    построен ни один участок, маршрут остаётся как был — `"straight"` и пометка в
    `warnings`.
    """
    if client is None and cache is None:
        raise ValueError("нужен либо клиент ORS, либо кэш с геометрией")

    routes: list[RouteResult] = []
    warnings: list[str] = list(result.warnings)
    empty: list[str] = []
    partial: list[str] = []
    reason = ""
    # Отказ почти всегда относится к профилю целиком (он не собран на инстансе), а не к
    # конкретному участку. Поэтому счёт неудач ведётся ПО ПРОФИЛЮ: отказы по
    # `foot-walking` прекращают запросы только для пеших маршрутов, а автомобильные
    # продолжают строиться. Общий счётчик здесь был бы ошибкой: три пеших инженера подряд
    # выключили бы геометрию всему плану.
    strikes: dict[str, int] = {}

    def leg_geometry(profile: str, a: GeoPoint, b: GeoPoint) -> list[list[float]] | None:
        """Ломаная одного участка: из кэша, иначе из сервиса, иначе None."""
        nonlocal reason
        if not refresh and cache is not None:
            known = cache.get_geometry(profile, a, b)
            if known is not None:
                return known
        if client is None or strikes.get(profile, 0) >= PROFILE_STRIKES:
            return None
        try:
            coordinates = _fetch_leg(client, profile, a, b)
        except OrsError as exc:
            reason = reason or str(exc)
            if exc.code not in POINT_SPECIFIC_CODES:
                strikes[profile] = strikes.get(profile, 0) + 1
            return None
        strikes[profile] = 0
        if cache is not None:
            cache.put_geometry(profile, a, b, coordinates)
        return coordinates

    for route in result.routes:
        if not route.visits:
            routes.append(route)
            continue

        waypoints = route.polyline
        profile = (client.profiles if client else DEFAULT_PROFILES).get(route.transport_mode)
        if profile is None:
            legs: list[list[list[float]] | None] = [None] * (len(waypoints) - 1)
        else:
            legs = [
                leg_geometry(profile, a, b) for a, b in zip(waypoints, waypoints[1:])
            ]

        built = sum(1 for leg in legs if leg is not None)
        if built == 0:
            empty.append(route.engineer_id)
            routes.append(route)
            continue
        if built < len(legs):
            partial.append(route.engineer_id)
        routes.append(_apply_geometry(route, waypoints, legs))

    if empty:
        # Офлайн-режим и отказ сервиса — разные вещи, и путать их в отчёте нельзя:
        # в первом случае геометрии просто нет в кэше, чинится прогревом.
        what = "не построена" if client is not None else "отсутствует в кэше"
        warnings.append(
            f"ORS: геометрия {what} для {len(empty)} маршрутов "
            f"({', '.join(empty[:5])}{'…' if len(empty) > 5 else ''})"
            + (f": {reason}" if reason else "")
            + " — на карте они останутся прямыми"
        )
    if partial:
        warnings.append(
            f"ORS: у {len(partial)} маршрутов часть участков не построена "
            f"({', '.join(partial[:5])}{'…' if len(partial) > 5 else ''}) — "
            "они показаны прямыми внутри линии"
        )

    return dc_replace(result, routes=tuple(routes), warnings=tuple(warnings))


# --------------------------------------------------------------------------------------
# Единая точка подключения
# --------------------------------------------------------------------------------------


class Routing:
    """Всё, что нужно расчёту для работы с реальной маршрутизацией, одним объектом.

    Типовое использование (и в `demo.py`, и в основном сервисе):

        routing = setup_routing(scenario, url="http://localhost:8080/ors")
        result = plan(scenario, travel=routing.travel)
        result = routing.attach(result)      # линии маршрутов для карты
        routing.save()                       # ответы сервиса — в кэш

    Если сервис не поднят, а кэша нет, `travel` равен `None` — это законный режим:
    `plan(scenario, travel=None)` считает по координатам, как и раньше.
    """

    __slots__ = ("travel", "client", "cache", "notes")

    def __init__(
        self,
        travel: TravelModel | None,
        client: OrsClient | None,
        cache: RoutingCache | None,
        notes: Sequence[str] = (),
    ) -> None:
        self.travel = travel
        self.client = client
        self.cache = cache
        self.notes: tuple[str, ...] = tuple(notes)

    @property
    def enabled(self) -> bool:
        """Реально ли расстояния приходят от сервиса.

        Модель, которая не получила ни одной матрицы (сервис лёг, профили не собраны),
        считает всё по координатам — и притворяться работающей маршрутизацией не должна.
        """
        if self.travel is None:
            return False
        if isinstance(self.travel, OrsTravelModel):
            return self.travel.has_matrix
        return True

    def attach(self, result: PlanResult) -> PlanResult:
        """Дописать в план геометрию маршрутов и накопленные предупреждения."""
        extra = tuple(self.notes)
        if isinstance(self.travel, OrsTravelModel):
            extra = extra + tuple(n for n in self.travel.report() if n not in extra)
        if self.client is None and self.cache is None:
            return dc_replace(result, warnings=result.warnings + extra) if extra else result
        enriched = attach_route_geometry(result, self.client, cache=self.cache)
        merged = enriched.warnings + tuple(n for n in extra if n not in enriched.warnings)
        return dc_replace(enriched, warnings=merged)

    def save(self) -> Path | None:
        """Сохранить кэш, если он менялся. Возвращает путь либо `None`."""
        if self.cache is None or not self.cache.dirty or self.cache.path is None:
            return None
        return self.cache.save()


def setup_routing(
    scenario: Scenario,
    *,
    url: str | None = None,
    api_key: str | None = None,
    cache_path: Path | str | None = DEFAULT_CACHE_PATH,
    refresh: bool = False,
    max_routes: int = 25000,
    timeout: float = 180.0,
) -> Routing:
    """Подключить реальную маршрутизацию настолько, насколько это сейчас возможно.

    Три режима, и переключение между ними автоматическое:

    * задан `url` — идём в сервис, попутно наполняя кэш;
    * `url` не задан, но кэш существует — работаем офлайн на сохранённых ответах;
    * ни того, ни другого — `travel is None`, расчёт по координатам.

    Функция никогда не бросает исключений из-за сети: недоступный сервис — это
    предупреждение в плане, а не отказ в расчёте.
    """
    path = Path(cache_path) if cache_path is not None else None
    cache = RoutingCache(path) if path is not None else None
    notes: list[str] = []

    if url:
        client = OrsClient(
            url, api_key=api_key, max_routes_per_request=max_routes, timeout=timeout
        )
        travel = OrsTravelModel.for_scenario(scenario, client, cache=cache, refresh=refresh)
        return Routing(travel, client, cache, travel.warnings)

    if cache is not None and cache.stats()["legs"]:
        travel = OrsTravelModel.from_cache(scenario.settings, cache)
        notes.append(
            "ORS: расстояния взяты из сохранённого кэша маршрутного сервиса "
            f"({cache.stats()['legs']} участков), сервис не опрашивался"
        )
        return Routing(travel, None, cache, notes)

    return Routing(None, None, cache, notes)


PT_WALKING_TIME = "PT30M"
"""Сколько разрешено идти пешком до остановки и от неё при построении маршрута.

Дефолт ORS — 15 минут, и с ним часть участков не строится вовсе: сервис отвечает
`PT entry and exit points found but no connecting route` и прямо советует увеличить
это время. Наш фид собран из выгрузок наземного транспорта, метро и МЦД в нём нет,
поэтому до автобусной сети идти дальше, чем предполагает дефолт. Проверено на паре,
которая с 15 минутами не строилась: с 30 минутами — маршрут за 36 минут, с 60 тот же
самый, то есть 30 минут уже достаточно.
"""


def _geometry_options(profile: str) -> dict[str, Any]:
    """Параметры `directions`, зависящие от профиля."""
    if profile in GEOMETRY_ONLY_PROFILES:
        return {"walking_time": PT_WALKING_TIME}
    return {}


PROFILE_STRIKES = 3
"""Сколько несистемных отказов подряд по одному профилю выключают запросы по нему.

Смысл счётчика — отличить «профиль на инстансе не собран» от «конкретная пара точек
не строится»: в первом случае продолжать бессмысленно, во втором — наоборот. Различие
делается по коду ошибки (см. `POINT_SPECIFIC_CODES`), а счётчик — страховка на случай,
когда ORS вернул что-то, чего мы не разбираем; любой успешный участок обнуляет его.
"""

POINT_SPECIFIC_CODES = frozenset({2004, 2009, 2010, 2015})
"""Коды ORS, означающие вердикт по КОНКРЕТНОЙ паре точек, а не поломку профиля.

Замерено на нашем инстансе (ORS 10.0.0): 2015 — «Route could not be found between
points», 2004 — маршрут длиннее разрешённых сервисом 500 км, 2009 и 2010 — точка вне
графа. Всё это нормальные ответы для адреса за пределами покрытия: Кашира с фидом
наземного транспорта Москвы не свяжется никогда, и выключать из-за неё геометрию
остальным маршрутам профиля нельзя. Коды вне этого списка (например 2003, «нет такого
профиля») считаются поломкой профиля целиком.
"""


def _fetch_leg(
    client: OrsClient, profile: str, a: GeoPoint, b: GeoPoint
) -> list[list[float]]:
    """Один запрос `directions` на участок: ломаная в формате GeoJSON."""
    response = client.directions(profile, (a, b), **_geometry_options(profile))
    features = response.get("features") or []
    if not features:
        raise OrsError("пустой ответ directions")
    coordinates = (features[0].get("geometry") or {}).get("coordinates")
    if not coordinates:
        raise OrsError("в ответе directions нет геометрии")
    return [[float(c[0]), float(c[1])] for c in coordinates]


def _apply_geometry(
    route: RouteResult,
    waypoints: Sequence[GeoPoint],
    legs: Sequence[Sequence[Sequence[float]] | None],
) -> RouteResult:
    """Сшить участки в одну ломаную и разметить по ней визиты."""
    coordinates: list[Sequence[float]] = []
    bounds: list[int] = [0]
    for index, leg in enumerate(legs):
        a, b = waypoints[index], waypoints[index + 1]
        # Непостроенный участок рисуется прямой. Разрыв в линии был бы хуже: фронт
        # режет её индексами визитов, и дыра сдвинула бы все последующие срезы.
        points = list(leg) if leg is not None else [[a.lon, a.lat], [b.lon, b.lat]]
        # Конец предыдущего участка и начало этого — одна точка маршрута; дубль убираем.
        # Если сервис приклеил её к разным местам улицы, оставляем обе: это честнее,
        # чем прятать расхождение.
        skip = 1 if coordinates and list(coordinates[-1]) == list(points[0]) else 0
        coordinates.extend(points[skip:])
        bounds.append(len(coordinates) - 1)

    geometry = tuple(GeoPoint(lat=float(c[1]), lon=float(c[0])) for c in coordinates)
    visits = [
        dc_replace(visit, geometry_range=(bounds[index], bounds[index + 1]))
        for index, visit in enumerate(route.visits)
    ]
    return dc_replace(
        route,
        visits=tuple(visits),
        geometry=geometry,
        geometry_source="ors" if all(leg is not None for leg in legs) else "mixed",
    )

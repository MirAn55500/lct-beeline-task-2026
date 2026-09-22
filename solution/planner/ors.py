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

Общественный транспорт
----------------------
Для него этот путь не работает: у `/v2/matrix` нет параметра времени отправления, и
она отвечает пешей доступностью вместо поездки по расписанию (см. `NO_MATRIX_PROFILES`).
Поэтому у общественного транспорта источник чисел другой — `/v2/directions` с временем
отправления, участок за участком (`fetch_transit_legs`). Тем же ответом приходит и
состав поездки: какие маршруты, где садиться, сколько ждать (`TransitLeg`).

Расписания берутся из GTFS-фида, который собирается `tools/mosdata_to_gtfs.py` из
выгрузок data.mos.ru и включает наземный транспорт, метро, МЦК и МЦД.

Границы ответственности
-----------------------
Алгоритм планирования НЕ меняется. Модуль поставляет две вещи:

1. `OrsTravelModel` — реализация протокола `TravelModel`, то есть подстановка
   в `plan(scenario, travel=...)`. Всё остальное ядро её не отличает от расчёта
   по координатам;
2. `attach_route_geometry` — постобработка готового плана: дописывает в каждый
   маршрут настоящую линию по улицам и состав поездки на транспорте, не трогая ни
   назначения, ни расписание.

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

import concurrent.futures
import json
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace as dc_replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .enums import TRANSPORT_TITLES, TransportMode
from .models import Engineer, GeoPoint, Scenario, Settings
from .result import PlanResult, RouteResult, TransitLeg, Visit
from .travel import HaversineTravelModel, TravelModel

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_PROFILES",
    "DEFAULT_CACHE_PATH",
    "NO_MATRIX_PROFILES",
    "PT_DEPARTURE_HOUR",
    "OrsError",
    "OrsClient",
    "RoutingCache",
    "OrsTravelModel",
    "Routing",
    "setup_routing",
    "attach_route_geometry",
    "collect_points",
    "scenario_modes",
    "fetch_transit_legs",
    "scenario_departure",
    "departure_moment",
    "transit_sections",
    "transit_section_moment",
    "transit_reuse_section",
    "moment_title",
    "prefetch_hint",
    "as_number",
    "is_point_verdict",
    "TransitFailures",
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

NO_MATRIX_PROFILES: frozenset[str] = frozenset({"public-transport"})
"""Профили, чью матрицу брать нельзя.

У `/v2/matrix` нет параметра времени отправления, поэтому расписания в матрицу не
попадают: ORS отвечает на неё пешей доступностью. Внешне это неотличимо от рабочего
ответа — приходят правдоподобные числа, просто не те. Замер на нашем инстансе, пара
Медведково — Ясенево: матрица 428 мин, пешком 427 мин, реальный маршрут по расписанию
63 мин.

Это ограничение именно матрицы, а не профиля: `/v2/directions` время отправления
принимает и расписания учитывает. Поэтому для общественного транспорта расстояния и
времена собираются участок за участком через `directions` — см. `fetch_transit_legs`.
"""

PT_DEPARTURE_HOUR = 10
"""Час отправления, на который считается матрица общественного транспорта.

Время поездки на общественном транспорте — не свойство пары точек: в час пик автобус
ходит вчетверо чаще, чем в девять вечера. Матрица же по своему устройству одна на весь
день, и выбрать для неё приходится один момент.

Десять утра — середина рабочего дня инженера и при этом не пик: в пик оценка вышла бы
оптимистичной для всего остального дня, поздним вечером — пессимистичной для всего
рабочего времени. Цена такого выбора замерена на 57 парах реальных адресов восточного
набора: против значения на 10:00 время в 08:00, 13:00, 17:00 и 20:00 отличается в
среднем на 5–7 % (медиана 0.5–6 %), и только на отдельных парах — до трети.

Конкретный маршрут диспетчеру показывается на **фактическое** время выезда, а не на
это (см. `attach_route_geometry`): здесь выбирается только опорное значение для
планирования, а не то, что увидит человек.
"""

_UTC = timezone.utc

PT_ROUND_MINUTES = 5
"""Шаг округления времени отправления в ключе кэша.

Без округления каждый пересчёт плана сдвигал бы время выезда на секунды и промахивался
бы мимо кэша целиком. Пять минут — меньше интервала движения почти любого маршрута,
поэтому на выбор рейса округление не влияет.
"""


def transit_profile(profile: str, when: str) -> str:
    """Имя раздела кэша для поездки, отправляющейся в момент `when`.

    Ответ `directions` для общественного транспорта зависит от времени отправления, а
    ключ кэша у остальных профилей — только от пары точек. Время уходит в имя профиля:
    так формат файла кэша не меняется, а участки, посчитанные на разное время, не
    смешиваются.
    """
    return f"{profile}@{when}"


def transit_moment(moment: datetime) -> str:
    """Момент отправления в виде, пригодном и для запроса, и для ключа кэша.

    Время переводится в UTC, потому что ORS читает `departure` без зоны именно как UTC,
    а план живёт в местном времени (`models.MSK`). Без перевода запрос уезжал бы на три
    часа вперёд: выезд в 09:00 считался бы по расписанию полудня, а выезд в 23:00 — по
    расписанию следующего утра. Проверено на инстансе: с `departure` 02:30 первый рейс
    приходит в 02:41, то есть ровно в 05:41 по Москве, когда метро и открывается.
    """
    if moment.tzinfo is not None:
        moment = moment.astimezone(_UTC)
    step = PT_ROUND_MINUTES
    rounded = moment.replace(second=0, microsecond=0, minute=moment.minute // step * step)
    return rounded.strftime("%Y-%m-%dT%H:%M:%S")


def departure_moment(day: Any, offset_hours: float = 3.0) -> str:
    """Опорный момент отправления для произвольного дня.

    Вынесено из `scenario_departure`, чтобы кэш можно было прогреть на дату, которой в
    выгрузке нет: у прогрева от сценария нужны только точки, а день задаётся отдельно
    (`tools/ors_prefetch.py --date`).
    """
    offset = timezone(timedelta(hours=offset_hours))
    return transit_moment(datetime.combine(day, time(hour=PT_DEPARTURE_HOUR), tzinfo=offset))


def scenario_departure(scenario: Scenario) -> str:
    """Опорный момент отправления сценария: день расчёта, `PT_DEPARTURE_HOUR` по месту."""
    return departure_moment(scenario.date, scenario.settings.timezone_offset_hours)


def transit_sections(
    profiles: Mapping[TransportMode, str], departure: str | None
) -> dict[TransportMode, str]:
    """Раздел кэша для каждого способа передвижения.

    У всех профилей это сам профиль, у общественного транспорта — профиль вместе со
    временем отправления: участки, посчитанные на разное время, обязаны лежать врозь.

    Когда время не задано, раздел получает заведомо пустое имя, а не имя профиля. Разница
    существенная: под именем профиля в старом кэше могли осесть числа, полученные от
    `/v2/matrix` до того, как выяснилось, что она отвечает пешей доступностью, — и они
    молча выдали бы себя за расчёт по расписанию.
    """
    return {
        mode: (
            transit_profile(profile, departure or "")
            if profile in NO_MATRIX_PROFILES else profile
        )
        for mode, profile in profiles.items()
    }


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


def transit_section_moment(section: str) -> str:
    """Момент отправления из имени раздела кэша; пусто, если раздел от него не зависит.

    Обратная операция к `transit_profile`. Нужна отчёту: строка «посчитано по
    расписанию» без момента, на который это расписание взято, не отвечает ни на один
    вопрос — а момент уже лежит в имени раздела, его надо только достать.
    """
    profile, sep, when = section.partition("@")
    return when if sep and profile in NO_MATRIX_PROFILES else ""


def _moment_local(when: str, offset_hours: float) -> datetime | None:
    """Момент из ключа кэша в местное время плана. `None`, если ключ не разбирается."""
    if not when:
        return None
    try:
        moment = datetime.strptime(when, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return moment.replace(tzinfo=_UTC).astimezone(timezone(timedelta(hours=offset_hours)))


WEEKDAY_TITLES = (
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
)
"""День недели для сообщений. Он тут не украшение: расписание зависит именно от него,
и «17.08.2026, понедельник» рядом с «21.09.2026, понедельник» сразу объясняет, почему
одно подставилось вместо другого."""


def moment_title(when: str, offset_hours: float = 3.0) -> str:
    """Момент отправления так, как его прочитает диспетчер: местное время и день недели.

    В ключе кэша момент лежит в UTC (см. `transit_moment`), а план человек читает в
    местном времени. Написать в предупреждении «07:00», когда в плане стоит 10:00,
    значит заставить его сверять часовые пояса вместо того, чтобы понять, чего не хватает.
    """
    local = _moment_local(when, offset_hours)
    if local is None:
        return when or "момент не задан"
    return f"{local:%d.%m.%Y %H:%M} ({WEEKDAY_TITLES[local.weekday()]})"


def prefetch_hint(departure: str | None, offset_hours: float = 3.0) -> str:
    """Команда прогрева расписаний на нужный день — готовая к копированию.

    Совет «прогрейте кэш» без даты бесполезен ровно в том случае, ради которого он и
    пишется: кэш уже прогрет, но на другой день, и повторный прогон без `--date`
    добавит тот же самый раздел заново.
    """
    local = _moment_local(departure or "", offset_hours)
    day = f" --date {local:%Y-%m-%d}" if local is not None else ""
    return f"python tools/ors_prefetch.py --transit{day}"


def transit_reuse_section(
    available: Mapping[str, int], departure: str, offset_hours: float
) -> str | None:
    """Раздел кэша на другой день, годный как приближение к запрошенному моменту.

    Годится только тот же день недели и тот же час отправления: от них расписание
    зависит напрямую (будни против выходных, пик против межпика), а от календарной даты
    — только праздниками, ремонтами и вводом новых маршрутов. Разница между двумя
    понедельниками в сентябре и августе несравнимо меньше, чем между поездкой по
    расписанию и расчётом по прямой, ради которого альтернативой пришлось бы выбросить
    весь прогретый кэш.

    Приближение всегда попадает в `warnings` (см. `_transit_from_cache`): подмена, о
    которой не сказали, — это не приближение, а ошибка.
    """
    asked = _moment_local(departure, offset_hours)
    if asked is None:
        return None
    best: tuple[int, str] | None = None
    for section, size in available.items():
        when = transit_section_moment(section)
        if not when or when == departure or not size:
            continue
        other = _moment_local(when, offset_hours)
        if other is None or other.weekday() != asked.weekday():
            continue
        if (other.hour, other.minute) != (asked.hour, asked.minute):
            continue
        # При нескольких подходящих днях берём самый полный: он даст меньше пар,
        # доехавших до расчёта по координатам.
        if best is None or size > best[0] or (size == best[0] and section < best[1]):
            best = (size, section)
    return best[1] if best is not None else None


def as_number(value: Any) -> float | None:
    """Число из ответа сервиса или `None`, если это не число.

    Сервис внешний, и его ответ — не наши данные: поле `distance` со значением `"нет"`
    или `null` приходит с кодом 200 и обязано кончиться откатом на расчёт по
    координатам, а не `ValueError` посреди готового плана.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # NaN и бесконечность арифметику плана портят молча, поэтому тоже «не число».
    return number if number == number and abs(number) != float("inf") else None


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

    __slots__ = ("path", "_legs", "_geometry", "_transit", "_dirty")

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
        self._transit: dict[str, dict[str, list[dict]]] = {}
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
            # Раздел появился позже и версию формата не поднимал: старый кэш просто
            # не содержит его ключа, а старый код не читает — обе стороны совместимы,
            # и 38 тысяч посчитанных пар не пропадают из-за нового поля.
            self._transit = payload.get("transit", {}) or {}
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

    def sections_of(self, profile: str) -> dict[str, int]:
        """Разделы кэша, относящиеся к профилю, и число участков в каждом.

        У обычного профиля раздел один и называется как сам профиль. У общественного
        транспорта их столько, на сколько моментов отправления кэш прогревали, — и
        только этот список отвечает на вопрос «расписания не взялись потому, что их
        нет вовсе, или потому, что они посчитаны на другой день?».
        """
        prefix = f"{profile}@"
        return {
            name: len(legs)
            for name, legs in sorted(self._legs.items())
            if name == profile or name.startswith(prefix)
        }

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

    # -- состав поездки на общественном транспорте --
    #
    # Хранится отдельно от геометрии, хотя приходит тем же ответом `directions`: линия
    # нужна карте на любом профиле, а состав поездки — только общественному транспорту,
    # и мешать их в одном разделе значило бы таскать `null` по всем остальным.

    def get_transit(self, profile: str, a: GeoPoint, b: GeoPoint) -> list[dict] | None:
        return self._transit.get(profile, {}).get(self._geometry_key(a, b))

    def put_transit(
        self, profile: str, a: GeoPoint, b: GeoPoint, legs: Sequence[Mapping[str, Any]]
    ) -> None:
        self._transit.setdefault(profile, {})[self._geometry_key(a, b)] = [
            dict(leg) for leg in legs
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
            "transit": {p: dict(sorted(v.items())) for p, v in sorted(self._transit.items())},
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
            "transit": sum(len(v) for v in self._transit.values()),
            "profiles": len(set(self._legs) | set(self._geometry) | set(self._transit)),
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
        "_departure",
        "_by_mode",
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
        departure: str | None = None,
    ) -> None:
        self._settings = settings
        self._legs = {p: dict(t) for p, t in legs.items()}
        self._profiles = dict(DEFAULT_PROFILES if profiles is None else profiles)
        self._fallback = fallback or HaversineTravelModel(settings)
        self._add_overhead = add_overhead
        self._cache: dict[tuple[str, str, TransportMode], tuple[float, float]] = {}
        self._departure = departure
        """Момент, на который взяты расписания. Нужен отчёту: без него строка «посчитано
        по расписанию» не говорит, по расписанию какого дня."""
        self._by_mode: dict[TransportMode, list[int]] = {}
        """Счётчики попаданий и откатов отдельно по способу передвижения: общий итог не
        различает «автомобиль лёг весь» и «не хватило пары адресов у пешехода»."""
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
        transit: bool = False,
        transit_workers: int = 8,
        on_progress: Callable[[int, int, int], None] | None = None,
        departure: str | None = None,
    ) -> "OrsTravelModel":
        """Запросить матрицы под сценарий и собрать модель.

        Сеть трогается ровно столько раз, сколько профилей реально нужно; всё, что уже
        лежит в кэше, не перезапрашивается. Любая ошибка сервиса не поднимается выше:
        соответствующий режим просто останется на расчёте по координатам.

        `transit` включает сбор матрицы общественного транспорта перебором участков.
        По умолчанию он выключен, и это сознательно: перебор стоит десятки минут против
        секунд у обычной матрицы (см. `fetch_transit_legs`), и запускать его при каждом
        расчёте нельзя. Уже посчитанные участки берутся из кэша в любом случае — то есть
        после одного прогона `tools/ors_prefetch.py --transit` расчёт идёт по расписанию
        и без флага.

        `departure` подменяет опорный момент отправления сценария. Нужен прогреву: даты
        в выгрузке и даты, на которые строят план, совпадают не всегда, а раздел кэша
        расписаний включает дату (см. `transit_profile`).
        """
        points = collect_points(scenario)
        wanted = tuple(modes) if modes is not None else scenario_modes(scenario)
        # Момент можно задать снаружи: прогрев кэша на другую дату (`--date`) считает
        # те же точки, но на тот день, на который план будут строить.
        departure = departure or scenario_departure(scenario)
        sections = transit_sections(client.profiles, departure)
        offset = scenario.settings.timezone_offset_hours
        legs: dict[str, dict[tuple[str, str], tuple[float, float]]] = {}
        warnings: list[str] = []

        for mode in wanted:
            try:
                profile = client.profile_of(mode)
            except OrsError as exc:
                warnings.append(
                    f"ORS: {exc}; «{TRANSPORT_TITLES[mode]}» считается по координатам"
                )
                continue

            # Раздел кэша совпадает с профилем везде, кроме общественного транспорта:
            # там в него входит время отправления, на которое считалась матрица.
            section = sections[mode]
            table = {} if refresh else (cache.legs_of(section) if cache else {})

            if profile in NO_MATRIX_PROFILES:
                # Матрица этого профиля вернула бы пешее время под видом транспортного,
                # см. NO_MATRIX_PROFILES. Считаем перебором через directions — но только
                # если об этом попросили: перебор идёт десятки минут.
                if not transit:
                    table, note = _transit_from_cache(
                        mode, profile, cache, departure, offset, table, points
                    )
                    warnings.append(note)
                    if table:
                        legs[section] = table
                    continue
                if _covers(table, points):
                    legs[section] = table
                    continue
                fetched, failures = fetch_transit_legs(
                    client, profile, points, departure,
                    workers=transit_workers, on_progress=on_progress,
                    known=None if refresh else table,
                )
                warnings.extend(failures.notes(mode, moment_title(departure, offset)))
            else:
                if _covers(table, points):
                    legs[section] = table
                    continue
                try:
                    fetched = fetch_matrix(client, profile, points)
                except OrsError as exc:
                    warnings.append(
                        f"ORS: {exc}; «{TRANSPORT_TITLES[mode]}» считается по координатам"
                    )
                    if table:
                        legs[section] = table
                    continue

            table.update(fetched)
            if cache is not None:
                index = {point_key(p): p for p in points}
                for (ka, kb), (km, minutes) in fetched.items():
                    cache.put_leg(section, index[ka], index[kb], km, minutes)
            legs[section] = table

        return cls(
            scenario.settings,
            legs,
            profiles=sections,
            add_overhead=add_overhead,
            warnings=warnings,
            departure=departure,
        )

    @classmethod
    def from_cache(
        cls,
        settings: Settings,
        cache: RoutingCache,
        *,
        profiles: Mapping[TransportMode, str] | None = None,
        add_overhead: bool = True,
        departure: str | None = None,
        modes: Sequence[TransportMode] | None = None,
        points: Sequence[GeoPoint] = (),
    ) -> "OrsTravelModel":
        """Модель целиком из файла кэша: офлайн, без поднятого контейнера.

        `departure` задаёт, на какой момент отправления брать участки общественного
        транспорта. Без него они не берутся вовсе: взять «какие нашлись» значило бы
        посчитать утренний план по вечерним интервалам и никому об этом не сказать.

        `modes` ограничивает, о каких способах передвижения писать в отчёт: матрицы
        читаются все (инженера могут переназначить вручную), а предупреждение
        «расписания не прогреты» в плане, где ни один инженер не ездит на транспорте, —
        это шум, из-за которого перестают читать и остальные предупреждения.

        `points` нужны только отчёту: по ним считается, сколько пар из скольких закрыто.
        """
        profile_of = dict(DEFAULT_PROFILES if profiles is None else profiles)
        sections = transit_sections(profile_of, departure)
        offset = settings.timezone_offset_hours
        reported = set(modes) if modes is not None else set(profile_of)
        legs: dict[str, dict[tuple[str, str], tuple[float, float]]] = {}
        warnings: list[str] = []

        for mode, section in sections.items():
            profile = profile_of.get(mode)
            if profile not in NO_MATRIX_PROFILES:
                found = cache.legs_of(section)
                if found:
                    legs[section] = found
                continue
            if departure is None:
                # Раздел с пустым именем момента заведомо пуст (см. `transit_sections`),
                # и раньше это был тихий отказ. Тихим он быть не может: числа съезжают
                # на расчёт по прямой, а план при этом выглядит точно так же.
                if mode in reported:
                    warnings.append(
                        "ORS: момент отправления не задан — расписания "
                        f"«{TRANSPORT_TITLES[mode]}» из кэша не берутся, режим "
                        "считается по координатам"
                    )
                continue
            found, note = _transit_from_cache(
                mode, profile, cache, departure, offset, cache.legs_of(section), points
            )
            if mode in reported:
                warnings.append(note)
            if found:
                legs[section] = found

        return cls(
            settings,
            {p: t for p, t in legs.items() if t},
            profiles=sections,
            add_overhead=add_overhead,
            warnings=warnings,
            departure=departure,
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

        counted = self._by_mode.setdefault(mode, [0, 0])
        profile = self._profiles.get(mode)
        value = self._legs.get(profile, {}).get((ka, kb)) if profile else None
        if value is None:
            self.fallback_hits += 1
            counted[1] += 1
            result = (
                self._fallback.distance_km(a, b, mode),
                self._fallback.travel_minutes(a, b, mode),
            )
        else:
            self.matrix_hits += 1
            counted[0] += 1
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
        """Предупреждения модели плюс итог по покрытию — для `PlanResult.warnings`.

        Итог разбит по способам передвижения, и у каждого названо, откуда взялись
        числа: матрица такого-то профиля или расписание на такой-то момент. Строка
        «посчитаны по координатам» сама по себе не отвечает ни на «что именно», ни на
        «вместо чего» — а именно эти два вопроса у неё и возникают.
        """
        lines = list(self.warnings)
        total = self.matrix_hits + self.fallback_hits
        if not total or not self.fallback_hits:
            return tuple(lines)
        lines.append(
            f"ORS: {self.fallback_hits} из {total} обращений к расстояниям "
            f"посчитаны по координатам (покрытие матрицей {self.coverage:.1%})"
        )
        offset = self._settings.timezone_offset_hours
        for mode in TransportMode:
            counted = self._by_mode.get(mode)
            if counted is None or not counted[1]:
                continue
            hits, misses = counted
            section = self._profiles.get(mode) or ""
            if section.partition("@")[0] in NO_MATRIX_PROFILES:
                when = transit_section_moment(section) or self._departure or ""
                basis = f"по расписанию на {moment_title(when, offset)}"
            else:
                basis = f"по матрице профиля «{section}»" if section else "по матрице ORS"
            lines.append(
                f"ORS: «{TRANSPORT_TITLES[mode]}»: {basis} посчитано {hits} пар "
                f"из {hits + misses}, остальные {misses} — по координатам"
            )
        return tuple(lines)


TRANSIT_WARMED_SHARE = 0.9
"""С какой доли прогретых пар кэш расписаний считается рабочим.

Полного покрытия не будет никогда: часть адресов (Кашира, Ступино) лежит вне зоны
действия фида, и такие пары не построятся сколько их ни запрашивай. Если из-за них
план каждый раз советовал бы «прогрейте кэш», совет обесценился бы — а он должен
означать ровно одно: прогона `--transit` не было.
"""


def _covered(
    table: Mapping[tuple[str, str], tuple[float, float]], points: Sequence[GeoPoint]
) -> tuple[int, int]:
    """Сколько пар ЭТОГО расчёта закрыто таблицей и сколько их всего.

    Считать длину таблицы нельзя: раздел кэша общий на все регионы, и в нём лежит
    девять тысяч пар, когда в расчёте их четыре. «9432 пары из 4290» — это не отчёт.
    """
    if not points:
        return len(table), 0
    keys = [point_key(p) for p in points]
    needed = [(a, b) for a in keys for b in keys if a != b]
    return sum(1 for pair in needed if pair in table), len(needed)


def _of_total(count: int, total: int) -> str:
    """«N пар из M» или просто «N пар», когда общее число пар расчёта неизвестно."""
    return f"{count} пар из {total}" if total else f"{count} пар"


def _transit_from_cache(
    mode: TransportMode,
    profile: str,
    cache: "RoutingCache | None",
    departure: str,
    offset_hours: float,
    table: Mapping[tuple[str, str], tuple[float, float]],
    points: Sequence[GeoPoint],
) -> tuple[dict[tuple[str, str], tuple[float, float]], str]:
    """Что взять из кэша для расписаний и что об этом написать в план.

    Раздел кэша расписаний включает дату (см. `transit_profile`), поэтому план на
    другой день не находит в нём НИЧЕГО, даже когда кэш полон на соседнюю неделю.
    Внешне такой план не отличается ничем — меняются только числа, и в этом всё дело:
    поездка на метро тихо превращается в прямую линию, а отчёт молчит.

    Поэтому исходов здесь четыре, и каждый обязан быть различим в отчёте:

    * участки на нужный момент есть — берём их и называем момент;
    * их нет, но есть на тот же день недели и час — берём как ПРИБЛИЖЕНИЕ, называем
      обе даты и говорим, чего это приближение не учитывает;
    * в кэше есть расписания, но на другие дни недели или часы — берём координаты и
      перечисляем, что в кэше лежит;
    * расписаний нет вовсе — берём координаты и советуем прогрев.

    Молчаливого исхода нет ни одного.
    """
    title = TRANSPORT_TITLES[mode]
    asked = moment_title(departure, offset_hours)
    hint = prefetch_hint(departure, offset_hours)

    if table:
        covered, total = _covered(table, points)
        share = covered / total if total else 1.0
        if share >= TRANSIT_WARMED_SHARE:
            return dict(table), (
                f"ORS: «{title}» посчитан по расписанию на {asked} из кэша "
                f"({_of_total(covered, total)}); остальные пары — вне зоны "
                "действия фида и посчитаны по координатам"
            )
        return dict(table), (
            f"ORS: расписания «{title}» на {asked} прогреты частично "
            f"({_of_total(covered, total)}, {share:.0%}) — остальное по "
            f"координатам; прогрев: {hint}"
        )

    available = cache.sections_of(profile) if cache is not None else {}
    spare = transit_reuse_section(available, departure, offset_hours)
    if spare is not None and cache is not None:
        reused = cache.legs_of(spare)
        covered, total = _covered(reused, points)
        return reused, (
            f"ORS: расписаний «{title}» на {asked} в кэше нет — взяты участки, "
            f"посчитанные на {moment_title(transit_section_moment(spare), offset_hours)}: "
            f"тот же день недели и тот же час ({_of_total(covered, total)}). Это "
            "приближение — праздники, ремонты и изменения маршрутной сети между этими "
            f"датами в нём не учтены; точный расчёт: {hint}"
        )

    known = [s for s in available if transit_section_moment(s)]
    if known:
        listed = ", ".join(
            moment_title(transit_section_moment(s), offset_hours) for s in known[:3]
        )
        return {}, (
            f"ORS: расписаний «{title}» на {asked} в кэше нет, а те, что есть "
            f"({listed}{'…' if len(known) > 3 else ''}), посчитаны на другой день "
            f"недели или час — режим считается по координатам; прогрев: {hint}"
        )

    return {}, (
        f"ORS: матрица профиля «{profile}» не учитывает расписания, а расчёт по "
        f"расписанию не прогрет — «{title}» считается по координатам; прогрев: {hint}"
    )


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
        # Меньше строк, чем источников в запросе, — это сломанный ответ целиком, а не
        # дырка в нём: какие именно источники пропущены, ответ не сообщает, и раскладка
        # по парам стала бы угадыванием. Ошибка уходит наверх, где режим честно
        # откатывается на расчёт по координатам с предупреждением в плане.
        if len(distances) < len(block) or len(durations) < len(block):
            raise OrsError(
                f"профиль {profile}: матрица вернула {min(len(distances), len(durations))} "
                f"строк вместо {len(block)}"
            )

        start = block[-1] + 1
        for row_index, source_index in enumerate(block):
            distance_row = distances[row_index]
            duration_row = durations[row_index]
            if not isinstance(distance_row, list) or not isinstance(duration_row, list):
                continue
            for column, key_b in enumerate(keys):
                if column == source_index:
                    continue  # диагональ: точка сама с собой, значение известно и так
                # Короткий ряд — та же несчитанная пара, что и null: ряд обрывается
                # молча, а падение по индексу посреди сборки матрицы уронило бы весь
                # расчёт из-за чужого ответа.
                if column >= len(distance_row) or column >= len(duration_row):
                    continue
                km = as_number(distance_row[column])
                seconds = as_number(duration_row[column])
                # null или не число («distance»: «нет») = точки нет в графе, она
                # недостижима либо сервис ответил мусором: пара остаётся незаполненной
                # и уходит в расчёт по координатам.
                if km is None or seconds is None:
                    continue
                table[(keys[source_index], key_b)] = (km, seconds / 60.0)

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
    """Дописать в план настоящие линии маршрутов по улицам и состав поездок на транспорте.

    Назначения, расписание и метрики не трогаются — меняется только то, что показывают
    карта и карточка визита:

    * `RouteResult.geometry` — ломаная по улицам целиком, в порядке объезда;
    * `RouteResult.geometry_source` — `"ors"`, `"mixed"` или `"straight"`, чтобы
      интерфейс честно показывал, насколько линия настоящая;
    * `Visit.geometry_range` — срез общей ломаной, приходящийся на участок ДО этого
      визита. Индексы, а не копия точек: иначе JSON плана удваивается на ровном месте,
      а фронту всё равно нужен `slice` для подсветки одного участка;
    * `Visit.transit` — для маршрутов на общественном транспорте: чем именно ехать,
      где садиться и сколько ждать (см. `TransitLeg`).

    Линия собирается по участкам: на каждую пару соседних точек свой запрос и своя
    запись в кэше. Запросов при этом выходит в несколько раз больше, чем при одном
    `directions` на весь маршрут, — сознательный размен, см. комментарий у геометрии
    в `RoutingCache`.

    Общественный транспорт запрашивается на **фактическое время выезда** из расписания
    плана, а не на опорный час матрицы: диспетчеру показывается тот рейс, на который
    инженер действительно успевает. Поэтому у такого участка и ключ кэша свой — время
    входит в него (`transit_profile`).

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

    def leg_geometry(
        profile: str, a: GeoPoint, b: GeoPoint, when: str | None = None
    ) -> tuple[list[list[float]] | None, list[dict]]:
        """Ломаная участка и состав поездки: из кэша, иначе из сервиса, иначе пусто.

        Ключ кэша у поездки на транспорте включает время отправления: один и тот же
        участок в девять утра и в девять вечера — это разные автобусы и разное время.
        """
        nonlocal reason
        # Счётчик отказов ведётся по профилю ORS, а раздел кэша у транспорта свой:
        # иначе каждое новое время выезда заводило бы собственный счётчик и порог
        # `PROFILE_STRIKES` не срабатывал бы никогда.
        section = profile if when is None else transit_profile(profile, when)
        if not refresh and cache is not None:
            known = cache.get_geometry(section, a, b)
            steps = cache.get_transit(section, a, b) or []
            # У поездки на транспорте состав обязателен: даже полностью пеший вариант
            # приходит от сервиса хотя бы одним участком. Пустой состав при известной
            # линии означает запись, сделанную до появления этого раздела, — её надо
            # добрать, а не выдавать за поездку без единого автобуса.
            if known is not None and (when is None or steps):
                return known, steps
        if client is None or strikes.get(profile, 0) >= PROFILE_STRIKES:
            return None, []
        try:
            _km, _minutes, coordinates, transit = _fetch_leg(client, profile, a, b, when=when)
        except OrsError as exc:
            reason = reason or str(exc)
            if not is_point_verdict(exc.code):
                strikes[profile] = strikes.get(profile, 0) + 1
            return None, []
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            # Ответ 200 неожиданной формы — то же самое, что отказ участка: рисуем
            # прямую и пишем причину. Уронить готовый план из-за поля в чужом JSON
            # нельзя: контракт модуля обещает откат на прямую, а не исключение.
            reason = reason or f"неразбираемый ответ сервиса: {exc}"
            strikes[profile] = strikes.get(profile, 0) + 1
            return None, []
        strikes[profile] = 0
        if cache is not None:
            cache.put_geometry(section, a, b, coordinates)
            if transit:
                cache.put_transit(section, a, b, transit)
        return coordinates, transit

    for route in result.routes:
        if not route.visits:
            routes.append(route)
            continue

        waypoints = route.polyline
        profile = (client.profiles if client else DEFAULT_PROFILES).get(route.transport_mode)
        transit_mode = route.transport_mode is TransportMode.PUBLIC_TRANSPORT
        if profile is None:
            legs: list[list[list[float]] | None] = [None] * (len(waypoints) - 1)
            transit: list[list[dict]] = [[] for _ in legs]
        else:
            answers = [
                leg_geometry(
                    profile, a, b,
                    transit_moment(visit.departure_at) if transit_mode else None,
                )
                for (a, b), visit in zip(zip(waypoints, waypoints[1:]), route.visits)
            ]
            legs = [coordinates for coordinates, _ in answers]
            transit = [steps for _, steps in answers]

        built = sum(1 for leg in legs if leg is not None)
        if built == 0:
            # Состав поездки приходит тем же ответом, что и линия: нет линии — нет и его.
            empty.append(route.engineer_id)
            routes.append(route)
            continue
        if built < len(legs):
            partial.append(route.engineer_id)
        routes.append(_apply_transit(_apply_geometry(route, waypoints, legs), transit))

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
    transit: bool = False,
) -> Routing:
    """Подключить реальную маршрутизацию настолько, насколько это сейчас возможно.

    Три режима, и переключение между ними автоматическое:

    * задан `url` — идём в сервис, попутно наполняя кэш;
    * `url` не задан, но кэш существует — работаем офлайн на сохранённых ответах;
    * ни того, ни другого — `travel is None`, расчёт по координатам.

    `transit` разрешает досчитать недостающие участки общественного транспорта через
    `directions`. Это отдельный флаг, а не часть `url`, потому что стоит десятки минут
    (см. `fetch_transit_legs`); уже посчитанное берётся из кэша всегда.

    Функция никогда не бросает исключений из-за сети: недоступный сервис — это
    предупреждение в плане, а не отказ в расчёте.
    """
    path = Path(cache_path) if cache_path is not None else None
    cache = RoutingCache(path) if path is not None else None
    notes: list[str] = []
    if transit and not url:
        # Досчитывать нечем: без адреса сервиса идти некуда. Молчать об этом нельзя —
        # человек попросил расписания и вправе знать, что их не запрашивали.
        notes.append(
            "ORS: флаг расписаний задан, но адрес сервиса не указан — "
            "запрашивать нечего, берётся только то, что уже в кэше"
        )

    if url:
        client = OrsClient(
            url, api_key=api_key, max_routes_per_request=max_routes, timeout=timeout
        )
        travel = OrsTravelModel.for_scenario(
            scenario, client, cache=cache, refresh=refresh, transit=transit
        )
        return Routing(travel, client, cache, travel.warnings)

    if cache is not None and cache.stats()["legs"]:
        travel = OrsTravelModel.from_cache(
            scenario.settings,
            cache,
            departure=scenario_departure(scenario),
            modes=scenario_modes(scenario),
            points=collect_points(scenario),
        )
        notes.append(
            "ORS: расстояния взяты из сохранённого кэша маршрутного сервиса "
            f"({cache.stats()['legs']} участков), сервис не опрашивался"
        )
        return Routing(travel, None, cache, notes + list(travel.warnings))

    return Routing(None, None, cache, notes)


PT_WALKING_TIME = "PT30M"
"""Сколько разрешено идти пешком до остановки и от неё при построении маршрута.

Дефолт ORS — 15 минут, и с ним часть участков не строится вовсе: сервис отвечает
`PT entry and exit points found but no connecting route` и прямо советует увеличить
это время. Заметнее всего это на окраинах и в области, где до ближайшей остановки идти
дольше четверти часа. Проверено на паре, которая с 15 минутами не строилась: с 30
минутами — маршрут за 36 минут, с 60 тот же самый, то есть 30 уже достаточно.
"""


def _geometry_options(profile: str) -> dict[str, Any]:
    """Параметры `directions`, зависящие от профиля."""
    if profile in NO_MATRIX_PROFILES:
        return {"walking_time": PT_WALKING_TIME}
    return {}


PROFILE_STRIKES = 3
"""Сколько несистемных отказов подряд по одному профилю выключают запросы по нему.

Смысл счётчика — отличить «профиль на инстансе не собран» от «конкретная пара точек
не строится»: в первом случае продолжать бессмысленно, во втором — наоборот. Различие
делается по коду ошибки (см. `is_point_verdict`), а счётчик — страховка на случай,
когда ORS вернул что-то, чего мы не разбираем; любой успешный участок обнуляет его.
"""

REQUEST_LEVEL_CODES = frozenset({2000, 2001, 2002, 2003, 2006, 2011, 2012})
"""Коды ORS, относящиеся к САМОМУ запросу или профилю, а не к паре точек.

Разбор ответа: невалидный JSON, пропущенный или неразобранный параметр, недопустимое
значение (сюда же 2003 — «нет такого профиля»), неподдерживаемый формат выгрузки,
несовместимые и неизвестные параметры. Общее у них одно: ответ будет тот же самый на
любых координатах, поэтому продолжать перебор бессмысленно.

Список намеренно перечисляет то, что относится к запросу, а НЕ то, что относится к
точкам, — и это второй заход. Сначала перечислялись «коды про пару точек», и каждый
неучтённый код молча превращался в поломку профиля. Так вскрылись 2014 («PT exit point
cannot be reached» — вне фида прибытие) и 2013 («PT entry point…» — вне фида
отправление): 2538 пар «Юго-востока» ушли в отчёт как отказ сервиса с советом
пересчитать план, когда сервис поднимут (а он не падал), и `PROFILE_STRIKES` после
трёх подряд выключил геометрию общественного транспорта всему набору — построилось
2 участка вместо сотни.

Перечень «про запрос» конечен и не зависит от данных; перечень «про точки» растёт с
каждым новым типом местности, и угадать его заранее нельзя. Поэтому умолчание для
незнакомого кода теперь безопасное: считаем вердиктом о паре точек, то есть продолжаем
работать. Цена ошибки в эту сторону — несколько лишних запросов на прогреве; в обратную
— потерянная геометрия целого набора.
"""

POINT_VERDICT_CODES_SEEN = frozenset({2004, 2009, 2010, 2013, 2014, 2015})
"""Коды вердиктов о паре точек, реально наблюдавшиеся на нашем инстансе (ORS 10.0.0).

На решения не влияет (его принимает `is_point_verdict`) — это справка для человека:
2015 — «Route could not be found between points», 2004 — маршрут длиннее разрешённых
сервисом 500 км, 2009 и 2010 — точка вне графа, 2013 и 2014 — от адреса не дойти пешком
ни до одной остановки фида (отправление и прибытие соответственно). Всё это нормальные
ответы для адреса за пределами покрытия: Кашира с фидом наземного транспорта Москвы
не свяжется никогда.
"""


def is_point_verdict(code: int | None) -> bool:
    """Вердикт ли это о КОНКРЕТНОЙ паре точек (а не о запросе, профиле или связи).

    `None` — кода нет, значит сервис вообще не ответил: это обрыв связи, а не вердикт.
    """
    return code is not None and code not in REQUEST_LEVEL_CODES


GTFS_ROUTE_KINDS = {
    0: "tram", 1: "subway", 2: "rail", 3: "bus", 4: "ferry",
    5: "cable", 6: "gondola", 7: "funicular", 11: "trolleybus", 12: "monorail",
}
"""`route_type` из GTFS в наши коды. Значения — из спецификации GTFS; фид собирается
`tools/mosdata_to_gtfs.py`, и коды в нём выставлены по ней же."""


def _fetch_leg(
    client: OrsClient, profile: str, a: GeoPoint, b: GeoPoint, *, when: str | None = None
) -> tuple[float | None, float | None, list[list[float]], list[dict]]:
    """Один запрос `directions` на участок.

    Возвращает всё, что сервис сказал об участке: расстояние (км), время (мин), ломаную
    для карты и состав поездки для общественного транспорта. Разделять эти четыре вещи
    по разным запросам смысла нет — они приходят одним ответом, а запрос стоит секунды.

    Расстояние и время могут быть `None`: ответ без `summary` (или с нечисловым полем
    в нём) — это «сервис не сказал, сколько ехать», а вовсе не «ехать ноль». Раньше
    такой ответ подставлял нули, и пара точек сохранялась в кэш как бесплатная поездка
    через весь город. Линия при этом остаётся годной: карте `summary` не нужна.

    Неразбираемая геометрия, наоборот, — отказ участка (`OrsError`): рисовать по ней
    нечего, и вызывающая сторона заменит участок прямой.
    """
    options = _geometry_options(profile)
    if when is not None:
        options["departure"] = when
    response = client.directions(profile, (a, b), **options)
    features = response.get("features") or []
    if not features:
        raise OrsError("пустой ответ directions")
    feature = features[0]
    coordinates = (feature.get("geometry") or {}).get("coordinates")
    if not coordinates:
        raise OrsError("в ответе directions нет геометрии")
    line: list[list[float]] = []
    for point in coordinates:
        pair = point if isinstance(point, (list, tuple)) and len(point) >= 2 else ()
        lon = as_number(pair[0]) if pair else None
        lat = as_number(pair[1]) if pair else None
        if lon is None or lat is None:
            raise OrsError("в ответе directions неразбираемая геометрия")
        line.append([lon, lat])
    if len(line) < 2:
        raise OrsError("в ответе directions нет геометрии")
    properties = feature.get("properties") or {}
    summary = properties.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    metres = as_number(summary.get("distance"))
    seconds = as_number(summary.get("duration"))
    return (
        None if metres is None else metres / 1000.0,
        None if seconds is None else seconds / 60.0,
        line,
        _transit_legs(properties),
    )


def _transit_legs(properties: Mapping[str, Any]) -> list[dict]:
    """Состав поездки из ответа `directions`: пешие подходы и поездки в транспорте.

    ORS отдаёт его в `properties.legs` — это и есть ответ на вопрос «на чём ехать и где
    садиться». Здесь он только ужимается до нужных полей: идентификаторы рейса и фида
    диспетчеру не нужны, а в кэше заняли бы больше самого маршрута.

    Для остальных профилей раздела `legs` в ответе нет, и функция честно отдаёт пустой
    список: пеший маршрут «состоит» из самого себя.
    """
    result: list[dict] = []
    for leg in properties.get("legs") or []:
        if not isinstance(leg, Mapping):
            continue
        walking = leg.get("type") != "pt"
        stops = [
            str(s.get("name", "")) for s in (leg.get("stops") or []) if isinstance(s, Mapping)
        ]
        # Нечисловые длительность и расстояние обнуляются, а не роняют разбор: это
        # подпись к поездке для диспетчера, и терять из-за неё весь состав поездки
        # (а с ним и линию на карте) несоразмерно.
        minutes = as_number(leg.get("duration")) or 0.0
        metres = as_number(leg.get("distance")) or 0.0
        result.append({
            "kind": "walk" if walking else GTFS_ROUTE_KINDS.get(leg.get("route_type"), "bus"),
            "route": "" if walking else str(leg.get("route_short_name") or ""),
            "line": "" if walking else str(leg.get("route_long_name") or ""),
            "headsign": "" if walking else str(leg.get("trip_headsign") or ""),
            # `departure_location` у пешего участка — слово «Walk», а не остановка.
            "from": "" if walking else str(leg.get("departure_location") or ""),
            "to": "" if walking else (stops[-1] if stops else ""),
            "departure": leg.get("departure"),
            "arrival": leg.get("arrival"),
            "minutes": round(minutes / 60.0, 2),
            "km": round(metres / 1000.0, 4),
            # Перегонов на один меньше, чем остановок: первая — это посадка.
            "stops": max(len(stops) - 1, 0),
        })
    return result


class TransitFailures:
    """Почему пары не посчитались по расписанию. Разные причины — разные действия.

    Вердикт сервиса по КОНКРЕТНОЙ паре («точка вне графа», «до остановки не дойти») —
    это граница фида: Кашира с московским фидом не свяжется никогда, чинить тут нечего,
    и план настолько точен, насколько это вообще возможно.

    Отказ связи — это выключенный, перегруженный или отвалившийся по таймауту
    контейнер. Пары те же, отчёт был бы тот же, а смысл противоположный: числа станут
    правильными сами собой, как только сервис поднимут, и план стоит пересчитать.

    Вердикт сервиса НЕ про пару точек («нет такого профиля») — третий случай: сервис
    отвечает, пересчёт плана не поможет, и смотреть надо конфигурацию инстанса. Свалить
    его в «границу фида» значило бы посоветовать смириться с тем, что чинится одной
    строкой в `ors-config.yml`.

    Раньше все они писались в план одной строкой «не связал по расписанию (адрес вне
    зоны действия фида)», и диспетчер не мог их различить: таймаут выглядел как Кашира.
    Поэтому причины считаются врозь и врозь же попадают в `warnings`.

    `reasons` — текст первого отказа в каждой группе: без него строки про отказ сервиса
    и про отклонённый запрос не отвечают на единственный возникающий вопрос — какой
    именно отказ.
    """

    __slots__ = ("outside", "outage", "rejected", "malformed", "reasons")

    KINDS = ("outside", "outage", "rejected", "malformed")

    def __init__(self) -> None:
        self.outside = 0
        """Вердикт сервиса по паре точек: адрес вне зоны действия фида."""
        self.outage = 0
        """Сервис не ответил: сеть, таймаут, 5xx без кода ORS в теле."""
        self.rejected = 0
        """Сервис ответил вердиктом, но не про пару точек: профиль, параметры запроса."""
        self.malformed = 0
        """Ответ 200, но без расстояния или времени — считать по нему нечего."""
        self.reasons: dict[str, str] = {}

    @property
    def total(self) -> int:
        return sum(getattr(self, kind) for kind in self.KINDS)

    def __bool__(self) -> bool:
        return bool(self.total)

    def count(self, kind: str, reason: str) -> None:
        setattr(self, kind, getattr(self, kind) + 1)
        self.reasons.setdefault(kind, reason)

    def notes(self, mode: TransportMode, when: str) -> list[str]:
        """Строки для `PlanResult.warnings` — по одной на каждую случившуюся причину."""
        title = TRANSPORT_TITLES[mode]
        lines: list[str] = []
        if self.outside:
            lines.append(
                f"ORS: {self.outside} пар точек сервис не связал по расписанию на "
                f"{when} — адрес вне зоны действия фида; они посчитаны по координатам"
            )
        if self.outage:
            lines.append(
                f"ORS: {self.outage} пар точек остались без расписания из-за отказа "
                f"сервиса ({self.reasons.get('outage') or 'связь потеряна'}) — они "
                f"посчитаны по координатам; «{title}» стоит пересчитать, когда сервис "
                "ответит"
            )
        if self.rejected:
            lines.append(
                f"ORS: {self.rejected} запросов расписания сервис отклонил "
                f"({self.reasons.get('rejected') or 'причина не указана'}) — это ответ "
                "про профиль или параметры, а не про адреса; пары посчитаны по "
                "координатам, и пересчёт плана тут не поможет"
            )
        if self.malformed:
            lines.append(
                f"ORS: по {self.malformed} парам точек сервис ответил без расстояния "
                "или времени в пути — они посчитаны по координатам"
            )
        return lines


def fetch_transit_legs(
    client: OrsClient,
    profile: str,
    points: Sequence[GeoPoint],
    when: str,
    *,
    workers: int = 8,
    on_progress: Callable[[int, int, int], None] | None = None,
    known: Mapping[tuple[str, str], tuple[float, float]] | None = None,
) -> tuple[dict[tuple[str, str], tuple[float, float]], TransitFailures]:
    """Матрица общественного транспорта, собранная по одному участку за раз.

    Почему не `/v2/matrix`: см. `NO_MATRIX_PROFILES` — у матрицы нет времени отправления,
    и она отвечает пешей доступностью. `directions` время принимает, но берёт одну пару
    точек за запрос, поэтому матрица здесь собирается перебором: для сотни точек это
    около десяти тысяч запросов.

    Это дорого — десятки минут, — и потому делается отдельным прогоном
    (`tools/ors_prefetch.py --transit`), а не при каждом расчёте. Результат ложится в
    кэш и дальше работает офлайн, ровно как матрицы остальных профилей.

    Запросы идут в несколько потоков: ORS их держит, а последовательный перебор той же
    сотни точек занял бы часы вместо минут. Порядок ответов на результат не влияет —
    ключ пары задаётся координатами, а не очередью.

    Пара, которую сервис не построил, в результат не попадает: для неё останется расчёт
    по координатам. Но ПОЧЕМУ она не построилась, записывается (см. `TransitFailures`) —
    граница фида и лежащий сервис дают одинаковый результат и совершенно разный вывод.
    """
    pairs = [
        (a, b) for a in points for b in points
        if point_key(a) != point_key(b)
        and (known is None or (point_key(a), point_key(b)) not in known)
    ]
    table: dict[tuple[str, str], tuple[float, float]] = {}
    failures = TransitFailures()
    if not pairs:
        return table, failures

    def one(pair: tuple[GeoPoint, GeoPoint]):
        a, b = pair
        try:
            km, minutes, _, _ = _fetch_leg(client, profile, a, b, when=when)
        except OrsError as exc:
            # Три исхода, и различает их код ORS. Кода нет вовсе — сервис не ответил
            # (сеть, таймаут, немой 5xx). Код есть и он про пару точек — граница фида.
            # Код есть, но про другое — сервис жив и отклонил сам запрос.
            if exc.code is None:
                kind = "outage"
            elif is_point_verdict(exc.code):
                kind = "outside"
            else:
                kind = "rejected"
            return None, kind, str(exc)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            # Ловим шире, чем `OrsError`, намеренно: прогон идёт полчаса и тысячами
            # запросов, и один ответ неожиданной формы не имеет права его уронить.
            return None, "malformed", str(exc)
        if km is None or minutes is None:
            # Пустой summary — это не поездка длиной ноль. Записать такую пару как
            # 0 км и 0 мин значит подарить инженеру бесплатный переезд через город,
            # причём в кэш, то есть навсегда.
            return None, "malformed", "ответ без summary"
        return ((point_key(a), point_key(b)), (km, minutes)), "", ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for index, (answer, kind, reason) in enumerate(pool.map(one, pairs), start=1):
            if answer is None:
                failures.count(kind, reason)
            else:
                key, value = answer
                table[key] = value
            if on_progress is not None and (index % 100 == 0 or index == len(pairs)):
                on_progress(index, len(pairs), failures.total)
    return table, failures


def _parse_moment(value: Any, zone: Any = None) -> datetime | None:
    """Момент из ответа ORS, переведённый в зону плана.

    ORS отдаёт времена рейсов в UTC (`…Z`), а в плане всё местное. Оставить как есть
    нельзя: диспетчер прочитает «сесть на автобус в 07:08» вместо 10:08 и решит, что
    расчёт сломан. Зона берётся у самого визита, а не задаётся константой, — тогда
    смена часового пояса в настройках доедет и сюда.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.astimezone(zone) if zone is not None and moment.tzinfo else moment


def _apply_transit(route: RouteResult, steps: Sequence[Sequence[Mapping[str, Any]]]) -> RouteResult:
    """Разложить состав поездок по визитам маршрута.

    Пешие участки по краям поездки не выбрасываются намеренно: «идти 12 минут до
    остановки» — половина ответа на вопрос, почему дорога заняла сорок минут, и без
    них список выглядел бы так, будто автобус подают к подъезду.
    """
    if not any(steps):
        return route
    visits = []
    for visit, legs in zip(route.visits, steps):
        zone = visit.departure_at.tzinfo
        visits.append(dc_replace(visit, transit=tuple(
            TransitLeg(
                kind=str(leg.get("kind") or "walk"),
                route=str(leg.get("route") or ""),
                line=str(leg.get("line") or ""),
                headsign=str(leg.get("headsign") or ""),
                from_stop=str(leg.get("from") or ""),
                to_stop=str(leg.get("to") or ""),
                departure_at=_parse_moment(leg.get("departure"), zone),
                arrival_at=_parse_moment(leg.get("arrival"), zone),
                minutes=float(leg.get("minutes") or 0.0),
                distance_km=float(leg.get("km") or 0.0),
                stops=int(leg.get("stops") or 0),
            )
            for leg in legs
        )))
    return dc_replace(route, visits=tuple(visits))


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

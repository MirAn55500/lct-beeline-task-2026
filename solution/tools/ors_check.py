"""Проверка инстанса openrouteservice: что он реально умеет.

Интеграция рассчитана на то, что сервис может быть собран без части профилей, а
`public-transport` на многих сборках не отвечает на матрицу. Гадать об этом не нужно —
скрипт спрашивает сам инстанс и печатает таблицу.

Запуск:
    python tools/ors_check.py
    python tools/ors_check.py --url http://localhost:8080/ors
    python tools/ors_check.py --url https://api.openrouteservice.org --key <ключ>

Код возврата 0, если хотя бы один профиль отвечает и на матрицу, и на маршрут.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner.enums import TRANSPORT_TITLES, TransportMode  # noqa: E402
from planner.models import MSK, GeoPoint  # noqa: E402
from planner.ors import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_PROFILES,
    NO_MATRIX_PROFILES,
    PT_DEPARTURE_HOUR,
    PT_WALKING_TIME,
    OrsClient,
    OrsError,
    as_number,
    transit_moment,
)

# Две точки в пределах Москвы: Медведково и Ясенево. Разные концы города и разные
# линии метро: пара строится любым профилем, но у общественного транспорта отвечает
# на главный вопрос — работает ли рельсовый каркас в фиде. Без метро этот маршрут
# занимает 151 минуту, с метро — около часа.
PROBE = (GeoPoint(lat=55.8875, lon=37.6375), GeoPoint(lat=55.6064, lon=37.5333))


def probe_departure() -> str:
    """Время отправления для пробы общественного транспорта.

    День — сегодняшний: проверять надо тот календарь, по которому фид действует прямо
    сейчас. Час — тот же опорный, что у планировщика, и через тот же `transit_moment`,
    иначе проба уехала бы на три часа мимо (ORS читает время без зоны как UTC).
    """
    local = datetime.combine(datetime.now(MSK).date(), time(hour=PT_DEPARTURE_HOUR), tzinfo=MSK)
    return transit_moment(local)


def _check(client: OrsClient, profile: str) -> tuple[str, str]:
    """Пара «матрица, маршрут»: либо результат, либо причина отказа."""
    schedule_based = profile in NO_MATRIX_PROFILES
    try:
        payload = client.matrix(profile, PROBE)
        km = as_number(payload["distances"][0][1])
        seconds = as_number(payload["durations"][0][1])
        minutes = (seconds or 0.0) / 60.0
        if km is None or seconds is None:
            # null — недостижимо, не число — ответ 200 с мусором в поле. Для проверки
            # инстанса это одно и то же: чисел, на которые можно опереться, нет.
            matrix = "ok  (недостижимо)"
        elif schedule_based:
            # Ответ приходит, но это пешее время: у /matrix нет времени отправления.
            # Показывать его как «ok» — значит предлагать взять заведомо неверные числа.
            matrix = f"пешком! {km:.2f} км / {minutes:.0f} мин"
        else:
            matrix = f"ok  {km:.2f} км / {minutes:.0f} мин"
    except (OrsError, KeyError, IndexError, TypeError) as exc:
        matrix = f"нет ({_short(exc)})"

    options = {}
    if schedule_based:
        # Ровно тот запрос, которым планировщик считает общественный транспорт:
        # со временем отправления, иначе ответ снова придёт пешим.
        options = {"walking_time": PT_WALKING_TIME, "departure": probe_departure()}
    try:
        response = client.directions(profile, PROBE, **options)
        feature = response["features"][0]
        if schedule_based:
            directions = _transit_summary(feature["properties"])
        else:
            points = len(feature["geometry"]["coordinates"])
            directions = f"ok  {points} точек линии"
    except (OrsError, KeyError, IndexError, TypeError) as exc:
        directions = f"нет ({_short(exc)})"

    return matrix, directions


def _transit_summary(properties: dict) -> str:
    """Итог поездки по расписанию: время и на чём ехать.

    Это и есть проверка фида. Пустой список поездок при построенном маршруте означает,
    что расписания не загрузились и сервис провёл человека пешком, — такой ответ выглядит
    успешным, но им не является.
    """
    seconds = as_number((properties.get("summary") or {}).get("duration"))
    # Ответ без длительности — не поездка длиной ноль, а «сервис не сказал»: показать
    # тут «0 мин» значило бы выдать сломанный ответ за самый быстрый маршрут.
    duration = "время не указано" if seconds is None else f"{seconds / 60.0:.0f} мин"
    rides = [
        leg for leg in properties.get("legs") or []
        if isinstance(leg, dict) and leg.get("type") == "pt"
    ]
    if not rides:
        return f"пешком! {duration}, ни одного рейса — расписания не загрузились"
    names = ", ".join(str(leg.get("route_short_name") or "?") for leg in rides[:4])
    tail = "…" if len(rides) > 4 else ""
    return f"ok  {duration} по расписанию: {names}{tail}"


def _short(exc: Exception, limit: int = 60) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="адрес инстанса ORS")
    parser.add_argument("--key", help="ключ API (нужен только для публичного сервиса)")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    client = OrsClient(args.url, api_key=args.key, timeout=args.timeout, retries=0)
    print(f"Инстанс: {client.base_url}\n")
    print(f"{'способ передвижения':<24} {'профиль ORS':<20} {'матрица':<28} маршрут")
    print("─" * 110)

    usable = 0
    geometry_only = False
    for mode in TransportMode:
        profile = DEFAULT_PROFILES.get(mode, "—")
        matrix, directions = _check(client, profile)
        # У общественного транспорта источник чисел — маршрут, а не матрица, поэтому
        # и пригодность профиля определяется по нему: требовать «ok» от матрицы,
        # которую планировщик заведомо не берёт, значило бы считать рабочий профиль
        # сломанным.
        needed = (directions,) if profile in NO_MATRIX_PROFILES else (matrix, directions)
        if all(answer.startswith("ok") for answer in needed):
            usable += 1
        if matrix.startswith("пешком!"):
            geometry_only = True
        print(f"{TRANSPORT_TITLES[mode]:<24} {profile:<20} {matrix:<28} {directions}")

    print()
    if usable:
        print(f"Готовы к использованию профили: {usable} из {len(TransportMode)}.")
        print("Остальные способы передвижения планировщик посчитает по координатам")
        print("и напишет об этом в warnings плана — расчёт не сломается.")
        if geometry_only:
            print()
            print("Пометка «пешком!» в колонке матрицы — норма: у /matrix нет времени")
            print("отправления, и она отдаёт пешее время. Планировщик такую матрицу не")
            print("берёт, а считает общественный транспорт через /directions со временем")
            print("отправления — это колонка «маршрут» (planner/ors.py: NO_MATRIX_PROFILES).")
            print()
            print("А вот «пешком!» в колонке маршрута — уже поломка: профиль собран, но")
            print("расписания в него не попали. Проверьте фид: python tools/gtfs_check.py")
        return 0

    print("Ни один профиль не ответил. Проверьте, что контейнер поднят и графы собраны:")
    print("  docker compose -f deploy/ors/docker-compose.yml logs -f")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

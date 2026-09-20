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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner.enums import TRANSPORT_TITLES, TransportMode  # noqa: E402
from planner.models import GeoPoint  # noqa: E402
from planner.ors import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_PROFILES,
    GEOMETRY_ONLY_PROFILES,
    OrsClient,
    OrsError,
)

# Две точки в пределах Москвы: Таганка и Автозаводская. Достаточно близко, чтобы
# маршрут строился любым профилем, включая пеший.
PROBE = (GeoPoint(lat=55.742, lon=37.655), GeoPoint(lat=55.707, lon=37.657))


def _check(client: OrsClient, profile: str) -> tuple[str, str]:
    """Пара «матрица, маршрут»: либо результат, либо причина отказа."""
    try:
        payload = client.matrix(profile, PROBE)
        km = payload["distances"][0][1]
        minutes = payload["durations"][0][1] / 60.0
        if km is None:
            matrix = "ok  (недостижимо)"
        elif profile in GEOMETRY_ONLY_PROFILES:
            # Ответ приходит, но это пешее время: у /matrix нет времени отправления.
            # Показывать его как «ok» — значит предлагать взять заведомо неверные числа.
            matrix = f"пешком! {km:.2f} км / {minutes:.0f} мин"
        else:
            matrix = f"ok  {km:.2f} км / {minutes:.0f} мин"
    except (OrsError, KeyError, IndexError, TypeError) as exc:
        matrix = f"нет ({_short(exc)})"

    try:
        response = client.directions(profile, PROBE)
        points = len(response["features"][0]["geometry"]["coordinates"])
        directions = f"ok  {points} точек линии"
    except (OrsError, KeyError, IndexError, TypeError) as exc:
        directions = f"нет ({_short(exc)})"

    return matrix, directions


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
        if matrix.startswith("ok") and directions.startswith("ok"):
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
            print("Пометка «пешком!» — матрица профиля не учитывает расписания и отдаёт")
            print("пешее время. Планировщик такую матрицу не берёт: время и расстояние")
            print("считаются по координатам, а линия на карте строится через /directions,")
            print("где расписания учитываются (planner/ors.py: GEOMETRY_ONLY_PROFILES).")
        return 0

    print("Ни один профиль не ответил. Проверьте, что контейнер поднят и графы собраны:")
    print("  docker compose -f deploy/ors/docker-compose.yml logs -f")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Прогрев кэша маршрутного сервиса: расстояния по улицам и геометрия маршрутов.

Зачем: смысл тот же, что у `tools/geocode.py`. Один раз сходили в openrouteservice,
сложили ответы в `data/routing_cache.json` — дальше расчёт идёт офлайн, детерминированно
и без поднятого контейнера. На защите это означает, что реальные расстояния по улицам
работают даже без сети.

Запуск:
    python tools/ors_prefetch.py                         # все три региона, матрицы
    python tools/ors_prefetch.py --region east           # один регион
    python tools/ors_prefetch.py --with-geometry         # ещё и линии маршрутов плана
    python tools/ors_prefetch.py --transit               # ещё и расписания транспорта
    python tools/ors_prefetch.py --transit --date 2026-09-21   # на конкретный день
    python tools/ors_prefetch.py --url http://host:8081/ors
    python tools/ors_prefetch.py --dry-run               # что будет запрошено

Матрица считается «все со всеми» по точкам сценария: старты инженеров плюс адреса
заявок. Для набора из ~100 точек это ~10 000 пар на профиль — один-два запроса.

Общественный транспорт — исключение, и `--transit` вынесен отдельным флагом именно
поэтому. Его матрицу приходится собирать по одной паре точек за запрос (у `/v2/matrix`
нет времени отправления, см. `planner/ors.py: NO_MATRIX_PROFILES`), то есть теми же
~4 000 пар, но четырьмя тысячами запросов вместо одного. На нашем инстансе это около
получаса на все три региона в восемь потоков. Платится один раз: дальше расписания
лежат в кэше, и расчёт идёт по ним офлайн, без флага и без контейнера.

Раздел кэша расписаний включает ДАТУ отправления: одна и та же пара точек в будний
день и в воскресенье — разные интервалы движения. Поэтому у прогрева есть `--date`: без
него греется день из самой выгрузки, а план могут строить на другой. План, не нашедший
своей даты, об этом скажет (и подставит ближайший тот же день недели как приближение),
но точные числа даёт только прогрев на нужный день. `--date` можно повторять.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner import Algorithm, plan  # noqa: E402
from planner.enums import TRANSPORT_TITLES  # noqa: E402
from planner.io_csv import build_scenario, find_dataset_dir  # noqa: E402
from planner.ors import (  # noqa: E402
    DEFAULT_BASE_URL,
    OrsClient,
    OrsError,
    OrsTravelModel,
    RoutingCache,
    attach_route_geometry,
    collect_points,
    departure_moment,
    moment_title,
    scenario_departure,
    scenario_modes,
)

SOURCES = {
    "east": ("Восток", "Восток Синтетические данные.csv", "Восток Контрольное распределение..csv"),
    "southeast": (
        "Юго-восток",
        "Юго-восток Синтетические данные.csv",
        "Юго-восток Контрольное распределение.csv",
    ),
    "southcentral": (
        "Югоцентр",
        "Югоцентр Синтетические данные.csv",
        "Югоцентр Контрольное распределение..csv",
    ),
}

DATASET_DIR = find_dataset_dir() or (ROOT.parent / "Обезличивание")
CACHE_PATH = ROOT / "data" / "routing_cache.json"


def _scenario(region: str, shift: str, lunch: str):
    title, synthetic, control = SOURCES[region]
    source = DATASET_DIR / synthetic
    if not source.exists():
        return None, title
    lunch_t = None if lunch.lower() in {"нет", "no", "none"} else tuple(lunch.split("-"))
    scenario, _notes = build_scenario(
        source,
        control_csv=DATASET_DIR / control,
        region_key=region,
        shift=tuple(shift.split("-")),
        lunch=lunch_t,
        name=title,
    )
    return scenario, title


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=sorted(SOURCES), action="append", help="можно повторять")
    parser.add_argument("--url", default=DEFAULT_BASE_URL)
    parser.add_argument("--key", help="ключ API (только для публичного сервиса)")
    parser.add_argument("--cache", type=Path, default=CACHE_PATH)
    parser.add_argument("--shift", default="09:00-22:00")
    parser.add_argument("--lunch", default="13:00-14:00")
    parser.add_argument("--limit", type=float, default=5.0, help="лимит поиска, секунд")
    parser.add_argument("--with-geometry", action="store_true", help="ещё и линии маршрутов")
    parser.add_argument(
        "--transit",
        action="store_true",
        help="ещё и общественный транспорт по расписанию (десятки минут, см. ниже)",
    )
    parser.add_argument(
        "--date",
        action="append",
        metavar="ГГГГ-ММ-ДД",
        help="день, на который греть расписания (можно повторять); "
             "по умолчанию — день из выгрузки",
    )
    parser.add_argument(
        "--transit-workers",
        type=int,
        default=8,
        help="сколько запросов расписания держать одновременно",
    )
    parser.add_argument("--refresh", action="store_true", help="перезапросить уже закэшированное")
    parser.add_argument("--dry-run", action="store_true", help="показать план работ и выйти")
    parser.add_argument(
        "--max-routes",
        type=int,
        default=25000,
        help="лимит maximum_routes инстанса; матрица режется на блоки под него",
    )
    args = parser.parse_args()

    try:
        days = [_date.fromisoformat(value) for value in (args.date or [])]
    except ValueError as exc:
        parser.error(f"--date: {exc}")
    if days and not args.transit:
        parser.error("--date имеет смысл только вместе с --transit")

    regions = args.region or sorted(SOURCES)
    client = OrsClient(
        args.url, api_key=args.key, max_routes_per_request=args.max_routes, timeout=180.0
    )
    cache = RoutingCache(args.cache)
    print(f"Инстанс: {client.base_url}")
    print(f"Кэш:     {args.cache} ({cache.stats()['legs']} участков уже известно)\n")

    failures = 0
    for region in regions:
        scenario, title = _scenario(region, args.shift, args.lunch)
        if scenario is None:
            print(f"· {title}: выгрузка не найдена в {DATASET_DIR} — пропускаю")
            continue

        points = collect_points(scenario)
        modes = scenario_modes(scenario)
        names = ", ".join(TRANSPORT_TITLES[m] for m in modes)
        pairs = len(points) * (len(points) - 1)
        print(f"· {title}: {len(points)} точек, режимы: {names} → {pairs} пар на режим")

        if args.dry_run:
            continue

        scenario.settings.time_limit_seconds = args.limit

        def progress(done: int, total: int, failed: int, title: str = title) -> None:
            share = done / total * 100 if total else 100.0
            print(f"    {title}: расписания {done}/{total} ({share:.0f}%), "
                  f"не связано {failed}", end="\r", flush=True)

        # Дни греются по очереди и каждый в свой раздел кэша: расписание зависит от
        # дня недели, и складывать понедельник с воскресеньем в одну таблицу нельзя.
        offset = scenario.settings.timezone_offset_hours
        moments = (
            [departure_moment(day, offset) for day in days]
            if days else [scenario_departure(scenario)]
        )
        travel = None
        for moment in moments:
            if len(moments) > 1 or days:
                print(f"    день отправления: {moment_title(moment, offset)}")
            travel = OrsTravelModel.for_scenario(
                scenario, client, cache=cache, refresh=args.refresh,
                transit=args.transit, transit_workers=args.transit_workers,
                on_progress=progress if args.transit else None,
                departure=moment,
            )
            if args.transit:
                print()  # закрыть строку прогресса
            for warning in travel.warnings:
                print(f"    ! {warning}")
                failures += 1

        if args.with_geometry:
            # Греются ОБА плана. Карта показывает базовый и оптимизированный по
            # переключателю, и если линии есть только у одного, сравнение читается как
            # «улицы против прямых» — то есть как подтасовка в пользу оптимизации.
            # Геометрия кэшируется участками, но рассчитывать на то, что второй план
            # возьмёт их у первого, не стоит: планы развозят разные заявки разными
            # инженерами, и общих участков у них замерено 2%.
            plans = ((Algorithm.BASELINE, "базовый"), (Algorithm.OPTIMIZED, "оптимизированный"))
            for algorithm, label in plans:
                try:
                    result = plan(scenario, algorithm, travel=travel)
                    before = cache.stats()["geometry"]
                    attach_route_geometry(result, client, cache=cache, refresh=args.refresh)
                    added = cache.stats()["geometry"] - before
                    print(f"    геометрия ({label}): +{added} участков")
                except OrsError as exc:
                    print(f"    ! геометрия ({label}) не построена: {exc}")
                    failures += 1

        stats = cache.stats()
        print(f"    в кэше: {stats['legs']} участков матрицы, "
              f"{stats['geometry']} участков геометрии, "
              f"{stats['transit']} поездок на транспорте")

    if args.dry_run:
        print("\nЭто был --dry-run: в сервис не ходили, кэш не менялся.")
        return 0

    if cache.dirty:
        path = cache.save()
        size_mb = path.stat().st_size / 1024 / 1024
        print(f"\nКэш сохранён: {path} ({size_mb:.1f} МБ)")
    else:
        print("\nНовых данных нет, кэш не изменился.")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

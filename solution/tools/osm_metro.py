"""Извлечение линий метро, МЦК и МЦД из выгрузки OpenStreetMap.

Зачем отдельный инструмент
--------------------------
Портал data.mos.ru отдаёт станции метро («Станции метро.csv»), их вестибюли и рейтинг,
но **не отдаёт порядок станций на линии** — а без порядка расписание не собрать.
У старых линий порядок совпадает с кодом станции (86…109 — Калужско-Рижская), у новых
уже нет: у Большой кольцевой коды идут 230, 238, 242, 298, 307, 312…, потому что
станции попадали в справочник по мере открытия. Восстановить порядок геометрией тоже
нельзя: два кольца и ветка Филёвской ломают любую сортировку «вдоль линии».

В OSM порядок задан явно — отношением `type=route` с упорядоченными участниками.
Оттуда же берутся станции новых линий (Троицкая, Рублёво-Архангельская), которых в
выгрузке портала ещё нет.

Что берётся
-----------
Отношения `route=subway` сети «Московский метрополитен» (16 линий), `route=train` той
же сети (МЦК) и сети «МЦД» (диаметры D1–D4). Трамвай 14 и «Аэроэкспресс» под фильтр
не попадают: первый — обычный маршрут наземной сети, он уже есть в выгрузках портала,
второй — коммерческий экспресс, инженеру он не транспорт.

Результат — `data/метро.json`: линии, направления, упорядоченные станции с
координатами. Файл маленький и лежит в репозитории, поэтому `tools/mosdata_to_gtfs.py`
собирает фид без osmium и без выгрузки OSM на 877 МБ. Перезапускать этот скрипт нужно
только при обновлении выгрузки.

Запуск:
    pip install osmium
    python tools/osm_metro.py
    python tools/osm_metro.py --pbf deploy/ors/files/region.osm.pbf --out data/метро.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PBF = ROOT / "deploy" / "ors" / "files" / "region.osm.pbf"
DEFAULT_OUT = ROOT / "data" / "метро.json"

# Сеть в OSM -> как мы её называем и каким видом транспорта считаем.
# Код вида — GTFS `route_type`: 1 метро, 2 пригородный рельсовый транспорт.
NETWORKS = {
    ("subway", "Московский метрополитен"): ("metro", 1),
    ("train", "Московский метрополитен"): ("mcc", 2),   # МЦК: в OSM это route=train
    ("train", "МЦД"): ("mcd", 2),
}

MIN_STATIONS = 3
"""Короче трёх станций — служебная связка вроде МЦД-4А, а не линия."""

EARTH_RADIUS_KM = 6371.0088


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = lat2 - lat1
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


# --------------------------------------------------------------------------------------
# Путь к выгрузке
# --------------------------------------------------------------------------------------


def ascii_path(path: Path) -> tuple[str, Path | None]:
    """Путь к файлу, который примет osmium, и каталог-связку на удаление.

    osmium открывает файл средствами C++ и на Windows передаёт имя в кодировке ANSI:
    кириллица в пути («ЛЦТ 2026») превращается в мусор, и открытие падает с «The system
    cannot find the file specified» — при том, что Python этот же файл читает свободно.

    Копированием это не обойти: выгрузка весит 877 МБ. Поэтому во временном каталоге
    создаётся junction (`mklink /J`) на каталог выгрузки: прав администратора он не
    требует, работает между томами и не занимает места. Связка удаляется после разбора,
    сам файл не трогается.
    """
    if path.name.isascii() and str(path.parent).isascii():
        return str(path), None
    if os.name != "nt":
        # На POSIX кириллица в пути проблемы не создаёт — обходной путь не нужен.
        return str(path), None
    root = Path(tempfile.mkdtemp(prefix="osm_metro_"))
    link = root / "src"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(path.parent)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "не удалось создать связку для пути с кириллицей: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return str(link / path.name), root


def drop_link(root: Path | None) -> None:
    """Снять связку. Именно `rmdir`, а не `shutil.rmtree`: удалять надо саму связку."""
    if root is None:
        return
    subprocess.run(["cmd", "/c", "rmdir", str(root / "src")], capture_output=True)
    try:
        root.rmdir()
    except OSError:
        pass


# --------------------------------------------------------------------------------------
# Разбор выгрузки
# --------------------------------------------------------------------------------------


def read_routes(pbf: str) -> list[dict]:
    """Отношения-маршруты нужных сетей: теги и участники в порядке следования."""
    import osmium

    class Handler(osmium.SimpleHandler):
        def __init__(self) -> None:
            super().__init__()
            self.found: list[dict] = []

        def relation(self, relation) -> None:  # noqa: ANN001 - тип приходит из osmium
            tags = relation.tags
            if tags.get("type") != "route":
                return
            key = (tags.get("route"), tags.get("network"))
            if key not in NETWORKS:
                return
            kind, route_type = NETWORKS[key]
            self.found.append({
                "id": relation.id,
                "kind": kind,
                "route_type": route_type,
                "ref": (tags.get("ref") or "").strip(),
                "name": (tags.get("name") or "").strip(),
                "colour": (tags.get("colour") or "").strip(),
                # Роль `stop` — точка остановки поезда (`public_transport=stop_position`).
                # Платформы идут отдельными участниками и повторяют тот же порядок, но
                # у части станций отсутствуют, поэтому опираемся на `stop`.
                "stops": [
                    m.ref for m in relation.members
                    if m.type == "n" and m.role.startswith("stop")
                ],
            })

    handler = Handler()
    handler.apply_file(pbf)
    return handler.found


def read_nodes(pbf: str, wanted: set[int]) -> dict[int, dict]:
    """Координаты и названия нужных узлов. Отдельным проходом: узлы в PBF идут первыми."""
    import osmium

    class Handler(osmium.SimpleHandler):
        def __init__(self) -> None:
            super().__init__()
            self.found: dict[int, dict] = {}

        def node(self, node) -> None:  # noqa: ANN001 - тип приходит из osmium
            if node.id not in wanted:
                return
            self.found[node.id] = {
                "name": (node.tags.get("name") or "").strip(),
                "lat": round(node.location.lat, 6),
                "lon": round(node.location.lon, 6),
            }

    handler = Handler()
    handler.apply_file(pbf)
    return handler.found


# --------------------------------------------------------------------------------------
# Сборка линий
# --------------------------------------------------------------------------------------


def pick_directions(routes: list[dict]) -> list[dict]:
    """Два основных хода линии из всех её отношений.

    У большинства линий отношений ровно два — туда и обратно. У МЦД-4 их девять: кроме
    полного хода есть укороченные (Марьина Роща — Апрелевка и подобные). Полный ход
    всегда длиннее укороченного, поэтому отбор идёт по числу станций.

    Второй ход обязан отличаться от первого, и проверять это по первой станции нельзя:
    у кольцевых линий маршрут замкнут и начинается там же, где заканчивается. Различие
    даёт пара «первая станция + вторая»: у внешнего и внутреннего кольца вторая разная.
    """
    ordered = sorted(routes, key=lambda r: (-len(r["stops"]), r["id"]))
    chosen: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for route in ordered:
        stops = route["stops"]
        if len(stops) < MIN_STATIONS:
            continue
        key = (stops[0], stops[1])
        if key in seen:
            continue
        seen.add(key)
        chosen.append(route)
        if len(chosen) == 2:
            break
    return chosen


_DIRECTION_LABEL = re.compile(r"\(([^)]*)\)\s*$")


def _line_name(relation_name: str, ref: str) -> str:
    """Название линии без хода: «Калужско-Рижская линия: А → Б» -> «Калужско-Рижская линия».

    У радиальных линий ход дописан через двоеточие, у кольцевых — скобкой в конце
    («Кольцевая линия (внешнее кольцо)»). Убираем оба вида, иначе название направления
    попадёт в название линии и карта подпишет кольцо дважды.
    """
    head = _DIRECTION_LABEL.sub("", relation_name.split(":")[0]).strip()
    return head or f"Линия {ref}"


def _direction_label(relation_name: str) -> str:
    """Ход кольцевой линии: «Кольцевая линия (внешнее кольцо)» -> «внешнее кольцо».

    У кольца конечной нет, поэтому назвать ход по последней станции нельзя: обе
    подписались бы одинаково. Единственное, что их различает, — это подпись в скобках.
    """
    match = _DIRECTION_LABEL.search(relation_name.strip())
    return match.group(1).strip() if match else ""


def build(pbf_path: Path, out: Path) -> int:
    try:
        import osmium  # noqa: F401
    except ImportError:
        print("Нужен пакет osmium: pip install osmium")
        return 1
    if not pbf_path.exists():
        print(f"Нет выгрузки OSM: {pbf_path}")
        print("Взять её можно скриптом deploy/ors/download-osm.sh")
        return 1

    pbf, link_root = ascii_path(pbf_path)
    try:
        print(f"Выгрузка: {pbf_path} ({pbf_path.stat().st_size / 1024 / 1024:.0f} МБ)")
        print("    проход по отношениям…")
        routes = read_routes(pbf)
        print(f"    маршрутных отношений нужных сетей: {len(routes)}")
        if not routes:
            print("    ! ни одной линии не найдено — проверьте, что выгрузка покрывает Москву")
            return 1

        wanted = {ref for route in routes for ref in route["stops"]}
        print(f"    проход по узлам ({len(wanted)} остановочных пунктов, минуты)…")
        nodes = read_nodes(pbf, wanted)
    finally:
        drop_link(link_root)

    missing = wanted - set(nodes)
    if missing:
        print(f"    ! узлов не нашлось в выгрузке: {len(missing)}")

    by_ref: dict[tuple[str, str], list[dict]] = {}
    for route in routes:
        by_ref.setdefault((route["kind"], route["ref"]), []).append(route)

    lines = []
    for (kind, ref), group in sorted(by_ref.items()):
        directions = []
        for route in pick_directions(group):
            stations = [
                {"osm_id": node_id, **nodes[node_id]}
                for node_id in route["stops"]
                if node_id in nodes
            ]
            if len(stations) < MIN_STATIONS:
                continue
            # Пункт назначения — последняя станция хода. В `name` отношения он тоже есть,
            # но разделитель в OSM плавает («→», «=>»), и разбирать текст ненадёжно.
            # У кольца последняя станция совпадает с первой, и туда идёт подпись хода.
            label = _direction_label(route["name"])
            closed = stations[0]["name"] == stations[-1]["name"]
            directions.append({
                "headsign": (label if closed and label else stations[-1]["name"]),
                "stations": stations,
            })
        if not directions:
            continue
        head = group[0]
        first = directions[0]["stations"]
        lines.append({
            "kind": kind,
            "ref": ref,
            "route_type": head["route_type"],
            "name": _line_name(head["name"], ref),
            "colour": head["colour"],
            # Кольцо замкнуто: последняя станция хода совпадает с первой.
            "circular": first[0]["name"] == first[-1]["name"],
            "directions": directions,
        })

    payload = {
        "source": pbf_path.name,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lines": lines,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    _report(lines, out)
    return 0


def _report(lines: list[dict], out: Path) -> None:
    print(f"\nСобрано: {out} ({out.stat().st_size / 1024:.0f} КБ)")
    stations = hops = 0
    span = 0.0
    for line in lines:
        row = line["directions"][0]["stations"]
        legs = [
            haversine_km((a["lat"], a["lon"]), (b["lat"], b["lon"]))
            for a, b in zip(row, row[1:])
        ]
        stations += len(row)
        hops += len(legs)
        span += sum(legs)
        ring = " кольцо" if line["circular"] else ""
        print(
            f"    {line['ref']:>4}  {len(row):>3} ст.  {sum(legs):6.1f} км  "
            f"ходов {len(line['directions'])}{ring}  {line['name']}"
        )
    print(
        f"\n    линий: {len(lines)}, станций (с учётом пересадочных узлов по разу на линию): "
        f"{stations}, перегонов: {hops}, длина сети: {span:.0f} км"
    )
    print("\nДальше: python tools/mosdata_to_gtfs.py")


def main() -> int:
    parser = argparse.ArgumentParser(description="Линии метро, МЦК и МЦД из выгрузки OSM")
    parser.add_argument("--pbf", type=Path, default=DEFAULT_PBF, help="выгрузка OpenStreetMap")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="куда положить JSON")
    args = parser.parse_args()
    return build(args.pbf, args.out)


if __name__ == "__main__":
    raise SystemExit(main())

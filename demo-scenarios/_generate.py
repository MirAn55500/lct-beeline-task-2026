"""Сценарии с нуля: инженеры + заявки на текущую дату, регион Юго-восток."""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(r"D:/Downloads")
OUT = Path(__file__).resolve().parent

# Стенд проверяем «сегодня» — дата из сессии пользователя.
DAY = date(2026, 9, 28)
DAY_STR = DAY.strftime("%d.%m.%Y")  # 28.09.2026
REGION = "Юго-восток"
OFFICE = "г. Москва, ул Бирюлёвская, д 1с1"
BRIGADE = "Бригада Юго-восток"

TICKET_HEADER = [
    "Заявка",
    "Тип заявки BK",
    "Статус BK",
    "Тип заявки HD",
    "Начало",
    "Окончание",
    "Район",
    "Адрес",
    "Бригада",
    "Подключение",
    "Гигабитное подключение",
]

ENGINEER_HEADER = [
    "ФИО",
    "Бригада",
    "Квалификация",
    "Навыки",
    "Транспорт",
    "Начало смены",
    "Конец смены",
    "Адрес старта",
]

# Как в planner.io_csv._SKILL_SETS / _TRANSPORT_SHARES и UI personnel/mocks.
ENGINEERS: list[dict[str, str]] = [
    {
        "ФИО": "Артём Соколов",
        "Квалификация": "Мастер",
        "Навыки": "Работы на подключение и дозаказы",
        "Транспорт": "Пешеход",
    },
    {
        "ФИО": "Мария Белова",
        "Квалификация": "Бывалый",
        "Навыки": "Локальные работы",
        "Транспорт": "Общ. транспорт",
    },
    {
        "ФИО": "Игорь Кузнецов",
        "Квалификация": "Новичок",
        "Навыки": "Работы на подключение и дозаказы, Локальные работы",
        "Транспорт": "Пешеход",
    },
    {
        "ФИО": "Елена Орлова",
        "Квалификация": "Мастер",
        "Навыки": "Работы на подключение и дозаказы, Аварийные работы",
        "Транспорт": "Общ. транспорт",
    },
    {
        "ФИО": "Павел Морозов",
        "Квалификация": "Бывалый",
        "Навыки": "Локальные работы, Аварийные работы",
        "Транспорт": "Автомобиль",
    },
    {
        "ФИО": "Анна Смирнова",
        "Квалификация": "Новичок",
        "Навыки": "Работы на подключение и дозаказы, Локальные работы, Аварийные работы",
        "Транспорт": "Пешеход",
    },
    {
        "ФИО": "Дмитрий Волков",
        "Квалификация": "Мастер",
        "Навыки": "Работы на подключение и дозаказы",
        "Транспорт": "Общ. транспорт",
    },
    {
        "ФИО": "Ольга Новикова",
        "Квалификация": "Бывалый",
        "Навыки": "Локальные работы",
        "Транспорт": "Автомобиль",
    },
    {
        "ФИО": "Сергей Лебедев",
        "Квалификация": "Новичок",
        "Навыки": "Работы на подключение и дозаказы, Локальные работы",
        "Транспорт": "Пешеход",
    },
    {
        "ФИО": "Наталья Козлова",
        "Квалификация": "Мастер",
        "Навыки": "Работы на подключение и дозаказы, Аварийные работы",
        "Транспорт": "Общ. транспорт",
    },
    {
        "ФИО": "Алексей Попов",
        "Квалификация": "Бывалый",
        "Навыки": "Локальные работы, Аварийные работы",
        "Транспорт": "Велосипед",
    },
    {
        "ФИО": "Юлия Федорова",
        "Квалификация": "Новичок",
        "Навыки": "Работы на подключение и дозаказы, Локальные работы, Аварийные работы",
        "Транспорт": "Автомобиль",
    },
]

LEGACY_GLOBS = (
    "01-east-*",
    "02-east-*",
    "01-southeast-*",
    "02-southeast-*",
    "06-southeast-*",
    "06-southcentral-*",
    "07-*",
)


def redate(value: str) -> str:
    """Любую ДД.ММ.ГГГГ в окне заявки меняет на DAY_STR."""
    return re.sub(r"\d{2}\.\d{2}\.\d{4}", DAY_STR, value)


def load_synthetic(path: Path) -> list[dict[str, str]]:
    text = None
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise RuntimeError(path)

    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Заявка"))
    rows: list[dict[str, str]] = []
    for raw in csv.DictReader(lines[start:], delimiter=";"):
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        external_id = row.get("Заявка", "")
        if not external_id or "адрес офиса" in external_id.lower():
            continue
        if not row.get("Начало") or not row.get("Окончание"):
            continue
        rows.append(
            {
                "Заявка": external_id,
                "Тип заявки BK": row.get("Тип заявки BK", ""),
                "Статус BK": row.get("Статус BK") or "Не отправлена",
                "Тип заявки HD": row.get("Тип заявки HD", ""),
                "Начало": redate(row.get("Начало", "")),
                "Окончание": redate(row.get("Окончание", "")),
                "Район": row.get("Район", ""),
                "Адрес": row.get("Адрес", ""),
                "Бригада": row.get("Бригада", ""),
                "Подключение": row.get("Подключение", ""),
                "Гигабитное подключение": row.get("Гигабитное подключение", "") or "Нет",
            }
        )
    return rows


def write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    body = ";".join(header) + "\n" + "\n".join(";".join(r.get(h, "") for h in header) for r in rows) + "\n"
    path.write_text("\ufeff" + body, encoding="utf-8")


def write_json(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def by_bk(rows: list[dict[str, str]], *needles: str) -> list[dict[str, str]]:
    keys = [n.lower() for n in needles]
    return [
        r
        for r in rows
        if any(k in r["Тип заявки BK"].lower() or k in r["Тип заявки HD"].lower() for k in keys)
    ]


def daytime(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        match = re.search(r"(\d{1,2}):(\d{2})$", row["Начало"])
        if not match:
            continue
        if 9 <= int(match.group(1)) <= 16:
            out.append(row)
    return out


def pick_diverse(pool: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    buckets = [
        by_bk(pool, "подключ"),
        by_bk(pool, "авария", "глобаль"),
        by_bk(pool, "локаль", "ремонт"),
        by_bk(pool, "дозаказ"),
    ]
    nonempty = [b for b in buckets if b]
    per = max(1, limit // max(1, len(nonempty)))
    result: list[dict[str, str]] = []
    for bucket in buckets:
        taken = 0
        for row in bucket:
            if row in result:
                continue
            result.append(row)
            taken += 1
            if taken >= per or len(result) >= limit:
                break
        if len(result) >= limit:
            return result
    for row in pool:
        if row not in result:
            result.append(row)
        if len(result) >= limit:
            break
    return result


def ticket(
    external_id: str,
    bk: str,
    hd: str,
    start_hm: str,
    end_hm: str,
    district: str,
    address: str,
    *,
    status: str = "Не отправлена",
    connection: str = "",
) -> dict[str, str]:
    return {
        "Заявка": external_id,
        "Тип заявки BK": bk,
        "Статус BK": status,
        "Тип заявки HD": hd,
        "Начало": f"{DAY_STR} {start_hm}",
        "Окончание": f"{DAY_STR} {end_hm}",
        "Район": district,
        "Адрес": address,
        "Бригада": "",
        "Подключение": connection,
        "Гигабитное подключение": "Нет",
    }


def clear_legacy() -> None:
    for pattern in LEGACY_GLOBS:
        for path in OUT.glob(pattern):
            path.unlink()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    clear_legacy()

    synths = {path.name: path for path in ROOT.rglob("*Синтетические*.csv")}
    southeast = load_synthetic(next(path for name, path in synths.items() if "Юго-восток" in name))
    southcentral = load_synthetic(next(path for name, path in synths.items() if "Югоцентр" in name))

    # --- 00 инженеры (загрузка / ручной ввод / seed) ---
    engineer_rows = [
        {
            **item,
            "Бригада": BRIGADE,
            "Начало смены": "09:00",
            "Конец смены": "22:00",
            "Адрес старта": OFFICE,
        }
        for item in ENGINEERS
    ]
    write_csv(OUT / "00-engineers-southeast.csv", ENGINEER_HEADER, engineer_rows)
    write_json(OUT / "00-engineers-southeast.json", engineer_rows)

    # --- заявки ---
    write_csv(OUT / "01-southeast-full.csv", TICKET_HEADER, southeast)
    write_json(OUT / "01-southeast-full.json", southeast)

    day = daytime(southeast) or southeast
    mini = pick_diverse(day, 10)
    # Аварии в исходнике часто с окном 0:01 — для мини подставляем нормальное дневное.
    mini = [
        r
        for r in mini
        if not (
            ("глобаль" in r["Тип заявки BK"].lower() or "авария" in r["Тип заявки BK"].lower())
            and "0:01" in r["Начало"]
        )
    ]
    sample = day[0]
    if not any("глобаль" in r["Тип заявки BK"].lower() or "авария" in r["Тип заявки BK"].lower() for r in mini):
        mini = mini[:9] + [
            ticket(
                "902100",
                "Авария",
                "Авария",
                "13:00",
                "15:00",
                sample["Район"],
                sample["Адрес"],
            )
        ]
    mini = mini[:10]
    write_csv(OUT / "02-southeast-mini.csv", TICKET_HEADER, mini)
    write_json(OUT / "02-southeast-mini.json", mini)

    sample = day or southeast
    fresh = [
        ticket(
            "901001",
            "Подключение",
            "Заказ подключения/Дозаказ оборудования",
            "15:00",
            "17:00",
            sample[0]["Район"],
            sample[0]["Адрес"],
            connection="FMC",
        ),
        ticket(
            "901002",
            "Локальная заявка",
            "Локальная",
            "16:00",
            "18:00",
            sample[1]["Район"],
            sample[1]["Адрес"],
        ),
        ticket(
            "901003",
            "Дозаказ",
            "Заказ подключения/Дозаказ оборудования",
            "14:00",
            "16:00",
            sample[2]["Район"],
            sample[2]["Адрес"],
        ),
    ]
    write_csv(OUT / "03-new-tickets-fix.csv", TICKET_HEADER, fresh)
    write_json(OUT / "03-new-tickets-fix.json", fresh)

    emergency = [
        ticket(
            "902001",
            "Авария",
            "Авария",
            "13:00",
            "15:00",
            sample[0]["Район"],
            sample[0]["Адрес"],
        )
    ]
    write_csv(OUT / "04-emergency-free.csv", TICKET_HEADER, emergency)
    write_json(OUT / "04-emergency-free.json", emergency)

    cancelled = [dict(r) for r in mini[:6]]
    cancelled.append(
        ticket(
            "903001",
            "Подключение",
            "Заказ подключения/Дозаказ оборудования",
            "11:00",
            "13:00",
            sample[0]["Район"],
            sample[0]["Адрес"],
            status="Отменена",
            connection="FMC",
        )
    )
    write_csv(OUT / "05-with-cancelled-row.csv", TICKET_HEADER, cancelled)

    sc_mini = pick_diverse(daytime(southcentral) or southcentral, 10)
    write_csv(OUT / "06-southcentral-mini.csv", TICKET_HEADER, sc_mini)
    write_json(OUT / "06-southcentral-mini.json", sc_mini)

    # инженеры Югоцентра — отдельный короткий набор, если смените регион
    sc_engineers = [
        {
            **ENGINEERS[i],
            "Бригада": "Бригада Югоцентр",
            "Начало смены": "09:00",
            "Конец смены": "22:00",
            "Адрес старта": "г.Москва проезд Симферопольский, д.7",
        }
        for i in range(8)
    ]
    write_csv(OUT / "00-engineers-southcentral.csv", ENGINEER_HEADER, sc_engineers)
    write_json(OUT / "00-engineers-southcentral.json", sc_engineers)

    print(f"day={DAY_STR} region={REGION}")
    print(f"engineers={len(engineer_rows)} tickets_full={len(southeast)} mini={len(mini)}")
    for path in sorted(OUT.iterdir()):
        if path.suffix in {".csv", ".json"}:
            print(f"  {path.name} ({path.stat().st_size})")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Разбор адресов и поиск данных: `tools.address`, `planner.io_csv` (SPEC §10).

`tools.address` — чистые функции без сети, поэтому покрываются плотно: именно здесь
жили настоящие баги разбора («д» в начале слова «Домодедово» съедала весь адрес;
«г. Кашира Кржижановского ул.» превращалось в улицу целиком). Такие ошибки не
падают, а тихо уводят координату на километры, и заметить их можно только тестом.

Отдельно — прогон по ВСЕМ уникальным адресам реальных выгрузок: он ловит регрессию
разбора на данных, которых нет в примерах.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

io_csv = pytest.importorskip("planner.io_csv", reason="модуль planner.io_csv ещё не готов")
address_mod = pytest.importorskip("tools.address", reason="модуль tools.address ещё не готов")

parse_address = address_mod.parse_address
build_queries = address_mod.build_queries
find_dataset_dir = io_csv.find_dataset_dir
normalize_address = io_csv.normalize_address

# Адрес с полноценным номером дома и хвост «, кв. N» — распознаются тестами
# независимо от регулярных выражений самого модуля.
HOUSE_WITH_NUMBER = re.compile(r"(?:^|[,\s])д\.?\s*\d", re.IGNORECASE)
APARTMENT_TAIL = re.compile(r",\s*кв\.?\s*\S", re.IGNORECASE)


# --------------------------------------------------------------------------
# find_dataset_dir
# --------------------------------------------------------------------------


def test_find_dataset_dir_locates_the_real_dataset():
    """В этом репозитории каталог выгрузок существует и обязан находиться сам.

    Жёсткий путь «на уровень выше solution/» ломается при первом же переносе папки,
    поэтому поиск идёт вверх по дереву.
    """
    found = find_dataset_dir()

    if found is None:
        pytest.skip("каталог «Обезличивание» отсутствует в этой копии репозитория")
    assert found.is_dir()
    assert found.name == io_csv.DATASET_DIR_NAME


def test_find_dataset_dir_climbs_up_from_a_nested_directory(tmp_path: Path):
    """Поиск поднимается вверх, а не смотрит только в текущий каталог."""
    (tmp_path / io_csv.DATASET_DIR_NAME).mkdir()
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)

    assert find_dataset_dir(deep) == tmp_path / io_csv.DATASET_DIR_NAME


def test_find_dataset_dir_accepts_a_file_as_a_starting_point(tmp_path: Path):
    """Точкой отсчёта служит и файл — модуль передаёт собственный `__file__`."""
    (tmp_path / io_csv.DATASET_DIR_NAME).mkdir()
    script = tmp_path / "pkg" / "module.py"
    script.parent.mkdir()
    script.write_text("# noop", encoding="utf-8")

    assert find_dataset_dir(script) == tmp_path / io_csv.DATASET_DIR_NAME


def test_find_dataset_dir_returns_none_when_there_is_nothing_to_find(tmp_path: Path):
    """Отсутствие данных — не ошибка: вызывающий сам решает, что делать (skip, заглушка)."""
    empty = tmp_path / "изолированный"
    empty.mkdir()

    assert find_dataset_dir(empty) is None


def test_find_dataset_dir_prefers_the_closest_match(tmp_path: Path):
    """Ближайший каталог вверх по дереву побеждает более дальний."""
    (tmp_path / io_csv.DATASET_DIR_NAME).mkdir()
    nested = tmp_path / "проект"
    nested.mkdir()
    (nested / io_csv.DATASET_DIR_NAME).mkdir()

    assert find_dataset_dir(nested) == nested / io_csv.DATASET_DIR_NAME


# --------------------------------------------------------------------------
# normalize_address
# --------------------------------------------------------------------------

APARTMENT_FORMS = [
    "Город Москва, ул.Медынская, д. 5 к 1, кв. 128",
    "Город Москва, ул.Медынская, д. 5 к 1, кв.128",
    "Город Москва, ул.Медынская, д. 5 к 1, КВ. 128",
    "Город Москва, ул.Медынская, д. 5 к 1,  кв. 128  ",
]


@pytest.mark.parametrize("raw", APARTMENT_FORMS)
def test_apartment_is_cut_in_every_spelling(raw):
    """Квартира — не адрес дома. Ключ кэша обязан быть одним для всех её написаний."""
    assert normalize_address(raw) == "Город Москва, ул.Медынская, д. 5 к 1"


def test_synthetic_and_control_forms_of_one_house_share_a_key():
    """Синтетика и контрольная выгрузка описывают те же дома, но с номером квартиры.

    Если ключи разойдутся, кэш координат раздуется вдвое, а половина адресов
    всё равно не найдётся.
    """
    synthetic = "Город Москва, б-р.Ореховый, д. 11 к 1"
    control = "Город Москва, б-р.Ореховый, д. 11 к 1, кв. 314"

    assert normalize_address(synthetic) == normalize_address(control)


def test_address_without_apartment_is_left_alone():
    """Обрезка не имеет права портить адрес, в котором квартиры нет."""
    raw = "обл.Московская область, г.Домодедово, ул.Жуковского, д. 14/18"

    assert normalize_address(raw) == raw


def test_repeated_spaces_are_collapsed():
    """Разные выгрузки ставят разное число пробелов — ключ обязан быть один."""
    assert normalize_address("ул.  Ленина,   д.   5") == "ул. Ленина, д. 5"


def test_trailing_separators_are_trimmed():
    """Хвостовая запятая встречается в выгрузке и не должна раздваивать ключ."""
    assert normalize_address(" ул. Ленина, д. 5, ") == "ул. Ленина, д. 5"


def test_normalize_address_is_idempotent():
    """Повторная нормализация ничего не меняет — иначе ключ зависел бы от числа вызовов."""
    once = normalize_address("Город Москва, ул.Медынская, д. 5 к 1, кв. 128")

    assert normalize_address(once) == once


def test_only_the_trailing_apartment_is_cut():
    """Режется хвост «кв. N», а не любое вхождение — иначе пострадают названия улиц."""
    raw = "Город Москва, ул.Квартальная, д. 7"

    assert normalize_address(raw) == raw


# --------------------------------------------------------------------------
# parse_address: четыре формата выгрузки
# --------------------------------------------------------------------------

FORMATS = [
    pytest.param(
        "Город Москва, ул.Грайвороновская, д. 10 к 2",
        {"city": "Москва", "street": "Грайвороновская улица", "house": "10к2", "settlement": ""},
        id="тип-улицы-перед-названием",
    ),
    pytest.param(
        "МО, г. Кашира Кржижановского ул. д. 5/1",
        {"city": "Кашира", "street": "Кржижановского улица", "house": "5/1", "settlement": ""},
        id="город-и-улица-одним-полем",
    ),
    pytest.param(
        "обл.Московская область, г.Домодедово, пгт.Востряково-1, ул.Жуковского, д. 14/18",
        {
            "city": "Домодедово",
            "street": "Жуковского улица",
            "house": "14/18",
            "settlement": "Востряково-1",
        },
        id="регион-город-посёлок-улица-дом",
    ),
    pytest.param(
        "Москва Бирюлевская ул. д. 44",
        {"city": "Москва", "street": "Бирюлевская улица", "house": "44", "settlement": ""},
        id="без-запятых",
    ),
]


@pytest.mark.parametrize("raw, expected", FORMATS)
def test_four_documented_formats_are_parsed(raw, expected):
    """Все четыре формата из докстринга модуля разбираются по признакам, а не по позициям."""
    parsed = parse_address(raw)

    assert parsed.city == expected["city"]
    assert parsed.street == expected["street"]
    assert parsed.house == expected["house"]
    assert parsed.settlement == expected["settlement"]
    assert parsed.is_usable


def test_city_starting_with_de_is_not_taken_for_a_house_number():
    """Регрессия: маркер «д.» цеплялся за букву «Д» в начале слова «Домодедово».

    Адрес разваливался целиком, а координата уезжала в центр Москвы.
    """
    parsed = parse_address("Домодедово, проезд.Советский 1-й, д. 1А")

    assert parsed.city == "Домодедово"
    assert parsed.street == "Советский 1-й проезд"
    assert parsed.house == "1А"


def test_house_marker_requires_a_digit():
    """Маркер дома опознаётся только перед цифрой — иначе съедает названия."""
    parsed = parse_address("Дмитров, ул.Лесная, д. 7")

    assert parsed.city == "Дмитров"
    assert parsed.house == "7"


def test_city_is_separated_from_the_street_in_a_shared_field():
    """Регрессия: «г. Кашира Кржижановского ул.» опознавалось одной улицей целиком.

    Город проверяется раньше улицы, а остаток поля разбирается отдельно.
    """
    parsed = parse_address("г. Кашира Кржижановского ул.")

    assert parsed.city == "Кашира"
    assert parsed.street == "Кржижановского улица"


def test_region_prefix_is_dropped():
    """Регион геокодеру не нужен: город определяет его однозначно."""
    parsed = parse_address("обл.Московская область, г.Домодедово, ул.Жуковского, д. 14")

    assert parsed.city == "Домодедово"
    assert "область" not in parsed.city
    assert "область" not in parsed.street


# --------------------------------------------------------------------------
# parse_address: нормализация номера дома
# --------------------------------------------------------------------------

HOUSES = [
    pytest.param("128 к 5", "128к5", id="корпус-через-пробелы"),
    pytest.param("128к5", "128к5", id="корпус-слитно"),
    pytest.param("13 стр. 1", "13с1", id="строение"),
    pytest.param("5/1", "5/1", id="дробь-не-трогаем"),
    pytest.param("6к1", "6к1", id="уже-нормализован"),
    pytest.param("20А", "20А", id="буква-сохраняется"),
    pytest.param("44", "44", id="простой-номер"),
]


@pytest.mark.parametrize("raw_house, expected", HOUSES)
def test_house_number_is_normalized(raw_house, expected):
    """Один дом — один ключ: «128 к 5» и «128к5» обязаны совпасть."""
    parsed = parse_address(f"Город Москва, ул.Грайвороновская, д. {raw_house}")

    assert parsed.house == expected


def test_house_spellings_collapse_to_the_same_query():
    """Разные написания корпуса не должны порождать два разных запроса к геокодеру."""
    a = build_queries("Город Москва, ул.Грайвороновская, д. 128 к 5")
    b = build_queries("Город Москва, ул.Грайвороновская, д. 128к5")

    assert a == b


# --------------------------------------------------------------------------
# parse_address: типы улиц
# --------------------------------------------------------------------------

STREET_TYPES = [
    pytest.param("ул.Грайвороновская", "Грайвороновская улица", id="ул-перед"),
    pytest.param("Кржижановского ул.", "Кржижановского улица", id="ул-после"),
    pytest.param("б-р.Ореховый", "Ореховый бульвар", id="бульвар"),
    pytest.param("пр-кт.Ленинский", "Ленинский проспект", id="проспект"),
    pytest.param("пер.Большой Рогожский", "Большой Рогожский переулок", id="переулок"),
    pytest.param("наб.Москворецкая", "Москворецкая набережная", id="набережная"),
    pytest.param("ш.Каширское", "Каширское шоссе", id="шоссе"),
    pytest.param("проезд.Советский 1-й", "Советский 1-й проезд", id="проезд"),
]


@pytest.mark.parametrize("chunk, expected", STREET_TYPES)
def test_street_type_is_expanded_on_both_sides(chunk, expected):
    """Тип улицы стоит и перед названием, и после него — разбор обязан понимать оба."""
    parsed = parse_address(f"Город Москва, {chunk}, д. 1")

    assert parsed.street == expected


# --------------------------------------------------------------------------
# build_queries
# --------------------------------------------------------------------------


def test_queries_go_from_precise_to_coarse():
    """Лестница запросов: дом → улица → населённый пункт.

    Если дома нет в OSM, промахнуться на сотню метров по улице лучше, чем
    свалиться в центр района на километры.
    """
    queries = build_queries("Город Москва, ул.Грайвороновская, д. 10 к 2")

    assert len(queries) >= 3
    assert "10к2" in queries[0]
    assert "Грайвороновская улица" in queries[0]
    assert "10к2" not in queries[1]
    assert "Грайвороновская улица" in queries[1]
    assert "Грайвороновская улица" not in queries[-1]
    assert "Москва" in queries[-1]


def test_settlement_is_kept_in_the_query():
    """Посёлок внутри округа — не мелочь: без него улица ищется в другом городе."""
    queries = build_queries(
        "обл.Московская область, г.Домодедово, пгт.Востряково-1, ул.Жуковского, д. 14/18"
    )

    assert "Востряково-1" in queries[0]
    assert "Домодедово" in queries[0]
    assert queries[-1].startswith("Востряково-1")


def test_queries_have_no_duplicates():
    """Дубликат — лишний поход в сеть и лишняя пауза между запросами."""
    for raw, *_ in [p.values for p in FORMATS]:
        queries = build_queries(raw)
        assert len(queries) == len(set(queries)), raw


def test_queries_are_country_scoped():
    """Каждый запрос доводится до страны — иначе «Кашира» находится где угодно."""
    for query in build_queries("МО, г. Кашира Кржижановского ул. д. 5/1"):
        assert query.endswith("Россия")


def test_address_without_a_house_starts_from_the_street():
    """Нет дома — лестница начинается с улицы, а не с пустого первого запроса."""
    queries = build_queries("г. Кашира Кржижановского ул.")

    assert queries[0].startswith("Кржижановского улица")
    assert queries[-1].startswith("Кашира")


GARBAGE = ["", "   ", ", ,", "д. 5", ",,,"]


@pytest.mark.parametrize("raw", GARBAGE)
def test_garbage_input_yields_no_queries(raw):
    """Из неразбираемой строки лучше не делать запросов вовсе, чем геокодировать мусор."""
    assert build_queries(raw) == []
    assert not parse_address(raw).is_usable


def test_parse_address_strips_the_apartment_itself():
    """Квартиру снимает сам разбор адреса, а не вызывающий.

    Геокодеру нужен дом, а не квартира. Полагаться на то, что вызывающий не забудет
    нормализовать адрес заранее, нельзя, поэтому `parse_address` делает это сам —
    и результат не зависит от того, нормализовали адрес до вызова или нет.
    """
    raw = "Город Москва, б-р.Волжский, д. 50 к 2, кв. 89"

    assert parse_address(raw).house == "50к2"
    assert parse_address(normalize_address(raw)) == parse_address(raw)


# --------------------------------------------------------------------------
# Прогон по реальным выгрузкам
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_addresses(anonymized_csv_dir: Path) -> list[str]:
    """Все уникальные адреса из предоставленных CSV."""
    if not anonymized_csv_dir.is_dir():
        pytest.skip(f"каталог с данными не найден: {anonymized_csv_dir}")
    files = sorted(anonymized_csv_dir.glob("*.csv"))
    if not files:
        pytest.skip(f"в {anonymized_csv_dir} нет CSV-файлов")

    seen: set[str] = set()
    for path in files:
        loaded = io_csv.load_requests(path)
        seen.update(r.address.strip() for r in loaded.requests if r.address.strip())
    if not seen:
        pytest.skip("в выгрузках нет колонки с адресом")
    return sorted(seen)


@pytest.mark.realdata
def test_every_real_address_is_usable(real_addresses):
    """У каждого реального адреса определён хотя бы населённый пункт или улица.

    Это и есть страховка от регрессии разбора: примеров в докстринге четыре,
    а форм записи в выгрузках заметно больше.
    """
    broken = [a for a in real_addresses if not parse_address(a).is_usable]

    assert broken == [], f"не разобрано адресов: {len(broken)} из {len(real_addresses)}"


@pytest.mark.realdata
def test_every_real_address_yields_queries(real_addresses):
    """Раз адрес разобран, для него обязан строиться хотя бы один запрос."""
    empty = [a for a in real_addresses if not build_queries(normalize_address(a))]

    assert empty == []


@pytest.mark.realdata
def test_real_addresses_keep_their_house_number(real_addresses):
    """После нормализации номер дома остаётся: без него геокодер бьёт по улице."""
    with_marker = [a for a in real_addresses if HOUSE_WITH_NUMBER.search(a)]
    assert with_marker, "стенд сломан: в выгрузках нет адресов с номером дома"

    without_house = [a for a in with_marker if not parse_address(normalize_address(a)).house]

    assert without_house == []


@pytest.mark.realdata
def test_normalize_address_merges_control_and_synthetic_addresses(real_addresses):
    """Нормализация реально схлопывает пары «дом» / «дом + квартира» из двух выгрузок."""
    keys = {normalize_address(a) for a in real_addresses}

    assert len(keys) < len(real_addresses)
    assert [key for key in keys if APARTMENT_TAIL.search(key)] == []


def test_house_given_only_by_corpus_is_not_mistaken_for_a_settlement():
    """В выгрузке встречается дом, записанный одним корпусом: «..., д. к5».

    Регрессия: «к5» попадало в населённый пункт, и дом искался в несуществующем
    посёлке «к5». Маркер дома распознаёт корпус, строение и владение наравне с цифрой.
    """
    parsed = parse_address("Город Москва, б-р.Самаркандский Квартал 137а, д. к5")

    assert parsed.settlement == ""
    assert parsed.house == "к5"

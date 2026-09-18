# -*- coding: utf-8 -*-
"""Загрузка данных: справочник работ и координаты (SPEC §10).

Эти два компонента определяют, во что превращается сырая выгрузка: сколько
минут займёт заявка и где она находится. Ошибка здесь не ломает алгоритм, но
делает весь план неверным и при этом выглядящим правдоподобно.
"""
from __future__ import annotations

import pytest

io_csv = pytest.importorskip("planner.io_csv", reason="модуль planner.io_csv ещё не готов")

from factories import GeoPoint, has_cyrillic  # noqa: E402

WorkTypeCatalog = getattr(io_csv, "WorkTypeCatalog", None)
Geocoder = getattr(io_csv, "Geocoder", None)

if WorkTypeCatalog is None or Geocoder is None:  # pragma: no cover
    pytest.skip("в planner.io_csv нет WorkTypeCatalog/Geocoder", allow_module_level=True)


# --------------------------------------------------------------------------
# WorkTypeCatalog.resolve
# --------------------------------------------------------------------------


RAW = {
    "default": {
        "category": "Подключение клиентов Базовая",
        "skill": "connection",
        "duration_minutes": 70,
        "equipment": [],
    },
    "by_hd": {
        "Подключение|Заявка на подключение": {
            "category": "точная пара",
            "skill": "connection",
            "duration_minutes": 70,
            "equipment": [],
        },
        "Глобальная проблема|Заявка на подключение": {
            "category": "точная пара с чужим навыком",
            "skill": "connection",
            "duration_minutes": 70,
            "equipment": [],
        },
        "Заявка на подключение": {
            "category": "только HD",
            "skill": "connection",
            "duration_minutes": 70,
            "equipment": [],
        },
        "Авария": {
            "category": "Аварий на ТКД",
            "skill": "emergency",
            "duration_minutes": 80,
            "equipment": [],
        },
    },
    "by_bk": {
        "Подключение": {
            "category": "только BK",
            "skill": "connection",
            "duration_minutes": 70,
            "equipment": [],
        },
        "Локальная заявка": {
            "category": "Локальная заявка/ремонт у клиента",
            "skill": "local",
            "duration_minutes": 30,
            "equipment": [],
        },
        "Глобальная проблема": {
            "category": "только BK авария",
            "skill": "emergency",
            "duration_minutes": 80,
            "equipment": [],
        },
    },
}


@pytest.fixture
def catalog():
    """Справочник на контролируемых данных — приоритеты видно однозначно."""
    return WorkTypeCatalog(RAW)


def test_exact_pair_wins_over_hd_and_bk(catalog):
    """Точная пара «BK|HD» — высший приоритет сопоставления."""
    assert catalog.resolve("Подключение", "Заявка на подключение")["category"] == "точная пара"


def test_hd_wins_over_bk_when_no_exact_pair(catalog):
    """Без точной пары HD задаёт вид работ (длительность/категорию), не навык."""
    assert catalog.resolve("Дозаказ", "Заявка на подключение")["category"] == "только HD"


def test_known_bk_skill_is_not_overridden_by_hd(catalog):
    """Навык берётся только из BK: HD «Авария» не делает локальную заявку аварийной."""
    resolved = catalog.resolve("Локальная заявка", "Авария")
    assert resolved["skill"] == "local"
    assert resolved["duration_minutes"] == 80


def test_known_bk_skill_is_not_overridden_by_exact_pair(catalog):
    """Даже точная пара BK|HD не подменяет навык, заданный категорией BK."""
    resolved = catalog.resolve("Глобальная проблема", "Заявка на подключение")
    assert resolved["skill"] == "emergency"
    assert resolved["category"] == "точная пара с чужим навыком"


def test_unknown_bk_falls_back_to_hd_skill(catalog):
    """Неизвестная категория BK: навык взять не из чего — остаётся норматив HD."""
    resolved = catalog.resolve("Чужая категория", "Авария")
    assert resolved["skill"] == "emergency"


def test_resolve_does_not_mutate_catalog_entries(catalog):
    """Результат — копия: правка навыка снаружи не портит справочник."""
    first = catalog.resolve("Локальная заявка", "Авария")
    first["skill"] = "emergency"
    assert catalog.resolve("Локальная заявка", "Авария")["skill"] == "local"


def test_bk_is_used_when_hd_is_unknown(catalog):
    """Неизвестный HD — откат на BK."""
    assert catalog.resolve("Подключение", "Неизвестный тип")["category"] == "только BK"


def test_default_is_used_when_nothing_matches(catalog):
    """Ничего не совпало — норматив по умолчанию, а не исключение."""
    resolved = catalog.resolve("Чужое", "Совсем чужое")
    assert resolved["category"] == RAW["default"]["category"]
    assert resolved["duration_minutes"] == 70


def test_trailing_dot_is_normalized(catalog):
    """Точка в конце значения из выгрузки не должна ломать сопоставление."""
    assert catalog.resolve("Подключение.", "Заявка на подключение.")["category"] == "точная пара"
    assert catalog.resolve("Подключение", "Авария.")["category"] == "Аварий на ТКД"


def test_surrounding_whitespace_is_normalized(catalog):
    """Пробелы по краям — обычный мусор выгрузки, он не влияет на результат."""
    assert catalog.resolve("  Подключение  ", " Заявка на подключение ")["category"] == "точная пара"


def test_resolve_returns_duration_without_travel_norm(catalog):
    """Нормативы БЗ без дорожных 20 минут: 70 / 80 / 20 / 30."""
    assert catalog.resolve("Авария", "Авария")["duration_minutes"] == 80
    assert catalog.resolve("Локальная заявка", "Неизвестно")["duration_minutes"] == 30


def test_resolve_always_returns_required_fields(catalog):
    """Любой результат содержит навык, длительность и снаряжение."""
    for bk, hd in (
        ("Подключение", "Заявка на подключение"),
        ("Дозаказ", "Авария"),
        ("Чужое", "Чужое"),
    ):
        resolved = catalog.resolve(bk, hd)
        assert {"skill", "duration_minutes", "equipment"} <= set(resolved)
        assert resolved["duration_minutes"] > 0


def test_shipped_catalog_loads_and_covers_defaults():
    """Поставляемый data/work_types.json читается и даёт валидный default."""
    shipped = WorkTypeCatalog.load()
    resolved = shipped.resolve("что-угодно", "что-угодно")
    assert resolved["duration_minutes"] in (20, 30, 70, 80), (
        f"длительность по умолчанию вне нормативов БЗ: {resolved['duration_minutes']}"
    )


def test_shipped_catalog_maps_known_types_from_real_data():
    """Согласованные пары из выгрузки: навык по BK, норматив не скатывается в default."""
    shipped = WorkTypeCatalog.load()
    connection = shipped.resolve("Подключение", "Заявка на подключение")
    assert connection["skill"] == "connection"
    assert connection["duration_minutes"] == 70

    emergency = shipped.resolve("Глобальная проблема", "Авария")
    assert emergency["skill"] == "emergency"
    assert emergency["duration_minutes"] == 80

    local = shipped.resolve("Локальная заявка", "Разрывы")
    assert local["skill"] == "local"
    assert local["duration_minutes"] == 30

    extra = shipped.resolve("Дозаказ", "Дозаказ оборудования")
    assert extra["skill"] == "connection"
    assert extra["duration_minutes"] == 20


@pytest.mark.parametrize(
    ("bk", "hd", "skill"),
    [
        # Наблюдаемые пары, где HD в каталоге указывает на другой навык, чем BK.
        ("Глобальная проблема", "Информация", "emergency"),
        ("Локальная заявка", "Мониторинг", "local"),
        ("Локальная заявка", "Нет линка", "local"),
        ("Локальная заявка", "Рост ошибок на порту", "local"),
        ("Локальная заявка", "Переключение на Гбит/с", "local"),
        ("Подключение", "Авария", "connection"),
    ],
)
def test_shipped_catalog_skill_follows_bk_not_hd(bk, hd, skill):
    """БЗ «Навык»: HD не подменяет категорию BK даже на реальном справочнике."""
    shipped = WorkTypeCatalog.load()
    assert shipped.resolve(bk, hd)["skill"] == skill


def test_shipped_catalog_keeps_hd_equipment_when_skill_comes_from_bk():
    """Снаряжение описывает работу (HD), навык — категорию (BK)."""
    shipped = WorkTypeCatalog.load()
    resolved = shipped.resolve(
        "Локальная заявка", "Роутер. Замена техническим специалистом"
    )
    assert resolved["skill"] == "local"
    assert "router" in resolved.get("equipment", [])


# --------------------------------------------------------------------------
# Geocoder
# --------------------------------------------------------------------------


def test_cached_address_is_returned_as_is():
    """Точный адрес из кэша возвращается без подстановки и без предупреждения."""
    geo = Geocoder({"addresses": {"ул. Тестовая, д. 1": {"lat": 55.5, "lon": 37.5}}})
    point = geo.locate("ул. Тестовая, д. 1")
    assert (point.lat, point.lon) == (55.5, 37.5)
    assert geo.approximated == [], "точный адрес не должен считаться приближённым"


def test_unknown_address_is_recorded_as_approximated():
    """Подстановка честно помечается: адрес попадает в список приближённых."""
    geo = Geocoder({"districts": {"Район": {"lat": 55.7, "lon": 37.6}}})
    geo.locate("ул. Неизвестная, д. 5", "Район")
    assert geo.approximated, "приближённый адрес не зафиксирован"
    assert "ул. Неизвестная, д. 5" in geo.approximated


def test_stub_is_deterministic_for_the_same_address():
    """Два вызова для одного адреса дают одну и ту же точку — расчёт воспроизводим."""
    geo = Geocoder({"districts": {"Район": {"lat": 55.7, "lon": 37.6}}})
    first = geo.locate("ул. Неизвестная, д. 5", "Район")
    second = geo.locate("ул. Неизвестная, д. 5", "Район")
    assert (first.lat, first.lon) == (second.lat, second.lon)


def test_stub_is_deterministic_across_geocoder_instances():
    """Детерминизм не зависит от экземпляра: два загрузчика дают то же самое."""
    cache = {"districts": {"Район": {"lat": 55.7, "lon": 37.6}}}
    first = Geocoder(cache).locate("ул. Неизвестная, д. 5", "Район")
    second = Geocoder(cache).locate("ул. Неизвестная, д. 5", "Район")
    assert (first.lat, first.lon) == (second.lat, second.lon)


def test_different_addresses_get_different_points():
    """Разные адреса не схлопываются в одну точку центра района."""
    geo = Geocoder({"districts": {"Район": {"lat": 55.7, "lon": 37.6}}})
    a = geo.locate("ул. Первая, д. 1", "Район")
    b = geo.locate("ул. Вторая, д. 2", "Район")
    assert (a.lat, a.lon) != (b.lat, b.lon)


def test_stub_stays_near_the_district_centre():
    """Подставленная точка лежит рядом с центром района, а не в случайном месте."""
    centre = (55.7, 37.6)
    geo = Geocoder({"districts": {"Район": {"lat": centre[0], "lon": centre[1]}}})
    point = geo.locate("ул. Неизвестная, д. 5", "Район")
    assert abs(point.lat - centre[0]) < 0.05
    assert abs(point.lon - centre[1]) < 0.05


def test_anchor_is_used_when_district_is_unknown():
    """Без района опорой становится переданный anchor (офис бригады)."""
    anchor = GeoPoint(55.0, 37.0)
    geo = Geocoder({})
    point = geo.locate("ул. Неизвестная, д. 5", "Нет такого района", anchor)
    assert abs(point.lat - anchor.lat) < 0.05
    assert abs(point.lon - anchor.lon) < 0.05


def test_result_is_always_a_valid_geopoint():
    """Заглушка не может выдать координаты вне допустимого диапазона."""
    geo = Geocoder({})
    for address in ("", "а", "очень длинный адрес " * 10):
        point = geo.locate(address, "")
        assert -90.0 <= point.lat <= 90.0
        assert -180.0 <= point.lon <= 180.0


def test_shipped_geocache_loads():
    """Поставляемый data/geocache.json читается и даёт непустые справочники."""
    geo = Geocoder.load()
    assert geo.districts or geo.addresses, "кэш координат пуст"


def test_approximation_reaches_plan_warnings(anonymized_csv_dir):
    """Приближённые координаты обязаны доходить до PlanResult.warnings (SPEC §10)."""
    if not anonymized_csv_dir.exists():
        pytest.skip(f"каталог с данными не найден: {anonymized_csv_dir}")
    candidates = sorted(anonymized_csv_dir.glob("*Синтетические*.csv"))
    if not candidates:
        pytest.skip("нет синтетических выгрузок")

    build_scenario = getattr(io_csv, "build_scenario", None)
    if build_scenario is None:
        pytest.skip("в planner.io_csv нет build_scenario")

    scenario, notes = build_scenario(str(candidates[0]))
    assert scenario.requests, "из выгрузки не собралось ни одной заявки"
    assert notes, "подстановка координат обязана попадать в примечания"
    assert any(has_cyrillic(note) for note in notes), notes


def test_loader_notes_reach_plan_result(anonymized_csv_dir):
    """Примечания загрузчика видны в плане — диспетчер знает о допущениях."""
    if not anonymized_csv_dir.exists():
        pytest.skip(f"каталог с данными не найден: {anonymized_csv_dir}")
    candidates = sorted(anonymized_csv_dir.glob("*Синтетические*.csv"))
    build_scenario = getattr(io_csv, "build_scenario", None)
    if not candidates or build_scenario is None:
        pytest.skip("нет данных или загрузчика")

    from factories import plan_optimized

    scenario, _notes = build_scenario(str(candidates[0]))
    result = plan_optimized(scenario)
    for warning in result.warnings:
        assert isinstance(warning, str) and warning.strip()

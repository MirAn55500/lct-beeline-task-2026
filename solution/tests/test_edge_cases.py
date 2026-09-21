# -*- coding: utf-8 -*-
"""Крайние случаи и валидация входа (SPEC §2.1, §2.2, §2.6, §9).

Вырожденный вход — то, на чём чаще всего падают демонстрации: пустые списки,
дубли идентификаторов, заявка, совпадающая с офисом, полностью нерабочий день.
Планировщик обязан отвечать корректным планом или внятной диагностикой, но не
исключением.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from factories import (
    AssignmentStatus,
    GeoPoint,
    Priority,
    ReasonCode,
    Scenario,
    TransportMode,
    WorkInterval,
    assigned_ids,
    assignments_by_id,
    eng,
    event,
    has_cyrillic,
    plan_baseline,
    plan_both,
    plan_optimized,
    replan,
    req,
    sc,
    t,
    unassigned_ids,
    validate_plan,
)

HOME = (55.70, 37.60)


# --------------------------------------------------------------------------
# Вырожденные сценарии
# --------------------------------------------------------------------------


def test_empty_request_list_produces_empty_plan():
    """Нет заявок — пустой план без маршрутов и без ошибок."""
    scenario = sc([], [eng("E1", at=HOME)])
    for result in plan_both(scenario):
        assert result.assignments == ()
        assert result.routes == ()
        assert result.metrics.assigned_count == 0
        assert result.metrics.unassigned_count == 0
        assert result.metrics.used_engineer_count == 0
        assert validate_plan(result, scenario) == []


def test_empty_engineer_list_marks_everything_no_engineers():
    """Нет инженеров — все заявки с кодом no_engineers и объяснением."""
    scenario = sc([req("R1", at=HOME), req("R2", at=HOME)], [])
    for result in plan_both(scenario):
        assert result.metrics.assigned_count == 0
        assert result.metrics.unassigned_count == 2
        assert result.metrics.available_engineer_count == 0
        for assignment in result.unassigned:
            assert assignment.reason == ReasonCode.NO_ENGINEERS
            assert assignment.explanation.strip()
        assert validate_plan(result, scenario) == []


def test_empty_scenario_is_handled():
    """Ни заявок, ни инженеров — план строится и он валиден."""
    scenario = sc([], [])
    result = plan_optimized(scenario)
    assert result.metrics.assigned_count == 0
    assert validate_plan(result, scenario) == []


def test_single_engineer_single_request():
    """Минимальный содержательный сценарий работает end-to-end."""
    scenario = sc([req("R1", window=("10:00", "12:00"), dur=60, at=HOME)], [eng("E1", at=HOME)])
    result = plan_optimized(scenario)
    assert assigned_ids(result) == {"R1"}
    assert result.metrics.used_engineer_count == 1
    assert validate_plan(result, scenario) == []


def test_request_at_engineer_start_point_has_zero_travel():
    """Заявка в точке офиса: нулевое расстояние и нулевое время перемещения."""
    scenario = sc([req("R1", window=("09:00", "12:00"), dur=60, at=HOME)], [eng("E1", at=HOME)])
    result = plan_optimized(scenario)
    visit = result.routes[0].visits[0]
    assert visit.distance_km == pytest.approx(0.0)
    assert visit.travel_minutes == pytest.approx(0.0)
    assert result.metrics.total_distance_km == pytest.approx(0.0)


def test_all_engineers_inactive_leaves_everything_unassigned():
    """Все инженеры неактивны — заявки не назначены, причина no_work_time."""
    scenario = sc(
        [req("R1", at=HOME)],
        [eng("E1", at=HOME, active=False), eng("E2", at=HOME, active=False)],
    )
    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]
    assert assignment.status == AssignmentStatus.UNASSIGNED
    assert assignment.reason == ReasonCode.NO_WORK_TIME
    assert result.metrics.available_engineer_count == 0


def test_all_engineers_have_empty_schedule():
    """Выходной день у всех: пустые графики дают no_work_time."""
    scenario = sc([req("R1", at=HOME)], [eng("E1", at=HOME, shift=()), eng("E2", at=HOME, shift=())])
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.reason == ReasonCode.NO_WORK_TIME


def test_required_transport_nobody_has():
    """Требуется транспорт, которого нет ни у кого — no_transport."""
    scenario = sc(
        [req("R1", transport="bicycle", at=HOME)],
        [eng("E1", transport="car", at=HOME), eng("E2", transport="walking", at=HOME)],
    )
    assignment = assignments_by_id(plan_optimized(scenario))["R1"]
    assert assignment.reason == ReasonCode.NO_TRANSPORT


def test_all_requests_emergency_is_handled():
    """Все заявки аварийные — приоритет перестаёт различать, план остаётся валидным."""
    requests = [
        req(f"R{i}", window=("09:00", "16:00"), dur=60, at=HOME, priority="emergency")
        for i in range(6)
    ]
    scenario = sc(requests, [eng("E1", at=HOME), eng("E2", at=HOME)])
    result = plan_optimized(scenario)
    assert result.metrics.emergency_unassigned_count == result.metrics.unassigned_count
    assert validate_plan(result, scenario) == []


def test_engineer_with_split_shift_and_request_exactly_in_break():
    """Два интервала и заявка ровно в перерыве — работа не идёт в обед."""
    engineer = eng("E1", shift=[("09:00", "13:00"), ("14:00", "18:00")], at=HOME)
    scenario = sc([req("R1", window=("13:00", "14:00"), dur=30, at=HOME)], [engineer])
    result = plan_optimized(scenario)
    assignment = assignments_by_id(result)["R1"]

    if assignment.status == AssignmentStatus.ASSIGNED:
        assert assignment.service_start_at in (t("13:00"), t("14:00")), (
            f"старт {assignment.service_start_at} попал внутрь перерыва"
        )
    assert validate_plan(result, scenario) == []


def test_window_width_exactly_equal_to_duration():
    """Окно шириной ровно в длительность — граничный, но допустимый случай."""
    scenario = sc(
        [req("R1", window=("10:00", "11:00"), dur=60, at=HOME)],
        [eng("E1", at=HOME)],
    )
    result = plan_optimized(scenario)
    assert assigned_ids(result) == {"R1"}
    assert validate_plan(result, scenario) == []


def test_zero_width_window_is_supported():
    """window_start == window_end допустимо: прибытие ровно в момент."""
    scenario = sc(
        [req("R1", window=("10:00", "10:00"), dur=30, at=HOME)],
        [eng("E1", at=HOME)],
    )
    result = plan_optimized(scenario)
    assert assigned_ids(result) == {"R1"}
    assert validate_plan(result, scenario) == []


def test_many_requests_one_engineer_keeps_plan_valid():
    """Заведомая перегрузка: часть заявок теряется, но план остаётся корректным."""
    requests = [req(f"R{i}", window=("09:00", "17:00"), dur=80, at=HOME) for i in range(20)]
    scenario = sc(requests, [eng("E1", at=HOME)])
    result = plan_optimized(scenario)
    assert result.metrics.assigned_count < 20
    assert result.metrics.assigned_count >= 1
    assert validate_plan(result, scenario) == []


def test_one_engineer_is_preferred_over_short_travel():
    """Число исполнителей важнее пробега (SPEC §5.2): один инженер объезжает оба офиса.

    Следствие приоритетов: даже 60 км крюка дешевле второго выехавшего инженера.
    Тест фиксирует это как осознанное поведение, а не случайность.
    """
    scenario = sc(
        [
            req("N", window=("09:00", "17:00"), dur=60, at=(55.90, 37.60)),
            req("S", window=("09:00", "17:00"), dur=60, at=(55.50, 37.60)),
        ],
        [eng("E1", at=(55.90, 37.60)), eng("E2", at=(55.50, 37.60))],
    )
    result = plan_optimized(scenario)
    assert result.metrics.used_engineer_count == 1
    assert validate_plan(result, scenario) == []


def test_baseline_splits_far_apart_clusters_between_offices():
    """Baseline берёт первого подходящего: заявка у второго офиса уходит к E1, если влезает."""
    scenario = sc(
        [
            req("N", window=("09:00", "10:00"), dur=60, at=(55.90, 37.60)),
            req("S", window=("09:00", "10:00"), dur=60, at=(55.50, 37.60)),
        ],
        [eng("E1", at=(55.90, 37.60)), eng("E2", at=(55.50, 37.60))],
    )
    result = plan_baseline(scenario)
    by_id = assignments_by_id(result)
    assert by_id["N"].engineer_id == "E1"
    assert by_id["S"].engineer_id == "E2", "узкие окна обязаны развести заявки по бригадам"
    assert result.metrics.total_distance_km == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------
# Валидация входа
# --------------------------------------------------------------------------


def test_duplicate_request_ids_raise_value_error():
    """Дубли идентификаторов заявок — ошибка, а не предупреждение (SPEC §2.6)."""
    with pytest.raises(ValueError):
        sc([req("R1", at=HOME), req("R1", at=HOME)], [eng("E1", at=HOME)]).validate()


def test_duplicate_engineer_ids_raise_value_error():
    """Дубли идентификаторов инженеров — тоже ValueError."""
    with pytest.raises(ValueError):
        sc([req("R1", at=HOME)], [eng("E1", at=HOME), eng("E1", at=HOME)]).validate()


def test_reversed_window_produces_warning():
    """window_end < window_start — предупреждение Scenario.validate()."""
    request = req("R1", window=(t("12:00"), t("10:00")), at=HOME)
    warnings = sc([request], [eng("E1", at=HOME)]).validate()
    assert warnings, "перевёрнутое окно не попало в предупреждения"
    assert any("R1" in w for w in warnings), warnings


def test_non_positive_duration_produces_warning():
    """duration <= 0 — предупреждение (SPEC §2.6)."""
    warnings = sc([req("R1", dur=0, at=HOME)], [eng("E1", at=HOME)]).validate()
    assert warnings, "нулевая длительность не попала в предупреждения"
    assert any("R1" in w for w in warnings), warnings


def test_negative_duration_is_rejected():
    """Отрицательная длительность отвергается в конструкторе Request."""
    with pytest.raises(ValueError) as exc_info:
        req("R1", dur=-30, at=HOME)
    assert "R1" in str(exc_info.value)
    assert "отрицательной" in str(exc_info.value)


def test_request_outside_scenario_date_produces_warning():
    """Заявка на другую дату — предупреждение, а не молчаливое назначение."""
    from datetime import date as _date

    other_day = _date(2026, 8, 18)
    request = req("R1", window=("10:00", "12:00"), at=HOME, day=other_day)
    warnings = sc([request], [eng("E1", at=HOME)]).validate()
    assert warnings, "заявка вне даты сценария не попала в предупреждения"


def test_valid_scenario_has_no_warnings():
    """Корректный сценарий не порождает ложных предупреждений."""
    scenario = sc([req("R1", at=HOME), req("R2", at=HOME)], [eng("E1", at=HOME)])
    assert scenario.validate() == []


def test_geopoint_validates_latitude_and_longitude():
    """GeoPoint проверяет диапазоны в __post_init__ (SPEC §2.1)."""
    GeoPoint(90.0, 180.0)
    GeoPoint(-90.0, -180.0)
    for bad in ((90.1, 0.0), (-90.1, 0.0), (0.0, 180.1), (0.0, -180.1)):
        with pytest.raises(ValueError):
            GeoPoint(*bad)


def test_work_interval_requires_positive_length():
    """WorkInterval требует end строго больше start (SPEC §2.2)."""
    WorkInterval(t("09:00"), t("09:01"))
    with pytest.raises(ValueError):
        WorkInterval(t("09:00"), t("09:00"))


def test_input_models_are_frozen():
    """Входные модели неизменяемы — защита от случайной мутации планировщиком."""
    engineer = eng("E1", at=HOME)
    request = req("R1", at=HOME)
    for obj, field in ((engineer, "id"), (request, "id")):
        with pytest.raises(Exception):
            setattr(obj, field, "hacked")


def test_scenario_can_be_planned_twice_with_same_result():
    """Повторное планирование того же объекта не зависит от предыдущего вызова."""
    scenario = sc(
        [req(f"R{i}", window=("09:00", "17:00"), dur=60, at=HOME) for i in range(5)],
        [eng("E1", at=HOME), eng("E2", at=HOME)],
    )
    first = plan_optimized(scenario).metrics.quality_key()
    second = plan_optimized(scenario).metrics.quality_key()
    assert first == second


def test_scenario_is_constructible_directly_without_factories():
    """Прямая сборка Scenario (как это сделает бэкенд) тоже работает."""
    scenario = Scenario(
        date=t("09:00").date(),
        requests=(req("R1", at=HOME),),
        engineers=(eng("E1", at=HOME),),
    )
    result = plan_optimized(scenario)
    assert validate_plan(result, scenario) == []


def test_unassigned_request_priority_is_reflected_in_metrics():
    """Неназначенная авария попадает в emergency_unassigned_count."""
    scenario = sc(
        [req("R1", window=("03:00", "04:00"), dur=30, at=HOME, priority="emergency")],
        [eng("E1", at=HOME)],
    )
    result = plan_optimized(scenario)
    assert result.metrics.emergency_unassigned_count == 1
    assert result.metrics.unassigned_count == 1


def test_baseline_and_optimized_agree_on_trivially_infeasible_requests():
    """Заведомо невыполнимая заявка отвергается обоими алгоритмами одинаково."""
    scenario = sc([req("R1", window=("02:00", "03:00"), dur=30, at=HOME)], [eng("E1", at=HOME)])
    baseline, optimized = plan_both(scenario)
    assert baseline.metrics.unassigned_count == optimized.metrics.unassigned_count == 1
    assert (
        assignments_by_id(baseline)["R1"].reason == assignments_by_id(optimized)["R1"].reason
    )


def test_priority_enum_values_are_stable():
    """Значения приоритетов сериализуются как строки БЗ; ранг — авария > подключение > ремонт."""
    assert Priority.EMERGENCY.value == "emergency"
    assert Priority.CONNECTION.value == "connection"
    assert Priority.REPAIR.value == "repair_or_addon"
    assert Priority.EMERGENCY.rank == 2
    assert Priority.CONNECTION.rank == 1
    assert Priority.REPAIR.rank == 0


def test_request_default_priority_is_connection():
    """Дефолт заявки — подключение, независимо от навыка (SPEC §2.4)."""
    request = req("R1", at=HOME)
    assert request.priority == Priority.CONNECTION
    assert request.is_emergency is False


def test_completed_request_is_excluded_from_assignments():
    """Закрытая заявка не входит в planning_requests и не получает Assignment."""
    closed = req("RDONE", window=("09:00", "12:00"), dur=60, at=HOME, execution_status="completed")
    open_request = req("R1", window=("09:00", "12:00"), dur=60, at=HOME)
    scenario = sc([closed, open_request], [eng("E1", at=HOME)])

    assert closed.id not in {r.id for r in scenario.planning_requests()}
    result = plan_optimized(scenario)
    assert closed.id not in {a.request_id for a in result.assignments}
    assert assigned_ids(result) == {"R1"}
    assert validate_plan(result, scenario) == []


def test_future_received_at_is_excluded_when_as_of_is_earlier():
    """Авария, поступившая после as_of, в этот снимок плана не входит."""
    emergency = req(
        "RE",
        window=("09:00", "21:00"),
        dur=100,
        skill="emergency",
        priority="emergency",
        at=HOME,
        received_at="13:00",
    )
    scenario = sc(
        [emergency],
        [eng("E1", skills=["emergency"], at=HOME)],
        as_of="09:00",
    )
    assert emergency.id not in {r.id for r in scenario.planning_requests()}
    result = plan_optimized(scenario)
    assert result.assignments == ()
    assert assigned_ids(result) == set()
    assert validate_plan(result, scenario) == []


def test_engineer_home_start_survives_dict_round_trip():
    """home_start — часть входа и обязан переживать сериализацию (SPEC §2.3)."""
    engineer = eng("E1", at=HOME, home_start=True)
    restored = type(engineer).from_dict(engineer.to_dict())
    assert restored.home_start is True
    assert eng("E2", at=HOME).home_start is False


def test_request_that_cannot_fit_any_shift_is_reported_as_a_warning():
    """Заявка, не помещающаяся в смену ни к кому, попадает в предупреждения плана.

    Реальный случай «Востока»: в выгрузке есть окна 20:00–22:00, а смена задана до 21:00.
    Авария длится 80 минут и не может начаться раньше 20:00 — её не выполнить ни при каком
    распределении. Без предупреждения такая заявка молча оседает в «не назначено»,
    и причину ищут в алгоритме, а не в границах смены.
    """
    scenario = sc(
        [
            req("R1", window=("10:00", "12:00"), dur=60),
            req("R2", window=("20:00", "22:00"), dur=80, skill="emergency", priority="emergency"),
        ],
        [eng("E1", skills=["connection", "emergency"], shift=("09:00", "21:00"))],
    )
    result = plan_optimized(scenario)

    assert "R2" in unassigned_ids(result)
    hint = [w for w in result.warnings if "не помещающихся в смену" in w]
    assert hint, f"нет предупреждения о заявке вне смены: {result.warnings}"
    assert "R2" in hint[0]
    assert "R1" not in hint[0], "нормальная заявка не должна попадать в предупреждение"


def test_explanation_says_the_work_does_not_fit_even_an_empty_day():
    """Объяснение отличает «не влезает в принципе» от «инженер занят».

    Инженер полностью свободен, и всё равно не может взять заявку: работа начинается
    не раньше 20:00 и длится 80 минут, а смена заканчивается в 21:00. Говорить про
    «уже запланированные работы» здесь было бы неправдой.
    """
    scenario = sc(
        [req("R1", window=("20:00", "22:00"), dur=80, skill="emergency", priority="emergency")],
        [eng("E1", skills=["emergency"], shift=("09:00", "21:00"))],
    )
    result = plan_optimized(scenario)
    explanation = assignments_by_id(result)["R1"].explanation

    assert "не помещается даже в пустой день" in explanation, explanation
    assert "уже запланированных работ" not in explanation, explanation


# --------------------------------------------------------------------------
# Грязный вход: внятная диагностика вместо исключения из глубины расчёта
# --------------------------------------------------------------------------


def test_zero_speed_is_rejected_with_a_readable_message():
    """Нулевая скорость — ошибка настроек, а не `ZeroDivisionError` из расчёта дороги."""
    scenario = sc([req("R1", at=(55.71, 37.61))], [eng("E1", at=HOME)])
    scenario.settings.speed_kmh = dict(scenario.settings.speed_kmh)
    scenario.settings.speed_kmh[TransportMode.CAR] = 0

    with pytest.raises(ValueError) as exc:
        plan_optimized(scenario)

    assert "car" in str(exc.value)
    assert has_cyrillic(str(exc.value))


def test_missing_transport_setting_is_rejected_with_a_readable_message():
    """Неполный словарь режимов тоже ловится на входе, а не `KeyError` в горячем пути."""
    scenario = sc([req("R1", at=(55.71, 37.61))], [eng("E1", at=HOME)])
    scenario.settings.overhead_minutes = {TransportMode.CAR: 8.0}

    with pytest.raises(ValueError) as exc:
        plan_optimized(scenario)

    assert "overhead_minutes" in str(exc.value)


def _scenario_with_setting(field, value):
    """Сценарий, у которого у автомобиля подменён один параметр перемещения."""
    scenario = sc([req("R1", at=(55.71, 37.61))], [eng("E1", at=HOME)])
    table = dict(getattr(scenario.settings, field))
    table[TransportMode.CAR] = value
    setattr(scenario.settings, field, table)
    return scenario


@pytest.mark.parametrize(
    "field, value",
    [
        ("speed_kmh", 0.0),
        ("speed_kmh", -28.0),
        ("speed_kmh", float("nan")),
        ("speed_kmh", float("inf")),
        ("detour_factor", 0.0),
        ("detour_factor", -1.35),
        ("detour_factor", float("nan")),
        ("overhead_minutes", -20.0),
        ("overhead_minutes", float("nan")),
    ],
)
def test_broken_transport_settings_are_rejected_on_input(field, value):
    """Мусор в параметрах перемещения ловится на входе, а не подделывает результат.

    Каждый случай врал по-своему и молча: отрицательная извилистость давала
    **отрицательный пробег** (и `compare()` счёл бы такой план улучшением), нулевая —
    нулевой, `NaN` проходил любое сравнение с нулём и уводил заявки в отказ «не успевает
    доехать», бесконечная скорость обнуляла дорогу, отрицательные сопутствующие затраты
    роняли расчёт из календаря. Верификатор ничего из этого не ловит: знак километров
    он не проверяет.
    """
    with pytest.raises(ValueError) as exc:
        plan_optimized(_scenario_with_setting(field, value))

    assert "car" in str(exc.value)
    assert has_cyrillic(str(exc.value))


def test_zero_overhead_is_allowed():
    """Ноль допустим только у сопутствующих затрат: парковка бывает бесплатной по времени."""
    result = plan_optimized(_scenario_with_setting("overhead_minutes", 0.0))
    assert "R1" in assigned_ids(result)


def test_naive_datetimes_are_normalized_instead_of_crashing():
    """Время без зоны — не повод падать: недостающая зона достраивается до MSK.

    Раньше `window_start` без `tzinfo` рядом с aware-сменой ронял расчёт
    `TypeError: can't compare offset-naive and offset-aware datetimes`.
    """
    naive_start = datetime(2026, 8, 17, 10, 0)
    naive_end = datetime(2026, 8, 17, 16, 0)
    request = req("R1", window=(naive_start, naive_end), dur=60, at=(55.71, 37.61))

    assert request.window_start.tzinfo is not None
    assert request.window_end.tzinfo is not None
    assert request.window_start == t("10:00")

    result = plan_optimized(sc([request], [eng("E1", at=HOME)]))
    assert "R1" in assigned_ids(result)


def test_naive_work_interval_is_normalized():
    """Смена, заданная без зоны, приводится к той же шкале, что и заявки."""
    interval = WorkInterval(
        start=datetime(2026, 8, 17, 9, 0), end=datetime(2026, 8, 17, 18, 0)
    )
    assert interval.start == t("09:00")
    assert interval.end == t("18:00")


def test_naive_snapshot_and_event_moment_are_normalized():
    """`as_of` и момент события — тоже время, и зона у них достраивается так же."""
    scenario = sc(
        [req("R1", window=("10:00", "16:00"), dur=60, at=(55.71, 37.61))],
        [eng("E1", at=HOME)],
        as_of=datetime(2026, 8, 17, 9, 0),
    )
    assert scenario.as_of == t("09:00")

    before = plan_optimized(scenario)
    ev = event("cancel_request", datetime(2026, 8, 17, 11, 0), request_id="R1")
    assert ev.at == t("11:00")
    assert replan(before, scenario, ev) is not None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_duration_is_rejected(value):
    """`NaN` и бесконечность в длительности ловятся на конструкторе.

    Порядок проверок имеет значение: `nan < 0` ложно, поэтому одной проверки знака мало.
    Раньше `NaN` доходил до `int(...)` в объяснении отказа, а `inf` — до `timedelta`.
    """
    with pytest.raises(ValueError) as exc:
        req("R1", dur=value, at=HOME)

    assert "R1" in str(exc.value)
    assert has_cyrillic(str(exc.value))


@pytest.mark.parametrize("bad", [-5.0, float("nan"), float("inf")])
def test_external_travel_matrix_is_validated(bad):
    """Подставленная снаружи матрица проверяется так же, как настройки расчёта.

    Отрицательный километр из чужого источника доходил до метрик молча: `compare()` счёл
    бы такой план улучшением, а верификатор смотрит ту же матрицу и расхождения не видит.
    """
    from planner.travel import HaversineTravelModel, MatrixTravelModel

    scenario = sc([req("R1", at=(55.71, 37.61))], [eng("E1", at=HOME)])
    key = ("55.700000,37.600000", "55.710000,37.610000", TransportMode.CAR)

    with pytest.raises(ValueError):
        MatrixTravelModel({key: bad}, {key: 10.0}, HaversineTravelModel(scenario.settings))
    with pytest.raises(ValueError):
        MatrixTravelModel({key: 1.0}, {key: bad}, HaversineTravelModel(scenario.settings))


@pytest.mark.parametrize("bad", [True, False])
def test_boolean_duration_is_rejected(bad):
    """`bool` — подкласс `int`, и `True` тихо становится работой на одну минуту.

    Из JSON такое приходит буквально: `"duration_minutes": true`. Проверки на конечность
    и на знак его пропускают обе, поэтому отсекать приходится по типу.
    """
    with pytest.raises(ValueError) as exc:
        req("R1", dur=bad)
    assert "R1" in str(exc.value)
    assert has_cyrillic(str(exc.value))


def test_travel_matrix_must_know_the_same_pairs():
    """Половина пары из матрицы, половина из расчёта по прямой — это «100 км за 13 минут».

    Расстояние и время обязаны приходить из одного источника: иначе скорость получается
    любой, а поймать это некому — верификатор смотрит ту же модель.
    """
    from planner.travel import HaversineTravelModel, MatrixTravelModel

    scenario = sc([req("R1", at=(55.71, 37.61))], [eng("E1", at=HOME)])
    fallback = HaversineTravelModel(scenario.settings)
    key = ("55.700000,37.600000", "55.710000,37.610000", TransportMode.CAR)

    with pytest.raises(ValueError) as exc:
        MatrixTravelModel({key: 100.0}, {}, fallback)
    assert has_cyrillic(str(exc.value))
    with pytest.raises(ValueError):
        MatrixTravelModel({}, {key: 10.0}, fallback)

    # Обе матрицы знают пару — расчёт согласован, модель создаётся.
    model = MatrixTravelModel({key: 100.0}, {key: 120.0}, fallback)
    assert model.distance_km(*_pair(scenario), TransportMode.CAR) == 100.0


def _pair(scenario):
    """Точки, по которым построен ключ матрицы: офис инженера и адрес заявки."""
    return scenario.engineers[0].start_point, scenario.requests[0].point

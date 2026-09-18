# -*- coding: utf-8 -*-
"""Запас до срыва и чистая длительность работ (SPEC §7.1, §7.2, §7.4).

Два поля визита существуют потому, что «посмотреть на разность времён» — неверно:

* `service_minutes` — чистая работа. Разность `service_end_at - service_start_at`
  включает обед, если работа его пересекла, и завышает трудозатраты.
* `slack_minutes` — запас до срыва: на сколько можно задержать начало, не сломав
  ни окно самой заявки, ни хвост маршрута. Это прогноз опозданий для диспетчера,
  и считать его «по окну» нельзя — ограничивает ещё и смена, и следующие визиты.

Ожидаемые значения считаются независимым оракулом `factories.OracleCalendar`,
а не вызовом того же `slack_m`, иначе тест проверял бы код его же кодом.
"""
from __future__ import annotations

import pytest

from factories import (
    Algorithm,
    assert_dt,
    eng,
    has_cyrillic,
    hhmm,
    minutes_between,
    oracle_calendar,
    plan,
    plan_baseline,
    plan_optimized,
    random_scenario,
    req,
    routes_by_engineer,
    sc,
    t,
    validate_plan,
)

TIGHT_THRESHOLD = 10.0


def oracle_slack(engineer, request, service_start):
    """Эталонный запас одиночного визита (SPEC §7.1).

    Задержать начало можно до момента, когда либо закроется окно прибытия, либо
    работа перестанет помещаться в смену, — что наступит раньше.
    """
    cal = oracle_calendar(engineer)
    by_shift = cal.sub(engineer.work_intervals[-1].end, request.duration_minutes)
    bounds = [request.window_end] + ([by_shift] if by_shift is not None else [])
    latest = min(bounds)
    return cal.working_between(service_start, latest)


def only_visit(result):
    assert len(result.routes) == 1 and len(result.routes[0].visits) == 1
    return result.routes[0].visits[0]


# --------------------------------------------------------------------------
# slack_minutes: одиночный визит против независимого оракула
# --------------------------------------------------------------------------

SOLO_CASES = [
    pytest.param(("09:00", "18:00"), ("10:00", "12:00"), 70, id="окно-режет-раньше-смены"),
    pytest.param(("09:00", "18:00"), ("10:00", "17:30"), 70, id="смена-режет-раньше-окна"),
    pytest.param(("09:00", "18:00"), ("09:30", "16:00"), 30, id="широкое-окно"),
    pytest.param(("09:00", "12:00"), ("09:30", "11:30"), 60, id="короткая-смена"),
]


@pytest.mark.parametrize("shift, window, duration", SOLO_CASES)
def test_solo_visit_slack_matches_oracle(shift, window, duration):
    """Запас одиночного визита = расстояние до окна либо до конца смены, что ближе."""
    engineer = eng("E1", skills=["connection"], shift=shift, at=(55.70, 37.60))
    request = req("R1", window=window, dur=duration, at=(55.71, 37.61))
    scenario = sc([request], [engineer])

    visit = only_visit(plan_optimized(scenario))
    expected = oracle_slack(engineer, request, visit.service_start_at)

    assert visit.slack_minutes == pytest.approx(expected, abs=1e-6), (
        f"начало {hhmm(visit.service_start_at)}, окно до {window[1]}, смена до {shift[1]}"
    )


def test_solo_visit_slack_with_lunch_counts_only_working_minutes():
    """Запас измеряется рабочими минутами: перерыв в него не входит.

    Календарные минуты дали бы диспетчеру на час больше времени, чем у него есть.
    """
    engineer = eng(
        "E1", skills=["connection"], shift=[("09:00", "13:00"), ("14:00", "18:00")], at=(55.70, 37.60)
    )
    request = req("R1", window=("10:00", "15:00"), dur=60, at=(55.71, 37.61))
    scenario = sc([request], [engineer])

    visit = only_visit(plan_optimized(scenario))
    expected = oracle_slack(engineer, request, visit.service_start_at)

    assert visit.slack_minutes == pytest.approx(expected, abs=1e-6)
    assert visit.slack_minutes < minutes_between(visit.service_start_at, t("15:00"))


def test_slack_is_zero_when_visit_starts_at_the_last_possible_moment():
    """Окно нулевой ширины — запаса нет, и это обязано быть видно в плане."""
    engineer = eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=(55.70, 37.60))
    request = req("R1", window=("11:00", "11:00"), dur=60, at=(55.71, 37.61))
    scenario = sc([request], [engineer])

    visit = only_visit(plan_optimized(scenario))

    assert_dt(visit.service_start_at, t("11:00"), "начало работы")
    assert visit.slack_minutes == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------
# slack_minutes: влияние хвоста маршрута
# --------------------------------------------------------------------------


def test_tight_follow_up_eats_the_slack_of_earlier_visits():
    """Запас считается по всему хвосту, а не по окну одной заявки.

    Пока заявка в маршруте одна, задержать её можно почти до вечера. Стоит добавить
    следующую с узким окном — задерживать первую уже нельзя, иначе сорвётся вторая.
    """
    engineer = eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=(55.70, 37.60))
    first = req("RA", window=("09:30", "16:00"), dur=60, at=(55.705, 37.605), order=0)
    tight = req("RB", window=("11:00", "11:10"), dur=60, at=(55.706, 37.606), order=1)

    alone = plan_optimized(sc([first], [engineer]))
    together = plan_optimized(sc([first, tight], [engineer]))

    slack_alone = only_visit(alone).slack_minutes
    route = routes_by_engineer(together)["E1"]
    slack_together = {v.request_id: v.slack_minutes for v in route.visits}

    assert set(slack_together) == {"RA", "RB"}
    assert slack_together["RA"] < slack_alone
    assert slack_together["RB"] <= 10.0 + 1e-6


def test_slack_of_a_visit_never_exceeds_its_own_window_room():
    """Запас не имеет права обещать больше, чем осталось до конца окна прибытия."""
    scenario = random_scenario(5, n_engineers=3, n_requests=15)
    result = plan_optimized(scenario)
    windows = {r.id: r.window_end for r in scenario.requests}

    for route in result.routes:
        for visit in route.visits:
            room = minutes_between(visit.service_start_at, windows[visit.request_id])
            assert visit.slack_minutes <= room + 1e-6, (
                f"{visit.request_id}: запас {visit.slack_minutes}, "
                f"до конца окна {room}"
            )


@pytest.mark.property
@pytest.mark.parametrize("seed", [21, 22, 23, 24])
@pytest.mark.parametrize("algorithm", [Algorithm.BASELINE, Algorithm.OPTIMIZED])
def test_slack_is_never_negative(seed, algorithm):
    """SPEC §7.1: запас — величина неотрицательная. Отрицательный означал бы,
    что план уже сорван, а такой план вообще не должен строиться."""
    scenario = random_scenario(seed, n_engineers=4, n_requests=20)
    result = plan(scenario, algorithm)

    for route in result.routes:
        for visit in route.visits:
            assert visit.slack_minutes >= 0.0, f"{route.engineer_id}/{visit.request_id}"


def test_slack_is_serialized():
    """Прогноз опозданий нужен интерфейсу, значит он есть в `to_dict()`."""
    scenario = sc(
        [req("R1", window=("10:00", "12:00"), dur=70)],
        [eng("E1", skills=["connection"], at=(55.70, 37.60))],
    )

    visit = plan_optimized(scenario).to_dict()["routes"][0]["visits"][0]

    assert "slack_minutes" in visit
    assert visit["slack_minutes"] >= 0.0


# --------------------------------------------------------------------------
# metrics.tight_visit_count
# --------------------------------------------------------------------------


def test_tight_visit_count_counts_visits_without_slack():
    """SPEC §7.4: в счётчик попадают визиты с запасом меньше 10 минут."""
    engineer = eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=(55.70, 37.60))
    tight = req("RT", window=("11:00", "11:05"), dur=60, at=(55.705, 37.605), order=0)
    relaxed = req("RR", window=("13:00", "16:00"), dur=60, at=(55.706, 37.606), order=1)
    scenario = sc([tight, relaxed], [engineer])

    result = plan_optimized(scenario)
    by_id = {v.request_id: v.slack_minutes for r in result.routes for v in r.visits}

    assert by_id["RT"] < TIGHT_THRESHOLD
    assert by_id["RR"] >= TIGHT_THRESHOLD
    assert result.metrics.tight_visit_count == 1


def test_tight_visit_count_is_zero_when_everyone_has_room():
    """Свободный день — ни одного визита без запаса."""
    engineer = eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=(55.70, 37.60))
    scenario = sc([req("R1", window=("09:30", "16:00"), dur=30, at=(55.705, 37.605))], [engineer])

    assert plan_optimized(scenario).metrics.tight_visit_count == 0


@pytest.mark.property
@pytest.mark.parametrize("seed", [31, 32, 33])
def test_tight_visit_count_agrees_with_the_visits(seed):
    """Метрика обязана быть пересчитываемой из самих визитов, а не жить своей жизнью."""
    result = plan_optimized(random_scenario(seed, n_engineers=4, n_requests=20))

    expected = sum(
        1 for route in result.routes for v in route.visits if v.slack_minutes < TIGHT_THRESHOLD
    )
    assert result.metrics.tight_visit_count == expected


# --------------------------------------------------------------------------
# service_minutes
# --------------------------------------------------------------------------


@pytest.mark.property
@pytest.mark.parametrize("seed", [41, 42])
def test_service_minutes_equals_request_duration(seed):
    """SPEC §7.1: чистая длительность работ = норматив заявки, ничего лишнего."""
    scenario = random_scenario(seed, n_engineers=4, n_requests=20)
    durations = {r.id: float(r.duration_minutes) for r in scenario.requests}
    result = plan_optimized(scenario)

    for route in result.routes:
        for visit in route.visits:
            assert visit.service_minutes == pytest.approx(durations[visit.request_id])


def test_service_minutes_equals_elapsed_time_without_a_break():
    """Без перерыва разность времён и чистая длительность совпадают — контрольный случай."""
    engineer = eng("E1", skills=["connection"], shift=("09:00", "18:00"), at=(55.70, 37.60))
    scenario = sc([req("R1", window=("10:00", "12:00"), dur=70, at=(55.71, 37.61))], [engineer])

    visit = only_visit(plan_optimized(scenario))

    assert visit.service_minutes == pytest.approx(70.0)
    assert minutes_between(visit.service_start_at, visit.service_end_at) == pytest.approx(70.0)


def test_service_minutes_differs_from_elapsed_time_across_lunch():
    """Работа, начатая перед обедом, идёт «по часам» дольше, чем длится по нормативу.

    Ровно ради этого случая `service_minutes` вынесено отдельным полем: считать
    трудозатраты разностью времён здесь нельзя.
    """
    engineer = eng(
        "E1", skills=["connection"], shift=[("09:00", "13:00"), ("14:00", "18:00")], at=(55.70, 37.60)
    )
    # Прибытие в точку офиса мгновенно, окно вынуждает начать в 12:30 —
    # 70 минут работы перешагивают часовой перерыв.
    request = req("R1", window=("12:30", "12:45"), dur=70, at=(55.70, 37.60))
    scenario = sc([request], [engineer])

    result = plan_optimized(scenario)
    visit = only_visit(result)

    assert_dt(visit.service_start_at, t("12:30"), "начало работы")
    assert_dt(visit.service_end_at, t("14:40"), "конец работы")
    assert visit.service_minutes == pytest.approx(70.0)
    assert minutes_between(visit.service_start_at, visit.service_end_at) == pytest.approx(130.0)
    assert validate_plan(result, scenario) == []


def test_route_service_minutes_is_the_sum_of_visits():
    """Итог маршрута собирается из чистых длительностей, а не из разностей времён."""
    engineer = eng(
        "E1", skills=["connection"], shift=[("09:00", "13:00"), ("14:00", "18:00")], at=(55.70, 37.60)
    )
    requests = [
        req("R1", window=("12:30", "12:45"), dur=70, at=(55.70, 37.60), order=0),
        req("R2", window=("15:00", "16:00"), dur=30, at=(55.705, 37.605), order=1),
    ]
    scenario = sc(requests, [engineer])

    result = plan_optimized(scenario)
    route = routes_by_engineer(result)["E1"]

    assert route.service_minutes == pytest.approx(sum(v.service_minutes for v in route.visits))
    assert route.service_minutes == pytest.approx(100.0)
    assert result.metrics.total_service_minutes == pytest.approx(100.0)


# --------------------------------------------------------------------------
# RouteResult.explanation и PlanMetrics.feasible_count
# --------------------------------------------------------------------------


@pytest.mark.property
@pytest.mark.parametrize("seed", [51, 52, 53])
@pytest.mark.parametrize("algorithm", [Algorithm.BASELINE, Algorithm.OPTIMIZED])
def test_every_route_with_visits_explains_itself(seed, algorithm):
    """Маршрут без объяснения бесполезен диспетчеру: он не поймёт, почему такой порядок."""
    result = plan(random_scenario(seed, n_engineers=4, n_requests=20), algorithm)

    assert result.routes, "стенд сломан: план без маршрутов"
    for route in result.routes:
        assert route.visits
        assert route.explanation.strip() != "", route.engineer_id
        assert has_cyrillic(route.explanation), route.engineer_id


def test_route_explanation_survives_serialization():
    """Объяснение уезжает в интерфейс вместе с маршрутом."""
    scenario = sc(
        [req("R1", window=("10:00", "12:00"), dur=70)],
        [eng("E1", skills=["connection"], at=(55.70, 37.60))],
    )

    route = plan_optimized(scenario).to_dict()["routes"][0]

    assert route["explanation"].strip() != ""


@pytest.mark.property
@pytest.mark.parametrize("seed", [61, 62, 63])
@pytest.mark.parametrize("algorithm", [Algorithm.BASELINE, Algorithm.OPTIMIZED])
def test_feasible_count_equals_assigned_count(seed, algorithm):
    """SPEC §7.4: план строится только из допустимых назначений, поэтому прогноз
    выполнимых заявок совпадает с числом назначенных."""
    result = plan(random_scenario(seed, n_engineers=4, n_requests=20), algorithm)

    assert result.metrics.feasible_count == result.metrics.assigned_count


def test_feasible_count_is_zero_when_nothing_is_assigned():
    """Граничный случай: никого не назначили — прогноз тоже нулевой, а не «по числу заявок»."""
    scenario = sc([req("R1", skill="emergency")], [eng("E1", skills=["connection"])])

    metrics = plan_optimized(scenario).metrics

    assert metrics.assigned_count == 0
    assert metrics.feasible_count == 0


def test_feasible_count_is_serialized():
    """Метрика обязательна по ТЗ, значит присутствует в выгружаемых метриках."""
    scenario = sc(
        [req("R1", window=("10:00", "12:00"), dur=70)],
        [eng("E1", skills=["connection"], at=(55.70, 37.60))],
    )

    metrics = plan_baseline(scenario).to_dict()["metrics"]

    assert metrics["feasible_count"] == metrics["assigned_count"] == 1
    assert metrics["tight_visit_count"] == 0

# -*- coding: utf-8 -*-
"""«Свободный» пересчёт посреди дня: начатое не трогается, остальное — заново."""
from __future__ import annotations

from dataclasses import replace

from factories import (
    assigned_ids,
    eng,
    plan_optimized,
    req,
    sc,
    t,
    validate_plan,
)
from planner import rebuild_unstarted

HOME = (55.70, 37.60)


def day_scenario(extra=()):
    engineers = [
        eng("E1", skills=["connection", "emergency"], at=HOME),
        eng("E2", skills=["connection", "emergency"], at=HOME),
    ]
    requests = [
        req("R1", window=("09:00", "10:00"), dur=60, at=(55.705, 37.605)),
        req("R2", window=("09:00", "10:00"), dur=60, at=(55.695, 37.595)),
        req("R3", window=("11:00", "12:00"), dur=60, at=(55.710, 37.610)),
        req("R4", window=("14:00", "15:00"), dur=60, at=(55.690, 37.590)),
        req("R5", window=("15:30", "16:30"), dur=45, at=(55.715, 37.615)),
        *extra,
    ]
    return sc(requests, engineers)


def visits_by_id(result):
    return {v.request_id: v for r in result.routes for v in r.visits}


def test_started_visits_keep_engineer_and_schedule():
    scenario = day_scenario()
    before = plan_optimized(scenario)
    now = t("11:30")
    after = rebuild_unstarted(before, scenario, now)

    old, new = visits_by_id(before), visits_by_id(after)
    started = [v for v in old.values() if v.departure_at < now]
    assert started, "в сценарии должны быть начатые визиты"
    for visit in started:
        kept = new[visit.request_id]
        assert kept.engineer_id == visit.engineer_id
        assert kept.service_start_at == visit.service_start_at
        assert kept.service_end_at == visit.service_end_at
        assert kept.locked
    assert validate_plan(after, scenario) == []


def test_unstarted_work_is_not_scheduled_in_the_past():
    scenario = day_scenario()
    before = plan_optimized(scenario)
    now = t("11:30")
    after = rebuild_unstarted(before, scenario, now)

    old = visits_by_id(before)
    for visit in visits_by_id(after).values():
        if old[visit.request_id].departure_at >= now:
            assert visit.departure_at >= now
    assert after.not_before == now


def test_new_emergency_gets_placed_over_frozen_prefix():
    scenario = day_scenario()
    before = plan_optimized(scenario)
    urgent = req(
        "U1",
        window=("12:00", "14:00"),
        dur=80,
        skill="emergency",
        priority="emergency",
        at=(55.700, 37.610),
    )
    with_urgent = replace(scenario, requests=scenario.requests + (replace(urgent, input_order=99),))
    after = rebuild_unstarted(before, with_urgent, t("11:30"))

    assert "U1" in assigned_ids(after)
    assert validate_plan(after, with_urgent) == []

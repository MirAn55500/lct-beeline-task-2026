# -*- coding: utf-8 -*-
"""Рабочий календарь (SPEC §3.1).

Календарь — фундамент всей модели времени: и работа, и перемещение потребляют
только рабочие минуты, в перерывах время «не течёт». Ошибка здесь тихо ломает
все расписания, поэтому проверяем каждую операцию и границы отдельно.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from factories import (
    OracleCalendar,
    WorkInterval,
    _normalize_shift,
    assert_dt,
    eng,
    hhmm,
    minutes_between,
    sym,
    t,
)

WorkCalendar = sym("WorkCalendar")

SINGLE = ("09:00", "18:00")
SPLIT = [("09:00", "13:00"), ("14:00", "18:00")]


ORIGIN = t("00:00")  # полночь даты плана — общая нулевая отметка расчёта


def cal(shift):
    """Построить WorkCalendar: сигнатура ``WorkCalendar(intervals, origin)``.

    ``origin`` — общая нулевая отметка всего расчёта, полночь даты плана.
    """
    return WorkCalendar(_normalize_shift(shift, None), ORIGIN)


# --------------------------------------------------------------------------
# capacity_minutes
# --------------------------------------------------------------------------


def test_capacity_minutes_single_interval_equals_shift_length():
    """Ёмкость одной смены 09:00-18:00 — ровно 540 минут."""
    assert cal(SINGLE).capacity_minutes == pytest.approx(540.0)


def test_capacity_minutes_excludes_lunch_break():
    """Обед не входит в ёмкость: 4ч + 4ч = 480, а не 540."""
    assert cal(SPLIT).capacity_minutes == pytest.approx(480.0)


def test_capacity_minutes_of_empty_calendar_is_zero():
    """Пустой график (выходной) даёт нулевую ёмкость."""
    assert cal(()).capacity_minutes == pytest.approx(0.0)


# --------------------------------------------------------------------------
# first_moment_at_or_after
# --------------------------------------------------------------------------


def test_first_moment_inside_interval_returns_same_moment():
    """Момент внутри смены — сам себе ближайший рабочий момент."""
    c = cal(SINGLE)
    assert_dt(c.first_moment_at_or_after(t("11:30")), t("11:30"), "момент внутри смены")


def test_first_moment_before_shift_returns_shift_start():
    """До начала смены время не течёт — прыжок на 09:00."""
    c = cal(SINGLE)
    assert_dt(c.first_moment_at_or_after(t("07:00")), t("09:00"), "до начала смены")


def test_first_moment_in_break_returns_next_interval_start():
    """Внутри обеда ближайший рабочий момент — начало второго интервала."""
    c = cal(SPLIT)
    assert_dt(c.first_moment_at_or_after(t("13:30")), t("14:00"), "внутри перерыва")


def test_first_moment_at_interval_start_is_the_start_itself():
    """Начало интервала — сам себе ближайший рабочий момент."""
    c = cal(SPLIT)
    for label in ("09:00", "14:00"):
        assert_dt(c.first_moment_at_or_after(t(label)), t(label), f"начало интервала {label}")


def test_first_moment_at_interval_end_is_consistent_with_contains():
    """Конец интервала: contains() и first_moment_at_or_after() обязаны согласоваться.

    SPEC §3.1 объявляет границы интервалов включительными для contains(), а
    first_moment_at_or_after() определяет как «ближайший рабочий момент >= t».
    Значит для 13:00 и 18:00 оба метода должны давать один и тот же ответ.
    """
    c = cal(SPLIT)
    for label in ("13:00", "18:00"):
        moment = t(label)
        assert c.contains(moment), f"{label} объявлен нерабочим — тогда и границы не включительны"
        assert_dt(
            c.first_moment_at_or_after(moment),
            moment,
            f"конец интервала {label}: contains()=True, но ближайший рабочий момент другой",
        )


def test_first_moment_after_shift_end_returns_none():
    """После конца смены рабочего момента нет — None."""
    c = cal(SINGLE)
    assert c.first_moment_at_or_after(t("18:01")) is None


def test_first_moment_on_empty_calendar_returns_none():
    """Пустой календарь никогда не даёт рабочего момента."""
    assert cal(()).first_moment_at_or_after(t("10:00")) is None


# --------------------------------------------------------------------------
# add
# --------------------------------------------------------------------------


def test_add_inside_single_interval_is_plain_addition():
    """Внутри непрерывной смены рабочие минуты равны календарным."""
    c = cal(SINGLE)
    assert_dt(c.add(t("10:00"), 90), t("11:30"), "add внутри смены")


def test_add_zero_equals_first_moment_at_or_after():
    """SPEC §3.1: add(t, 0) == first_moment_at_or_after(t) для любых t."""
    c = cal(SPLIT)
    for label in ("07:00", "09:00", "12:59", "13:00", "13:30", "14:00", "17:59", "18:00"):
        moment = t(label)
        assert c.add(moment, 0) == c.first_moment_at_or_after(moment), f"расхождение в {label}"


def test_add_zero_past_shift_end_returns_none():
    """add(t, 0) после конца смены тоже None — согласованность с first_moment."""
    c = cal(SINGLE)
    assert c.add(t("18:30"), 0) is None


def test_add_skips_break_without_consuming_it():
    """Перерыв «съедается»: 60 рабочих минут из 12:30 дают 14:30, а не 13:30."""
    c = cal(SPLIT)
    assert_dt(c.add(t("12:30"), 60), t("14:30"), "add через перерыв")


def test_add_from_inside_break_starts_after_break():
    """Старт из перерыва: отсчёт начинается с 14:00."""
    c = cal(SPLIT)
    assert_dt(c.add(t("13:20"), 30), t("14:30"), "add из перерыва")


def test_add_landing_exactly_on_interval_end_stays_on_boundary():
    """Ровно исчерпанный интервал даёт его конец, а не начало следующего."""
    c = cal(SPLIT)
    assert_dt(c.add(t("12:00"), 60), t("13:00"), "add точно до границы")


def test_add_exactly_to_shift_end_is_allowed():
    """Работа, заканчивающаяся ровно в конце смены, укладывается."""
    c = cal(SINGLE)
    assert_dt(c.add(t("17:00"), 60), t("18:00"), "add до конца смены")


def test_add_beyond_shift_end_returns_none():
    """Минуты, которых в смене нет, дают None — а не выход за 18:00."""
    c = cal(SINGLE)
    assert c.add(t("17:00"), 61) is None


def test_add_beyond_split_shift_capacity_returns_none():
    """Суммарной ёмкости 480 минут не хватает на 481."""
    c = cal(SPLIT)
    assert c.add(t("09:00"), 481) is None


def test_add_full_capacity_from_shift_start_hits_shift_end():
    """Ровно вся ёмкость приводит в конец последнего интервала."""
    c = cal(SPLIT)
    assert_dt(c.add(t("09:00"), 480), t("18:00"), "add на всю ёмкость")


def test_add_on_empty_calendar_returns_none():
    """Пустой календарь: add всегда None."""
    assert cal(()).add(t("10:00"), 5) is None


def test_add_matches_independent_oracle_on_grid():
    """Сверка add с независимой реализацией на сетке моментов и длительностей."""
    c = cal(SPLIT)
    ref = OracleCalendar(_normalize_shift(SPLIT, None))
    for start in ("08:00", "09:00", "10:15", "12:45", "13:30", "14:00", "16:00", "17:59"):
        for minutes in (0, 1, 15, 60, 125, 300, 479, 480, 600):
            got = c.add(t(start), minutes)
            expected = ref.add(t(start), minutes)
            assert (got is None) == (expected is None), f"add({start}, {minutes}): None-расхождение"
            if expected is not None:
                assert abs((got - expected).total_seconds()) <= 1, (
                    f"add({start}, {minutes}): {hhmm(got)} != {hhmm(expected)}"
                )


# --------------------------------------------------------------------------
# sub
# --------------------------------------------------------------------------


def test_sub_inside_single_interval_is_plain_subtraction():
    """Внутри смены sub — обычное вычитание."""
    c = cal(SINGLE)
    assert_dt(c.sub(t("11:30"), 90), t("10:00"), "sub внутри смены")


def test_sub_crosses_break_backwards():
    """sub через перерыв: 60 минут назад от 14:30 — это 12:30."""
    c = cal(SPLIT)
    assert_dt(c.sub(t("14:30"), 60), t("12:30"), "sub через перерыв")


def test_sub_before_shift_start_returns_none():
    """Если рабочих минут до момента не хватает — None."""
    c = cal(SINGLE)
    assert c.sub(t("09:30"), 31) is None


def test_sub_exactly_to_shift_start_is_allowed():
    """Ровно до начала смены — допустимо."""
    c = cal(SINGLE)
    assert_dt(c.sub(t("09:30"), 30), t("09:00"), "sub до начала смены")


def test_sub_zero_returns_the_same_moment_at_interval_start():
    """sub(t, 0) в начале интервала обязан вернуть сам t, а не None.

    Это прямое следствие требования «sub — обратная операция к add»:
    add(09:00, 0) == 09:00, значит и sub(09:00, 0) == 09:00.
    """
    c = cal(SPLIT)
    for label in ("09:00", "14:00", "10:00"):
        assert_dt(c.sub(t(label), 0), t(label), f"sub({label}, 0)")


def test_sub_is_exact_inverse_of_add():
    """SPEC §3.1: sub — точная обратная операция к add."""
    c = cal(SPLIT)
    for label in ("09:00", "10:00", "12:30", "14:00", "16:30"):
        for minutes in (0, 10, 45, 120, 240):
            forward = c.add(t(label), minutes)
            if forward is None:
                continue
            back = c.sub(forward, minutes)
            assert back is not None, f"sub вернул None для add({label}, {minutes})"
            expected = c.first_moment_at_or_after(t(label))
            assert abs((back - expected).total_seconds()) <= 1, (
                f"add/sub не обратимы для ({label}, {minutes}): {hhmm(back)} != {hhmm(expected)}"
            )


def test_sub_on_empty_calendar_returns_none():
    """Пустой календарь: sub всегда None."""
    assert cal(()).sub(t("10:00"), 5) is None


# --------------------------------------------------------------------------
# working_between
# --------------------------------------------------------------------------


def test_working_between_inside_one_interval():
    """Рабочие минуты внутри смены считаются напрямую."""
    c = cal(SINGLE)
    assert c.working_between(t("10:00"), t("11:15")) == pytest.approx(75.0)


def test_working_between_excludes_break():
    """Интервал, накрывающий обед, не считает перерыв рабочим временем."""
    c = cal(SPLIT)
    assert c.working_between(t("12:00"), t("15:00")) == pytest.approx(120.0)


def test_working_between_clamps_outside_shift():
    """Время до начала и после конца смены не считается."""
    c = cal(SINGLE)
    assert c.working_between(t("06:00"), t("20:00")) == pytest.approx(540.0)


def test_working_between_returns_zero_when_b_le_a():
    """SPEC §3.1: при b <= a результат строго 0.0."""
    c = cal(SINGLE)
    assert c.working_between(t("12:00"), t("12:00")) == pytest.approx(0.0)
    assert c.working_between(t("12:00"), t("11:00")) == pytest.approx(0.0)


def test_working_between_fully_inside_break_is_zero():
    """Отрезок целиком в перерыве не даёт рабочих минут."""
    c = cal(SPLIT)
    assert c.working_between(t("13:10"), t("13:50")) == pytest.approx(0.0)


def test_working_between_on_empty_calendar_is_zero():
    """Пустой календарь: рабочих минут нет никогда."""
    assert cal(()).working_between(t("09:00"), t("18:00")) == pytest.approx(0.0)


def test_working_between_is_consistent_with_add():
    """add и working_between согласованы: работа между t и add(t,m) равна m."""
    c = cal(SPLIT)
    start = t("12:00")
    end = c.add(start, 150)
    assert c.working_between(start, end) == pytest.approx(150.0, abs=1e-6)


# --------------------------------------------------------------------------
# contains
# --------------------------------------------------------------------------


def test_contains_includes_interval_boundaries():
    """Границы интервалов включительны (SPEC §3.1)."""
    c = cal(SPLIT)
    for label in ("09:00", "13:00", "14:00", "18:00", "10:00"):
        assert c.contains(t(label)), f"{label} должен быть рабочим моментом"


def test_contains_excludes_break_and_outside():
    """Перерыв и время вне смены рабочими не считаются."""
    c = cal(SPLIT)
    for label in ("08:59", "13:30", "18:01"):
        assert not c.contains(t(label)), f"{label} не должен быть рабочим моментом"


def test_contains_on_empty_calendar_is_false():
    """Пустой календарь не содержит ни одного момента."""
    assert cal(()).contains(t("12:00")) is False


# --------------------------------------------------------------------------
# Включительность правой границы интервала (согласованное решение по SPEC §3.1)
# --------------------------------------------------------------------------


def test_right_boundary_is_working_moment_for_every_method():
    """Правая граница интервала — рабочий момент для contains/first/add(0)/sub(0).

    Согласованное решение: границы включительны ВЕЗДЕ. Раньше `first_m` работал
    как полуинтервал [начало, конец) и перепрыгивал 13:00 на 14:00.
    """
    c = cal(SPLIT)
    edge = t("13:00")
    assert c.contains(edge)
    assert_dt(c.first_moment_at_or_after(edge), edge, "first_moment на правой границе")
    assert_dt(c.add(edge, 0), edge, "add(t, 0) на правой границе")
    assert_dt(c.sub(edge, 0), edge, "sub(t, 0) на правой границе")


def test_zero_length_operations_never_jump_over_the_break():
    """Нулевые add/sub не переносят момент через перерыв.

    Это важно для расписания: `departure_at = add(t0, 0)` не должен сам по себе
    отправлять инженера обедать.
    """
    c = cal(SPLIT)
    for label in ("09:00", "11:11", "13:00", "14:00", "18:00"):
        moment = t(label)
        assert_dt(c.add(moment, 0), moment, f"add({label}, 0)")
        assert_dt(c.sub(moment, 0), moment, f"sub({label}, 0)")


def test_consumption_still_skips_the_exhausted_interval():
    """Включительная граница не ломает расходование: add(13:00, 30) == 14:30.

    Момент 13:00 рабочий, но работать из него уже негде — минуты уходят во
    второй интервал.
    """
    c = cal(SPLIT)
    assert_dt(c.add(t("13:00"), 30), t("14:30"), "расход из правой границы")
    assert_dt(c.add(t("13:00"), 1), t("14:01"), "одна минута из правой границы")


def test_sub_from_left_boundary_goes_into_previous_interval():
    """Симметрично: расход назад из левой границы уходит в предыдущий интервал."""
    c = cal(SPLIT)
    assert_dt(c.sub(t("14:00"), 30), t("12:30"), "расход назад из левой границы")


def test_add_and_sub_agree_on_boundaries_in_working_time():
    """add и sub согласованы на всех четырёх границах графика.

    Точное равенство моментов тут требовать нельзя: 13:00 и 14:00 разделены нулём
    рабочих минут, то есть это одна и та же точка в рабочем времени, и sub вправе
    вернуть любую из них. Проверяем именно это — нулевой рабочий зазор.
    """
    c = cal(SPLIT)
    for label in ("09:00", "13:00", "14:00", "18:00"):
        for minutes in (0, 5, 60, 240):
            forward = c.add(t(label), minutes)
            if forward is None:
                continue
            back = c.sub(forward, minutes)
            assert back is not None, f"sub вернул None для add({label}, {minutes})"
            lo, hi = sorted((back, t(label)))
            assert c.working_between(lo, hi) == pytest.approx(0.0, abs=1e-6), (
                f"add/sub({label}, {minutes}): вернулись в {hhmm(back)} — "
                f"это другая точка рабочего времени"
            )


def test_shift_end_is_reachable_and_terminal():
    """Конец смены — рабочий момент, но расходовать из него уже нечего."""
    c = cal(SINGLE)
    end = t("18:00")
    assert c.contains(end)
    assert_dt(c.first_moment_at_or_after(end), end, "конец смены")
    assert_dt(c.add(end, 0), end, "add(18:00, 0)")
    assert c.add(end, 1) is None, "после конца смены работать нельзя"


# --------------------------------------------------------------------------
# сквозная согласованность
# --------------------------------------------------------------------------


def test_three_intervals_are_handled_in_order():
    """Календарь из трёх кусков: минуты копятся последовательно."""
    c = cal([("09:00", "10:00"), ("11:00", "12:00"), ("13:00", "14:00")])
    assert c.capacity_minutes == pytest.approx(180.0)
    # 30 минут в первом интервале + 60 во втором = 90, конец ровно на границе 12:00.
    assert_dt(c.add(t("09:30"), 90), t("12:00"), "три интервала")
    assert_dt(c.add(t("09:30"), 91), t("13:01"), "переход в третий интервал")
    assert c.working_between(t("09:00"), t("14:00")) == pytest.approx(180.0)


def test_interval_with_end_not_after_start_is_rejected():
    """WorkInterval требует end строго больше start (SPEC §2.2)."""
    with pytest.raises(ValueError):
        WorkInterval(t("10:00"), t("10:00"))
    with pytest.raises(ValueError):
        WorkInterval(t("10:00"), t("09:00"))


def test_add_supports_fractional_minutes():
    """Время в пути — float, поэтому дробные минуты обязаны работать."""
    c = cal(SINGLE)
    got = c.add(t("09:00"), 12.5)
    assert_dt(got, t("09:00") + timedelta(minutes=12.5), "дробные минуты", tol=0.5)

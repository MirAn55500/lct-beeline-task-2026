"""Независимая проверка готового плана.

Верификатор намеренно **не** использует внутренние структуры планировщика: он заново
считает расписание каждого маршрута по определению из спецификации и сверяет с тем, что
план заявляет. Смысл в том, чтобы ошибка в оптимизаторе не могла «подтвердить сама себя».

Пустой список нарушений = план корректен. Это же используется в тестах как единственный
критерий допустимости результата.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .calendar import WorkCalendar
from .enums import AssignmentStatus
from .feasibility import check_static
from .models import Scenario
from .result import PlanResult
from .travel import HaversineTravelModel, TravelModel

__all__ = ["validate_plan"]

_TOL_MINUTES = 1.0 / 60.0  # одна секунда
_TOL_KM = 1e-6


def validate_plan(
    result: PlanResult, scenario: Scenario, travel: TravelModel | None = None
) -> list[str]:
    """Возвращает список найденных нарушений. Пустой список означает корректный план."""
    problems: list[str] = []
    travel = travel or HaversineTravelModel(scenario.settings)
    requests = scenario.request_by_id
    engineers = scenario.engineer_by_id

    problems += _check_coverage(result, scenario)
    problems += _check_no_duplicates(result)

    for route in result.routes:
        problems += _check_route(
            route, scenario, requests, engineers, travel, result.not_before
        )

    problems += _check_totals(result)
    problems += _check_unassigned(result)
    problems += _check_assignments_match_routes(result)

    return problems


# --------------------------------------------------------------------------------------


def _check_coverage(result: PlanResult, scenario: Scenario) -> list[str]:
    problems: list[str] = []
    seen = [a.request_id for a in result.assignments]
    expected = {r.id for r in scenario.planning_requests()}
    if len(seen) != len(set(seen)):
        problems.append("Инвариант 1: на одну заявку приходится больше одного назначения")
    missing = expected - set(seen)
    if missing:
        problems.append(f"Инвариант 1: без результата распределения остались заявки {sorted(missing)}")
    extra = set(seen) - expected
    if extra:
        problems.append(f"Инвариант 1: в плане есть заявки не из входных данных: {sorted(extra)}")
    return problems


def _check_no_duplicates(result: PlanResult) -> list[str]:
    seen: dict[str, str] = {}
    problems: list[str] = []
    for route in result.routes:
        if not route.visits:
            problems.append(f"Инвариант 7: маршрут {route.engineer_id} создан без визитов")
        for visit in route.visits:
            if visit.request_id in seen:
                problems.append(
                    f"Инвариант 2: заявка {visit.request_id} назначена и "
                    f"{seen[visit.request_id]}, и {route.engineer_id}"
                )
            seen[visit.request_id] = route.engineer_id
    return problems


def _check_route(
    route, scenario, requests, engineers, travel, not_before=None
) -> list[str]:
    problems: list[str] = []
    engineer = engineers.get(route.engineer_id)
    if engineer is None:
        return [f"Маршрут ссылается на неизвестного инженера {route.engineer_id}"]
    if not engineer.active:
        problems.append(f"Инженер {engineer.id} не участвует в планировании, но имеет маршрут")

    if not route.start_point.is_same_as(engineer.start_point):
        problems.append(f"Инвариант 9: маршрут {engineer.id} стартует не из точки инженера")

    positions = [v.position for v in route.visits]
    if positions != list(range(1, len(route.visits) + 1)):
        problems.append(f"Инвариант 5: нарушена нумерация визитов в маршруте {engineer.id}")

    calendar = WorkCalendar(engineer.work_intervals, _origin(scenario, engineer))
    settings = scenario.settings
    strict = settings.service_must_start_within_window

    cursor = calendar.shift_start
    point = engineer.start_point
    distance_sum = 0.0
    travel_sum = 0.0
    previous_end: datetime | None = None

    for visit in route.visits:
        request = requests.get(visit.request_id)
        if request is None:
            problems.append(f"Визит ссылается на неизвестную заявку {visit.request_id}")
            continue

        static = check_static(engineer, request, settings)
        if not static.ok:
            problems.append(
                f"Жёсткое ограничение нарушено ({static.reason}): заявка {request.id} "
                f"у инженера {engineer.id} — {static.detail}"
            )

        if visit.locked:
            # Начатая работа — зафиксированный факт предыдущего плана, а не решение
            # текущего расчёта. Пересчитывать её нечем и незачем: проверяется только
            # непротиворечивость (работы не наезжают друг на друга) и допуск инженера.
            if previous_end is not None and visit.departure_at < previous_end - timedelta(seconds=1):
                problems.append(
                    f"Инвариант 4: в маршруте {engineer.id} работы пересекаются перед заявкой {request.id}"
                )
            if visit.service_end_at < visit.service_start_at:
                problems.append(
                    f"Заявка {request.id}: зафиксированная работа заканчивается раньше, чем начинается"
                )
            distance_sum += visit.distance_km
            travel_sum += visit.travel_minutes
            previous_end = visit.service_end_at
            cursor = visit.service_end_at
            point = request.point
            continue

        if cursor is None:
            problems.append(f"Инженер {engineer.id}: рабочее время исчерпано до заявки {request.id}")
            break

        # «Сейчас» после события: работа, которая ещё не началась, не могла быть назначена
        # раньше него — верификатор обязан считать по тому же правилу, что и планировщик
        # (`RouteState.floor_m`). Пол применяется к КАЖДОЙ незамороженной работе, а не
        # только к началу маршрута: после начатого визита курсор встаёт в его окончание,
        # и без пола верификатор ждал следующую работу сразу за ним — в прошлом.
        if not_before is not None and cursor < not_before:
            cursor = not_before

        mode = engineer.transport_mode
        km = travel.distance_km(point, request.point, mode)
        earliest_departure = calendar.first_moment_at_or_after(cursor)
        # Общественный транспорт по профилю: время в пути — своё у каждого момента выезда
        timed = travel if getattr(travel, "is_timed", None) and travel.is_timed(mode) else None

        def leg_minutes(departure: datetime | None, a=point, b=request.point) -> float:
            if timed is None or departure is None:
                return travel.travel_minutes(a, b, mode)
            return timed.minutes_at(a, b, mode, calendar.to_minutes(departure))

        minutes = leg_minutes(earliest_departure)
        earliest_arrival = (
            calendar.add(earliest_departure, minutes) if earliest_departure else None
        )

        if earliest_arrival is None:
            problems.append(f"Заявка {request.id}: до неё невозможно доехать в пределах смены")
            break
        if earliest_arrival > request.window_end:
            problems.append(
                f"Инвариант 3: заявка {request.id} — прибытие {earliest_arrival:%H:%M} "
                f"позже конца окна {request.window_end:%H:%M}"
            )
        service_start = calendar.first_moment_at_or_after(
            max(earliest_arrival, request.service_not_before)
        )
        if service_start is None:
            problems.append(f"Заявка {request.id}: работу негде начать в рабочем времени")
            break

        # Отложенный выезд (SPEC §3.3): выезжаем так, чтобы приехать к началу работ,
        # но не раньше, чем освободились, и не позже конца окна прибытия.
        aim = min(service_start, request.window_end)
        if timed is None:
            departure = calendar.sub(aim, minutes)
            if departure is None or departure < earliest_departure:
                departure, arrival = earliest_departure, earliest_arrival
            else:
                arrival = calendar.add(departure, minutes)
                if arrival is None or arrival > request.window_end:
                    departure, arrival = earliest_departure, earliest_arrival
        else:
            # Самый поздний выезд, с которым по расписанию успеваем к началу работ
            departure, arrival = earliest_departure, earliest_arrival
            later = calendar.first_moment_at_or_after(calendar.to_datetime(
                timed.depart_by(point, request.point, mode, calendar.to_minutes(aim))
            ))
            if later is not None and later > earliest_departure:
                later_arrival = calendar.add(later, leg_minutes(later))
                if later_arrival is not None and later_arrival <= aim + timedelta(seconds=1):
                    departure, arrival = later, later_arrival
            minutes = leg_minutes(departure)
        if service_start < request.window_start:
            problems.append(
                f"Инвариант 3: заявка {request.id} — работа начата до открытия окна"
            )
        if request.received_at is not None and service_start < request.received_at:
            problems.append(
                f"Инвариант 3: заявка {request.id} — работа начата до поступления "
                f"({service_start:%H:%M} < {request.received_at:%H:%M})"
            )
        if strict and service_start > request.window_end:
            problems.append(
                f"Инвариант 3: заявка {request.id} — начало работ {service_start:%H:%M} "
                f"позже конца окна {request.window_end:%H:%M}"
            )
        service_end = calendar.add(service_start, request.duration_minutes)
        if service_end is None:
            problems.append(
                f"Инвариант 3: заявка {request.id} не укладывается в смену инженера {engineer.id}"
            )
            break

        if previous_end is not None and visit.departure_at < previous_end - timedelta(seconds=1):
            problems.append(
                f"Инвариант 4: в маршруте {engineer.id} работы пересекаются перед заявкой {request.id}"
            )

        problems += _compare_moment(request.id, "выезд", visit.departure_at, departure)
        problems += _compare_moment(request.id, "прибытие", visit.arrival_at, arrival)
        problems += _compare_moment(request.id, "начало работ", visit.service_start_at, service_start)
        problems += _compare_moment(request.id, "окончание работ", visit.service_end_at, service_end)

        if abs(visit.distance_km - km) > _TOL_KM:
            problems.append(
                f"Заявка {request.id}: заявленное расстояние участка {visit.distance_km:.4f} км "
                f"не совпадает с расчётным {km:.4f} км"
            )

        distance_sum += km
        travel_sum += minutes
        previous_end = service_end
        cursor = service_end
        point = request.point

    if abs(route.distance_km - distance_sum) > 1e-6:
        problems.append(
            f"Маршрут {engineer.id}: сумма участков {distance_sum:.4f} км "
            f"не равна заявленному пробегу {route.distance_km:.4f} км"
        )
    if abs(route.travel_minutes - travel_sum) > _TOL_MINUTES:
        problems.append(f"Маршрут {engineer.id}: заявленное время в пути не сходится с расчётным")

    return problems


def _compare_moment(request_id: str, label: str, declared, computed) -> list[str]:
    if declared is None:
        return [f"Заявка {request_id}: не указано {label}"]
    delta = abs((declared - computed).total_seconds()) / 60.0
    if delta > _TOL_MINUTES:
        return [
            f"Заявка {request_id}: заявленное {label} {declared:%H:%M:%S} "
            f"расходится с расчётным {computed:%H:%M:%S}"
        ]
    return []


def _check_totals(result: PlanResult) -> list[str]:
    problems: list[str] = []
    total_distance = sum(r.distance_km for r in result.routes)
    if abs(total_distance - result.metrics.total_distance_km) > 1e-6:
        problems.append("Инвариант 8: суммарный пробег плана не равен сумме пробегов маршрутов")
    used = sum(1 for r in result.routes if r.visits)
    if used != result.metrics.used_engineer_count:
        problems.append("Инвариант 7: число задействованных инженеров не совпадает с числом маршрутов")
    assigned = sum(1 for a in result.assignments if a.is_assigned)
    if assigned != result.metrics.assigned_count:
        problems.append("Метрика assigned_count не совпадает с числом назначенных заявок")
    if assigned + result.metrics.unassigned_count != len(result.assignments):
        problems.append("Назначенные и неназначенные в сумме не дают всех заявок плана")
    return problems


def _check_unassigned(result: PlanResult) -> list[str]:
    problems: list[str] = []
    for assignment in result.assignments:
        if assignment.status is AssignmentStatus.UNASSIGNED:
            if assignment.reason is None:
                problems.append(f"Инвариант 6: у заявки {assignment.request_id} нет кода причины")
            if not assignment.explanation.strip():
                problems.append(f"Инвариант 6: у заявки {assignment.request_id} нет объяснения")
            if assignment.engineer_id is not None:
                problems.append(
                    f"У неназначенной заявки {assignment.request_id} указан исполнитель"
                )
    return problems


def _check_assignments_match_routes(result: PlanResult) -> list[str]:
    problems: list[str] = []
    in_routes: dict[str, tuple[str, int]] = {}
    for route in result.routes:
        for visit in route.visits:
            in_routes[visit.request_id] = (route.engineer_id, visit.position)

    # Обратная сторона инварианта 1: визит в маршруте обязан иметь своё назначение.
    # Без этой проверки заявка, попавшая в маршрут мимо `planning_requests()`, молча
    # исчезала из назначений и из метрик, а план выглядел корректным.
    declared = {a.request_id for a in result.assignments}
    for request_id in sorted(set(in_routes) - declared):
        engineer_id, position = in_routes[request_id]
        problems.append(
            f"Инвариант 1: заявка {request_id} стоит в маршруте {engineer_id} "
            f"на позиции {position}, но у неё нет Assignment"
        )

    for assignment in result.assignments:
        if assignment.is_assigned:
            placed = in_routes.get(assignment.request_id)
            if placed is None:
                problems.append(
                    f"Заявка {assignment.request_id} помечена назначенной, но её нет ни в одном маршруте"
                )
            elif placed != (assignment.engineer_id, assignment.position):
                problems.append(
                    f"Заявка {assignment.request_id}: назначение и маршрут расходятся "
                    f"({assignment.engineer_id}/{assignment.position} против {placed[0]}/{placed[1]})"
                )
        elif assignment.request_id in in_routes:
            problems.append(
                f"Заявка {assignment.request_id} помечена неназначенной, но присутствует в маршруте"
            )
    return problems


def _origin(scenario: Scenario, engineer) -> datetime:
    from datetime import time as _time_cls

    tzinfo = (
        engineer.work_intervals[0].start.tzinfo
        if engineer.work_intervals
        else (scenario.requests[0].window_start.tzinfo if scenario.requests else None)
    )
    return datetime.combine(scenario.date, _time_cls(0, 0), tzinfo=tzinfo)

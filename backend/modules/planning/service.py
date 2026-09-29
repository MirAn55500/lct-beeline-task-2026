import asyncio
import logging
import math
from collections.abc import Iterable
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from sqlmodel.ext.asyncio.session import AsyncSession

from core.database import async_session_factory
from core.exceptions import AppError
from modules.algorithm.service import AlgorithmService
from modules.planning import background
from modules.planning import board as boards
from modules.planning import transit
from modules.planning.models.assignment import Assignment
from modules.planning.models.plan import Plan
from modules.planning.repository import PlanningRepository
from modules.planning.scenario_builder import (
    _REASON_LABELS,
    assignments_from_result,
    build_travel,
    fetch_lines,
    finish_plan,
    lunch_address_ids,
    lunch_rows,
    route_legs,
    build_scenario,
    reason_index,
    restrict_availability,
    run_plan,
    street_path,
)
from modules.planning import routing_cache
from modules.planning.schemas import (
    CounterPair,
    MoveBatchRequest,
    MoveLunchExport,
    MoveRequest,
    MoveResponse,
    MoveVisitExport,
    PlanSlotsResponse,
    RequestSlotsExport,
    PlanEngineerExport,
    PlanExportResponse,
    PlanLunchExport,
    PlanRequestExport,
    PlanRouteExport,
    PlanUnassignedExport,
    PlanVisitExport,
    DayOverviewResponse,
    Distribution,
    EngineersCounter,
    PlanComparison,
    ComparisonLine,
    PlanEventRequest,
    PlanEventResponse,
    PlanVersionResponse,
    RecalculateResponse,
    RemakeLevel,
)
from planner import Algorithm
from planner.dispatch import Board, MoveOutcome, StoredLunch, StoredVisit
from planner.enums import EventType, ReasonCode, ReplanScope
from planner.metrics import compare as compare_plans
from planner.models import ReplanEvent, Scenario
from planner.ors import DEFAULT_PROFILES, Routing
from planner.replan import rebuild_unstarted, replan
from planner.result import PlanResult

logger = logging.getLogger(__name__)

# Базовые планы, которые считаются в фоне: plan_id версии → задача. Сравнение, открытое
# сразу после «Обновить план», дожидается задачи, а не считает второй раз.
_baseline_jobs: dict[int, asyncio.Task] = {}


def schedule_baseline(plan: Plan) -> None:
    """Базовый план при версии — в фоне: версия сохранена, ответ не ждёт линий по улицам."""
    if plan.plan_id is None or plan.distribution == Distribution.EVEN.value:
        return
    plan_id = plan.plan_id

    async def job() -> None:
        try:
            async with async_session_factory() as session:
                service = PlanningService(session)
                source = await service._repo.get_plan(plan_id)
                if source is not None:
                    await service._save_baseline(source)
        finally:
            _baseline_jobs.pop(plan_id, None)

    _baseline_jobs[plan_id] = asyncio.create_task(job())


def inherit_baseline(source_id: int, plan: Plan) -> None:
    """Базовый план версии после ручного хода — тот же, что у исходной версии.

    Ход на Ганте не меняет ни заявок, ни инженеров, а базовый план считается с нуля
    именно по ним: ручных правок алгоритм ТЗ не видит. Пересчёт на каждый ход стоил
    секунды CPU (расчёт, линии по улицам всех маршрутов, снимок) и шёл в фоне как раз
    тогда, когда диспетчер делал следующий ход. Базовый план исходной версии, который
    ещё считается, дожидаемся; если его нет — сравнение посчитает его по запросу.
    """
    if plan.plan_id is None:
        return
    plan_id = plan.plan_id

    async def job() -> None:
        try:
            source_job = _baseline_jobs.get(source_id)
            if source_job is not None:
                await asyncio.shield(source_job)
            async with async_session_factory() as session:
                await PlanningService(session)._copy_baseline(source_id, plan_id)
        except Exception:
            logger.exception("Базовый план версии %d не перенесён с версии %d", plan_id, source_id)
        finally:
            _baseline_jobs.pop(plan_id, None)

    _baseline_jobs[plan_id] = asyncio.create_task(job())


# Линии по улицам для новых участков — после ответа, по одному плану за раз: ORS на
# стенде строит участок пешехода 3–14 с, а несколько поисков сразу роняли его по памяти
_drawing = asyncio.Lock()
_drawing_jobs: set[asyncio.Task] = set()


def schedule_lines(plan_id: int, routing: Routing, result: PlanResult) -> None:
    """Достроить в фоне линии, которых не было в кэше, и обновить снимок версии.

    Версия сохранена с прямыми участками там, где линии ещё не было (`lines="cache"`).
    Выдача плана подхватит линии из кэша (`street_path`), а снимок — вид версии в
    истории — пересохраняется, когда они готовы.
    """

    async def job() -> None:
        async with _drawing:
            try:
                if not await asyncio.to_thread(fetch_lines, routing, result):
                    return
                async with async_session_factory() as session:
                    service = PlanningService(session)
                    plan = await service._repo.get_plan(plan_id)
                    if plan is not None:
                        await service._save_snapshot(plan)
            except Exception:
                logger.exception("Линии по улицам версии %d не достроены", plan_id)

    task = asyncio.create_task(job())
    _drawing_jobs.add(task)
    task.add_done_callback(_drawing_jobs.discard)


_REMAKE_TO_SCOPE = {
    RemakeLevel.FIX: ReplanScope.LOW,
    RemakeLevel.ENGINEER: ReplanScope.MEDIUM,
    RemakeLevel.FREE: ReplanScope.HIGH,
}

_DISTRIBUTION_TO_ALGORITHM = {
    Distribution.EVEN: Algorithm.BASELINE,
    Distribution.EFFICIENT: Algorithm.OPTIMIZED,
}


def reason_code(label: str) -> str:
    """Код причины неназначения по значению словаря: там код или старая подпись."""
    label = label.strip().lower()
    return next((c for c, text in _REASON_LABELS.items() if label in {c, text}), "not_found")


def _minutes(value: float) -> float:
    return round(value, 2)


def _not_before(value: float) -> float:
    """Ранний край окна постановки — с округлением вверх: 562,066 → 562,07, а не раньше."""
    return math.ceil(value * 100 - 1e-6) / 100


def _not_after(value: float) -> float:
    """Поздний край — вниз: 567,998 не должен стать 568,00, в которое заявка уже не встанет."""
    return math.floor(value * 100 + 1e-6) / 100


class PlanningService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = PlanningRepository(session)
        self._rows: tuple[list, list] = ([], [])
        self._algorithm = AlgorithmService()

    def health(self) -> dict[str, str]:
        return {"module": "planning", "status": "ok"}

    async def get_day_overview(
        self, region_id: int, day: date, plan_id: int | None = None
    ) -> DayOverviewResponse:
        planning, planning_error, planning_eta = background.status(region_id, day)
        tickets_total = await self._repo.count_requests(region_id, day)
        engineers_total = await self._repo.count_engineers(region_id)
        planned_dates = await self._repo.list_planned_dates(region_id)
        plans = await self._repo.list_plans(region_id, day)
        versions = [
            PlanVersionResponse(
                plan_id=item.plan_id,
                version=item.version,
                created_at=item.created_at,
                distribution=_plan_distribution(item.distribution),
            )
            for item in plans
            if item.plan_id is not None
        ]
        if plan_id is None:
            plan = plans[0] if plans else None
        else:
            plan = next((item for item in plans if item.plan_id == plan_id), None)
            if plan is None:
                raise AppError("План не найден", status_code=404)

        if plan is None or plan.plan_id is None:
            return DayOverviewResponse(
                plan_id=None,
                plan_version=None,
                has_plan=False,
                tickets=CounterPair(assigned=None, total=tickets_total),
                engineers=EngineersCounter(engaged=None, total=engineers_total),
                planned_dates=planned_dates,
                plans=versions,
                planning=planning,
                planning_error=planning_error,
                planning_eta_seconds=planning_eta,
                rebuild_eta_seconds=background.rebuild_estimate(),
            )

        # Сводка считается из того же вида версии, что показывают карта и Гант: старая —
        # из снимка, последняя — по текущим данным. Отдельные запросы к БД расходились с планом
        # (заявка, перенесённая на другой день, оставалась в «назначено»).
        shown = await self._export(plan, latest=plan is plans[0])
        visits = [v for route in shown.routes for v in route.visits]
        tickets_total = len(shown.requests)
        assigned = len(visits)
        engaged = sum(1 for route in shown.routes if route.visits)
        travel_minutes = sum(v.travelMinutes for v in visits)
        distance_km = sum(v.distanceKm for v in visits)

        return DayOverviewResponse(
            plan_id=plan.plan_id,
            plan_version=plan.version,
            has_plan=True,
            tickets=CounterPair(assigned=assigned, total=tickets_total),
            engineers=EngineersCounter(engaged=engaged, total=engineers_total),
            planned_dates=planned_dates,
            plans=versions,
            planning=planning,
            planning_error=planning_error,
            planning_eta_seconds=planning_eta,
            rebuild_eta_seconds=background.rebuild_estimate(),
            travel_minutes=round(travel_minutes, 1),
            distance_km=round(distance_km, 1),
        )

    async def _scenario(self, region_id: int, day: date):
        region = await self._repo.get_region(region_id)
        if region is None:
            raise AppError("Регион не найден", status_code=404)

        requests = await self._repo.list_requests_for_plan(region_id, day)
        if not requests:
            raise AppError("На эту дату в регионе нет заявок")

        engineers = await self._repo.list_engineers_for_plan(region_id)
        # Инженеры в выходной (свой или бригады) в новый план не попадают
        working = [e for e in engineers if e.works_on(day)]
        if engineers and not working:
            raise AppError(
                "В этот день никто из инженеров региона не работает — проверьте рабочий "
                "график в карточках бригады и инженеров"
            )
        engineers = working
        scenario, transport_by_engineer = build_scenario(
            day=day,
            region_id=region_id,
            region_name=region.region_name,
            requests=requests,
            engineers=engineers,
        )
        scenario = restrict_availability(scenario, await self._repo.unavailable_cutoffs(day))
        if not scenario.requests:
            raise AppError("Нет открытых заявок для расчёта")
        self._rows = (requests, engineers)
        return scenario, transport_by_engineer

    async def recalculate(
        self,
        region_id: int,
        day: date,
        *,
        remake_level: RemakeLevel = RemakeLevel.FREE,
        distribution: Distribution = Distribution.EFFICIENT,
        fresh: Iterable[int] = (),
        compare: bool = False,
    ) -> RecalculateResponse:
        """Новая версия плана дня.

        «Свободный» пересобирает весь день, но сегодня не трогает начатое: визиты, к которым
        инженер уже выехал, остаются как есть (`_rebuild_unstarted`). Первый план дня,
        прошедший или будущий день и «Базовое» — расчёт с нуля. «Фикс» и «Инженерный» берут
        последнюю версию и только ставят в неё заявки, которых там нет: в свободные окна
        или (Инженерный) с вытеснением внутри маршрута одного инженера, см. `Board.place_new`.
        `fresh` — id добавленных и изменённых загрузкой заявок: их прежние визиты
        не сохраняются, заявки ставятся заново.
        """
        scenario, transport_by_engineer = await self._scenario(region_id, day)
        scenario.settings.replan_scope = _REMAKE_TO_SCOPE[remake_level]
        algorithm = _DISTRIBUTION_TO_ALGORITHM[distribution]

        previous = await self._repo.find_latest_plan(region_id, day)
        profiles = await transit.load_profiles(self._repo.session, scenario)
        result = None
        if remake_level is not RemakeLevel.FREE and previous is not None:
            result = await self._extend(previous.plan_id or 0, day, scenario, profiles, fresh, remake_level)
        elif previous is not None and algorithm is Algorithm.OPTIMIZED:
            result = await self._rebuild_unstarted(previous.plan_id or 0, day, scenario, profiles, fresh)
        if result is None:
            result = await asyncio.to_thread(run_plan, scenario, algorithm, profiles)
        comparison = None
        if compare and algorithm is Algorithm.OPTIMIZED:
            baseline = await asyncio.to_thread(
                run_plan, scenario, Algorithm.BASELINE, profiles, lines="none"
            )
            comparison = _comparison(compare_plans(baseline, result))
        plan, assigned, unassigned = await self._persist(
            region_id,
            day,
            scenario,
            result,
            transport_by_engineer,
            distribution=distribution.value,
        )
        response = RecalculateResponse(
            plan_id=plan.plan_id or 0,
            version=plan.version,
            assigned=assigned,
            unassigned=unassigned,
            comparison=comparison,
        )
        schedule_baseline(plan)
        return response

    async def _persist(
        self,
        region_id: int,
        day: date,
        scenario,
        result,
        transport_by_engineer,
        *,
        distribution: str | None = None,
    ):
        reasons = await self._repo.ensure_unassigned_reasons()
        rows, assigned, unassigned = assignments_from_result(
            result,
            transport_by_engineer=transport_by_engineer,
            reason_by_code=reason_index(reasons),
            offset_hours=scenario.settings.timezone_offset_hours,
            scenario=scenario,
        )
        previous = await self._repo.find_latest_plan(region_id, day)
        version = (previous.version + 1) if previous is not None else 1
        requests, engineers = self._rows
        offset = scenario.settings.timezone_offset_hours
        # События и ручные правки без явного режима наследуют прошлую версию.
        saved_distribution = distribution or (
            previous.distribution if previous is not None else Distribution.EFFICIENT.value
        )
        plan = await self._repo.save_plan(
            region_id=region_id,
            day=day,
            version=version,
            reference_plan_id=previous.plan_id if previous is not None else None,
            rows=rows,
            lunches=lunch_rows(result, offset),
            distribution=saved_distribution,
            legs=self._legs(result, transport_by_engineer, offset),
        )
        await self._save_snapshot(plan)
        if previous is not None and previous.plan_id is not None:
            boards.drop(previous.plan_id)
        return plan, assigned, unassigned

    def _legs(self, result, transport_by_engineer, offset: float) -> dict[int, dict]:
        """Участки маршрутов для таблицы `routes` — по заявкам и инженерам последнего сценария."""
        requests, engineers = self._rows
        return route_legs(
            result,
            address_of={r.request_id: r.address_id for r in requests if r.request_id is not None},
            office_of={
                e.engineer_id: e.brigade.office_address_id
                for e in engineers
                if e.engineer_id is not None and e.brigade is not None
            },
            transport_of=transport_by_engineer,
            offset_hours=offset,
            lunch_address_of=lunch_address_ids(engineers),
        )

    async def _save_baseline(self, plan: Plan) -> Plan | None:
        """Базовый план при версии: алгоритм ТЗ (п. 2.3) по тем же заявкам и инженерам.

        Для сравнения планов — что дал бы наивный алгоритм на том же дне. Считается с нуля
        по данным на момент версии (начатые визиты не держит). У «Базовой» версии базовый план —
        она сама. Сбой не мешает версии: сравнение останется без базового.
        """
        if plan.plan_id is None or plan.distribution == Distribution.EVEN.value:
            return None
        plan_id, version, region_id, day = plan.plan_id, plan.version, plan.region_id, plan.date
        try:
            scenario, transport_by_engineer = await self._scenario(region_id, day)
            profiles = await transit.load_profiles(self._repo.session, scenario)
            # Без линий по улицам: базовый план показывают только в сравнении, без карты
            result = await asyncio.to_thread(
                run_plan, scenario, Algorithm.BASELINE, profiles, lines="none"
            )
            reasons = await self._repo.ensure_unassigned_reasons()
            offset = scenario.settings.timezone_offset_hours
            rows, _, _ = assignments_from_result(
                result,
                transport_by_engineer=transport_by_engineer,
                reason_by_code=reason_index(reasons),
                offset_hours=offset,
                scenario=scenario,
            )
            baseline = await self._repo.save_plan(
                region_id=region_id,
                day=day,
                version=version,
                reference_plan_id=None,
                rows=rows,
                lunches=lunch_rows(result, offset),
                distribution=Distribution.EVEN.value,
                baseline_of_id=plan_id,
                legs=self._legs(result, transport_by_engineer, offset),
            )
            await self._save_snapshot(baseline)
            return baseline
        except Exception:
            logger.exception("Базовый план при версии %d не посчитан", plan_id)
            await self._repo.session.rollback()
            return None

    async def _copy_baseline(self, source_id: int, plan_id: int) -> Plan | None:
        """Базовый план версии `source_id` — ещё и базовым планом версии `plan_id`.

        Сравнение показывает базовый план из снимка, поэтому копируется снимок, а не строки
        назначений. Нет снимка у исходного — None: сравнение досчитает по запросу.
        """
        source = await self._repo.find_baseline(source_id)
        target = await self._repo.get_plan(plan_id)
        snapshot = await self._repo.get_snapshot(source.plan_id) if source and source.plan_id else None
        if source is None or snapshot is None or target is None:
            return None
        copy = Plan(
            version=target.version,
            date=target.date,
            region_id=target.region_id,
            created_at=datetime.now(),
            distribution=Distribution.EVEN.value,
            baseline_of_id=plan_id,
            lunches=source.lunches,
        )
        self._repo.session.add(copy)
        await self._repo.session.flush()
        copy.snapshot = {**snapshot, "planId": copy.plan_id, "version": copy.version}
        await self._repo.session.commit()
        return copy

    async def apply_event(
        self, region_id: int, day: date, body: PlanEventRequest
    ) -> PlanEventResponse:
        """Отмена заявки или недоступность инженера: ремонт остатка дня и разница с прошлым планом."""
        if day < datetime.now(_PLAN_ZONE).date():
            raise AppError(_PAST_DAY, status_code=409)
        previous_plan = await self._repo.find_latest_plan(region_id, day)
        if previous_plan is None or previous_plan.plan_id is None:
            raise AppError("Сначала составьте план на этот день")
        moment = datetime.combine(day, body.at or time(12, 0), tzinfo=timezone(timedelta(hours=3)))
        scenario, transport_by_engineer = await self._scenario(region_id, day)
        scenario.settings.replan_scope = ReplanScope.HIGH

        if body.type == "cancel_request":
            if body.request_id is None:
                raise AppError("Для отмены нужна заявка")
            if str(body.request_id) not in {request.id for request in scenario.requests}:
                raise AppError("Этой заявки нет среди открытых на выбранный день")
            event = ReplanEvent(
                type=EventType.CANCEL_REQUEST,
                at=moment,
                request_id=str(body.request_id),
            )
        else:
            if body.engineer_id is None:
                raise AppError("Для недоступности нужен инженер")
            if str(body.engineer_id) not in {engineer.id for engineer in scenario.engineers}:
                raise AppError("Этого инженера нет в расчёте на выбранный день")
            event = ReplanEvent(
                type=EventType.ENGINEER_UNAVAILABLE,
                at=moment,
                engineer_id=str(body.engineer_id),
            )

        boards.drop(previous_plan.plan_id)
        entry = await self._open_board(previous_plan.plan_id)
        entry.scenario.settings.replan_scope = ReplanScope.HIGH

        def run():
            with entry.lock:
                previous = entry.board.result(plan_id=str(previous_plan.plan_id))
                repaired = replan(previous, entry.scenario, event, travel=entry.travel)
                drawn = finish_plan(
                    entry.scenario, repaired, entry.routing, entry.travel, lines="cache"
                )
                return repaired, drawn

        repaired, result = await asyncio.to_thread(run)
        if body.type == "cancel_request" and body.request_id is not None:
            await self._repo.cancel_request(body.request_id, moment.replace(tzinfo=None))
        await self._repo.add_replan_event(
            event_type=body.type,
            event_time=moment,
            request_id=body.request_id,
            engineer_id=body.engineer_id,
        )
        plan, assigned, unassigned = await self._persist(
            region_id, day, entry.scenario, result, transport_by_engineer
        )
        summary = result.diff.summary if result.diff is not None else "План пересчитан"
        response = PlanEventResponse(
            plan_id=plan.plan_id or 0,
            version=plan.version,
            assigned=assigned,
            unassigned=unassigned,
            summary=summary,
            warnings=_dispatcher_notes(result.warnings),
        )
        schedule_baseline(plan)
        if plan.plan_id is not None:
            schedule_lines(plan.plan_id, entry.routing, repaired)
        return response

    async def _extend(
        self,
        plan_id: int,
        day: date,
        scenario: Scenario,
        profiles,
        fresh: Iterable[int],
        remake_level: RemakeLevel,
    ) -> PlanResult | None:
        """Версия плана + заявки, которых в ней нет. None — восстановить нечего, считать с нуля.

        Кандидаты — новые и изменённые заявки, а также оставшиеся в версии без инженера:
        свободное окно могло найтись и для них.
        """
        fresh_ids = {str(i) for i in fresh}
        rows = [r for r in await self._repo.list_assignments(plan_id) if str(r.request_id) not in fresh_ids]
        visits, unassigned = self._stored_visits(rows, scenario)
        if not visits and any(r.engineer_id is not None for r in rows):
            return None  # в версии нет расписания визитов
        lunches = await self._stored_lunches(plan_id, scenario)
        in_plan = {v.request_id for v in visits}
        candidates = [r.id for r in scenario.planning_requests() if r.id not in in_plan]
        zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))
        now = datetime.now(zone)
        # Начатое замораживается только сегодня. Прошедший день (разбор выгрузки задним
        # числом) считается, как и расчёт с нуля, без «сейчас» — иначе заморожен весь день.
        if now.date() != day:
            now = None

        def compute() -> PlanResult:
            routing, travel = build_travel(scenario, profiles)
            board = Board(
                scenario, visits, unassigned=unassigned, travel=travel, now=now, lunches=lunches
            )
            board.place_new(candidates, scope=_REMAKE_TO_SCOPE[remake_level])
            return finish_plan(scenario, board.result(), routing, travel)

        return await asyncio.to_thread(compute)

    async def _rebuild_unstarted(
        self,
        plan_id: int,
        day: date,
        scenario: Scenario,
        profiles,
        fresh: Iterable[int],
    ) -> PlanResult | None:
        """«Свободный» посреди дня: начатое и выполненное на месте, остальное — заново.

        Начатым считается визит, к которому инженер выехал до «сейчас». None — замораживать
        нечего (не сегодня или в версии нет расписания), и день считается с нуля.
        """
        zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))
        now = datetime.now(zone)
        if now.date() != day:
            return None
        fresh_ids = {str(i) for i in fresh}
        rows = [r for r in await self._repo.list_assignments(plan_id) if str(r.request_id) not in fresh_ids]
        visits, unassigned = self._stored_visits(rows, scenario)
        if not visits:
            return None
        lunches = await self._stored_lunches(plan_id, scenario)

        def compute() -> PlanResult:
            routing, travel = build_travel(scenario, profiles)
            board = Board(
                scenario, visits, unassigned=unassigned, travel=travel, now=now, lunches=lunches
            )
            result = rebuild_unstarted(board.result(), scenario, now, travel=travel)
            return finish_plan(scenario, result, routing, travel)

        return await asyncio.to_thread(compute)

    @staticmethod
    def _stored_visits(
        rows: list[Assignment], scenario: Scenario
    ) -> tuple[list[StoredVisit], dict[str, ReasonCode]]:
        """Сохранённая версия плана → визиты для `Board` и причины неназначенных."""
        zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))

        def aware(moment: datetime | None, fallback: datetime | None = None) -> datetime:
            moment = moment or fallback
            assert moment is not None
            return moment.replace(tzinfo=zone) if moment.tzinfo is None else moment

        visits = [
            StoredVisit(
                request_id=str(r.request_id),
                engineer_id=str(r.engineer_id),
                position=r.position or 0,
                departure_at=aware(r.planned_departure_at, r.planned_start_at),
                arrival_at=aware(r.planned_arrival_at, r.planned_start_at),
                service_start_at=aware(r.planned_start_at),
                service_end_at=aware(r.planned_end_at, r.planned_start_at),
                travel_minutes=r.travel_minutes or 0.0,
                distance_km=r.distance_km or 0.0,
                waiting_minutes=r.waiting_minutes or 0.0,
            )
            for r in rows
            if r.engineer_id is not None and r.planned_start_at is not None
        ]
        unassigned = {
            str(r.request_id): ReasonCode(
                reason_code(r.unassigned_reason.value if r.unassigned_reason else "")
            )
            for r in rows
            if r.engineer_id is None
        }
        return visits, unassigned

    async def _stored_lunches(self, plan_id: int, scenario: Scenario) -> list[StoredLunch]:
        """Обеды сохранённой версии — начатые доска оставит на месте."""
        plan = await self._repo.get_plan(plan_id)
        return stored_lunches(plan.lunches if plan is not None else None, scenario)

    async def get_plan(
        self,
        region_id: int,
        day: date,
        plan_id: int | None = None,
        *,
        baseline: bool = False,
    ) -> PlanExportResponse:
        """План дня с расписанием визитов — для карты и Ганта.

        Форма ответа — как у выгрузки планировщика, на которой сделаны моки frontend
        (`PlanExport`): инженеры, заявки, маршруты с выездом/прибытием/работой и
        неназначенные с причиной. Геометрии по улицам backend не строит — маршрут
        рисуется прямыми между точками (`geometrySource: "straight"`).

        Без версии плана на день — тот же каркас: инженеры региона и заявки дня
        (все неназначенные), пустые маршруты. Так Гант/карта показывают ленту без
        задач, как «Ganta — Empty», а не пустой экран.
        """
        plans = await self._repo.list_plans(region_id, day)
        if plan_id is None:
            plan = plans[0] if plans else None
        else:
            plan = next((item for item in plans if item.plan_id == plan_id), None)
        if plan is None or plan.plan_id is None:
            return await self._empty_day(region_id, day)
        latest = plan is plans[0]
        if baseline and plan.distribution != Distribution.EVEN.value:
            # Версии до базовых расчётов: последней досчитываем по текущим данным — они те же,
            # а старую честно не восстановить, заявки с тех пор менялись.
            job = _baseline_jobs.get(plan.plan_id)
            if job is not None:
                await asyncio.shield(job)
            found = await self._repo.find_baseline(plan.plan_id)
            if found is None and latest:
                found = await self._save_baseline(plan)
            if found is None:
                raise AppError("Для этой версии базовый план не сохранялся", status_code=404)
            return await self._export(found, latest=False)
        return await self._export(plan, latest=latest)

    async def _empty_day(self, region_id: int, day: date) -> PlanExportResponse:
        """День без версии плана: инженеры и заявки есть, визитов нет."""
        region = await self._repo.get_region(region_id)
        if region is None:
            raise AppError("Регион не найден", status_code=404)
        requests = await self._repo.list_requests_for_plan(region_id, day)
        engineers = await self._repo.list_engineers_for_plan(region_id)
        working = [e for e in engineers if e.works_on(day)]
        engineers = working or engineers
        if not engineers and not requests:
            return PlanExportResponse(
                planId=0,
                version=0,
                key=str(region_id),
                region=region.region_name,
                date=day,
                engineers=[],
                requests=[],
                routes=[],
                unassigned=[],
            )
        scenario, _ = build_scenario(
            day=day,
            region_id=region_id,
            region_name=region.region_name,
            requests=requests,
            engineers=engineers,
        )
        zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))
        suffix = datetime(2000, 1, 1, tzinfo=zone).strftime("%z")
        suffix = f"{suffix[:3]}:{suffix[3:]}"

        def iso(moment: datetime | None) -> str:
            if moment is None:
                return ""
            if moment.tzinfo is not None:
                moment = moment.astimezone(zone).replace(tzinfo=None)
            return moment.isoformat(timespec="seconds") + suffix

        engineers_out = [
            PlanEngineerExport(
                id=e.id,
                name=e.name,
                start=[e.start_point.lon, e.start_point.lat],
                workIntervals=[[iso(w.start), iso(w.end)] for w in e.work_intervals],
                skills=sorted(s.value for s in e.skills),
                transport=e.transport_mode.value,
                equipment=sorted(e.equipment),
            )
            for e in scenario.engineers
        ]
        requests_out = [
            PlanRequestExport(
                id=r.id,
                point=[r.point.lon, r.point.lat],
                window=[iso(r.window_start), iso(r.window_end)],
                address=r.address,
                type=r.request_type_bk,
                skill=r.required_skill.value,
                duration=r.duration_minutes,
                priority=r.priority.value,
                equipment=sorted(r.required_equipment),
            )
            for r in scenario.requests
        ]
        starts = {e.id: [e.start_point.lon, e.start_point.lat] for e in scenario.engineers}
        routes_out = [
            PlanRouteExport(
                engineerId=e.id,
                startAt=None,
                endAt=None,
                utilization=0.0,
                geometrySource="straight",
                polyline=[starts[e.id]],
                geometry=[],
                visits=[],
            )
            for e in scenario.engineers
        ]
        unassigned_out = [
            PlanUnassignedExport(
                requestId=r.id,
                reason="no_engineers",
                explanation="План на этот день ещё не составлен",
            )
            for r in scenario.requests
        ]
        return PlanExportResponse(
            planId=0,
            version=0,
            key=str(region_id),
            region=scenario.name,
            date=day,
            engineers=engineers_out,
            requests=requests_out,
            routes=routes_out,
            unassigned=unassigned_out,
        )

    async def _export(self, plan: Plan, *, latest: bool) -> PlanExportResponse:
        """Вид версии. Старая — история: ровно такой, какой была сохранена (снимок)."""
        if not latest and plan.plan_id is not None:
            snapshot = await self._repo.get_snapshot(plan.plan_id)
            if snapshot is not None:
                return PlanExportResponse.model_validate(snapshot)
        return await self._build_export(plan)

    async def _save_snapshot(self, plan: Plan) -> None:
        """Запоминает вид версии на момент сохранения — потом она из него и показывается."""
        export = await self._build_export(plan)
        plan.snapshot = export.model_dump(mode="json")
        self._repo.session.add(plan)
        await self._repo.session.commit()

    async def _build_export(self, plan: Plan) -> PlanExportResponse:
        """Вид версии плана по текущим данным БД: заявки, инженеры, строки плана, линии."""
        assert plan.plan_id is not None
        region_id, day = plan.region_id, plan.date
        region = await self._repo.get_region(region_id)
        requests = await self._repo.list_requests_for_plan(region_id, day)
        engineers = await self._repo.list_engineers_for_plan(region_id)
        rows = await self._repo.list_assignments(plan.plan_id)
        # Версия плана — история: заявка, которую потом отменили или закрыли, в ней остаётся
        # такой, какой была. Иначе старые версии задним числом теряли бы строки.
        in_plan = {row.request_id for row in rows}
        # Окно, с которым версия считалась; у планов до миграции 0015 его нет — окно заявки
        saved_windows = {
            str(row.request_id): (row.window_start, row.window_end)
            for row in rows
            if row.window_start is not None and row.window_end is not None
        }
        scenario, _ = build_scenario(
            day=day,
            region_id=region_id,
            region_name=region.region_name if region else "",
            requests=requests,
            engineers=engineers,
            keep_closed=in_plan,
        )
        zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))
        suffix = datetime(2000, 1, 1, tzinfo=zone).strftime("%z")
        suffix = f"{suffix[:3]}:{suffix[3:]}"

        def iso(moment: datetime | None) -> str:
            if moment is None:
                return ""
            if moment.tzinfo is not None:
                moment = moment.astimezone(zone).replace(tzinfo=None)
            return moment.isoformat(timespec="seconds") + suffix

        requests_out = [
            PlanRequestExport(
                id=r.id,
                point=[r.point.lon, r.point.lat],
                window=[iso(moment) for moment in saved_windows.get(r.id, (r.window_start, r.window_end))],
                address=r.address,
                type=r.request_type_bk,
                skill=r.required_skill.value,
                duration=r.duration_minutes,
                priority=r.priority.value,
                equipment=sorted(r.required_equipment),
            )
            for r in scenario.requests
        ]
        known = {r.id for r in scenario.requests}
        engineers_out = [
            PlanEngineerExport(
                id=e.id,
                name=e.name,
                start=[e.start_point.lon, e.start_point.lat],
                workIntervals=[[iso(w.start), iso(w.end)] for w in e.work_intervals],
                skills=sorted(s.value for s in e.skills),
                transport=e.transport_mode.value,
                equipment=sorted(e.equipment),
            )
            for e in scenario.engineers
        ]
        shift_minutes = {
            e.id: sum((w.end - w.start).total_seconds() / 60 for w in e.work_intervals)
            for e in scenario.engineers
        }
        # Смена в местном времени без пояса — как времена строк плана и обедов
        shift_spans = {
            e.id: [
                (w.start.astimezone(zone).replace(tzinfo=None), w.end.astimezone(zone).replace(tzinfo=None))
                for w in e.work_intervals
            ]
            for e in scenario.engineers
        }

        def on_shift(engineer_id: str, start: datetime | None, end: datetime | None) -> float:
            """Минуты отрезка внутри текущей смены инженера.

            Загрузка — доля текущей смены: работа, оставшаяся в версии за пределами смены
            (смену поменяли после расчёта), её не занимает, и процент не уходит за 100.
            """
            if start is None or end is None:
                return 0.0
            if start.tzinfo is not None:
                start = start.astimezone(zone).replace(tzinfo=None)
            if end.tzinfo is not None:
                end = end.astimezone(zone).replace(tzinfo=None)
            return sum(
                max(0.0, (min(end, to) - max(start, since)).total_seconds() / 60)
                for since, to in shift_spans.get(engineer_id, [])
            )
        points = {r.id: [r.point.lon, r.point.lat] for r in scenario.requests}
        starts = {e.id: [e.start_point.lon, e.start_point.lat] for e in scenario.engineers}

        paths = await self._repo.list_route_paths(plan.plan_id)
        lunch_of = {str(item.get("engineer_id")): item for item in plan.lunches or []}
        # Участки, сохранённые прямыми до того, как фон достроил линию, — по кэшу
        cache = routing_cache.shared()
        profile_of = {e.id: DEFAULT_PROFILES.get(e.transport_mode) for e in scenario.engineers}
        by_engineer: dict[str, list] = {}
        unassigned_out: list[PlanUnassignedExport] = []
        for row in rows:
            request_id = str(row.request_id)
            if request_id not in known:
                continue
            if row.engineer_id is None:
                label = row.unassigned_reason.value if row.unassigned_reason else ""
                unassigned_out.append(PlanUnassignedExport(
                    requestId=request_id, reason=reason_code(label), explanation=row.explanation or label,
                ))
            elif row.planned_start_at is not None and str(row.engineer_id) in starts:
                by_engineer.setdefault(str(row.engineer_id), []).append(row)

        routes_out = []
        for engineer_id, rows in by_engineer.items():
            rows.sort(key=lambda r: (r.position or 0, r.planned_start_at))
            lunch = lunch_of.get(engineer_id)
            # Занятость — дорога, ожидание и работа: от выезда до конца работ
            busy = sum(on_shift(engineer_id, r.planned_departure_at, r.planned_end_at) for r in rows)
            shift = shift_minutes.get(engineer_id) or 0
            if lunch is not None:
                # Час обеда — не рабочее время, а дорога к месту обеда — занятость
                busy += on_shift(engineer_id, _local(lunch.get("departure_at")), _local(lunch.get("arrival_at")))
                shift = max(0.0, shift - on_shift(engineer_id, _local(lunch.get("start_at")), _local(lunch.get("end_at"))))
            detour = lunch is not None and bool(lunch.get("detour")) and lunch.get("path")
            lunch_at = int(lunch.get("after_position", 0)) if lunch is not None else -1
            # Линия маршрута — участки подряд; у визита — его срез (geometryRange),
            # дорога к месту обеда — свой срез между визитами
            geometry: list[list[float]] = []
            ranges: list[list[int] | None] = []
            lunch_range: list[int] | None = None
            real = 0
            legs = 0

            def add(path: dict) -> list[int] | None:
                nonlocal real, legs
                legs += 1
                path = street_path(path, profile_of.get(engineer_id), cache)
                segment = path.get("line") or []
                if len(segment) < 2:
                    return None
                skip = 1 if geometry and geometry[-1] == segment[0] else 0
                start = len(geometry) - 1 if skip else len(geometry)
                geometry.extend(segment[skip:])
                real += 0 if path.get("straight") else 1
                return [max(0, start), len(geometry) - 1]

            polyline = [starts[engineer_id]]
            for index, r in enumerate(rows):
                if detour and index == lunch_at:
                    lunch_range = add(lunch["path"])
                    polyline.append(lunch["point"])
                ranges.append(add(paths.get(r.assignment_id) or {}))
                polyline.append(points[str(r.request_id)])
            if detour and lunch_at >= len(rows):
                lunch_range = add(lunch["path"])
                polyline.append(lunch["point"])
            source = "ors" if real == legs else ("mixed" if real else "straight")
            start_at, end_at = rows[0].planned_departure_at, rows[-1].planned_end_at
            lunch_out = None
            if lunch is not None:
                lunch_out = PlanLunchExport(
                    afterPosition=lunch_at,
                    departureAt=iso(_local(lunch.get("departure_at"))),
                    arrivalAt=iso(_local(lunch.get("arrival_at"))),
                    startAt=iso(_local(lunch.get("start_at"))),
                    endAt=iso(_local(lunch.get("end_at"))),
                    travelMinutes=lunch.get("travel_minutes") or 0.0,
                    distanceKm=lunch.get("distance_km") or 0.0,
                    place=lunch.get("place") or "last_request",
                    address=lunch.get("address") or "",
                    point=lunch.get("point") or starts[engineer_id],
                    detour=bool(lunch.get("detour")),
                    locked=bool(lunch.get("locked")),
                    geometryRange=lunch_range if real else None,
                    transit=[leg.get("title", "") for leg in (lunch.get("path") or {}).get("transit", [])],
                )
                if lunch_at == 0 and _local(lunch.get("departure_at")) is not None:
                    start_at = min(start_at, _local(lunch.get("departure_at")))
                if lunch_at >= len(rows) and _local(lunch.get("end_at")) is not None:
                    end_at = max(end_at, _local(lunch.get("end_at")))
            routes_out.append(PlanRouteExport(
                engineerId=engineer_id,
                startAt=iso(start_at),
                endAt=iso(end_at),
                utilization=round(busy / shift, 4) if shift else 0.0,
                polyline=polyline,
                lunch=lunch_out,
                geometrySource=source,
                geometry=geometry if real else [],
                visits=[
                    PlanVisitExport(
                        requestId=str(r.request_id),
                        departureAt=iso(r.planned_departure_at),
                        arrivalAt=iso(r.planned_arrival_at),
                        serviceStartAt=iso(r.planned_start_at),
                        serviceEndAt=iso(r.planned_end_at),
                        travelMinutes=r.travel_minutes or 0.0,
                        distanceKm=r.distance_km or 0.0,
                        waitingMinutes=r.waiting_minutes or 0.0,
                        idleMinutes=r.idle_minutes or 0.0,
                        geometryRange=ranges[i] if real else None,
                        explanation=r.explanation or "",
                        transit=[
                            leg.get("title", "")
                            for leg in (paths.get(r.assignment_id) or {}).get("transit", [])
                        ],
                    )
                    for i, r in enumerate(rows)
                ],
            ))
        # Начатый обед инженера, у которого не осталось заявок: маршрут из одного обеда
        for engineer_id, lunch in lunch_of.items():
            if engineer_id in by_engineer or engineer_id not in starts or not lunch.get("locked"):
                continue
            departure, end = _local(lunch.get("departure_at")), _local(lunch.get("end_at"))
            if departure is None or end is None:
                continue
            detour = bool(lunch.get("detour"))
            shift = max(0.0, (shift_minutes.get(engineer_id) or 0) - on_shift(engineer_id, _local(lunch.get("start_at")), end))
            road = on_shift(engineer_id, departure, _local(lunch.get("arrival_at")))
            routes_out.append(PlanRouteExport(
                engineerId=engineer_id,
                startAt=iso(departure),
                endAt=iso(end),
                utilization=round(min(road, shift) / shift, 4) if shift else 0.0,
                polyline=[starts[engineer_id]] + ([lunch["point"]] if detour and lunch.get("point") else []),
                lunch=PlanLunchExport(
                    afterPosition=0,
                    departureAt=iso(departure),
                    arrivalAt=iso(_local(lunch.get("arrival_at"))),
                    startAt=iso(_local(lunch.get("start_at"))),
                    endAt=iso(end),
                    travelMinutes=lunch.get("travel_minutes") or 0.0,
                    distanceKm=lunch.get("distance_km") or 0.0,
                    place=lunch.get("place") or "last_request",
                    address=lunch.get("address") or "",
                    point=lunch.get("point") or starts[engineer_id],
                    detour=detour,
                    locked=bool(lunch.get("locked")),
                ),
                geometrySource="straight",
                geometry=[],
                visits=[],
            ))
        order = {e.id: i for i, e in enumerate(scenario.engineers)}
        routes_out.sort(key=lambda r: order.get(r.engineerId, 0))

        return PlanExportResponse(
            planId=plan.plan_id,
            version=plan.version,
            key=str(region_id),
            region=scenario.name,
            date=day,
            engineers=engineers_out,
            requests=requests_out,
            routes=routes_out,
            unassigned=unassigned_out,
        )

    # ------------------------------------------------------------ ручная правка на Ганте

    async def _open_board(self, plan_id: int) -> boards.OpenBoard:
        """Доска плана для ручных ходов: из кэша процесса или собранная из БД."""
        cached = boards.get(plan_id)
        if cached is not None:
            return cached
        plan = await self._repo.get_plan(plan_id)
        if plan is None:
            raise AppError("План не найден", status_code=404)
        region = await self._repo.get_region(plan.region_id)
        requests = await self._repo.list_requests_for_plan(plan.region_id, plan.date)
        engineers = await self._repo.list_engineers_for_plan(plan.region_id)
        scenario, transport_of = build_scenario(
            day=plan.date,
            region_id=plan.region_id,
            region_name=region.region_name if region else "",
            requests=requests,
            engineers=engineers,
        )
        scenario = restrict_availability(
            scenario, await self._repo.unavailable_cutoffs(plan.date)
        )
        zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))
        rows = await self._repo.list_assignments(plan_id)
        visits, unassigned = self._stored_visits(rows, scenario)
        if not visits and any(r.engineer_id is not None for r in rows):
            raise AppError(
                "В этой версии плана нет расписания визитов — обновите план", status_code=409
            )
        profiles = await transit.load_profiles(self._repo.session, scenario)
        lunches = stored_lunches(plan.lunches, scenario)

        def build():
            routing, travel = build_travel(scenario, profiles)
            board = Board(
                scenario,
                visits,
                unassigned=unassigned,
                travel=travel,
                now=datetime.now(zone),
                lunches=lunches,
            )
            return routing, travel, board

        routing, travel, board = await asyncio.to_thread(build)
        entry = boards.OpenBoard(
            board=board,
            scenario=scenario,
            routing=routing,
            travel=travel,
            region_id=plan.region_id,
            day=plan.date,
            transport_of=transport_of,
            address_of={r.request_id: r.address_id for r in requests if r.request_id is not None},
            office_of={
                e.engineer_id: e.brigade.office_address_id
                for e in engineers
                if e.engineer_id is not None and e.brigade is not None
            },
            lunch_address_of=lunch_address_ids(engineers),
        )
        boards.put(plan_id, entry)
        return entry

    async def _frozen_reason(self, plan_id: int) -> str | None:
        """Почему версию нельзя править руками: старая версия или прошедший день. None — можно.

        Старые версии — история. Прошедший день целиком в прошлом: ставить в него заявки
        некуда, и перетаскивание только показывало бы, что время прошло.
        """
        plan = await self._repo.get_plan(plan_id)
        if plan is None:
            raise AppError("План не найден", status_code=404)
        latest = await self._repo.find_latest_plan(plan.region_id, plan.date)
        if latest is None or latest.plan_id != plan_id:
            return _OLD_VERSION
        if plan.date < datetime.now(_PLAN_ZONE).date():
            return _PAST_DAY
        return None

    async def get_slots(
        self, plan_id: int, request_ids: list[str] | None = None
    ) -> PlanSlotsResponse:
        """Куда можно поставить заявки плана: окна по инженерам и позициям маршрута."""
        frozen = await self._frozen_reason(plan_id)
        entry = await self._open_board(plan_id)

        def compute():
            with entry.lock:
                return entry.board.slots(request_ids or None)

        items = await asyncio.to_thread(compute)
        if frozen is not None:
            items = [
                replace(item, movable=False, reason=frozen, slots={}, refusals={})
                for item in items
            ]
        return PlanSlotsResponse(
            planId=plan_id,
            requests=[
                RequestSlotsExport(
                    requestId=item.request_id,
                    movable=item.movable,
                    reason=item.reason,
                    slots={
                        engineer_id: [
                            [
                                slot.position,
                                _not_before(slot.earliest),
                                _not_after(slot.latest),
                                _minutes(slot.departure),
                                _minutes(slot.travel_minutes),
                            ]
                            for slot in slots
                        ]
                        for engineer_id, slots in item.slots.items()
                    },
                    refusals=item.refusals,
                )
                for item in items
            ],
        )

    async def move(self, plan_id: int, body: MoveRequest) -> MoveResponse:
        """Ручной ход: проверка с превью или (commit) новая версия плана."""
        frozen = await self._frozen_reason(plan_id)
        if frozen is not None:
            raise AppError(frozen, status_code=409)
        entry = await self._open_board(plan_id)
        options = dict(
            start=body.start, position=body.position, release=body.release, commit=body.commit
        )

        def apply():
            with entry.lock:
                outcome = entry.board.move(body.requestId, body.engineerId, **options)
                if not outcome.ok or not body.commit:
                    return outcome, None, None, None
                result = entry.board.result()
                # Линии по улицам — только изменившимся маршрутам: на весь план это секунды,
                # а участки остальных переносятся из исходной версии как есть.
                changed = set(outcome.engineers)
                partial = replace(
                    result,
                    routes=tuple(r for r in result.routes if r.engineer_id in changed),
                    idle_lunches=tuple(item for item in result.idle_lunches if item[0] in changed),
                )
                # Линии — из кэша: недостающие ORS достроит в фоне (`schedule_lines`)
                drawn = finish_plan(
                    entry.scenario, partial, entry.routing, entry.travel, lines="cache"
                )
                return outcome, partial, result, drawn

        try:
            outcome, partial, result, drawn = await asyncio.to_thread(apply)
        except Exception:
            boards.drop(plan_id)
            raise
        if result is None:
            return self._move_response(outcome)

        # Доска уже сделала ход: если сохранить не вышло, она расходится с БД — выбрасываем.
        try:
            reasons = await self._repo.ensure_unassigned_reasons()
            offset = entry.scenario.settings.timezone_offset_hours
            rows, _, _ = assignments_from_result(
                result,
                transport_by_engineer=entry.transport_of,
                reason_by_code=reason_index(reasons),
                offset_hours=offset,
                scenario=entry.scenario,
                window_shift=(
                    {body.requestId: outcome.window_shift} if outcome.window_shift else None
                ),
            )
            changed = set(outcome.engineers)
            legs = {
                request_id: leg
                for request_id, (engineer_id, leg) in (await self._repo.list_route_legs(plan_id)).items()
                if engineer_id is not None and str(engineer_id) not in changed
            }
            legs.update(
                route_legs(
                    drawn,
                    address_of=entry.address_of,
                    office_of=entry.office_of,
                    transport_of=entry.transport_of,
                    offset_hours=offset,
                    lunch_address_of=entry.lunch_address_of,
                )
            )
            # Обеды изменившихся маршрутов — из хода, остальные — из исходной версии как есть
            # (с её линией до места обеда). Если доска держит обед иначе, чем версия (обед
            # поменяли в карточке), — по доске: строки визитов тоже с неё.
            source = await self._repo.get_plan(plan_id)
            kept = {
                str(item.get("engineer_id")): item
                for item in (source.lunches if source is not None else None) or []
            }
            board_lunches = {str(item["engineer_id"]): item for item in lunch_rows(result, offset)}
            lunches = lunch_rows(drawn, offset)
            for engineer_id, item in board_lunches.items():
                if engineer_id in changed:
                    continue
                old = kept.get(engineer_id)
                same = old is not None and all(
                    old.get(key) == item[key] for key in ("after_position", "start_at", "place")
                )
                lunches.append(old if same else item)
            # Версию с прежним обедом, который в новые настройки не влез, доска держит без
            # обеда, но с теми же визитами — обед остаётся прежним, пока план не обновят
            lunches += [
                item
                for engineer_id, item in kept.items()
                if engineer_id not in changed and engineer_id not in board_lunches
            ]
            if outcome.window_shift:
                # Клиент согласился на время вне окна: иначе пересчёт вернул бы заявку в старое.
                await self._repo.shift_request_window(int(body.requestId), outcome.window_shift)
            latest = await self._repo.find_latest_plan(entry.region_id, entry.day)
            saved = await self._repo.save_plan(
                region_id=entry.region_id,
                day=entry.day,
                version=(latest.version + 1) if latest is not None else 1,
                reference_plan_id=plan_id,
                rows=rows,
                legs=legs,
                lunches=lunches,
                distribution=(
                    latest.distribution
                    if latest is not None and latest.distribution
                    else Distribution.EFFICIENT.value
                ),
            )
            await self._save_snapshot(saved)
        except Exception:
            boards.drop(plan_id)
            raise
        if outcome.window_shift:
            # Окно заявки в БД сдвинуто, а сценарий доски помнит старое — следующая версия
            # записала бы его. Доска соберётся заново уже с новым окном.
            boards.drop(plan_id)
        else:
            boards.rename(plan_id, saved.plan_id or 0)
        response = self._move_response(outcome)
        response.planId = saved.plan_id
        response.version = saved.version
        if outcome.window_shift:
            schedule_baseline(saved)  # окно заявки в БД сдвинуто — входные данные другие
        else:
            inherit_baseline(plan_id, saved)
        schedule_lines(saved.plan_id or 0, entry.routing, partial)
        return response

    async def move_batch(self, plan_id: int, body: MoveBatchRequest) -> MoveResponse:
        """Несколько ручных ходов подряд: превью без сохранения или одна новая версия."""
        frozen = await self._frozen_reason(plan_id)
        if frozen is not None:
            raise AppError(frozen, status_code=409)
        entry = await self._open_board(plan_id)

        def apply():
            with entry.lock:
                last: MoveOutcome | None = None
                changed: set[str] = set()
                shifts: dict[str, float] = {}
                # Превью и отказ посередине возвращают доску сюда: собирать её заново из БД
                # на каждую правку черновика — это секунды на стенде
                point = entry.board.checkpoint()
                for item in body.moves:
                    last = entry.board.move(
                        item.requestId,
                        item.engineerId,
                        start=item.start,
                        position=item.position,
                        release=item.release,
                        # Цепочка: каждый ход опирается на предыдущий; превью тоже мутирует
                        # доску — после ответа её сбросим, если commit=false.
                        commit=True,
                    )
                    if not last.ok:
                        entry.board.rollback(point)
                        return last, None, None, None, changed, shifts
                    changed.update(last.engineers)
                    if last.window_shift:
                        shifts[item.requestId] = last.window_shift
                assert last is not None
                if not body.commit:
                    entry.board.rollback(point)
                    return last, None, None, None, changed, shifts
                result = entry.board.result()
                # Линии по улицам — только изменившимся маршрутам: на весь план это секунды,
                # а участки остальных переносятся из исходной версии как есть.
                partial = replace(
                    result,
                    routes=tuple(r for r in result.routes if r.engineer_id in changed),
                    idle_lunches=tuple(item for item in result.idle_lunches if item[0] in changed),
                )
                # Линии — из кэша: недостающие ORS достроит в фоне (`schedule_lines`)
                drawn = finish_plan(
                    entry.scenario, partial, entry.routing, entry.travel, lines="cache"
                )
                return last, partial, result, drawn, changed, shifts

        try:
            outcome, partial, result, drawn, changed, shifts = await asyncio.to_thread(apply)
        except Exception:
            boards.drop(plan_id)
            raise
        if result is None:
            # Превью или отказ посередине пакета — доска уже откачена к исходной версии
            return self._move_response(outcome)

        # Доска уже сделала ходы: если сохранить не вышло, она расходится с БД — выбрасываем.
        try:
            reasons = await self._repo.ensure_unassigned_reasons()
            offset = entry.scenario.settings.timezone_offset_hours
            rows, _, _ = assignments_from_result(
                result,
                transport_by_engineer=entry.transport_of,
                reason_by_code=reason_index(reasons),
                offset_hours=offset,
                scenario=entry.scenario,
                window_shift=shifts or None,
            )
            legs = {
                request_id: leg
                for request_id, (engineer_id, leg) in (await self._repo.list_route_legs(plan_id)).items()
                if engineer_id is not None and str(engineer_id) not in changed
            }
            legs.update(
                route_legs(
                    drawn,
                    address_of=entry.address_of,
                    office_of=entry.office_of,
                    transport_of=entry.transport_of,
                    offset_hours=offset,
                    lunch_address_of=entry.lunch_address_of,
                )
            )
            # Обеды изменившихся маршрутов — из хода, остальные — из исходной версии как есть
            # (с её линией до места обеда). Если доска держит обед иначе, чем версия (обед
            # поменяли в карточке), — по доске: строки визитов тоже с неё.
            source = await self._repo.get_plan(plan_id)
            kept = {
                str(item.get("engineer_id")): item
                for item in (source.lunches if source is not None else None) or []
            }
            board_lunches = {str(item["engineer_id"]): item for item in lunch_rows(result, offset)}
            lunches = lunch_rows(drawn, offset)
            for engineer_id, item in board_lunches.items():
                if engineer_id in changed:
                    continue
                old = kept.get(engineer_id)
                same = old is not None and all(
                    old.get(key) == item[key] for key in ("after_position", "start_at", "place")
                )
                lunches.append(old if same else item)
            # Версию с прежним обедом, который в новые настройки не влез, доска держит без
            # обеда, но с теми же визитами — обед остаётся прежним, пока план не обновят
            lunches += [
                item
                for engineer_id, item in kept.items()
                if engineer_id not in changed and engineer_id not in board_lunches
            ]
            for request_id, minutes in shifts.items():
                # Клиент согласился на время вне окна: иначе пересчёт вернул бы заявку в старое.
                await self._repo.shift_request_window(int(request_id), minutes)
            latest = await self._repo.find_latest_plan(entry.region_id, entry.day)
            saved = await self._repo.save_plan(
                region_id=entry.region_id,
                day=entry.day,
                version=(latest.version + 1) if latest is not None else 1,
                reference_plan_id=plan_id,
                rows=rows,
                legs=legs,
                lunches=lunches,
                distribution=(
                    latest.distribution
                    if latest is not None and latest.distribution
                    else Distribution.EFFICIENT.value
                ),
            )
            await self._save_snapshot(saved)
        except Exception:
            boards.drop(plan_id)
            raise
        if shifts:
            # Окна заявок в БД сдвинуты, а сценарий доски помнит старые — следующая версия
            # записала бы их. Доска соберётся заново уже с новыми окнами.
            boards.drop(plan_id)
        else:
            boards.rename(plan_id, saved.plan_id or 0)
        response = self._move_response(outcome)
        response.planId = saved.plan_id
        response.version = saved.version
        if shifts:
            schedule_baseline(saved)  # окна заявок в БД сдвинуты — входные данные другие
        else:
            inherit_baseline(plan_id, saved)
        schedule_lines(saved.plan_id or 0, entry.routing, partial)
        return response

    @staticmethod
    def _move_response(outcome: MoveOutcome) -> MoveResponse:
        return MoveResponse(
            ok=outcome.ok,
            reason=outcome.reason,
            outsideWindow=outcome.outside_window,
            windowShift=_minutes(outcome.window_shift),
            engineers=list(outcome.engineers),
            visits=[
                MoveVisitExport(
                    requestId=v.request_id,
                    engineerId=v.engineer_id,
                    position=v.position,
                    departure=_minutes(v.departure),
                    arrival=_minutes(v.arrival),
                    start=_minutes(v.start),
                    end=_minutes(v.end),
                    travelMinutes=_minutes(v.travel_minutes),
                )
                for v in outcome.visits
            ],
            released=list(outcome.released),
            lunches=[
                MoveLunchExport(
                    engineerId=lunch.engineer_id,
                    afterPosition=lunch.after_position,
                    departure=_minutes(lunch.departure),
                    arrival=_minutes(lunch.arrival),
                    start=_minutes(lunch.start),
                    end=_minutes(lunch.end),
                )
                for lunch in outcome.lunches
            ],
        )


# Служебные записи маршрутизации: откуда взяты расстояния и расписания, команды прогрева
# кэша. Диспетчеру они ничего не говорят — остаются в логах backend (`finish_plan`).
_ROUTING_NOTE_PREFIXES = ("ORS:", "RAPTOR", "rRAPTOR", "Общественный транспорт:")


def _dispatcher_notes(warnings: Iterable[str]) -> list[str]:
    """Предупреждения плана, которые стоит показать диспетчеру: без служебных про маршрутизацию."""
    return [w for w in warnings if w and not w.startswith(_ROUTING_NOTE_PREFIXES)]


_OLD_VERSION = "Это старая версия плана — менять можно только последнюю"
_PAST_DAY = "День плана уже прошёл — его план не меняется"
# Пояс, в котором живут дни планов (как `Settings.timezone_offset_hours` планировщика)
_PLAN_ZONE = timezone(timedelta(hours=3))


_COMPARE_LINES = (
    ("assigned_count", "Назначено заявок", True),
    ("used_engineer_count", "Инженеров", True),
    ("total_travel_minutes", "Минут в пути", True),
    ("total_distance_km", "Пробег, км", False),
    ("distance_per_assigned_km", "Км на заявку", False),
)


def _plan_distribution(raw: str | None) -> Literal["even", "efficient"] | None:
    if raw in ("even", "efficient"):
        return raw  # type: ignore[return-value]
    return None


def _comparison(raw: dict) -> PlanComparison:
    lines: list[ComparisonLine] = []
    metrics = raw["metrics"]
    for key, label, whole in _COMPARE_LINES:
        item = metrics[key]
        render = (lambda value: str(int(round(value)))) if whole else (lambda value: f"{value:.1f}")
        lines.append(
            ComparisonLine(
                label=label,
                baseline=render(item["baseline"]),
                optimized=render(item["optimized"]),
                verdict=item["verdict"],
            )
        )
    return PlanComparison(summary=raw["summary"], lines=lines)


def _local(value: str | None) -> datetime | None:
    """Местное время обеда из `plans.lunches` (ISO без пояса)."""
    return datetime.fromisoformat(value) if value else None


def stored_lunches(items: list[dict] | None, scenario: Scenario) -> list[StoredLunch]:
    """Обеды версии плана → вход доски: начатый обед она оставит на месте."""
    zone = timezone(timedelta(hours=scenario.settings.timezone_offset_hours))
    out: list[StoredLunch] = []
    for item in items or []:
        moments = [_local(item.get(key)) for key in ("departure_at", "arrival_at", "start_at", "end_at")]
        if any(moment is None for moment in moments):
            continue
        departure, arrival, start, end = (m.replace(tzinfo=zone) for m in moments)
        out.append(
            StoredLunch(
                engineer_id=str(item.get("engineer_id")),
                departure_at=departure,
                arrival_at=arrival,
                start_at=start,
                end_at=end,
                travel_minutes=float(item.get("travel_minutes") or 0.0),
                distance_km=float(item.get("distance_km") or 0.0),
                after_position=(
                    int(item["after_position"]) if item.get("after_position") is not None else None
                ),
            )
        )
    return out

"""Планировщик рабочих маршрутов выездных инженеров.

Задача — TRSP: VRPTW с временными окнами плюс требования к навыкам, транспорту и
снаряжению исполнителя, открытые маршруты (возврат в офис не планируется), фиксированный
состав исполнителей и разрешённый отказ от части заявок с обязательным объяснением.

Точка входа одна:

    >>> from planner import plan, Scenario, Algorithm
    >>> result = plan(scenario)                      # оптимизированный расчёт
    >>> base = plan(scenario, Algorithm.BASELINE)    # базовый вариант для сравнения
    >>> compare(base, result)                        # сравнение по обязательным метрикам
    >>> replan(result, scenario, event)              # пересчёт после события дня

`plan()` не меняет переданный сценарий и полностью детерминирован: одинаковый вход даёт
побайтово одинаковый выход.
"""

from __future__ import annotations

from .context import PlanContext
from .cost import InsertionCost
from .enums import (
    Algorithm,
    AssignmentStatus,
    EventType,
    ExecutionStatus,
    Priority,
    ReasonCode,
    Skill,
    TransportMode,
)
from .feasibility import FeasibilityResult, check_static
from .manual import reassign
from .metrics import compare
from .ors import (
    DEFAULT_PROFILES,
    OrsClient,
    OrsError,
    OrsTravelModel,
    Routing,
    RoutingCache,
    attach_route_geometry,
    setup_routing,
)
from .models import (
    MSK,
    Engineer,
    GeoPoint,
    ReplanEvent,
    Request,
    Scenario,
    Settings,
    WorkInterval,
)
from .replan import apply_event, replan
from .result import (
    Assignment,
    EngineerMetrics,
    PlanDiff,
    PlanMetrics,
    PlanResult,
    RouteResult,
    Visit,
)
from .solver import plan, solve
from .travel import HaversineTravelModel, MatrixTravelModel, TravelModel
from .verify import validate_plan

__version__ = "1.0.0"

__all__ = [
    # вход
    "Scenario",
    "Request",
    "Engineer",
    "Settings",
    "GeoPoint",
    "WorkInterval",
    "ReplanEvent",
    "MSK",
    # перечисления
    "Skill",
    "TransportMode",
    "Priority",
    "ExecutionStatus",
    "Algorithm",
    "AssignmentStatus",
    "EventType",
    "ReasonCode",
    # выход
    "PlanResult",
    "RouteResult",
    "Visit",
    "Assignment",
    "PlanMetrics",
    "EngineerMetrics",
    "PlanDiff",
    # API
    "plan",
    "replan",
    "apply_event",
    "reassign",
    "compare",
    "validate_plan",
    "solve",
    # расширение
    "TravelModel",
    "HaversineTravelModel",
    "MatrixTravelModel",
    # реальная маршрутизация по улицам (openrouteservice)
    "OrsClient",
    "OrsError",
    "OrsTravelModel",
    "RoutingCache",
    "Routing",
    "setup_routing",
    "attach_route_geometry",
    "DEFAULT_PROFILES",
    "PlanContext",
    "FeasibilityResult",
    "check_static",
    "InsertionCost",
]

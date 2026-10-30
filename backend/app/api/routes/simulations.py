from __future__ import annotations

import logging
from threading import RLock
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.simulation.engine import (
    CoordinationMode,
    DEFAULT_COVERAGE_TARGET_PERCENTAGE,
    MAX_TICKS_PER_ADVANCE,
    FailureScheduleConflict,
    SimulationEngine,
)
from app.simulation.loader import (
    DatasetError,
    FailureScenarioNotFound,
    InvalidCustomFailurePlan,
    IncompatibleFailureScenario,
    ScenarioLoader,
)

logger = logging.getLogger(__name__)
router = APIRouter()
loader = ScenarioLoader()
MAX_CUSTOM_FAILURE_BODY_BYTES = 65_536


class CreateSimulationRequest(BaseModel):
    scenario_id: str = Field(min_length=1)
    mode: CoordinationMode = CoordinationMode.CENTRALIZED
    coverage_target_percentage: float = Field(
        default=DEFAULT_COVERAGE_TARGET_PERCENTAGE,
        ge=1,
        le=100,
    )


class AdvanceTicksRequest(BaseModel):
    ticks: int = Field(default=1, ge=1, le=MAX_TICKS_PER_ADVANCE)


class InstallFailureScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_scenario_id: str | None = Field(default=None, min_length=1, max_length=100)
    custom_plan: CustomFailurePlan | None = None

    @model_validator(mode="after")
    def require_exactly_one_schedule(self):
        if (self.failure_scenario_id is None) == (self.custom_plan is None):
            raise ValueError("Provide exactly one of failure_scenario_id or custom_plan.")
        return self


class CustomReconnectionTicks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detect_timeout_ticks: int = Field(strict=True, ge=0, le=10_000)
    reconnect_delay_ticks: int = Field(strict=True, ge=0, le=10_000)
    resync_time_ticks: int = Field(strict=True, ge=0, le=10_000)


class CustomPartitionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(min_length=1, max_length=50)
    drone_ids: list[str] = Field(min_length=1, max_length=100)
    has_controller_link: bool


class CustomFailureEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["controller_outage", "network_partition", "drone_unresponsive"]
    start_tick: int = Field(strict=True, ge=1, le=100_000)
    restore_tick: int | None = Field(default=None, strict=True, ge=1, le=100_000)
    drone_id: str | None = Field(default=None, min_length=1, max_length=100)
    groups: list[CustomPartitionGroup] | None = Field(default=None, min_length=2, max_length=20)
    reconnection: CustomReconnectionTicks | None = None

    @model_validator(mode="after")
    def validate_type_fields(self):
        if self.restore_tick is not None and self.restore_tick <= self.start_tick:
            raise ValueError("restore_tick must be greater than start_tick.")
        if self.type == "drone_unresponsive":
            if not self.drone_id or self.groups is not None or self.reconnection is not None:
                raise ValueError("drone_unresponsive requires only a drone_id target.")
        elif self.type == "controller_outage":
            if self.restore_tick is None or self.drone_id is not None or self.groups is not None or self.reconnection is None:
                raise ValueError("controller_outage requires restore_tick and reconnection timing.")
        elif self.type == "network_partition":
            if self.restore_tick is None or self.drone_id is not None or self.groups is None or self.reconnection is None:
                raise ValueError("network_partition requires restore_tick, groups, and reconnection timing.")
        return self


class CustomFailurePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[CustomFailureEvent] = Field(min_length=1, max_length=10)


class SimulationRuns:
    def __init__(self) -> None:
        self._runs: dict[str, SimulationEngine] = {}
        self._lock = RLock()

    def create(self, engine: SimulationEngine) -> dict[str, Any]:
        with self._lock:
            self._runs[engine.run_id] = engine
            return engine.get_state()

    def advance(self, run_id: str, ticks: int) -> dict[str, Any]:
        with self._lock:
            return self._get(run_id).advance(ticks)

    def install_failure_schedule(
        self,
        run_id: str,
        failure_scenario_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            engine = self._get(run_id)
            schedule = loader.load_failure_scenario(
                failure_scenario_id,
                engine.scenario.scenario_id,
            )
            return engine.install_failure_schedule(schedule)

    def install_custom_failure_schedule(
        self,
        run_id: str,
        custom_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self._lock:
            engine = self._get(run_id)
            schedule = loader.load_custom_failure_schedule(
                engine.scenario.scenario_id,
                custom_events,
            )
            return engine.install_custom_failure_schedule(schedule)

    def state(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            return self._get(run_id).get_state()

    def _get(self, run_id: str) -> SimulationEngine:
        engine = self._runs.get(run_id)
        if engine is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Simulation run not found.",
            )
        return engine


runs = SimulationRuns()


def _load_scenarios():
    try:
        return loader.load_all()
    except DatasetError:
        logger.exception("Scenario dataset validation failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scenario dataset is unavailable or invalid.",
        ) from None


@router.get("/scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    return [
        {
            "scenario_id": scenario.scenario_id,
            "name": scenario.name,
            "disaster_type": scenario.disaster_type,
            "width": scenario.width,
            "height": scenario.height,
            "task_count": len(scenario.tasks),
            "drone_count": len(scenario.drones),
            "candidate_detection_count": len(scenario.candidate_detections),
        }
        for scenario in _load_scenarios()
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_simulation(request: CreateSimulationRequest) -> dict[str, Any]:
    scenario = next(
        (
            item
            for item in _load_scenarios()
            if item.scenario_id == request.scenario_id
        ),
        None,
    )
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scenario not found.",
        )
    return runs.create(
        SimulationEngine(
            scenario,
            coordination_mode=request.mode,
            coverage_target_percentage=request.coverage_target_percentage,
            mission_duration_ticks=loader.mission_duration_ticks,
        )
    )


@router.post("/{run_id}/ticks")
def advance_simulation(
    run_id: str,
    request: AdvanceTicksRequest,
) -> dict[str, Any]:
    try:
        return runs.advance(run_id, request.ticks)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid tick count.",
        ) from None


@router.post("/{run_id}/failures")
async def install_failure_schedule(
    run_id: str,
    request: Request,
    payload: InstallFailureScheduleRequest,
) -> dict[str, Any]:
    if len(await request.body()) > MAX_CUSTOM_FAILURE_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Failure schedule payload exceeds {MAX_CUSTOM_FAILURE_BODY_BYTES} bytes.",
        )
    if len(payload.model_dump_json().encode("utf-8")) > MAX_CUSTOM_FAILURE_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Failure schedule payload exceeds {MAX_CUSTOM_FAILURE_BODY_BYTES} bytes.",
        )
    try:
        if payload.custom_plan is not None:
            return runs.install_custom_failure_schedule(
                run_id,
                [event.model_dump() for event in payload.custom_plan.events],
            )
        assert payload.failure_scenario_id is not None
        return runs.install_failure_schedule(run_id, payload.failure_scenario_id)
    except FailureScenarioNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Failure scenario not found.",
        ) from None
    except IncompatibleFailureScenario:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Failure scenario is not configured for this scenario.",
        ) from None
    except FailureScheduleConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    except InvalidCustomFailurePlan as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    except DatasetError:
        logger.exception("Failure scenario dataset validation failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failure scenario dataset is unavailable or invalid.",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None


@router.get("/{run_id}")
def get_simulation(run_id: str) -> dict[str, Any]:
    return runs.state(run_id)

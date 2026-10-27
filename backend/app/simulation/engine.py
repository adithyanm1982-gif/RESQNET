from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from itertools import combinations, permutations
from uuid import uuid4

from app.simulation.loader import (
    CustomFailureScheduleDefinition,
    FailureScenarioDefinition,
    ScenarioDefinition,
    TaskDefinition,
)

MAX_TICKS_PER_ADVANCE = 1000
NEIGHBOR_OFFSETS = ((1, 0), (0, 1), (-1, 0), (0, -1))


class CoordinationMode(str, Enum):
    CENTRALIZED = "centralized"
    DECENTRALIZED = "decentralized"
    HYBRID = "hybrid"


@dataclass
class DroneState:
    drone_id: str
    drone_type: str
    x: int
    y: int
    status: str
    task_id: str | None = None


@dataclass
class TaskState:
    definition: TaskDefinition
    status: str = "pending"
    assigned_to: list[str] = field(default_factory=list)
    work_positions: dict[str, tuple[int, int]] = field(default_factory=dict)
    claim_ticks: dict[str, int] = field(default_factory=dict)
    claim_groups: dict[str, str] = field(default_factory=dict)
    released_claims: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class TaskClaimProposal:
    task_id: str
    drone_id: str
    claim_tick: int


class FailureScheduleConflict(ValueError):
    pass


class SimulationEngine:
    def __init__(
        self,
        scenario: ScenarioDefinition,
        coordination_mode: CoordinationMode | str = CoordinationMode.CENTRALIZED,
    ) -> None:
        self.scenario = scenario
        try:
            self.coordination_mode = CoordinationMode(coordination_mode)
        except ValueError:
            allowed = ", ".join(mode.value for mode in CoordinationMode)
            raise ValueError(f"coordination_mode must be one of: {allowed}.") from None
        self.run_id = str(uuid4())
        self.tick = 0
        self.drones = {
            drone.drone_id: DroneState(
                drone_id=drone.drone_id,
                drone_type=drone.drone_type,
                x=drone.x,
                y=drone.y,
                status=drone.initial_status,
            )
            for drone in scenario.drones
        }
        self.tasks = {
            task.task_id: TaskState(definition=task)
            for task in scenario.tasks
        }
        self._movement_priority_offset = 0
        self._yield_goals: dict[str, tuple[int, int]] = {}
        self.failure_scenario_id: str | None = None
        self.failure_schedule_type: str | None = None
        self._failure_schedule_installed = False
        self._failure_tick_s: int | None = None
        self._failure_status_values: dict[str, str] = {}
        self._failure_events: list[dict[str, object]] = []
        self._failure_test_matrix_entry: dict[str, object] | None = None
        self._unresponsive_drone_ids: set[str] = set()
        self._processing_tick = 0
        self._operational_strategy = "centralized_allocation"
        self._controller_available = True
        self._controller_reachable = True
        self._partition_state: list[dict[str, object]] = []
        self._reconciliation_history: list[dict[str, object]] = []
        self._reconciled_event_ids: set[str] = set()
        self._reconciliation_this_tick = False
        initial_positions = [
            (drone.x, drone.y)
            for drone in self.drones.values()
        ]
        if len(initial_positions) != len(set(initial_positions)):
            raise ValueError("Drones must start on distinct grid cells.")
        self.visited_cells = {
            (drone.x, drone.y)
            for drone in self.drones.values()
            if self.is_traversable((drone.x, drone.y))
        }
        self.traversable_cell_count = (
            scenario.width * scenario.height
            - len(scenario.blocked_cells)
            - len(scenario.restricted_cells)
        )

    def is_traversable(self, position: tuple[int, int]) -> bool:
        x, y = position
        return (
            0 <= x < self.scenario.width
            and 0 <= y < self.scenario.height
            and (x, y) not in self.scenario.blocked_cells
            and (x, y) not in self.scenario.restricted_cells
        )

    def advance(self, ticks: int = 1) -> dict[str, object]:
        if (
            isinstance(ticks, bool)
            or not isinstance(ticks, int)
            or not 1 <= ticks <= MAX_TICKS_PER_ADVANCE
        ):
            raise ValueError(f"ticks must be between 1 and {MAX_TICKS_PER_ADVANCE}.")
        for _ in range(ticks):
            self._processing_tick = self.tick + 1
            self._reconciliation_this_tick = False
            self._update_failure_events(self._processing_tick)
            self._assign_tasks()
            self._move_drones()
            self.tick += 1
        self._processing_tick = self.tick
        return self.get_state()

    def install_failure_schedule(
        self,
        schedule: FailureScenarioDefinition,
    ) -> dict[str, object]:
        if self.tick != 0:
            raise FailureScheduleConflict(
                "A failure schedule must be installed before advancing the run."
            )
        if self._failure_schedule_installed:
            if (
                self.failure_schedule_type == "predefined"
                and self.failure_scenario_id == schedule.failure_scenario_id
            ):
                return self.get_state()
            raise FailureScheduleConflict("A failure schedule is already installed for this run.")
        return self._commit_failure_schedule(
            scenario_id=schedule.scenario_id,
            tick_s=schedule.tick_s,
            events=schedule.events,
            event_status_values=schedule.event_status_values,
            schedule_type="predefined",
            failure_scenario_id=schedule.failure_scenario_id,
            test_matrix_entry=schedule.test_matrix_entry,
        )

    def install_custom_failure_schedule(
        self,
        schedule: CustomFailureScheduleDefinition,
    ) -> dict[str, object]:
        if self.tick != 0:
            raise FailureScheduleConflict(
                "A failure schedule must be installed before advancing the run."
            )
        if self._failure_schedule_installed:
            raise FailureScheduleConflict("A failure schedule is already installed for this run.")
        return self._commit_failure_schedule(
            scenario_id=schedule.scenario_id,
            tick_s=schedule.tick_s,
            events=schedule.events,
            event_status_values=schedule.event_status_values,
            schedule_type="custom",
            failure_scenario_id=None,
            test_matrix_entry=None,
        )

    def _commit_failure_schedule(
        self,
        *,
        scenario_id: str,
        tick_s: int,
        events: tuple[dict[str, object], ...],
        event_status_values: tuple[str, ...],
        schedule_type: str,
        failure_scenario_id: str | None,
        test_matrix_entry: dict[str, object] | None,
    ) -> dict[str, object]:
        if scenario_id != self.scenario.scenario_id:
            raise ValueError("Failure schedule scenario does not match the run.")
        if not isinstance(tick_s, int) or isinstance(tick_s, bool) or tick_s <= 0:
            raise ValueError("Failure schedule tick duration is invalid.")
        if self.tick != 0:
            raise FailureScheduleConflict(
                "A failure schedule must be installed before advancing the run."
            )

        copied_events = deepcopy(list(events))
        if any(not isinstance(event, dict) for event in copied_events):
            raise ValueError("Failure schedule events have not been validated.")
        event_ids = [event.get("id") for event in copied_events]
        if (
            any(not isinstance(event_id, str) or not event_id for event_id in event_ids)
            or len(event_ids) != len(set(event_ids))
            or any(event.get("status") != "scheduled" for event in copied_events)
            or not {"scheduled", "active", "recovering", "resolved"}.issubset(
                set(event_status_values)
            )
        ):
            raise ValueError("Failure schedule events have not been validated.")

        # Commit the validated schedule only after all checks have passed.
        self.failure_scenario_id = failure_scenario_id
        self.failure_schedule_type = schedule_type
        self._failure_schedule_installed = True
        self._failure_tick_s = tick_s
        self._failure_status_values = {
            value: value
            for value in ("scheduled", "active", "recovering", "resolved")
        }
        self._failure_events = copied_events
        self._failure_test_matrix_entry = deepcopy(test_matrix_entry)
        self._update_failure_events()
        return self.get_state()

    def _update_failure_events(self, tick: int | None = None) -> None:
        if self._failure_tick_s is None:
            return
        event_tick = self.tick if tick is None else tick
        elapsed_s = event_tick * self._failure_tick_s
        scheduled_status = self._failure_status_values["scheduled"]
        active_status = self._failure_status_values["active"]
        recovering_status = self._failure_status_values["recovering"]
        resolved_status = self._failure_status_values["resolved"]
        unresponsive_drones: set[str] = set()

        for event in self._failure_events:
            start_s = int(event["start_s"])
            end_s = event["end_s"]
            if elapsed_s < start_s:
                event_status = scheduled_status
            elif end_s is None or elapsed_s < int(end_s):
                event_status = active_status
            else:
                reconnection = event.get("reconnection")
                recovery_s = (
                    int(reconnection["total_recovery_s"])
                    if isinstance(reconnection, dict)
                    else 0
                )
                event_status = (
                    recovering_status
                    if elapsed_s < int(end_s) + recovery_s
                    else resolved_status
                )

            event["status"] = event_status
            if (
                event.get("type") == "drone_unresponsive"
                and event_status in {active_status, recovering_status}
            ):
                drone_id = event.get("drone_id")
                if isinstance(drone_id, str) and drone_id in self.drones:
                    unresponsive_drones.add(drone_id)

        for drone_id in unresponsive_drones:
            drone = self.drones[drone_id]
            self._unresponsive_drone_ids.add(drone_id)
            drone.status = "disconnected"
            if self.coordination_mode is CoordinationMode.DECENTRALIZED:
                self._release_drone_claims(drone_id, "disconnected")
            elif self.coordination_mode is CoordinationMode.HYBRID:
                self._release_drone_claims(drone_id, "disconnected")

        for drone_id in list(self._unresponsive_drone_ids):
            if drone_id in unresponsive_drones:
                continue
            drone = self.drones[drone_id]
            if drone.status == "disconnected":
                drone.status = self._regular_drone_status(drone)
            self._unresponsive_drone_ids.remove(drone_id)

        if self.coordination_mode is CoordinationMode.HYBRID:
            self._update_hybrid_connectivity(event_tick)
            recovering_events = [
                event
                for event in self._failure_events
                if event["status"] == recovering_status
                and event.get("type") in {"controller_outage", "network_partition"}
                and event["id"] not in self._reconciled_event_ids
                and elapsed_s
                >= int(event["end_s"])
                + int(event.get("reconnection", {}).get("reconnect_delay_s", 0))
            ]
            for event in recovering_events:
                self._reconcile_hybrid_claims(event)

    def _update_hybrid_connectivity(self, event_tick: int) -> None:
        elapsed_s = event_tick * (self._failure_tick_s or 0)
        controller_fault = any(
            event.get("type") == "controller_outage"
            and event.get("status") == self._failure_status_values["active"]
            for event in self._failure_events
        )
        active_partitions = [
            event
            for event in self._failure_events
            if event.get("type") == "network_partition"
            and event.get("status") == self._failure_status_values["active"]
        ]
        recovering_faults = [
            event
            for event in self._failure_events
            if event.get("type") in {"controller_outage", "network_partition"}
            and event.get("status") == self._failure_status_values["recovering"]
        ]
        self._controller_available = not controller_fault
        self._partition_state = [
            {
                "event_id": event["id"],
                "groups": deepcopy(event["groups"]),
            }
            for event in active_partitions
        ]
        if controller_fault:
            self._controller_reachable = False
            self._operational_strategy = "decentralized_fallback"
        elif active_partitions:
            self._controller_reachable = any(
                group["has_controller_link"]
                for event in active_partitions
                for group in event["groups"]
            )
            self._operational_strategy = "decentralized_fallback"
        elif recovering_faults:
            before_reconnect = any(
                elapsed_s
                < int(event["end_s"])
                + int(event.get("reconnection", {}).get("reconnect_delay_s", 0))
                for event in recovering_faults
            )
            controller_reconnect_pending = any(
                event.get("type") == "controller_outage"
                and elapsed_s
                < int(event["end_s"])
                + int(event.get("reconnection", {}).get("reconnect_delay_s", 0))
                for event in recovering_faults
            )
            self._controller_reachable = not controller_reconnect_pending
            self._operational_strategy = (
                "decentralized_fallback"
                if before_reconnect
                else "reconciliation"
            )
        else:
            self._controller_reachable = True
            self._operational_strategy = "centralized_allocation"
        if self._reconciliation_this_tick:
            self._operational_strategy = "reconciliation"

    def _reconcile_hybrid_claims(self, event: dict[str, object]) -> None:
        event_id = str(event["id"])
        if event_id in self._reconciled_event_ids:
            return
        self._reconciled_event_ids.add(event_id)
        self._reconciliation_this_tick = True
        self._release_ineligible_claims()

        for task in sorted(self.tasks.values(), key=self._task_order):
            if task.status == "completed":
                self._reconciliation_history.append(
                    {
                        "event_id": event_id,
                        "tick": self._processing_tick,
                        "task_id": task.definition.task_id,
                        "action": "completed_preserved",
                        "drone_ids": sorted(task.assigned_to),
                    }
                )
                continue
            claims = [
                TaskClaimProposal(
                    task_id=task.definition.task_id,
                    drone_id=drone_id,
                    claim_tick=task.claim_ticks.get(drone_id, self._processing_tick),
                )
                for drone_id in task.assigned_to
            ]
            winners, losers = self._resolve_claim_conflicts(task, claims)
            winner_ids = {claim.drone_id for claim in winners}
            for claim in losers:
                if claim.drone_id in task.assigned_to:
                    self._release_claim(task, claim.drone_id, "reconciliation_lost")
                    self._reconciliation_history.append(
                        {
                            "event_id": event_id,
                            "tick": self._processing_tick,
                            "task_id": task.definition.task_id,
                            "action": "claim_released",
                            "drone_id": claim.drone_id,
                            "claim_tick": claim.claim_tick,
                            "reason": "reconciliation_lost",
                        }
                    )
            reserved: set[tuple[int, int]] = {
                position
                for other_task in self.tasks.values()
                if other_task is not task
                and other_task.status in {"assigned", "in_progress", "blocked"}
                for position in other_task.work_positions.values()
            }
            for claim in winners:
                if claim.drone_id not in task.assigned_to:
                    continue
                position = task.work_positions.get(claim.drone_id)
                if position is None or position in reserved:
                    position = self._select_claim_work_position(
                        task,
                        self.drones[claim.drone_id],
                        reserved,
                    )
                    if position is None:
                        self._release_claim(task, claim.drone_id, "reconciliation_no_position")
                        winner_ids.discard(claim.drone_id)
                        self._reconciliation_history.append(
                            {
                                "event_id": event_id,
                                "tick": self._processing_tick,
                                "task_id": task.definition.task_id,
                                "action": "claim_released",
                                "drone_id": claim.drone_id,
                                "claim_tick": claim.claim_tick,
                                "reason": "reconciliation_no_position",
                            }
                        )
                        continue
                    task.work_positions[claim.drone_id] = position
                reserved.add(position)
                self._reconciliation_history.append(
                    {
                        "event_id": event_id,
                        "tick": self._processing_tick,
                        "task_id": task.definition.task_id,
                        "action": "claim_preserved",
                        "drone_id": claim.drone_id,
                        "claim_tick": claim.claim_tick,
                    }
                )
            task.assigned_to = [
                drone_id for drone_id in task.assigned_to if drone_id in winner_ids
            ]
            if task.assigned_to:
                task.status = "in_progress"
            else:
                task.status = "pending"

        self._operational_strategy = "reconciliation"

    def _regular_drone_status(self, drone: DroneState) -> str:
        if drone.task_id is None:
            return "idle"
        task = self.tasks[drone.task_id]
        return (
            "searching"
            if (drone.x, drone.y) == task.work_positions[drone.drone_id]
            else "moving"
        )

    def get_state(self) -> dict[str, object]:
        task_states = []
        for task in self.tasks.values():
            task_state = {
                "task_id": task.definition.task_id,
                "type": task.definition.task_type,
                "x": task.definition.x,
                "y": task.definition.y,
                "priority": task.definition.priority,
                "required_drones": task.definition.required_drones,
                "status": task.status,
                "assigned_to": sorted(task.assigned_to),
            }
            if self.coordination_mode in {
                CoordinationMode.DECENTRALIZED,
                CoordinationMode.HYBRID,
            }:
                task_state.update(
                    {
                        "claim_status": (
                            "completed"
                            if task.status == "completed"
                            else "claimed"
                            if task.assigned_to
                            else "unclaimed"
                        ),
                        "claims": [
                            {
                                "drone_id": drone_id,
                                "claim_tick": task.claim_ticks.get(drone_id),
                                **(
                                    {"group_id": task.claim_groups[drone_id]}
                                    if drone_id in task.claim_groups
                                    else {}
                                ),
                            }
                            for drone_id in sorted(task.assigned_to)
                        ],
                        "released_claims": deepcopy(task.released_claims),
                    }
                )
            task_states.append(task_state)
        completed_task_ids = [
            task["task_id"] for task in task_states if task["status"] == "completed"
        ]
        assigned_tasks = [
            task for task in task_states if task["assigned_to"]
        ]
        coverage_percent = (
            len(self.visited_cells) / self.traversable_cell_count * 100
            if self.traversable_cell_count
            else 0.0
        )
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario.scenario_id,
            "coordination_mode": self.coordination_mode.value,
            "operational_strategy": self._operational_strategy,
            "controller_available": self._controller_available,
            "controller_reachable": self._controller_reachable,
            "partition_state": deepcopy(self._partition_state),
            "reconciliation_history": deepcopy(self._reconciliation_history),
            "tick": self.tick,
            "grid": {
                "width": self.scenario.width,
                "height": self.scenario.height,
                "cells": list(self.scenario.grid),
            },
            "drones": [
                {
                    "drone_id": drone.drone_id,
                    "type": drone.drone_type,
                    "x": drone.x,
                    "y": drone.y,
                    "status": drone.status,
                    "task_id": drone.task_id,
                }
                for drone in sorted(
                    self.drones.values(),
                    key=lambda item: item.drone_id,
                )
            ],
            "tasks": task_states,
            "assigned_tasks": assigned_tasks,
            "completed_tasks": completed_task_ids,
            "coverage": {
                "visited_cells": len(self.visited_cells),
                "traversable_cells": self.traversable_cell_count,
                "percentage": round(coverage_percent, 2),
            },
            "candidate_detections": [
                {
                    "id": candidate.candidate_id,
                    "x": candidate.x,
                    "y": candidate.y,
                    "verification_status": candidate.verification_status,
                }
                for candidate in self.scenario.candidate_detections
            ],
            "failure_scenario_id": self.failure_scenario_id,
            "failure_schedule_type": self.failure_schedule_type,
            "failure_events": deepcopy(self._failure_events),
            "failure_test_matrix_entry": deepcopy(self._failure_test_matrix_entry),
        }

    def _assign_tasks(self) -> None:
        if self.coordination_mode is CoordinationMode.DECENTRALIZED:
            self._operational_strategy = "decentralized_fallback"
            self._assign_tasks_decentrally()
        elif self.coordination_mode is CoordinationMode.HYBRID:
            self._assign_tasks_hybrid()
        else:
            self._operational_strategy = "centralized_allocation"
            self._assign_tasks_centrally()

    def _assign_tasks_hybrid(self) -> None:
        elapsed_s = self._processing_tick * (self._failure_tick_s or 0)
        recovering_events = [
            event
            for event in self._failure_events
            if event.get("type") in {"controller_outage", "network_partition"}
            and event.get("status") == self._failure_status_values.get("recovering")
        ]
        partition = self._partition_state[-1]["groups"] if self._partition_state else []
        if not partition:
            reconnecting_partitions = [
                event
                for event in recovering_events
                if event.get("type") == "network_partition"
                and elapsed_s
                < int(event["end_s"])
                + int(event.get("reconnection", {}).get("reconnect_delay_s", 0))
            ]
            if reconnecting_partitions:
                partition = reconnecting_partitions[-1]["groups"]
        if partition:
            drone_group = {
                drone_id: (
                    "partition:controller"
                    if group["has_controller_link"]
                    else f"partition:{group['group_id']}"
                )
                for group in partition
                for drone_id in group["drone_ids"]
            }
            for task in self.tasks.values():
                for drone_id in task.assigned_to:
                    if drone_id in drone_group:
                        task.claim_groups[drone_id] = drone_group[drone_id]
        if self._reconciliation_this_tick:
            self._assign_tasks_decentrally(claim_scope="reconciliation")
            return
        if recovering_events:
            if partition:
                self._assign_partition_groups(partition, self._controller_available)
            else:
                self._assign_tasks_decentrally(claim_scope="reconnection")
            return
        if not self._controller_available:
            if partition:
                self._assign_partition_groups(partition, False)
            else:
                self._assign_tasks_decentrally(claim_scope="controller_outage")
            return
        if not partition:
            self._assign_tasks_centrally(claim_scope="controller")
            return

        self._assign_partition_groups(partition, True)

    def _assign_partition_groups(
        self,
        partition: list[dict[str, object]],
        controller_available: bool,
    ) -> None:
        controller_drones: set[str] = set()
        local_groups: list[tuple[str, set[str]]] = []
        for group in partition:
            drone_ids = set(group["drone_ids"])
            if controller_available and group["has_controller_link"]:
                controller_drones.update(drone_ids)
            else:
                local_groups.append((str(group["group_id"]), drone_ids))
        if controller_drones:
            self._assign_tasks_centrally(
                drone_ids=controller_drones,
                claim_scope="partition:controller",
                partition_local=True,
            )
        for group_id, drone_ids in sorted(local_groups):
            self._assign_tasks_decentrally(
                drone_ids=drone_ids,
                claim_scope=f"partition:{group_id}",
                partition_local=True,
            )

    def _assign_tasks_centrally(
        self,
        drone_ids: set[str] | None = None,
        claim_scope: str | None = None,
        partition_local: bool = False,
    ) -> None:
        available = [
            drone
            for drone in self.drones.values()
            if drone.task_id is None
            and drone.status != "disconnected"
            and (drone_ids is None or drone.drone_id in drone_ids)
        ]
        reserved_positions = self._reserved_work_positions(claim_scope, partition_local)
        pending_tasks = sorted(
            (
                task
                for task in self.tasks.values()
                if task.status != "completed"
                and self._claim_count(task, claim_scope, partition_local)
                < task.definition.required_drones
            ),
            key=lambda task: (
                -task.definition.priority,
                task.definition.deadline_s,
                task.definition.task_id,
            ),
        )
        for task in pending_tasks:
            remaining = task.definition.required_drones - self._claim_count(
                task,
                claim_scope,
                partition_local,
            )
            assignment = self._select_assignment(
                task,
                available,
                reserved_positions,
                required_drones=remaining,
            )
            if assignment is None:
                task.status = (
                    "pending"
                    if self._has_static_assignment(task)
                    else "blocked"
                )
                continue
            for drone, work_position in assignment:
                drone.task_id = task.definition.task_id
                drone.status = "moving"
                task.assigned_to.append(drone.drone_id)
                task.work_positions[drone.drone_id] = work_position
                if claim_scope is not None:
                    task.claim_ticks[drone.drone_id] = self._processing_tick
                    task.claim_groups[drone.drone_id] = claim_scope
                available.remove(drone)
                reserved_positions.add(work_position)
            task.status = "assigned"

    def _assign_tasks_decentrally(
        self,
        drone_ids: set[str] | None = None,
        claim_scope: str | None = None,
        partition_local: bool = False,
    ) -> None:
        if not partition_local:
            self._release_ineligible_claims()

        # Repair any over-capacity or duplicate claims before collecting new
        # independent proposals. Valid earlier claims remain in place.
        for task in sorted(self.tasks.values(), key=self._task_order):
            if task.status == "completed":
                continue
            existing = [
                TaskClaimProposal(
                    task_id=task.definition.task_id,
                    drone_id=drone_id,
                    claim_tick=task.claim_ticks.get(drone_id, self.tick),
                )
                for drone_id in task.assigned_to
                if self._claim_in_scope(task, drone_id, claim_scope, partition_local)
            ]
            winners, losers = self._resolve_claim_conflicts(task, existing)
            winning_owners = {claim.drone_id for claim in winners}
            for claim in losers:
                if claim.drone_id in task.assigned_to and claim.drone_id not in winning_owners:
                    self._release_claim(task, claim.drone_id, "claim_conflict")

        eligible = {
            drone.drone_id
            for drone in self.drones.values()
            if drone.task_id is None
            and drone.status != "disconnected"
            and (drone_ids is None or drone.drone_id in drone_ids)
        }
        excluded_tasks: dict[str, set[str]] = {drone_id: set() for drone_id in eligible}
        claim_tick = self.tick + 1

        while eligible:
            proposals = [
                proposal
                for drone_id in sorted(eligible)
                if (
                    proposal := self._select_decentralized_claim(
                        self.drones[drone_id],
                        excluded_tasks[drone_id],
                        claim_tick,
                        claim_scope,
                        partition_local,
                    )
                ) is not None
            ]
            if not proposals:
                break

            proposals_by_task: dict[str, list[TaskClaimProposal]] = {}
            for proposal in proposals:
                proposals_by_task.setdefault(proposal.task_id, []).append(proposal)

            newly_claimed: set[str] = set()
            for task_id in sorted(
                proposals_by_task,
                key=lambda item: self._task_order(self.tasks[item]),
            ):
                task = self.tasks[task_id]
                existing = [
                    TaskClaimProposal(
                        task_id=task_id,
                        drone_id=drone_id,
                        claim_tick=task.claim_ticks.get(drone_id, self.tick),
                    )
                    for drone_id in task.assigned_to
                    if self._claim_in_scope(
                        task,
                        drone_id,
                        claim_scope,
                        partition_local,
                    )
                ]
                winners, losers = self._resolve_claim_conflicts(
                    task,
                    [*existing, *proposals_by_task[task_id]],
                )
                current_owners = {
                    claim.drone_id for claim in existing
                }
                winning_owners = {claim.drone_id for claim in winners}

                for claim in losers:
                    if claim.drone_id in current_owners and claim.drone_id not in winning_owners:
                        self._release_claim(task, claim.drone_id, "claim_conflict")
                    elif claim.drone_id in eligible:
                        excluded_tasks[claim.drone_id].add(task_id)
                        self._record_released_proposal(
                            task,
                            claim,
                            "claim_conflict",
                            claim_scope,
                        )

                reserved_positions = self._reserved_work_positions(
                    claim_scope,
                    partition_local,
                )
                for claim in winners:
                    if claim.drone_id in current_owners:
                        continue
                    drone = self.drones[claim.drone_id]
                    work_position = self._select_claim_work_position(
                        task,
                        drone,
                        reserved_positions,
                        claim_scope,
                        partition_local,
                    )
                    if work_position is None:
                        excluded_tasks[claim.drone_id].add(task_id)
                        self._record_released_proposal(
                            task,
                            claim,
                            "no_feasible_work_position",
                            claim_scope,
                        )
                        continue

                    task.assigned_to.append(claim.drone_id)
                    task.claim_ticks[claim.drone_id] = claim.claim_tick
                    if claim_scope is not None:
                        task.claim_groups[claim.drone_id] = claim_scope
                    task.work_positions[claim.drone_id] = work_position
                    task.status = "assigned"
                    drone.task_id = task_id
                    drone.status = "moving"
                    reserved_positions.add(work_position)
                    eligible.remove(claim.drone_id)
                    newly_claimed.add(claim.drone_id)

                for claim in proposals_by_task[task_id]:
                    if claim.drone_id in eligible and claim.drone_id not in winning_owners:
                        excluded_tasks[claim.drone_id].add(task_id)

            if not newly_claimed and all(
                self._select_decentralized_claim(
                    self.drones[drone_id],
                    excluded_tasks[drone_id],
                    claim_tick,
                    claim_scope,
                    partition_local,
                ) is None
                for drone_id in eligible
            ):
                break

    @staticmethod
    def _task_order(task: TaskState) -> tuple[int, int, str]:
        return (
            -task.definition.priority,
            task.definition.deadline_s,
            task.definition.task_id,
        )

    def _select_decentralized_claim(
        self,
        drone: DroneState,
        excluded_tasks: set[str],
        claim_tick: int,
        claim_scope: str | None = None,
        partition_local: bool = False,
    ) -> TaskClaimProposal | None:
        if drone.status == "disconnected" or drone.task_id is not None:
            return None

        for task in sorted(self.tasks.values(), key=self._task_order):
            if (
                task.status == "completed"
                or task.definition.task_id in excluded_tasks
                or self._claim_count(task, claim_scope, partition_local)
                >= task.definition.required_drones
            ):
                continue
            if self._select_claim_work_position(
                task,
                drone,
                self._reserved_work_positions(claim_scope, partition_local),
                claim_scope,
                partition_local,
            ) is None:
                continue
            return TaskClaimProposal(
                task_id=task.definition.task_id,
                drone_id=drone.drone_id,
                claim_tick=claim_tick,
            )
        return None

    @staticmethod
    def _resolve_claim_conflicts(
        task: TaskState,
        proposals: list[TaskClaimProposal],
    ) -> tuple[list[TaskClaimProposal], list[TaskClaimProposal]]:
        if task.status == "completed":
            return [], list(proposals)

        earliest_by_drone: dict[str, TaskClaimProposal] = {}
        duplicate_proposals: list[TaskClaimProposal] = []
        for claim in sorted(proposals, key=lambda item: (item.claim_tick, item.drone_id)):
            current = earliest_by_drone.get(claim.drone_id)
            if current is None:
                earliest_by_drone[claim.drone_id] = claim
            else:
                duplicate_proposals.append(claim)

        ordered = sorted(
            earliest_by_drone.values(),
            key=lambda item: (item.claim_tick, item.drone_id),
        )
        winners = ordered[: task.definition.required_drones]
        winner_ids = {claim.drone_id for claim in winners}
        losers = [claim for claim in ordered if claim.drone_id not in winner_ids]
        losers.extend(duplicate_proposals)
        return winners, losers

    def _select_claim_work_position(
        self,
        task: TaskState,
        drone: DroneState,
        reserved_positions: set[tuple[int, int]],
        claim_scope: str | None = None,
        partition_local: bool = False,
    ) -> tuple[int, int] | None:
        available = [
            position
            for position in self._task_work_positions(task)
            if position not in reserved_positions
        ]
        reachable = [
            (distance, position[1], position[0], position)
            for position in available
            if (distance := self._distance((drone.x, drone.y), position)) is not None
        ]
        return min(reachable)[-1] if reachable else None

    def _claim_in_scope(
        self,
        task: TaskState,
        drone_id: str,
        claim_scope: str | None,
        partition_local: bool,
    ) -> bool:
        if not partition_local or claim_scope is None:
            return True
        return task.claim_groups.get(drone_id) == claim_scope

    def _claim_count(
        self,
        task: TaskState,
        claim_scope: str | None,
        partition_local: bool,
    ) -> int:
        if not partition_local or claim_scope is None:
            return len(set(task.assigned_to))
        return len(
            {
                drone_id
                for drone_id in task.assigned_to
                if self._claim_in_scope(task, drone_id, claim_scope, partition_local)
            }
        )

    def _reserved_work_positions(
        self,
        claim_scope: str | None,
        partition_local: bool,
    ) -> set[tuple[int, int]]:
        return {
            position
            for task in self.tasks.values()
            if task.status in {"assigned", "in_progress", "blocked"}
            for drone_id, position in task.work_positions.items()
            if self._claim_in_scope(task, drone_id, claim_scope, partition_local)
        }

    def _release_ineligible_claims(self) -> None:
        for task in self.tasks.values():
            if task.status == "completed":
                continue
            task.assigned_to = list(dict.fromkeys(task.assigned_to))
            for drone_id in list(task.assigned_to):
                drone = self.drones.get(drone_id)
                if drone is None:
                    self._release_claim(task, drone_id, "owner_missing")
                elif drone.status == "disconnected":
                    self._release_claim(task, drone_id, "disconnected")
                elif drone.task_id != task.definition.task_id:
                    self._release_claim(task, drone_id, "owner_ineligible")

    def _release_drone_claims(self, drone_id: str, reason: str) -> None:
        for task in self.tasks.values():
            if task.status != "completed" and (
                drone_id in task.assigned_to or drone_id in task.claim_ticks
            ):
                self._release_claim(task, drone_id, reason)

    def _release_claim(self, task: TaskState, drone_id: str, reason: str) -> None:
        if task.status == "completed":
            return
        claim_tick = task.claim_ticks.pop(drone_id, None)
        claim_group = task.claim_groups.pop(drone_id, None)
        was_assigned = drone_id in task.assigned_to
        task.assigned_to = [owner for owner in task.assigned_to if owner != drone_id]
        task.work_positions.pop(drone_id, None)
        if not was_assigned and claim_tick is None:
            return

        task.released_claims.append(
            {
                "drone_id": drone_id,
                "claim_tick": claim_tick,
                "released_tick": self._processing_tick,
                "reason": reason,
                **({"group_id": claim_group} if claim_group is not None else {}),
            }
        )
        drone = self.drones.get(drone_id)
        if drone is not None and drone.task_id == task.definition.task_id:
            drone.task_id = None
            if drone.status != "disconnected":
                drone.status = "idle"
        task.status = "assigned" if task.assigned_to else "pending"

    def _record_released_proposal(
        self,
        task: TaskState,
        claim: TaskClaimProposal,
        reason: str,
        claim_scope: str | None = None,
    ) -> None:
        task.released_claims.append(
            {
                "drone_id": claim.drone_id,
                "claim_tick": claim.claim_tick,
                "released_tick": self._processing_tick,
                "reason": reason,
                **({"group_id": claim_scope} if claim_scope is not None else {}),
            }
        )

    def _select_assignment(
        self,
        task: TaskState,
        available: list[DroneState],
        reserved_positions: set[tuple[int, int]],
        required_drones: int | None = None,
    ) -> list[tuple[DroneState, tuple[int, int]]] | None:
        required = (
            task.definition.required_drones
            if required_drones is None
            else required_drones
        )
        work_positions = self._task_work_positions(task)
        if len(available) < required or len(work_positions) < required:
            return None

        best_assignment = None
        best_score = None
        for selected_drones in combinations(
            sorted(available, key=lambda drone: drone.drone_id),
            required,
        ):
            for selected_positions in permutations(work_positions, required):
                if any(position in reserved_positions for position in selected_positions):
                    continue
                path_lengths = [
                    self._distance(
                        (drone.x, drone.y),
                        work_position,
                    )
                    for drone, work_position in zip(
                        selected_drones,
                        selected_positions,
                    )
                ]
                if any(distance is None for distance in path_lengths):
                    continue
                assignment = list(zip(selected_drones, selected_positions))
                score = (
                    sum(distance for distance in path_lengths if distance is not None),
                    tuple(
                        (drone.drone_id, position[1], position[0])
                        for drone, position in assignment
                    ),
                )
                if best_score is None or score < best_score:
                    best_assignment = assignment
                    best_score = score
        return best_assignment

    def _has_static_assignment(self, task: TaskState) -> bool:
        required = task.definition.required_drones
        work_positions = self._task_work_positions(task)
        if len(work_positions) < required:
            return False
        for selected_drones in combinations(
            sorted(self.drones.values(), key=lambda drone: drone.drone_id),
            required,
        ):
            for selected_positions in permutations(work_positions, required):
                if all(
                    self._distance((drone.x, drone.y), position) is not None
                    for drone, position in zip(selected_drones, selected_positions)
                ):
                    return True
        return False

    def _task_work_positions(self, task: TaskState) -> list[tuple[int, int]]:
        target = (task.definition.x, task.definition.y)
        if task.definition.required_drones == 1:
            return [target]
        positions = [target]
        positions.extend(
            (target[0] + dx, target[1] + dy)
            for dx, dy in NEIGHBOR_OFFSETS
        )
        return [
            position
            for position in positions
            if self.is_traversable(position)
        ]

    def _move_drones(self) -> None:
        self._plan_idle_yields()
        drones = sorted(
            self.drones.values(),
            key=lambda item: item.drone_id,
        )
        goals = {
            drone.drone_id: self.tasks[drone.task_id].work_positions[drone.drone_id]
            for drone in drones
            if drone.task_id is not None
        }
        goals.update(self._yield_goals)
        occupied_positions = {
            (drone.x, drone.y)
            for drone in drones
        }
        yielding_positions = {
            (self.drones[drone_id].x, self.drones[drone_id].y)
            for drone_id, goal in self._yield_goals.items()
            if (self.drones[drone_id].x, self.drones[drone_id].y) != goal
        }
        distances = {
            drone_id: self._distance_map(
                goal,
                occupied_positions
                - {
                    (self.drones[drone_id].x, self.drones[drone_id].y),
                    goal,
                },
                yielding_positions if drone_id not in self._yield_goals else None,
            )
            for drone_id, goal in goals.items()
        }
        options = {
            drone.drone_id: self._next_positions(
                drone,
                distances.get(drone.drone_id),
            )
            for drone in drones
        }
        next_positions = self._resolve_moves(drones, options)

        for drone in drones:
            position = next_positions[drone.drone_id]
            drone.x, drone.y = position
            self.visited_cells.add(position)
            if (
                drone.drone_id in self._yield_goals
                and position == self._yield_goals[drone.drone_id]
            ):
                del self._yield_goals[drone.drone_id]
            if drone.task_id is None:
                continue
            if drone.status == "disconnected":
                continue
            task = self.tasks[drone.task_id]
            if position == goals[drone.drone_id]:
                drone.status = "searching"
            else:
                drone.status = "moving"
            task.status = "in_progress"

        for task in self.tasks.values():
            if task.status not in {"assigned", "in_progress"}:
                continue
            if self.coordination_mode is CoordinationMode.HYBRID and self._partition_state:
                owners_by_group: dict[str, list[str]] = {}
                for drone_id in task.assigned_to:
                    group_id = task.claim_groups.get(drone_id, "controller")
                    owners_by_group.setdefault(group_id, []).append(drone_id)
                completing_team = next(
                    (
                        sorted(owners)[: task.definition.required_drones]
                        for _, owners in sorted(owners_by_group.items())
                        if len(owners) >= task.definition.required_drones
                        and all(
                            (self.drones[drone_id].x, self.drones[drone_id].y)
                            == task.work_positions[drone_id]
                            for drone_id in sorted(owners)[: task.definition.required_drones]
                        )
                    ),
                    None,
                )
            else:
                has_full_team = (
                    len(task.assigned_to) == task.definition.required_drones
                )
                completing_team = (
                    task.assigned_to
                    if has_full_team
                    and all(
                        (self.drones[drone_id].x, self.drones[drone_id].y)
                        == task.work_positions[drone_id]
                        for drone_id in task.assigned_to
                    )
                    else None
                )
            if completing_team:
                task.status = "completed"
                for drone_id in task.assigned_to:
                    drone = self.drones[drone_id]
                    drone.task_id = None
                    drone.status = "idle"
                continue
            occupied = {
                (drone.x, drone.y)
                for drone in drones
            }
            if any(
                not self._route_is_open(
                    self.drones[drone_id],
                    task.work_positions[drone_id],
                    occupied,
                )
                for drone_id in task.assigned_to
            ):
                task.status = "blocked"
            else:
                task.status = "in_progress"

        self._movement_priority_offset = (self._movement_priority_offset + 1) % len(drones)

    def _plan_idle_yields(self) -> None:
        for drone_id in list(self._yield_goals):
            drone = self.drones[drone_id]
            if (
                drone.task_id is not None
                or (drone.x, drone.y) == self._yield_goals[drone_id]
            ):
                del self._yield_goals[drone_id]

        occupied = {
            (drone.x, drone.y)
            for drone in self.drones.values()
        }
        reserved = {
            position
            for task in self.tasks.values()
            if task.status in {"assigned", "in_progress", "blocked"}
            for position in task.work_positions.values()
        }
        reserved.update(self._yield_goals.values())
        active_drones = sorted(
            (
                drone
                for drone in self.drones.values()
                if drone.task_id is not None
            ),
            key=lambda drone: drone.drone_id,
        )
        yielding_drones = set(self._yield_goals)

        for active in active_drones:
            goal = self.tasks[active.task_id].work_positions[active.drone_id]
            current = (active.x, active.y)
            if self._route_is_open(active, goal, occupied):
                continue
            path = self._shortest_path(current, goal)
            if path is None:
                continue
            route_cells = set(path)
            blockers = sorted(
                (
                    drone
                    for drone in self.drones.values()
                    if drone.task_id is None
                    and drone.drone_id not in yielding_drones
                    and (drone.x, drone.y) in route_cells
                ),
                key=lambda drone: (path.index((drone.x, drone.y)), drone.drone_id),
            )
            for blocker in blockers:
                blocker_position = (blocker.x, blocker.y)
                parking_positions = [
                    (blocker.x + dx, blocker.y + dy)
                    for dx, dy in NEIGHBOR_OFFSETS
                    if self.is_traversable((blocker.x + dx, blocker.y + dy))
                    and (blocker.x + dx, blocker.y + dy) not in occupied
                    and (blocker.x + dx, blocker.y + dy) not in reserved
                    and (blocker.x + dx, blocker.y + dy) not in route_cells
                ]
                for parking_position in parking_positions:
                    yield_distance = self._distance_map(
                        parking_position,
                        occupied - {blocker_position, parking_position},
                    )
                    if blocker_position not in yield_distance:
                        continue
                    self._yield_goals[blocker.drone_id] = parking_position
                    reserved.add(parking_position)
                    yielding_drones.add(blocker.drone_id)
                    break
                if blocker.drone_id in yielding_drones:
                    break

    def _route_is_open(
        self,
        drone: DroneState,
        goal: tuple[int, int],
        occupied: set[tuple[int, int]],
    ) -> bool:
        current = (drone.x, drone.y)
        if goal in occupied and goal != current:
            occupant = next(
                item
                for item in self.drones.values()
                if (item.x, item.y) == goal
            )
            if occupant.task_id is None and occupant.drone_id not in self._yield_goals:
                return False
        blocked_positions = occupied - {current, goal}
        distances = self._distance_map(goal, blocked_positions)
        return current in distances

    def _next_positions(
        self,
        drone: DroneState,
        distances: dict[tuple[int, int], int] | None,
    ) -> tuple[tuple[int, int], ...]:
        current = (drone.x, drone.y)
        if distances is None:
            return (current,)
        current_distance = distances.get(current)
        if current_distance is None or current_distance == 0:
            return (current,)
        return (
            current,
            *(
                neighbor
                for dx, dy in NEIGHBOR_OFFSETS
                if (neighbor := (drone.x + dx, drone.y + dy)) in distances
                and distances[neighbor] == current_distance - 1
            ),
        )

    def _resolve_moves(
        self,
        drones: list[DroneState],
        options: dict[str, tuple[tuple[int, int], ...]],
    ) -> dict[str, tuple[int, int]]:
        positions = {
            drone.drone_id: (drone.x, drone.y)
            for drone in drones
        }
        occupants = {
            position: drone_id
            for drone_id, position in positions.items()
        }
        rotation = self._movement_priority_offset
        ordered_drones = drones[rotation:] + drones[:rotation]
        current: dict[str, tuple[int, int]] = {}
        best_positions = positions
        best_score: tuple[int, tuple[bool, ...]] | None = None

        def search(index: int, moved_count: int) -> None:
            nonlocal best_positions, best_score
            if best_score is not None and moved_count + len(ordered_drones) - index < best_score[0]:
                return
            if index == len(ordered_drones):
                if not self._is_conflict_free(positions, current, occupants):
                    return
                score = (
                    moved_count,
                    tuple(
                        current[drone.drone_id] != positions[drone.drone_id]
                        for drone in ordered_drones
                    ),
                )
                if best_score is None or score > best_score:
                    best_score = score
                    best_positions = current.copy()
                return

            drone = ordered_drones[index]
            original = positions[drone.drone_id]
            for position in options[drone.drone_id]:
                current[drone.drone_id] = position
                search(index + 1, moved_count + (position != original))
            current.pop(drone.drone_id)

        search(0, 0)
        return best_positions

    @staticmethod
    def _is_conflict_free(
        positions: dict[str, tuple[int, int]],
        next_positions: dict[str, tuple[int, int]],
        occupants: dict[tuple[int, int], str],
    ) -> bool:
        if len(set(next_positions.values())) != len(next_positions):
            return False

        dependencies = {}
        for drone_id, destination in next_positions.items():
            if destination == positions[drone_id]:
                continue
            occupant = occupants.get(destination)
            if occupant is not None:
                dependencies[drone_id] = occupant

        complete: set[str] = set()
        for drone_id in dependencies:
            path: set[str] = set()
            current = drone_id
            while current in dependencies and current not in complete:
                if current in path:
                    return False
                path.add(current)
                current = dependencies[current]
            complete.update(path)
        return True

    def _distance(
        self,
        start: tuple[int, int],
        goal: tuple[int, int],
    ) -> int | None:
        return self._distance_map(goal).get(start)

    def _distance_map(
        self,
        goal: tuple[int, int],
        blocked_positions: set[tuple[int, int]] | None = None,
        temporarily_vacated: set[tuple[int, int]] | None = None,
    ) -> dict[tuple[int, int], int]:
        if not self.is_traversable(goal):
            return {}
        blocked_positions = blocked_positions or set()
        blocked_positions -= temporarily_vacated or set()
        distances = {goal: 0}
        queue = deque([goal])
        while queue:
            x, y = queue.popleft()
            for dx, dy in NEIGHBOR_OFFSETS:
                neighbor = (x + dx, y + dy)
                if (
                    neighbor in distances
                    or neighbor in blocked_positions
                    or not self.is_traversable(neighbor)
                ):
                    continue
                distances[neighbor] = distances[(x, y)] + 1
                queue.append(neighbor)
        return distances

    def _shortest_path(
        self,
        start: tuple[int, int],
        goal: tuple[int, int],
    ) -> list[tuple[int, int]] | None:
        distances = self._distance_map(goal)
        if start not in distances:
            return None
        path = []
        current = start
        while current != goal:
            next_distance = distances[current] - 1
            current = next(
                neighbor
                for dx, dy in NEIGHBOR_OFFSETS
                if (neighbor := (current[0] + dx, current[1] + dy))
                in distances
                and distances[neighbor] == next_distance
            )
            path.append(current)
        return path

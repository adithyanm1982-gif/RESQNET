from collections import deque
from dataclasses import dataclass, field
from itertools import combinations, permutations
from uuid import uuid4

from app.simulation.loader import ScenarioDefinition, TaskDefinition

MAX_TICKS_PER_ADVANCE = 1000
NEIGHBOR_OFFSETS = ((1, 0), (0, 1), (-1, 0), (0, -1))


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


class SimulationEngine:
    def __init__(self, scenario: ScenarioDefinition) -> None:
        self.scenario = scenario
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
            self._assign_tasks()
            self._move_drones()
            self.tick += 1
        return self.get_state()

    def get_state(self) -> dict[str, object]:
        task_states = [
            {
                "task_id": task.definition.task_id,
                "type": task.definition.task_type,
                "x": task.definition.x,
                "y": task.definition.y,
                "priority": task.definition.priority,
                "required_drones": task.definition.required_drones,
                "status": task.status,
                "assigned_to": sorted(task.assigned_to),
            }
            for task in self.tasks.values()
        ]
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
        }

    def _assign_tasks(self) -> None:
        available = [
            drone
            for drone in self.drones.values()
            if drone.task_id is None
        ]
        reserved_positions = {
            position
            for task in self.tasks.values()
            if task.status in {"assigned", "in_progress", "blocked"}
            for position in task.work_positions.values()
        }
        pending_tasks = sorted(
            (
                task
                for task in self.tasks.values()
                if task.status in {"pending", "blocked"} and not task.assigned_to
            ),
            key=lambda task: (
                -task.definition.priority,
                task.definition.deadline_s,
                task.definition.task_id,
            ),
        )
        for task in pending_tasks:
            assignment = self._select_assignment(
                task,
                available,
                reserved_positions,
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
                available.remove(drone)
                reserved_positions.add(work_position)
            task.status = "assigned"

    def _select_assignment(
        self,
        task: TaskState,
        available: list[DroneState],
        reserved_positions: set[tuple[int, int]],
    ) -> list[tuple[DroneState, tuple[int, int]]] | None:
        required = task.definition.required_drones
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
            task = self.tasks[drone.task_id]
            if position == goals[drone.drone_id]:
                drone.status = "searching"
            else:
                drone.status = "moving"
            task.status = "in_progress"

        for task in self.tasks.values():
            if task.status not in {"assigned", "in_progress"}:
                continue
            if all(
                (self.drones[drone_id].x, self.drones[drone_id].y)
                == task.work_positions[drone_id]
                for drone_id in task.assigned_to
            ):
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

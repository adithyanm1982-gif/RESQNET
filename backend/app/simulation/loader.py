import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_FILES = (
    "disaster_scenarios.json",
    "drone_config.json",
    "failure_scenarios.json",
)
VALID_GRID_CELLS = {".", "#", "X"}


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    task_type: str
    x: int
    y: int
    priority: int
    required_drones: int
    deadline_s: int


@dataclass(frozen=True)
class DroneDefinition:
    drone_id: str
    drone_type: str
    x: int
    y: int
    initial_status: str


@dataclass(frozen=True)
class CandidateDetection:
    candidate_id: str
    x: int
    y: int
    verification_status: str


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    name: str
    disaster_type: str
    seed: int
    width: int
    height: int
    grid: tuple[str, ...]
    blocked_cells: frozenset[tuple[int, int]]
    restricted_cells: frozenset[tuple[int, int]]
    tasks: tuple[TaskDefinition, ...]
    drones: tuple[DroneDefinition, ...]
    candidate_detections: tuple[CandidateDetection, ...]


class ScenarioLoader:
    def __init__(self, data_dir: Path = PROJECT_ROOT) -> None:
        self.data_dir = Path(data_dir)

    def load_all(self) -> tuple[ScenarioDefinition, ...]:
        disaster_data = self._read_json("disaster_scenarios.json")
        drone_data = self._read_json("drone_config.json")
        failure_data = self._read_json("failure_scenarios.json")

        scenarios = disaster_data.get("scenarios")
        fleets = drone_data.get("fleets")
        failure_scenarios = failure_data.get("failure_scenarios")
        test_matrix = failure_data.get("test_matrix")
        if not isinstance(scenarios, list) or not isinstance(fleets, list):
            raise DatasetError("Scenario and drone data must contain lists.")
        if not isinstance(failure_scenarios, list) or not isinstance(test_matrix, list):
            raise DatasetError("Failure data must contain scenario and test lists.")

        self._validate_linked_files(disaster_data, drone_data, failure_data)
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("failure_scenario_id"), str)
            for item in failure_scenarios
        ):
            raise DatasetError("Failure scenario IDs must be present and unique.")
        failure_id_list = [item["failure_scenario_id"] for item in failure_scenarios]
        failure_ids = set(failure_id_list)
        if len(failure_ids) != len(failure_id_list):
            raise DatasetError("Failure scenario IDs must be present and unique.")
        for failure in failure_scenarios:
            events = failure.get("events")
            if not isinstance(events, list) or any(
                not isinstance(event, dict)
                for event in events
            ):
                raise DatasetError("Failure scenario events must be lists.")
        for matrix_entry in test_matrix:
            if not isinstance(matrix_entry, dict):
                raise DatasetError("Failure test matrix entries must be objects.")
            failure_scenario_id = matrix_entry.get("failure_scenario_id")
            if (
                not isinstance(failure_scenario_id, str)
                or failure_scenario_id not in failure_ids
            ):
                raise DatasetError("Failure test matrix references an unknown case.")
            if not isinstance(matrix_entry.get("scenario_id"), str):
                raise DatasetError("Failure test matrix scenario IDs are invalid.")

        drone_types = drone_data.get("drone_types")
        if not isinstance(drone_types, dict) or any(
            not isinstance(definition, dict)
            for definition in drone_types.values()
        ):
            raise DatasetError("Drone types must be an object.")
        fleet_by_scenario = self._index_fleets(fleets)
        definitions = tuple(
            self._build_scenario(raw, fleet_by_scenario, drone_types)
            for raw in scenarios
        )
        if len({scenario.scenario_id for scenario in definitions}) != len(definitions):
            raise DatasetError("Scenario IDs must be unique.")
        if set(fleet_by_scenario) != {scenario.scenario_id for scenario in definitions}:
            raise DatasetError("Scenario and drone fleet IDs must match.")
        scenario_ids = {scenario.scenario_id for scenario in definitions}
        if any(
            entry["scenario_id"] not in scenario_ids
            for entry in test_matrix
        ):
            raise DatasetError("Failure test matrix references an unknown scenario.")
        return definitions

    def _read_json(self, filename: str) -> dict[str, Any]:
        path = self.data_dir / filename
        try:
            with path.open(encoding="utf-8") as file:
                content = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise DatasetError(f"Could not load {filename}.") from exc
        if not isinstance(content, dict):
            raise DatasetError(f"{filename} must contain a JSON object.")
        return content

    @staticmethod
    def _validate_linked_files(
        disaster_data: dict[str, Any],
        drone_data: dict[str, Any],
        failure_data: dict[str, Any],
    ) -> None:
        expected = set(DATA_FILES)
        linked: set[str] = set()
        for document in (disaster_data, drone_data, failure_data):
            meta = document.get("meta")
            linked_files = meta.get("linked_files") if isinstance(meta, dict) else None
            if not isinstance(linked_files, list) or any(
                not isinstance(filename, str)
                for filename in linked_files
            ):
                raise DatasetError("Dataset linked-file declarations are invalid.")
            if any(filename not in expected for filename in linked_files):
                raise DatasetError("Dataset declares an unexpected linked file.")
            linked.update(linked_files)
        if not expected.issubset(linked):
            raise DatasetError("Dataset linked-file declarations do not match.")

    @staticmethod
    def _index_fleets(fleets: list[Any]) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for fleet in fleets:
            if not isinstance(fleet, dict):
                raise DatasetError("Drone fleets must be objects.")
            scenario_id = fleet.get("scenario_id")
            if not isinstance(scenario_id, str) or scenario_id in indexed:
                raise DatasetError("Drone fleet scenario IDs must be unique.")
            indexed[scenario_id] = fleet
        return indexed

    def _build_scenario(
        self,
        raw: Any,
        fleet_by_scenario: dict[str, dict[str, Any]],
        drone_types: dict[str, Any],
    ) -> ScenarioDefinition:
        if not isinstance(raw, dict):
            raise DatasetError("Scenario entries must be objects.")
        scenario_id = raw.get("scenario_id")
        if not isinstance(scenario_id, str) or scenario_id not in fleet_by_scenario:
            raise DatasetError("Each scenario must have a matching drone fleet.")

        grid_data = raw.get("grid")
        if not isinstance(grid_data, dict):
            raise DatasetError(f"{scenario_id} must define a grid.")
        width = self._positive_int(grid_data.get("width"), "grid width")
        height = self._positive_int(grid_data.get("height"), "grid height")
        rows = grid_data.get("initial_cell_grid")
        if (
            not isinstance(rows, list)
            or len(rows) != height
            or any(not isinstance(row, str) or len(row) != width for row in rows)
            or any(cell not in VALID_GRID_CELLS for row in rows for cell in row)
        ):
            raise DatasetError(f"{scenario_id} has an invalid initial cell grid.")

        blocked = self._coordinate_set(raw.get("blocked_cells"), width, height)
        restricted = self._coordinate_set(raw.get("restricted_cells"), width, height)
        if blocked & restricted:
            raise DatasetError(f"{scenario_id} blocked and restricted cells overlap.")
        grid_blocked = {
            (x, y)
            for y, row in enumerate(rows)
            for x, cell in enumerate(row)
            if cell == "#"
        }
        grid_restricted = {
            (x, y)
            for y, row in enumerate(rows)
            for x, cell in enumerate(row)
            if cell == "X"
        }
        if blocked != grid_blocked or restricted != grid_restricted:
            raise DatasetError(f"{scenario_id} grid and cell lists disagree.")

        tasks = self._build_tasks(raw.get("tasks"), width, height, blocked | restricted)
        drones = self._build_drones(
            fleet_by_scenario[scenario_id],
            drone_types,
            width,
            height,
            blocked | restricted,
        )
        candidates = self._build_candidates(
            raw.get("candidate_detections", []),
            width,
            height,
        )
        return ScenarioDefinition(
            scenario_id=scenario_id,
            name=self._required_string(raw, "name"),
            disaster_type=self._required_string(raw, "disaster_type"),
            seed=self._positive_or_zero_int(raw.get("seed"), "scenario seed"),
            width=width,
            height=height,
            grid=tuple(rows),
            blocked_cells=frozenset(blocked),
            restricted_cells=frozenset(restricted),
            tasks=tuple(tasks),
            drones=tuple(drones),
            candidate_detections=tuple(candidates),
        )

    def _build_tasks(
        self,
        raw_tasks: Any,
        width: int,
        height: int,
        forbidden: set[tuple[int, int]],
    ) -> list[TaskDefinition]:
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise DatasetError("Each scenario must define tasks.")
        tasks = []
        seen_ids: set[str] = set()
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                raise DatasetError("Task entries must be objects.")
            task_id = self._required_string(raw, "id")
            x = self._bounded_int(raw.get("x"), "task x", width)
            y = self._bounded_int(raw.get("y"), "task y", height)
            required_drones = self._positive_int(
                raw.get("required_drones"),
                "required drone count",
            )
            if task_id in seen_ids or (x, y) in forbidden:
                raise DatasetError("Task IDs must be unique and targets traversable.")
            seen_ids.add(task_id)
            tasks.append(
                TaskDefinition(
                    task_id=task_id,
                    task_type=self._required_string(raw, "type"),
                    x=x,
                    y=y,
                    priority=self._positive_or_zero_int(raw.get("priority"), "priority"),
                    required_drones=required_drones,
                    deadline_s=self._positive_int(raw.get("deadline_s"), "deadline"),
                )
            )
        return tasks

    def _build_drones(
        self,
        fleet: dict[str, Any],
        drone_types: dict[str, Any],
        width: int,
        height: int,
        forbidden: set[tuple[int, int]],
    ) -> list[DroneDefinition]:
        raw_drones = fleet.get("drones")
        fleet_size = fleet.get("fleet_size")
        if (
            not isinstance(raw_drones, list)
            or not self._is_positive_int(fleet_size)
            or fleet_size != len(raw_drones)
            or fleet_size != 6
        ):
            raise DatasetError("Each fleet must contain exactly six drones.")
        drones = []
        seen_ids: set[str] = set()
        for raw in raw_drones:
            if not isinstance(raw, dict):
                raise DatasetError("Drone entries must be objects.")
            drone_id = self._required_string(raw, "id")
            drone_type = self._required_string(raw, "type")
            position = raw.get("initial_position")
            if drone_id in seen_ids or drone_type not in drone_types:
                raise DatasetError("Drone IDs or types are invalid.")
            if not isinstance(position, dict):
                raise DatasetError("Each drone must define an initial position.")
            x = self._bounded_int(position.get("x"), "drone x", width)
            y = self._bounded_int(position.get("y"), "drone y", height)
            if (x, y) in forbidden:
                raise DatasetError("A drone starts in a blocked or restricted cell.")
            seen_ids.add(drone_id)
            drones.append(
                DroneDefinition(
                    drone_id=drone_id,
                    drone_type=drone_type,
                    x=x,
                    y=y,
                    initial_status=self._required_string(raw, "initial_status"),
                )
            )
        return drones

    def _build_candidates(
        self,
        raw_candidates: Any,
        width: int,
        height: int,
    ) -> list[CandidateDetection]:
        if not isinstance(raw_candidates, list):
            raise DatasetError("Candidate detections must be a list.")
        candidates = []
        seen_ids: set[str] = set()
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                raise DatasetError("Candidate detections must be objects.")
            candidate_id = self._required_string(raw, "id")
            if candidate_id in seen_ids:
                raise DatasetError("Candidate detection IDs must be unique.")
            seen_ids.add(candidate_id)
            position = (
                self._bounded_int(raw.get("x"), "candidate x", width),
                self._bounded_int(raw.get("y"), "candidate y", height),
            )
            candidates.append(
                CandidateDetection(
                    candidate_id=candidate_id,
                    x=position[0],
                    y=position[1],
                    verification_status="unverified",
                )
            )
        return candidates

    @staticmethod
    def _coordinate_set(
        raw_cells: Any,
        width: int,
        height: int,
    ) -> set[tuple[int, int]]:
        if not isinstance(raw_cells, list):
            raise DatasetError("Blocked and restricted cells must be lists.")
        coordinates: set[tuple[int, int]] = set()
        for coordinate in raw_cells:
            if (
                not isinstance(coordinate, list)
                or len(coordinate) != 2
                or not all(ScenarioLoader._is_nonnegative_int(value) for value in coordinate)
            ):
                raise DatasetError("Cell coordinates must be integer [x, y] pairs.")
            x, y = coordinate
            if x >= width or y >= height or (x, y) in coordinates:
                raise DatasetError("Cell coordinates must be unique and within the grid.")
            coordinates.add((x, y))
        return coordinates

    @staticmethod
    def _required_string(raw: dict[str, Any], key: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise DatasetError(f"Required string field {key} is invalid.")
        return value

    @staticmethod
    def _is_nonnegative_int(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    @staticmethod
    def _is_positive_int(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    @classmethod
    def _positive_int(cls, value: Any, field: str) -> int:
        if not cls._is_positive_int(value):
            raise DatasetError(f"{field} must be a positive integer.")
        return value

    @classmethod
    def _positive_or_zero_int(cls, value: Any, field: str) -> int:
        if not cls._is_nonnegative_int(value):
            raise DatasetError(f"{field} must be a non-negative integer.")
        return value

    @classmethod
    def _bounded_int(cls, value: Any, field: str, limit: int) -> int:
        if not cls._is_nonnegative_int(value) or value >= limit:
            raise DatasetError(f"{field} is outside the grid.")
        return value

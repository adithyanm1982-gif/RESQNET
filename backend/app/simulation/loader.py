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
DEFAULT_MISSION_DURATION_TICKS = 300


class DatasetError(ValueError):
    pass


class FailureScenarioNotFound(ValueError):
    pass


class IncompatibleFailureScenario(ValueError):
    pass


class InvalidCustomFailurePlan(ValueError):
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


@dataclass(frozen=True)
class FailureScenarioDefinition:
    failure_scenario_id: str
    scenario_id: str
    tick_s: int
    event_status_values: tuple[str, ...]
    events: tuple[dict[str, Any], ...]
    test_matrix_entry: dict[str, Any]


@dataclass(frozen=True)
class CustomFailureScheduleDefinition:
    scenario_id: str
    tick_s: int
    event_status_values: tuple[str, ...]
    events: tuple[dict[str, Any], ...]


class ScenarioLoader:
    def __init__(self, data_dir: Path = PROJECT_ROOT) -> None:
        self.data_dir = Path(data_dir)
        self.mission_duration_ticks = DEFAULT_MISSION_DURATION_TICKS

    def load_all(self) -> tuple[ScenarioDefinition, ...]:
        disaster_data = self._read_json("disaster_scenarios.json")
        drone_data = self._read_json("drone_config.json")
        failure_data = self._read_json("failure_scenarios.json")

        failure_meta = failure_data.get("meta")
        units = failure_meta.get("units") if isinstance(failure_meta, dict) else None
        tick_s = units.get("tick_s") if isinstance(units, dict) else None
        mission_duration_s = (
            units.get("mission_duration_s") if isinstance(units, dict) else None
        )
        if (
            not self._is_positive_int(tick_s)
            or not self._is_positive_int(mission_duration_s)
            or mission_duration_s % tick_s
        ):
            raise DatasetError(
                "Failure dataset mission duration and tick duration are invalid."
            )
        self.mission_duration_ticks = mission_duration_s // tick_s

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

    def load_failure_scenario(
        self,
        failure_scenario_id: str,
        scenario_id: str,
    ) -> FailureScenarioDefinition:
        """Return a validated failure schedule and its compatible matrix entry.

        The existing ``load_all`` return value remains the scenario tuple. This
        method exposes failure data separately for callers that need to install
        a schedule on a live simulation.
        """
        scenarios = self.load_all()
        scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
        scenario = scenario_by_id.get(scenario_id)
        if scenario is None:
            raise DatasetError("Failure schedule references an unknown scenario.")

        data = self._read_json("failure_scenarios.json")
        meta = data.get("meta")
        if not isinstance(meta, dict):
            raise DatasetError("Failure dataset metadata must be an object.")

        units = meta.get("units")
        tick_s = units.get("tick_s") if isinstance(units, dict) else None
        if not self._is_positive_int(tick_s):
            raise DatasetError("Failure dataset tick_s must be a positive integer.")

        event_types = meta.get("event_types")
        event_status_values = meta.get("event_status_values")
        drone_ids = meta.get("drone_ids")
        message_types = meta.get("message_types")
        modes = meta.get("modes")
        if (
            not isinstance(event_types, dict)
            or not event_types
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in event_types.items())
            or not self._string_list(event_status_values)
            or not {"scheduled", "active", "recovering", "resolved"}.issubset(event_status_values)
            or len(set(event_status_values)) != len(event_status_values)
            or not self._string_list(drone_ids)
            or not drone_ids
            or len(set(drone_ids)) != len(drone_ids)
            or not self._string_list(message_types)
            or not message_types
            or len(set(message_types)) != len(message_types)
            or not self._string_list(modes)
            or not modes
            or len(set(modes)) != len(modes)
        ):
            raise DatasetError("Failure dataset metadata is invalid.")

        failure_scenarios = data.get("failure_scenarios")
        test_matrix = data.get("test_matrix")
        if not isinstance(failure_scenarios, list) or not isinstance(test_matrix, list):
            raise DatasetError("Failure data must contain scenario and test lists.")

        failures_by_id: dict[str, dict[str, Any]] = {}
        for failure in failure_scenarios:
            if not isinstance(failure, dict):
                raise DatasetError("Failure scenario entries must be objects.")
            failure_id = failure.get("failure_scenario_id")
            events = failure.get("events")
            if not isinstance(failure_id, str) or not failure_id or failure_id in failures_by_id:
                raise DatasetError("Failure scenario IDs must be present and unique.")
            if not isinstance(events, list):
                raise DatasetError("Failure scenario events must be lists.")
            event_ids: set[str] = set()
            for event in events:
                self._validate_failure_event(
                    event,
                    tick_s=tick_s,
                    event_types=set(event_types),
                    event_status_values=set(event_status_values),
                    drone_ids=set(drone_ids),
                    message_types=set(message_types),
                    scenario_by_id=scenario_by_id,
                    event_ids=event_ids,
                )
            failures_by_id[failure_id] = failure

        matrix_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        matrix_run_ids: set[str] = set()
        for entry in test_matrix:
            if not isinstance(entry, dict):
                raise DatasetError("Failure test matrix entries must be objects.")
            run_id = entry.get("run_id")
            failure_id = entry.get("failure_scenario_id")
            matrix_scenario_id = entry.get("scenario_id")
            entry_modes = entry.get("modes")
            seeds = entry.get("seeds")
            if (
                not isinstance(run_id, str)
                or not run_id
                or run_id in matrix_run_ids
                or not isinstance(failure_id, str)
                or failure_id not in failures_by_id
                or not isinstance(matrix_scenario_id, str)
                or matrix_scenario_id not in scenario_by_id
                or not self._string_list(entry_modes)
                or not entry_modes
                or any(mode not in modes for mode in entry_modes)
                or not isinstance(seeds, list)
                or not seeds
                or any(not self._is_nonnegative_int(seed) for seed in seeds)
                or not isinstance(entry.get("same_inputs_across_modes"), bool)
            ):
                raise DatasetError("Failure test matrix entries are invalid.")
            matrix_run_ids.add(run_id)
            pair = (failure_id, matrix_scenario_id)
            if pair in matrix_by_pair:
                raise DatasetError("Failure test matrix pairs must be unique.")
            matrix_by_pair[pair] = entry

        failure = failures_by_id.get(failure_scenario_id)
        if failure is None:
            raise FailureScenarioNotFound(failure_scenario_id)
        matrix_entry = matrix_by_pair.get((failure_scenario_id, scenario_id))
        if matrix_entry is None:
            raise IncompatibleFailureScenario(
                f"Failure scenario {failure_scenario_id} is not configured for {scenario_id}."
            )
        return FailureScenarioDefinition(
            failure_scenario_id=failure_scenario_id,
            scenario_id=scenario_id,
            tick_s=tick_s,
            event_status_values=tuple(event_status_values),
            events=tuple(dict(event) for event in failure["events"]),
            test_matrix_entry=dict(matrix_entry),
        )

    def load_custom_failure_schedule(
        self,
        scenario_id: str,
        custom_events: list[dict[str, Any]],
    ) -> CustomFailureScheduleDefinition:
        """Validate user-authored tick events and normalize them to dataset event fields."""
        scenarios = self.load_all()
        scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
        scenario = scenario_by_id.get(scenario_id)
        if scenario is None:
            raise InvalidCustomFailurePlan("Custom plan references an unknown scenario.")

        data = self._read_json("failure_scenarios.json")
        meta = data.get("meta")
        if not isinstance(meta, dict):
            raise DatasetError("Failure dataset metadata must be an object.")
        units = meta.get("units")
        tick_s = units.get("tick_s") if isinstance(units, dict) else None
        event_types = meta.get("event_types")
        status_values = meta.get("event_status_values")
        message_types = meta.get("message_types")
        if (
            not self._is_positive_int(tick_s)
            or not isinstance(event_types, dict)
            or not self._string_list(status_values)
            or not self._string_list(message_types)
        ):
            raise DatasetError("Failure dataset metadata is invalid.")

        allowed_custom_types = {
            "controller_outage",
            "drone_unresponsive",
            "network_partition",
        }
        if not isinstance(custom_events, list) or not 1 <= len(custom_events) <= 10:
            raise InvalidCustomFailurePlan("A custom plan must contain 1 to 10 events.")

        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(custom_events, start=1):
            if not isinstance(item, dict) or item.get("type") not in allowed_custom_types:
                raise InvalidCustomFailurePlan(
                    "Custom plans support controller_outage, network_partition, and drone_unresponsive events only."
                )
            start_tick = item.get("start_tick")
            restore_tick = item.get("restore_tick")
            if (
                not self._is_positive_int(start_tick)
                or start_tick > 100_000
                or (restore_tick is not None and (
                    not self._is_positive_int(restore_tick)
                    or restore_tick > 100_000
                    or restore_tick <= start_tick
                ))
            ):
                raise InvalidCustomFailurePlan(
                    "Event start_tick must be 1–100000 and restore_tick, when set, must be later."
                )
            event_type = item["type"]
            if event_type != "drone_unresponsive" and restore_tick is None:
                raise InvalidCustomFailurePlan(
                    f"{event_type} requires a restore_tick; only drone_unresponsive may be permanent."
                )

            start_s = start_tick * tick_s
            end_s = restore_tick * tick_s if restore_tick is not None else None
            event: dict[str, Any] = {
                "id": f"C{index:02d}",
                "type": event_type,
                "start_s": start_s,
                "end_s": end_s,
                "status": "scheduled",
            }
            if end_s is not None:
                event["duration_s"] = end_s - start_s

            if event_type == "controller_outage":
                event.update({
                    "target": "central_controller",
                    "severity": "full",
                    "cause": "power_failure",
                })
            elif event_type == "drone_unresponsive":
                event.update({
                    "drone_id": item.get("drone_id"),
                    "recovers": restore_tick is not None,
                    "cause": "hardware_fault",
                })
            else:
                event.update({
                    "groups": item.get("groups"),
                    "cause": "interference",
                })

            if event_type in {"controller_outage", "network_partition"}:
                recovery = item.get("reconnection")
                if not isinstance(recovery, dict):
                    raise InvalidCustomFailurePlan(
                        f"{event_type} requires reconnection timing in ticks."
                    )
                tick_fields = (
                    "detect_timeout_ticks",
                    "reconnect_delay_ticks",
                    "resync_time_ticks",
                )
                if any(
                    not self._is_nonnegative_int(recovery.get(field))
                    or recovery[field] > 10_000
                    for field in tick_fields
                ):
                    raise InvalidCustomFailurePlan(
                        "Reconnection timing fields must be integer tick counts from 0 to 10000."
                    )
                event["reconnection"] = {
                    "detect_timeout_s": recovery["detect_timeout_ticks"] * tick_s,
                    "reconnect_delay_s": recovery["reconnect_delay_ticks"] * tick_s,
                    "resync_time_s": recovery["resync_time_ticks"] * tick_s,
                    "total_recovery_s": (
                        recovery["reconnect_delay_ticks"]
                        + recovery["resync_time_ticks"]
                    ) * tick_s,
                    "state_sync": "delta",
                }

            normalized.append(event)

        self._validate_custom_conflicts(custom_events)
        event_ids: set[str] = set()
        drone_ids = {drone.drone_id for drone in scenario.drones}
        for event in normalized:
            try:
                self._validate_failure_event(
                    event,
                    tick_s=tick_s,
                    event_types=set(event_types),
                    event_status_values=set(status_values),
                    drone_ids=drone_ids,
                    message_types=set(message_types),
                    scenario_by_id=scenario_by_id,
                    event_ids=event_ids,
                )
            except DatasetError as exc:
                raise InvalidCustomFailurePlan(str(exc)) from exc

        return CustomFailureScheduleDefinition(
            scenario_id=scenario_id,
            tick_s=tick_s,
            event_status_values=tuple(status_values),
            events=tuple(normalized),
        )

    @staticmethod
    def _validate_custom_conflicts(events: list[dict[str, Any]]) -> None:
        intervals: list[tuple[str, str | None, int, int | None]] = []
        for event in events:
            event_type = event["type"]
            target = event.get("drone_id") if event_type == "drone_unresponsive" else None
            start = event["start_tick"]
            end = event["restore_tick"]
            if event_type in {"controller_outage", "network_partition"} and end is not None:
                recovery = event.get("reconnection", {})
                end += recovery.get("reconnect_delay_ticks", 0) + recovery.get("resync_time_ticks", 0)
            if event_type == "drone_unresponsive" and end is None:
                end = 100_001
            for prior_type, prior_target, prior_start, prior_end in intervals:
                same_resource = (
                    event_type == prior_type
                    and (event_type != "drone_unresponsive" or target == prior_target)
                )
                if same_resource and max(start, prior_start) < min(end or 100_001, prior_end or 100_001):
                    raise InvalidCustomFailurePlan(
                        "Overlapping events affecting the same controller, partition, or drone are not allowed."
                    )
            intervals.append((event_type, target, start, end))

    def _validate_failure_event(
        self,
        event: Any,
        *,
        tick_s: int,
        event_types: set[str],
        event_status_values: set[str],
        drone_ids: set[str],
        message_types: set[str],
        scenario_by_id: dict[str, ScenarioDefinition],
        event_ids: set[str],
    ) -> None:
        if not isinstance(event, dict):
            raise DatasetError("Failure events must be objects.")
        event_id = event.get("id")
        event_type = event.get("type")
        start_s = event.get("start_s")
        end_s = event.get("end_s")
        if (
            not isinstance(event_id, str)
            or not event_id
            or event_id in event_ids
            or not isinstance(event_type, str)
            or event_type not in event_types
            or "end_s" not in event
            or not self._is_nonnegative_int(start_s)
            or start_s % tick_s != 0
            or (end_s is not None and (not self._is_nonnegative_int(end_s) or end_s < start_s or end_s % tick_s != 0))
            or not isinstance(event.get("status"), str)
            or event.get("status") not in event_status_values
            or event.get("status") != "scheduled"
        ):
            raise DatasetError("Failure event identity, type, timing, or status is invalid.")
        event_ids.add(event_id)

        drone_id = event.get("drone_id")
        if drone_id is not None and (
            not isinstance(drone_id, str) or drone_id not in drone_ids
        ):
            raise DatasetError("Failure event references an unknown drone.")
        listed_drones = event.get("drone_ids", [])
        if (
            not isinstance(listed_drones, list)
            or any(not isinstance(item, str) or item not in drone_ids for item in listed_drones)
            or len(set(listed_drones)) != len(listed_drones)
        ):
            raise DatasetError("Failure event drone_ids are invalid.")
        affected_types = event.get("affected_message_types", [])
        if (
            not isinstance(affected_types, list)
            or any(not isinstance(item, str) or item not in message_types for item in affected_types)
        ):
            raise DatasetError("Failure event message types are invalid.")

        if "reconnection" in event:
            recovery = event["reconnection"]
            if not isinstance(recovery, dict):
                raise DatasetError("Failure event reconnection data must be an object.")
            recovery_fields = (
                "detect_timeout_s",
                "reconnect_delay_s",
                "resync_time_s",
                "total_recovery_s",
            )
            if any(not self._is_nonnegative_int(recovery.get(field)) for field in recovery_fields):
                raise DatasetError("Failure event reconnection times are invalid.")
            if recovery["total_recovery_s"] != recovery["reconnect_delay_s"] + recovery["resync_time_s"]:
                raise DatasetError("Failure event total_recovery_s does not match its components.")
            if recovery["total_recovery_s"] % tick_s != 0:
                raise DatasetError("Failure event recovery time must align to a simulation tick.")

        if event_type == "controller_outage":
            if (
                not isinstance(event.get("target"), str)
                or not isinstance(event.get("severity"), str)
                or not isinstance(event.get("cause"), str)
                or "reconnection" not in event
            ):
                raise DatasetError("Controller outage event fields are invalid.")
        elif event_type == "drone_unresponsive":
            if not isinstance(drone_id, str) or not isinstance(event.get("recovers"), bool):
                raise DatasetError("Drone failure event fields are invalid.")
            if not isinstance(event.get("cause"), str):
                raise DatasetError("Drone failure cause is invalid.")
            if end_s is None and event["recovers"]:
                raise DatasetError("An event with null end_s cannot be marked recoverable.")
            if end_s is not None and not event["recovers"]:
                raise DatasetError("A non-null end_s must agree with the event's recovers value.")
        elif event_type == "network_partition":
            groups = event.get("groups")
            if not isinstance(groups, list) or not groups or not isinstance(event.get("cause"), str) or "reconnection" not in event:
                raise DatasetError("Network partition groups are invalid.")
            group_ids: set[str] = set()
            partitioned_drones: set[str] = set()
            for group in groups:
                if (
                    not isinstance(group, dict)
                    or not isinstance(group.get("group_id"), str)
                    or group["group_id"] in group_ids
                    or not isinstance(group.get("has_controller_link"), bool)
                    or not isinstance(group.get("drone_ids"), list)
                    or not group["drone_ids"]
                    or any(
                        not isinstance(item, str) or item not in drone_ids
                        for item in group["drone_ids"]
                    )
                    or any(item in partitioned_drones for item in group["drone_ids"])
                ):
                    raise DatasetError("Network partition group entries are invalid.")
                group_ids.add(group["group_id"])
                partitioned_drones.update(group["drone_ids"])
            if partitioned_drones != drone_ids:
                raise DatasetError("Network partition groups must cover the declared drones.")
        elif event_type == "packet_loss":
            loss_pct = event.get("loss_pct")
            if (
                not isinstance(event.get("scope"), str)
                or not isinstance(event.get("pattern"), str)
                or ("burst_len_packets" in event and not self._is_positive_int(event["burst_len_packets"]))
                or not listed_drones
                or isinstance(loss_pct, bool)
                or not isinstance(loss_pct, (int, float))
                or not 0 <= loss_pct <= 100
                or not affected_types
            ):
                raise DatasetError("Packet loss event fields are invalid.")
        elif event_type == "message_delay":
            probabilities = ("reorder_probability", "duplicate_probability")
            numeric_fields = ("base_delay_ms", "jitter_ms", "max_delay_ms")
            if (
                not isinstance(event.get("scope"), str)
                or not affected_types
                or any(not self._is_nonnegative_int(event.get(field)) for field in numeric_fields)
                or event["max_delay_ms"] < event["base_delay_ms"]
                or any(
                    isinstance(event.get(field), bool)
                    or not isinstance(event.get(field), (int, float))
                    or not 0 <= event[field] <= 1
                    for field in probabilities
                )
            ):
                raise DatasetError("Message delay event fields are invalid.")
        elif event_type == "battery_override":
            overrides = event.get("overrides")
            if not isinstance(overrides, list) or not overrides:
                raise DatasetError("Battery override entries are invalid.")
            override_ids: set[str] = set()
            for override in overrides:
                if (
                    not isinstance(override, dict)
                    or not isinstance(override.get("drone_id"), str)
                    or override.get("drone_id") not in drone_ids
                    or override["drone_id"] in override_ids
                    or not self._is_nonnegative_int(override.get("battery_pct"))
                    or override["battery_pct"] > 100
                ):
                    raise DatasetError("Battery override entry is invalid.")
                override_ids.add(override["drone_id"])
        elif event_type == "no_fly_activation":
            cells_by_scenario = event.get("cells_by_scenario")
            if not isinstance(cells_by_scenario, dict) or not cells_by_scenario or not isinstance(event.get("reason"), str):
                raise DatasetError("No-fly scenario cells are invalid.")
            for scenario_id, cells in cells_by_scenario.items():
                scenario = scenario_by_id.get(scenario_id)
                if scenario is None or not isinstance(cells, list) or not cells:
                    raise DatasetError("No-fly event references an invalid scenario or cell list.")
                seen_cells: set[tuple[int, int]] = set()
                for cell in cells:
                    if (
                        not isinstance(cell, list)
                        or len(cell) != 2
                        or not all(self._is_nonnegative_int(value) for value in cell)
                        or cell[0] >= scenario.width
                        or cell[1] >= scenario.height
                        or tuple(cell) in seen_cells
                    ):
                        raise DatasetError("No-fly event cell coordinates are invalid.")
                    seen_cells.add(tuple(cell))

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
    def _string_list(value: Any) -> bool:
        return isinstance(value, list) and all(isinstance(item, str) and item for item in value)

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

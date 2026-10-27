import json
import shutil
from pathlib import Path

import pytest

from app.simulation.engine import CoordinationMode
from app.simulation.loader import (
    DatasetError,
    FailureScenarioNotFound,
    IncompatibleFailureScenario,
    InvalidCustomFailurePlan,
    ScenarioLoader,
)

DATA_DIR = Path(__file__).resolve().parents[2]
DATA_FILES = (
    "disaster_scenarios.json",
    "drone_config.json",
    "failure_scenarios.json",
)


def test_coordination_modes_match_repository_dataset_declarations() -> None:
    declared = set(
        json.loads((DATA_DIR / "failure_scenarios.json").read_text(encoding="utf-8"))[
            "meta"
        ]["modes"]
    )
    disaster_declared = set(
        json.loads((DATA_DIR / "disaster_scenarios.json").read_text(encoding="utf-8"))[
            "meta"
        ]["modes"]
    )

    implemented_names = {mode.value for mode in CoordinationMode}
    assert implemented_names == declared == disaster_declared


def _copy_datasets(target: Path) -> Path:
    for filename in DATA_FILES:
        shutil.copyfile(DATA_DIR / filename, target / filename)
    return target


def test_failure_schedule_exposes_case_and_compatible_matrix_entry() -> None:
    loader = ScenarioLoader(DATA_DIR)
    scenarios = loader.load_all()
    failure_data = json.loads((DATA_DIR / "failure_scenarios.json").read_text(encoding="utf-8"))

    for failure in failure_data["failure_scenarios"]:
        for scenario in scenarios:
            schedule = loader.load_failure_scenario(
                failure["failure_scenario_id"],
                scenario.scenario_id,
            )
            assert schedule.scenario_id == scenario.scenario_id
            assert schedule.failure_scenario_id == failure["failure_scenario_id"]
            assert schedule.tick_s == failure_data["meta"]["units"]["tick_s"]
            assert schedule.test_matrix_entry["scenario_id"] == scenario.scenario_id
            assert schedule.test_matrix_entry["failure_scenario_id"] == failure["failure_scenario_id"]
            assert all(event["status"] == "scheduled" for event in schedule.events)


def test_unknown_failure_scenario_is_distinguished_from_invalid_data() -> None:
    with pytest.raises(FailureScenarioNotFound):
        ScenarioLoader(DATA_DIR).load_failure_scenario("missing", "earthquake")


def test_failure_case_without_matrix_pair_is_rejected(tmp_path: Path) -> None:
    data_dir = _copy_datasets(tmp_path)
    path = data_dir / "failure_scenarios.json"
    failure_data = json.loads(path.read_text(encoding="utf-8"))
    failure_data["test_matrix"] = [
        entry
        for entry in failure_data["test_matrix"]
        if not (
            entry["scenario_id"] == "earthquake"
            and entry["failure_scenario_id"] == "demo_core"
        )
    ]
    path.write_text(json.dumps(failure_data), encoding="utf-8")

    with pytest.raises(IncompatibleFailureScenario):
        ScenarioLoader(data_dir).load_failure_scenario("demo_core", "earthquake")


@pytest.mark.parametrize(
    ("change_event", "message"),
    [
        (lambda event: event.update(start_s=121), "timing"),
        (lambda event: event.update(drone_id="D99"), "drone"),
    ],
)
def test_malformed_failure_events_are_rejected(
    tmp_path: Path,
    change_event,
    message: str,
) -> None:
    data_dir = _copy_datasets(tmp_path)
    path = data_dir / "failure_scenarios.json"
    failure_data = json.loads(path.read_text(encoding="utf-8"))
    failure = next(
        item
        for item in failure_data["failure_scenarios"]
        if item["failure_scenario_id"] == "drone_failure"
    )
    change_event(failure["events"][0])
    path.write_text(json.dumps(failure_data), encoding="utf-8")

    with pytest.raises(DatasetError, match=message):
        ScenarioLoader(data_dir).load_failure_scenario("drone_failure", "earthquake")


def test_custom_schedule_converts_ticks_and_uses_dataset_event_fields() -> None:
    schedule = ScenarioLoader(DATA_DIR).load_custom_failure_schedule(
        "earthquake",
        [{
            "type": "controller_outage",
            "start_tick": 3,
            "restore_tick": 8,
            "reconnection": {
                "detect_timeout_ticks": 2,
                "reconnect_delay_ticks": 3,
                "resync_time_ticks": 4,
            },
        }],
    )

    event = schedule.events[0]
    assert schedule.tick_s == 2
    assert event["start_s"] == 6
    assert event["end_s"] == 16
    assert event["duration_s"] == 10
    assert event["target"] == "central_controller"
    assert event["reconnection"] == {
        "detect_timeout_s": 4,
        "reconnect_delay_s": 6,
        "resync_time_s": 8,
        "total_recovery_s": 14,
        "state_sync": "delta",
    }


def test_custom_schedule_rejects_unsupported_types_and_conflicting_events() -> None:
    loader = ScenarioLoader(DATA_DIR)
    with pytest.raises(InvalidCustomFailurePlan, match="support"):
        loader.load_custom_failure_schedule(
            "earthquake",
            [{"type": "packet_loss", "start_tick": 1, "restore_tick": 2}],
        )

    recovery = {
        "detect_timeout_ticks": 1,
        "reconnect_delay_ticks": 1,
        "resync_time_ticks": 1,
    }
    with pytest.raises(InvalidCustomFailurePlan, match="Overlapping"):
        loader.load_custom_failure_schedule(
            "earthquake",
            [
                {"type": "controller_outage", "start_tick": 1, "restore_tick": 5, "reconnection": recovery},
                {"type": "controller_outage", "start_tick": 6, "restore_tick": 9, "reconnection": recovery},
            ],
        )

from pathlib import Path

import pytest

from app.simulation.engine import (
    CoordinationMode,
    FailureScheduleConflict,
    SimulationEngine,
    TaskClaimProposal,
)
from app.simulation.loader import (
    DatasetError,
    DroneDefinition,
    FailureScenarioDefinition,
    ScenarioDefinition,
    ScenarioLoader,
    TaskDefinition,
)

DATA_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def scenarios():
    return ScenarioLoader(DATA_DIR).load_all()


def test_real_scenarios_load_and_initialise_six_drones(scenarios) -> None:
    assert {scenario.scenario_id for scenario in scenarios} == {
        "earthquake",
        "cyclone",
        "flood",
    }
    for scenario in scenarios:
        state = SimulationEngine(scenario).get_state()

        assert (state["grid"]["width"], state["grid"]["height"]) == (20, 20)
        assert len(state["drones"]) == 6
        assert {drone["drone_id"] for drone in state["drones"]} == {
            f"D{i}" for i in range(1, 7)
        }
        assert all(
            scenario.grid[drone["y"]][drone["x"]] == "."
            for drone in state["drones"]
        )
        positions = {(drone["x"], drone["y"]) for drone in state["drones"]}
        assert len(positions) == 6


def test_real_scenarios_keep_unique_traversable_positions_for_100_ticks(scenarios) -> None:
    for scenario in scenarios:
        engine = SimulationEngine(scenario)
        for _ in range(100):
            state = engine.advance()
            positions = {(drone["x"], drone["y"]) for drone in state["drones"]}

            assert len(positions) == 6
            assert all(engine.is_traversable(position) for position in positions)


def test_all_six_drones_move_legally_on_each_real_grid(scenarios) -> None:
    for scenario in scenarios:
        engine = SimulationEngine(scenario)
        initial_positions = {
            drone.drone_id: (drone.x, drone.y)
            for drone in engine.drones.values()
        }
        moved_ids = set()

        for _ in range(10):
            state = engine.advance()
            positions = [(drone["x"], drone["y"]) for drone in state["drones"]]
            moved_ids.update(
                drone["drone_id"]
                for drone in state["drones"]
                if (drone["x"], drone["y"]) != initial_positions[drone["drone_id"]]
            )

            assert len(positions) == len(set(positions))
            assert all(engine.is_traversable(position) for position in positions)

        assert moved_ids == {f"D{i}" for i in range(1, 7)}


def test_blocked_cells_are_never_entered() -> None:
    drones = (
        _drone("D1", 0, 0),
        _drone("D2", 0, 2),
        _drone("D3", 1, 2),
        _drone("D4", 2, 2),
        _drone("D5", 1, 1),
        _drone("D6", 2, 1),
    )
    scenario = _small_scenario(
        grid=("..#", "...", "..."),
        blocked=frozenset({(2, 0)}),
        drones=drones,
        task_position=(1, 0),
    )
    engine = SimulationEngine(scenario)

    state = engine.advance()

    assert (engine.drones["D1"].x, engine.drones["D1"].y) == (1, 0)
    assert all(engine.is_traversable((drone["x"], drone["y"])) for drone in state["drones"])


def test_task_assignment_is_unique_and_supports_required_team_size(scenarios) -> None:
    scenario = next(item for item in scenarios if item.scenario_id == "earthquake")
    state = SimulationEngine(scenario).advance()

    assigned = state["assigned_tasks"]
    assert assigned
    assert all(len(task["assigned_to"]) == task["required_drones"] for task in assigned)
    assigned_drone_ids = [
        drone_id for task in assigned for drone_id in task["assigned_to"]
    ]
    assert len(assigned_drone_ids) == len(set(assigned_drone_ids))


def test_engine_retains_selected_coordination_mode(scenarios) -> None:
    scenario = next(item for item in scenarios if item.scenario_id == "earthquake")

    engine = SimulationEngine(scenario, CoordinationMode.DECENTRALIZED)

    assert engine.coordination_mode is CoordinationMode.DECENTRALIZED
    assert engine.get_state()["coordination_mode"] == "decentralized"


def test_centralized_earthquake_baseline_completes_deterministically(scenarios) -> None:
    scenario = next(item for item in scenarios if item.scenario_id == "earthquake")
    engine = SimulationEngine(scenario, CoordinationMode.CENTRALIZED)
    replay = SimulationEngine(scenario, CoordinationMode.CENTRALIZED)
    state = engine.get_state()

    assert state["coordination_mode"] == "centralized"
    for expected_tick in range(1, 101):
        state = engine.advance()
        replay_state = replay.advance()
        assert state["tick"] == expected_tick
        assert state["coordination_mode"] == "centralized"

        active_owners = [
            drone_id
            for task in state["tasks"]
            if task["status"] != "completed"
            for drone_id in task["assigned_to"]
        ]
        assert len(active_owners) == len(set(active_owners))

        state_without_run_id = {key: value for key, value in state.items() if key != "run_id"}
        replay_without_run_id = {
            key: value for key, value in replay_state.items() if key != "run_id"
        }
        assert state_without_run_id == replay_without_run_id
        if len(state["completed_tasks"]) == len(state["tasks"]):
            break

    assert len(state["completed_tasks"]) == len(state["tasks"])


def test_hybrid_uses_centralized_allocation_when_controller_is_available() -> None:
    scenario = _small_scenario(
        grid=(".......", ".......", "......."),
        blocked=frozenset(),
        drones=tuple(_drone(f"D{i}", i - 1, 0) for i in range(1, 7)),
        task_position=(3, 2),
        required_drones=2,
    )
    engine = SimulationEngine(scenario, CoordinationMode.HYBRID)

    state = engine.advance()

    assert state["operational_strategy"] == "centralized_allocation"
    assert state["controller_available"] is True
    assert state["controller_reachable"] is True
    assert len(engine.tasks["T1"].assigned_to) == 2
    assert all(
        engine.tasks["T1"].claim_groups[drone_id] == "controller"
        for drone_id in engine.tasks["T1"].assigned_to
    )


def test_hybrid_controller_outage_fallback_and_recovery_timing(scenarios) -> None:
    scenario = next(item for item in scenarios if item.scenario_id == "earthquake")
    schedule = ScenarioLoader(DATA_DIR).load_failure_scenario(
        "controller_failure",
        "earthquake",
    )
    engine = SimulationEngine(scenario, CoordinationMode.HYBRID)
    engine.install_failure_schedule(schedule)

    before_start = engine.advance(59)
    assert before_start["tick"] == 59
    assert before_start["operational_strategy"] == "centralized_allocation"
    assert before_start["failure_events"][0]["status"] == "scheduled"

    outage_tick = engine.advance()
    assert outage_tick["tick"] == 60
    assert outage_tick["failure_events"][0]["status"] == "active"
    assert outage_tick["operational_strategy"] == "decentralized_fallback"
    assert outage_tick["controller_available"] is False
    assert outage_tick["controller_reachable"] is False

    recovery_start = engine.advance(90)
    assert recovery_start["tick"] == 150
    assert recovery_start["failure_events"][0]["status"] == "recovering"
    assert recovery_start["operational_strategy"] == "decentralized_fallback"
    assert recovery_start["controller_available"] is True
    assert recovery_start["controller_reachable"] is False

    resync_start = engine.advance(3)
    assert resync_start["tick"] == 153
    assert resync_start["operational_strategy"] == "reconciliation"
    assert resync_start["controller_reachable"] is True
    assert resync_start["reconciliation_history"]

    while engine.tick < 157:
        recovered = engine.advance()
    assert recovered["failure_events"][0]["status"] == "resolved"
    assert recovered["operational_strategy"] == "centralized_allocation"


def test_hybrid_partition_claims_are_local_then_reconciled_idempotently() -> None:
    scenario = _small_scenario(
        grid=tuple("." * 11 for _ in range(11)),
        blocked=frozenset(),
        drones=(
            _drone("D1", 0, 0),
            _drone("D2", 0, 1),
            _drone("D3", 0, 2),
            _drone("D4", 10, 8),
            _drone("D5", 10, 9),
            _drone("D6", 10, 10),
        ),
        task_position=(5, 5),
    )
    groups = [
        {"group_id": "A", "drone_ids": ["D1", "D2", "D3"], "has_controller_link": True},
        {"group_id": "B", "drone_ids": ["D4", "D5", "D6"], "has_controller_link": False},
    ]
    schedule = FailureScenarioDefinition(
        failure_scenario_id="test_partition",
        scenario_id="test",
        tick_s=2,
        event_status_values=("scheduled", "active", "recovering", "resolved"),
        events=(
            {
                "id": "P01",
                "type": "network_partition",
                "start_s": 2,
                "end_s": 8,
                "groups": groups,
                "reconnection": {
                    "detect_timeout_s": 2,
                    "reconnect_delay_s": 2,
                    "resync_time_s": 2,
                    "total_recovery_s": 4,
                    "state_sync": "delta",
                },
                "status": "scheduled",
            },
        ),
        test_matrix_entry={"scenario_id": "test"},
    )
    engine = SimulationEngine(scenario, CoordinationMode.HYBRID)
    engine.drones["D4"].status = "disconnected"
    engine.install_failure_schedule(schedule)
    replay = SimulationEngine(scenario, CoordinationMode.HYBRID)
    replay.drones["D4"].status = "disconnected"
    replay.install_failure_schedule(schedule)

    partitioned = engine.advance()
    replay_partitioned = replay.advance()
    assert {
        key: value for key, value in partitioned.items() if key != "run_id"
    } == {key: value for key, value in replay_partitioned.items() if key != "run_id"}
    task = partitioned["tasks"][0]
    assert partitioned["operational_strategy"] == "decentralized_fallback"
    assert partitioned["controller_available"] is True
    assert partitioned["controller_reachable"] is True
    assert partitioned["partition_state"][0]["groups"] == groups
    assert len(task["claims"]) == 2
    assert all(claim["drone_id"] != "D4" for claim in task["claims"])
    assert {claim["group_id"] for claim in task["claims"]} == {
        "partition:controller",
        "partition:B",
    }
    assert len(task["claims"]) > task["required_drones"]

    recovery_wait = engine.advance(3)
    replay_recovery_wait = replay.advance(3)
    assert {
        key: value for key, value in recovery_wait.items() if key != "run_id"
    } == {key: value for key, value in replay_recovery_wait.items() if key != "run_id"}
    assert recovery_wait["tick"] == 4
    assert recovery_wait["failure_events"][0]["status"] == "recovering"
    assert recovery_wait["operational_strategy"] == "decentralized_fallback"

    reconciliation = engine.advance()
    replay_reconciliation = replay.advance()
    assert {
        key: value for key, value in reconciliation.items() if key != "run_id"
    } == {key: value for key, value in replay_reconciliation.items() if key != "run_id"}
    reconciled_task = reconciliation["tasks"][0]
    assert reconciliation["tick"] == 5
    assert reconciliation["failure_events"][0]["status"] == "recovering"
    assert reconciliation["operational_strategy"] == "reconciliation"
    assert len(reconciled_task["claims"]) == 1
    assert reconciled_task["claims"][0]["drone_id"] == "D3"
    assert reconciled_task["claims"][0]["group_id"] == "partition:controller"
    assert any(
        claim["drone_id"] == "D5" and claim["reason"] == "reconciliation_lost"
        for claim in reconciled_task["released_claims"]
    )

    stable_state = engine.get_state()
    event = engine._failure_events[0]
    engine._reconcile_hybrid_claims(event)
    assert engine.get_state() == stable_state

    recovered = engine.advance()
    replay_recovered = replay.advance()
    assert {
        key: value for key, value in recovered.items() if key != "run_id"
    } == {key: value for key, value in replay_recovered.items() if key != "run_id"}
    assert recovered["tick"] == 6
    assert recovered["failure_events"][0]["status"] == "resolved"
    assert recovered["operational_strategy"] == "centralized_allocation"

    completed_engine = SimulationEngine(scenario, CoordinationMode.HYBRID)
    completed_engine.install_failure_schedule(schedule)
    completed_engine.tasks["T1"].status = "completed"
    completed = completed_engine.advance(6)
    assert completed["tasks"][0]["status"] == "completed"
    assert "T1" in completed["completed_tasks"]


def test_hybrid_reconciliation_releases_later_partition_claim_and_preserves_completed_task() -> None:
    scenario = _small_scenario(
        grid=tuple("." * 11 for _ in range(11)),
        blocked=frozenset(),
        drones=(
            _drone("D1", 0, 0),
            _drone("D2", 0, 1),
            _drone("D3", 0, 2),
            _drone("D4", 10, 8),
            _drone("D5", 10, 9),
            _drone("D6", 10, 10),
        ),
        task_position=(5, 5),
        tasks=(
            TaskDefinition("T1", "search", 5, 5, 2, 1, 100),
            TaskDefinition("T2", "search", 6, 5, 1, 1, 100),
        ),
    )
    groups = [
        {"group_id": "A", "drone_ids": ["D1", "D2", "D3"], "has_controller_link": True},
        {"group_id": "B", "drone_ids": ["D4", "D5", "D6"], "has_controller_link": False},
    ]
    schedule = FailureScenarioDefinition(
        failure_scenario_id="staggered_partition",
        scenario_id="test",
        tick_s=2,
        event_status_values=("scheduled", "active", "recovering", "resolved"),
        events=(
            {
                "id": "P01",
                "type": "network_partition",
                "start_s": 2,
                "end_s": 10,
                "groups": groups,
                "reconnection": {
                    "detect_timeout_s": 2,
                    "reconnect_delay_s": 2,
                    "resync_time_s": 2,
                    "total_recovery_s": 4,
                    "state_sync": "delta",
                },
                "status": "scheduled",
            },
            {
                "id": "D05",
                "type": "drone_unresponsive",
                "drone_id": "D5",
                "start_s": 2,
                "end_s": 4,
                "status": "scheduled",
            },
        ),
        test_matrix_entry={"scenario_id": "test"},
    )
    engine = SimulationEngine(scenario, CoordinationMode.HYBRID)
    engine.drones["D4"].status = "disconnected"
    engine.drones["D6"].status = "disconnected"
    engine.tasks["T2"].status = "completed"
    engine.install_failure_schedule(schedule)

    first_claims = engine.advance()
    first_task = first_claims["tasks"][0]
    assert first_task["task_id"] == "T1"
    assert first_task["status"] != "completed"
    assert len(first_task["claims"]) == 1
    first_claim = first_task["claims"][0]
    assert first_claim["drone_id"] == "D3"
    assert first_claim["claim_tick"] == 1

    competing_claims = engine.advance()
    contested = next(task for task in competing_claims["tasks"] if task["task_id"] == "T1")
    assert contested["status"] != "completed"
    assert [(claim["drone_id"], claim["claim_tick"]) for claim in contested["claims"]] == [
        ("D3", 1),
        ("D5", 2),
    ]
    assert len(contested["claims"]) > contested["required_drones"]

    recovering = engine.advance(3)
    assert recovering["tick"] == 5
    assert next(task for task in recovering["tasks"] if task["task_id"] == "T1")["status"] != "completed"
    # Model a stale pre-existing claim at the synchronization boundary; D4 is
    # still disconnected and must be released before conflict resolution.
    task = engine.tasks["T1"]
    task.assigned_to.append("D4")
    task.claim_ticks["D4"] = 0
    task.claim_groups["D4"] = "partition:B"
    task.work_positions["D4"] = (4, 5)

    reconciliation = engine.advance()
    reconciled = next(task for task in reconciliation["tasks"] if task["task_id"] == "T1")
    assert reconciliation["tick"] == 6
    assert reconciliation["operational_strategy"] == "reconciliation"
    assert reconciled["status"] != "completed"
    assert [(claim["drone_id"], claim["claim_tick"]) for claim in reconciled["claims"]] == [
        ("D3", 1)
    ]
    assert any(
        claim["drone_id"] == "D5"
        and claim["claim_tick"] == 2
        and claim["reason"] == "reconciliation_lost"
        for claim in reconciled["released_claims"]
    )
    assert any(
        claim["drone_id"] == "D4"
        and claim["claim_tick"] == 0
        and claim["reason"] == "disconnected"
        for claim in reconciled["released_claims"]
    )
    assert "T2" in reconciliation["completed_tasks"]
    stable_state = engine.get_state()
    engine._reconcile_hybrid_claims(engine._failure_events[0])
    assert engine.get_state() == stable_state


def test_decentralized_claim_conflicts_keep_earliest_then_lowest_drone_id() -> None:
    drones = tuple(_drone(f"D{i}", i, 0) for i in range(1, 7))
    scenario = _small_scenario(
        grid=(".......", ".......", "......."),
        blocked=frozenset(),
        drones=drones,
        task_position=(3, 2),
        required_drones=2,
    )
    engine = SimulationEngine(scenario, CoordinationMode.DECENTRALIZED)
    task = engine.tasks["T1"]

    winners, losers = engine._resolve_claim_conflicts(
        task,
        [
            TaskClaimProposal("T1", "D3", 4),
            TaskClaimProposal("T1", "D2", 5),
            TaskClaimProposal("T1", "D1", 5),
        ],
    )

    assert [(claim.claim_tick, claim.drone_id) for claim in winners] == [
        (4, "D3"),
        (5, "D1"),
    ]
    assert [(claim.claim_tick, claim.drone_id) for claim in losers] == [(5, "D2")]


def test_decentralized_claims_deduplicate_drone_and_enforce_team_capacity() -> None:
    drones = tuple(_drone(f"D{i}", i, 0) for i in range(1, 7))
    scenario = _small_scenario(
        grid=(".......", ".......", "......."),
        blocked=frozenset(),
        drones=drones,
        task_position=(3, 2),
        required_drones=2,
    )
    engine = SimulationEngine(scenario, CoordinationMode.DECENTRALIZED)
    task = engine.tasks["T1"]

    winners, losers = engine._resolve_claim_conflicts(
        task,
        [
            TaskClaimProposal("T1", "D1", 3),
            TaskClaimProposal("T1", "D1", 2),
            TaskClaimProposal("T1", "D2", 3),
            TaskClaimProposal("T1", "D3", 3),
        ],
    )

    assert [(claim.claim_tick, claim.drone_id) for claim in winners] == [
        (2, "D1"),
        (3, "D2"),
    ]
    assert len({claim.drone_id for claim in winners}) == len(winners)
    assert len(winners) <= task.definition.required_drones
    assert {claim.drone_id for claim in losers} == {"D1", "D3"}


def test_completed_decentralized_task_rejects_and_preserves_all_claims() -> None:
    drones = tuple(_drone(f"D{i}", i, 0) for i in range(1, 7))
    scenario = _small_scenario(
        grid=(".......", "......."),
        blocked=frozenset(),
        drones=drones,
        task_position=(3, 1),
    )
    engine = SimulationEngine(scenario, CoordinationMode.DECENTRALIZED)
    task = engine.tasks["T1"]
    task.status = "completed"
    task.assigned_to = ["D1"]
    task.claim_ticks = {"D1": 1}

    winners, losers = engine._resolve_claim_conflicts(
        task,
        [TaskClaimProposal("T1", "D2", 2)],
    )

    assert winners == []
    assert [(claim.drone_id, claim.claim_tick) for claim in losers] == [("D2", 2)]
    assert task.status == "completed"
    assert task.assigned_to == ["D1"]
    assert task.claim_ticks == {"D1": 1}


def test_decentralized_excludes_disconnected_drones_and_releases_stale_claims() -> None:
    drones = tuple(_drone(f"D{i}", i, 0) for i in range(1, 7))
    scenario = _small_scenario(
        grid=(".......", ".......", "......."),
        blocked=frozenset(),
        drones=drones,
        task_position=(3, 2),
    )
    engine = SimulationEngine(scenario, CoordinationMode.DECENTRALIZED)
    engine.drones["D1"].status = "disconnected"

    first = engine.advance()
    assert all("D1" not in task["assigned_to"] for task in first["tasks"])
    assert all(
        task["claim_status"] in {"unclaimed", "claimed", "completed"}
        for task in first["tasks"]
    )

    claimed_task = next(
        task for task in engine.tasks.values() if "D2" in task.assigned_to
    )
    engine.drones["D2"].status = "disconnected"
    next_state = engine.advance()

    assert "D2" not in claimed_task.assigned_to
    assert {
        "drone_id": "D2",
        "claim_tick": 1,
        "released_tick": 2,
        "reason": "disconnected",
    } in claimed_task.released_claims
    assert next_state["drones"][1]["status"] == "disconnected"


def test_decentralized_failure_releases_claim_and_refills_required_team() -> None:
    drones = tuple(_drone(f"D{i}", i, 0) for i in range(1, 7))
    scenario = _small_scenario(
        grid=(".......", ".......", "......."),
        blocked=frozenset(),
        drones=drones,
        task_position=(3, 2),
        required_drones=2,
    )
    engine = SimulationEngine(scenario, CoordinationMode.DECENTRALIZED)
    schedule = FailureScenarioDefinition(
        failure_scenario_id="test_drone_failure",
        scenario_id="test",
        tick_s=2,
        event_status_values=("scheduled", "active", "recovering", "resolved"),
        events=(
            {
                "id": "E01",
                "type": "drone_unresponsive",
                "start_s": 4,
                "end_s": None,
                "drone_id": "D1",
                "status": "scheduled",
            },
        ),
        test_matrix_entry={"scenario_id": "test"},
    )
    engine.install_failure_schedule(schedule)
    engine.advance()

    after_failure = engine.advance()
    task = engine.tasks["T1"]
    assert engine.drones["D1"].status == "disconnected"
    assert "D1" not in task.assigned_to
    assert any(
        claim["drone_id"] == "D1" and claim["reason"] == "disconnected"
        for claim in task.released_claims
    )
    engine.advance()
    assert len(task.assigned_to) == task.definition.required_drones
    assert "D1" not in task.assigned_to
    assert all(claim["drone_id"] != "D1" for claim in after_failure["tasks"][0]["claims"])


def test_decentralized_real_scenario_progress_is_deterministic(scenarios) -> None:
    scenario = next(item for item in scenarios if item.scenario_id == "earthquake")
    first = SimulationEngine(scenario, CoordinationMode.DECENTRALIZED)
    second = SimulationEngine(scenario, CoordinationMode.DECENTRALIZED)

    for expected_tick in range(1, 101):
        first_state = first.advance()
        second_state = second.advance()
        assert first_state["tick"] == expected_tick
        assert first_state["coordination_mode"] == "decentralized"
        assert all("claim_status" in task and "claims" in task for task in first_state["tasks"])
        for task in first_state["tasks"]:
            assert len(task["assigned_to"]) <= task["required_drones"] or task["status"] == "completed"
            if task["claim_status"] == "claimed":
                assert len(task["claims"]) == len(task["assigned_to"])
                assert len({claim["drone_id"] for claim in task["claims"]}) == len(task["claims"])

        first_comparable = {key: value for key, value in first_state.items() if key != "run_id"}
        second_comparable = {key: value for key, value in second_state.items() if key != "run_id"}
        assert first_comparable == second_comparable

    assert first_state["completed_tasks"]


def test_coverage_counts_only_traversable_visited_cells() -> None:
    drones = (
        _drone("D1", 0, 0),
        _drone("D2", 0, 1),
        _drone("D3", 0, 2),
        _drone("D4", 1, 2),
        _drone("D5", 2, 2),
        _drone("D6", 2, 1),
    )
    scenario = _small_scenario(
        grid=("...", "...", "..."),
        blocked=frozenset({(2, 0)}),
        drones=drones,
        task_position=(1, 0),
    )
    engine = SimulationEngine(scenario)
    initial_coverage = engine.get_state()["coverage"]

    state = engine.advance()

    assert state["coverage"]["visited_cells"] == initial_coverage["visited_cells"] + 1
    assert state["coverage"]["traversable_cells"] == 8
    assert (2, 0) not in engine.visited_cells
    assert state["coverage"]["percentage"] == pytest.approx(7 / 8 * 100, abs=0.01)


def test_task_is_completed_when_assigned_drones_reach_target() -> None:
    drones = (
        _drone("D1", 0, 0),
        _drone("D2", 0, 1),
        _drone("D3", 0, 2),
        _drone("D4", 1, 2),
        _drone("D5", 2, 2),
        _drone("D6", 2, 1),
    )
    scenario = _small_scenario(
        grid=("...", "...", "..."),
        blocked=frozenset(),
        drones=drones,
        task_position=(0, 0),
    )

    state = SimulationEngine(scenario).advance()

    assert state["completed_tasks"] == ["T1"]
    assert state["tasks"][0]["status"] == "completed"
    assert state["drones"][0]["status"] == "idle"


def test_cooperative_task_travels_to_distinct_work_positions_and_releases_drones() -> None:
    drones = (
        _drone("D1", 0, 0),
        _drone("D2", 6, 0),
        _drone("D3", 0, 6),
        _drone("D4", 6, 6),
        _drone("D5", 3, 0),
        _drone("D6", 3, 6),
    )
    scenario = _small_scenario(
        grid=tuple("......." for _ in range(7)),
        blocked=frozenset(),
        drones=drones,
        task_position=(3, 3),
        required_drones=2,
    )
    engine = SimulationEngine(scenario)
    initial_positions = {
        drone_id: (drone.x, drone.y)
        for drone_id, drone in engine.drones.items()
    }
    state = engine.advance()
    task = engine.tasks["T1"]

    assert len(task.work_positions) == 2
    assert len(set(task.work_positions.values())) == 2
    assert all(engine.is_traversable(position) for position in task.work_positions.values())
    assert all(
        engine._distance(initial_positions[drone_id], position) is not None
        for drone_id, position in task.work_positions.items()
    )
    assert sum(
        initial_positions[drone_id] != position
        for drone_id, position in task.work_positions.items()
    ) == 2
    assert state["tasks"][0]["status"] != "completed"

    for _ in range(20):
        positions = {
            drone_id: (drone.x, drone.y)
            for drone_id, drone in engine.drones.items()
        }
        at_work_positions = all(
            positions[drone_id] == position
            for drone_id, position in task.work_positions.items()
        )
        if not at_work_positions:
            assert task.status != "completed"
        if task.status == "completed":
            break
        state = engine.advance()
        current_positions = [
            (drone["x"], drone["y"])
            for drone in state["drones"]
        ]
        assert len(current_positions) == len(set(current_positions))
        assert all(engine.is_traversable(position) for position in current_positions)
        all_at_work_positions = all(
            (engine.drones[drone_id].x, engine.drones[drone_id].y) == position
            for drone_id, position in task.work_positions.items()
        )
        assert (task.status == "completed") == all_at_work_positions

    assert task.status == "completed"
    assert state["completed_tasks"] == ["T1"]
    assert all(engine.drones[drone_id].task_id is None for drone_id in task.assigned_to)
    assert all(engine.drones[drone_id].status == "idle" for drone_id in task.assigned_to)


def test_real_destination_conflict_waits_then_yields_and_completes_tasks() -> None:
    drones = (
        _drone("D1", 1, 1),
        _drone("D2", 3, 1),
        _drone("D3", 5, 0),
        _drone("D4", 5, 1),
        _drone("D5", 5, 2),
        _drone("D6", 5, 3),
    )
    tasks = (
        TaskDefinition("T1", "search", 2, 1, 2, 1, 100),
        TaskDefinition("T2", "search", 2, 3, 1, 1, 100),
    )
    scenario = _small_scenario(
        grid=("#####.", "#...#.", "##.##.", "##.##.", "######"),
        blocked=frozenset(
            (x, y)
            for y, row in enumerate(("#####.", "#...#.", "##.##.", "##.##.", "######"))
            for x, cell in enumerate(row)
            if cell == "#"
        ),
        drones=drones,
        task_position=(2, 1),
        tasks=tasks,
    )
    engine = SimulationEngine(scenario)
    for drone_id, task_id, goal in (
        ("D1", "T1", (2, 1)),
        ("D2", "T2", (2, 3)),
    ):
        drone = engine.drones[drone_id]
        task = engine.tasks[task_id]
        drone.task_id = task_id
        drone.status = "moving"
        task.status = "assigned"
        task.assigned_to.append(drone_id)
        task.work_positions[drone_id] = goal

    first_state = engine.advance()
    first_positions = {
        drone_id: (drone.x, drone.y)
        for drone_id, drone in engine.drones.items()
    }
    assert first_positions["D2"] == (3, 1)
    assert engine.tasks["T1"].status == "completed"
    assert engine.tasks["T2"].status == "blocked"
    assert engine.drones["D1"].task_id is None
    assert engine.drones["D2"].task_id == "T2"
    assert engine.tasks["T2"].assigned_to == ["D2"]
    assert engine.tasks["T2"].work_positions == {"D2": (2, 3)}
    assert len({
        (drone["x"], drone["y"])
        for drone in first_state["drones"]
    }) == 6
    assert all(engine.is_traversable(position) for position in first_positions.values())

    state = engine.advance()
    assert (engine.drones["D2"].x, engine.drones["D2"].y) == (2, 1)
    assert (engine.drones["D1"].x, engine.drones["D1"].y) == (1, 1)
    assert engine.drones["D2"].task_id == "T2"
    assert engine.tasks["T2"].status == "in_progress"
    assert engine.tasks["T2"].work_positions == {"D2": (2, 3)}

    for _ in range(5):
        if "T2" in state["completed_tasks"]:
            break
        state = engine.advance()

    assert set(state["completed_tasks"]) == {"T1", "T2"}
    assert engine.drones["D2"].task_id is None
    assert engine.drones["D2"].status == "idle"


def test_stationary_blocker_yields_in_corridor_without_oscillation() -> None:
    rows = ("......", "#.####", "######", "......")
    drones = (
        _drone("D1", 0, 0),
        _drone("D2", 1, 0),
        _drone("D3", 0, 3),
        _drone("D4", 1, 3),
        _drone("D5", 2, 3),
        _drone("D6", 3, 3),
    )
    tasks = (
        TaskDefinition("T1", "search", 1, 0, 2, 1, 100),
        TaskDefinition("T2", "search", 5, 0, 1, 1, 100),
    )
    scenario = _small_scenario(
        grid=rows,
        blocked=frozenset(
            (x, y)
            for y, row in enumerate(rows)
            for x, cell in enumerate(row)
            if cell == "#"
        ),
        drones=drones,
        task_position=(1, 0),
        tasks=tasks,
    )
    engine = SimulationEngine(scenario)

    first = engine.advance()
    assert "T1" in first["completed_tasks"]
    assert engine.drones["D2"].task_id is None
    assert (engine.drones["D2"].x, engine.drones["D2"].y) == (1, 0)
    assert engine.drones["D1"].task_id == "T2"

    states = [engine.get_state()]
    for _ in range(25):
        states.append(engine.advance())
        positions = [(drone["x"], drone["y"]) for drone in states[-1]["drones"]]
        assert len(positions) == len(set(positions))
        assert all(engine.is_traversable(position) for position in positions)
        task_owners = [
            drone_id
            for task in states[-1]["tasks"]
            if task["status"] in {"assigned", "in_progress", "blocked"}
            for drone_id in task["assigned_to"]
        ]
        assert len(task_owners) == len(set(task_owners))
        assert all(
            engine.drones[drone_id].task_id == task["task_id"]
            for task in states[-1]["tasks"]
            if task["status"] in {"assigned", "in_progress", "blocked"}
            for drone_id in task["assigned_to"]
        )
    assert states[-1]["tasks"][1]["status"] == "completed"
    assert states[-1]["completed_tasks"] == ["T1", "T2"]
    assert (states[2]["drones"][0]["x"], states[2]["drones"][0]["y"]) == (2, 0)
    assert (states[2]["drones"][1]["x"], states[2]["drones"][1]["y"]) == (1, 1)
    assert (engine.drones["D2"].x, engine.drones["D2"].y) == (1, 1)

    repeated = SimulationEngine(scenario)
    repeated_states = [repeated.advance()]
    for _ in range(25):
        repeated_states.append(repeated.advance())
    normalize = lambda state: {
        key: value for key, value in state.items() if key != "run_id"
    }
    assert [normalize(state) for state in repeated_states] == [
        normalize(state) for state in states
    ]


def test_unreachable_pending_task_is_reported_as_blocked() -> None:
    rows = ("......", "######", "##....")
    drones = (
        _drone("D1", 0, 0),
        _drone("D2", 1, 0),
        _drone("D3", 2, 0),
        _drone("D4", 3, 0),
        _drone("D5", 4, 0),
        _drone("D6", 5, 0),
    )
    scenario = _small_scenario(
        grid=rows,
        blocked=frozenset(
            (x, y)
            for y, row in enumerate(rows)
            for x, cell in enumerate(row)
            if cell == "#"
        ),
        drones=drones,
        task_position=(2, 2),
    )
    state = SimulationEngine(scenario).advance()

    assert state["tasks"][0]["status"] == "blocked"
    assert state["tasks"][0]["assigned_to"] == []
    assert state["completed_tasks"] == []


def test_blocked_restricted_cells_and_grid_boundaries_are_respected() -> None:
    drones = (
        _drone("D1", 0, 0),
        _drone("D2", 1, 0),
        _drone("D3", 0, 2),
        _drone("D4", 1, 2),
        _drone("D5", 2, 2),
        _drone("D6", 2, 1),
    )
    scenario = _small_scenario(
        grid=("..#", "...", "..."),
        blocked=frozenset({(2, 0)}),
        restricted=frozenset({(0, 1)}),
        drones=drones,
        task_position=(1, 1),
    )
    engine = SimulationEngine(scenario)

    for _ in range(20):
        state = engine.advance()
        for drone in state["drones"]:
            position = (drone["x"], drone["y"])
            assert 0 <= position[0] < scenario.width
            assert 0 <= position[1] < scenario.height
            assert engine.is_traversable(position)
    assert (engine.drones["D1"].x, engine.drones["D1"].y) == (0, 0)


def test_same_destination_conflict_uses_rotating_priority() -> None:
    drones = [
        _drone("D1", 0, 1),
        _drone("D2", 2, 1),
        _drone("D3", 0, 0),
        _drone("D4", 1, 0),
        _drone("D5", 2, 0),
        _drone("D6", 3, 3),
    ]
    engine = SimulationEngine(
        _small_scenario(
            grid=("....", "....", "....", "...."),
            blocked=frozenset(),
            drones=tuple(drones),
            task_position=(3, 2),
        )
    )
    destination = (1, 1)
    options = {
        drone.drone_id: ((drone.x, drone.y),)
        for drone in drones
    }
    options["D1"] = ((0, 1), destination)
    options["D2"] = ((2, 1), destination)

    first = engine._resolve_moves(drones, options)
    engine._movement_priority_offset = 1
    second = engine._resolve_moves(drones, options)

    assert first["D1"] == destination
    assert first["D2"] == (2, 1)
    assert second["D2"] == destination
    assert second["D1"] == (0, 1)
    assert len(set(first.values())) == len(drones)
    assert len(set(second.values())) == len(drones)


def test_head_on_swap_is_rejected() -> None:
    drones = [
        _drone("D1", 0, 0),
        _drone("D2", 1, 0),
        _drone("D3", 0, 2),
        _drone("D4", 1, 2),
        _drone("D5", 2, 2),
        _drone("D6", 3, 2),
    ]
    engine = SimulationEngine(
        _small_scenario(
            grid=("....", "....", "...."),
            blocked=frozenset(),
            drones=tuple(drones),
            task_position=(3, 1),
        )
    )
    options = {
        drone.drone_id: ((drone.x, drone.y),)
        for drone in drones
    }
    options["D1"] = ((0, 0), (1, 0))
    options["D2"] = ((1, 0), (0, 0))

    result = engine._resolve_moves(drones, options)

    assert result["D1"] == (0, 0)
    assert result["D2"] == (1, 0)


def test_four_drone_movement_cycle_is_rejected() -> None:
    drones = [
        _drone("D1", 0, 0),
        _drone("D2", 1, 0),
        _drone("D3", 1, 1),
        _drone("D4", 0, 1),
        _drone("D5", 2, 0),
        _drone("D6", 2, 2),
    ]
    engine = SimulationEngine(
        _small_scenario(
            grid=("...", "...", "..."),
            blocked=frozenset(),
            drones=tuple(drones),
            task_position=(2, 1),
        )
    )
    options = {
        drone.drone_id: ((drone.x, drone.y),)
        for drone in drones
    }
    options["D1"] = ((0, 0), (1, 0))
    options["D2"] = ((1, 0), (1, 1))
    options["D3"] = ((1, 1), (0, 1))
    options["D4"] = ((0, 1), (0, 0))

    result = engine._resolve_moves(drones, options)

    assert all(result[drone.drone_id] == (drone.x, drone.y) for drone in drones)
    assert len(set(result.values())) == len(drones)


def test_invalid_tick_count_is_rejected(scenarios) -> None:
    engine = SimulationEngine(scenarios[0])

    for ticks in (0, -1, True, 1001):
        with pytest.raises(ValueError):
            engine.advance(ticks)


def test_candidate_detections_remain_unverified_and_hide_ground_truth(scenarios) -> None:
    state = SimulationEngine(scenarios[0]).get_state()

    assert state["candidate_detections"]
    assert all(
        candidate["verification_status"] == "unverified"
        for candidate in state["candidate_detections"]
    )
    assert all("ground_truth" not in candidate for candidate in state["candidate_detections"])


def test_ticks_are_deterministic_for_the_same_real_scenario(scenarios) -> None:
    first = SimulationEngine(scenarios[1])
    second = SimulationEngine(scenarios[1])

    first_state = first.advance(8)
    second_state = second.advance(8)

    first_state.pop("run_id")
    second_state.pop("run_id")
    assert first_state == second_state


def test_failure_event_lifecycle_uses_tick_time_and_recovery_metadata(scenarios) -> None:
    scenario = next(item for item in scenarios if item.scenario_id == "earthquake")
    schedule = ScenarioLoader(DATA_DIR).load_failure_scenario("demo_core", "earthquake")
    engine = SimulationEngine(scenario)
    initial = engine.install_failure_schedule(schedule)

    assert initial["failure_scenario_id"] == "demo_core"
    assert initial["failure_test_matrix_entry"]["scenario_id"] == "earthquake"
    assert [event["status"] for event in initial["failure_events"]] == [
        "scheduled",
        "scheduled",
    ]

    before_start = engine.advance(59)
    assert before_start["tick"] == 59
    assert before_start["failure_events"][0]["status"] == "scheduled"

    at_start = engine.advance()
    assert at_start["tick"] == 60
    assert at_start["failure_events"][0]["status"] == "active"

    at_recovery = engine.advance(90)
    assert at_recovery["tick"] == 150
    assert at_recovery["failure_events"][0]["status"] == "recovering"

    after_recovery = engine.advance(7)
    assert after_recovery["failure_events"][0]["status"] == "resolved"
    assert after_recovery["failure_events"][1]["status"] == "scheduled"

    partition_start = engine.advance(23)
    assert partition_start["tick"] == 180
    assert partition_start["failure_events"][1]["status"] == "active"

    partition_end = engine.advance(60)
    assert partition_end["tick"] == 240
    assert partition_end["failure_events"][1]["status"] == "recovering"

    partition_resolved = engine.advance(10)
    assert partition_resolved["tick"] == 250
    assert partition_resolved["failure_events"][1]["status"] == "resolved"


def test_unresponsive_drone_stays_disconnected_for_null_end(scenarios) -> None:
    scenario = next(item for item in scenarios if item.scenario_id == "earthquake")
    schedule = ScenarioLoader(DATA_DIR).load_failure_scenario("drone_failure", "earthquake")
    engine = SimulationEngine(scenario)
    engine.install_failure_schedule(schedule)

    before_start = engine.advance(74)
    drone_before = next(drone for drone in before_start["drones"] if drone["drone_id"] == "D3")
    assert drone_before["status"] != "disconnected"
    assert before_start["failure_events"][0]["status"] == "scheduled"

    at_start = engine.advance()
    drone_at_start = next(drone for drone in at_start["drones"] if drone["drone_id"] == "D3")
    assert drone_at_start["status"] == "disconnected"
    assert at_start["failure_events"][0]["status"] == "active"

    after_more_ticks = engine.advance(20)
    drone_after = next(drone for drone in after_more_ticks["drones"] if drone["drone_id"] == "D3")
    assert drone_after["status"] == "disconnected"
    assert after_more_ticks["failure_events"][0]["status"] == "active"


def test_failure_schedule_must_be_installed_before_advancing(scenarios) -> None:
    scenario = next(item for item in scenarios if item.scenario_id == "earthquake")
    schedule = ScenarioLoader(DATA_DIR).load_failure_scenario("demo_core", "earthquake")
    engine = SimulationEngine(scenario)
    engine.advance()

    with pytest.raises(FailureScheduleConflict):
        engine.install_failure_schedule(schedule)

    state = engine.get_state()
    assert state["tick"] == 1
    assert state["failure_scenario_id"] is None
    assert state["failure_events"] == []


def test_loader_rejects_invalid_grid_rows(tmp_path: Path) -> None:
    for filename in (
        "disaster_scenarios.json",
        "drone_config.json",
        "failure_scenarios.json",
    ):
        (tmp_path / filename).write_bytes((DATA_DIR / filename).read_bytes())
    scenario_path = tmp_path / "disaster_scenarios.json"
    content = scenario_path.read_text(encoding="utf-8")
    content = content.replace("." * 20, "." * 19, 1)
    scenario_path.write_text(content, encoding="utf-8")

    with pytest.raises(DatasetError, match="invalid initial cell grid"):
        ScenarioLoader(tmp_path).load_all()


def _drone(drone_id: str, x: int, y: int):
    return DroneDefinition(
        drone_id=drone_id,
        drone_type="scout",
        x=x,
        y=y,
        initial_status="idle",
    )


def _small_scenario(
    grid: tuple[str, ...],
    blocked: frozenset[tuple[int, int]],
    drones,
    task_position: tuple[int, int],
    required_drones: int = 1,
    restricted: frozenset[tuple[int, int]] = frozenset(),
    tasks: tuple[TaskDefinition, ...] | None = None,
) -> ScenarioDefinition:
    task = TaskDefinition(
        task_id="T1",
        task_type="search",
        x=task_position[0],
        y=task_position[1],
        priority=1,
        required_drones=required_drones,
        deadline_s=100,
    )
    return ScenarioDefinition(
        scenario_id="test",
        name="Test",
        disaster_type="test",
        seed=1,
        width=len(grid[0]),
        height=len(grid),
        grid=grid,
        blocked_cells=blocked,
        restricted_cells=restricted,
        tasks=tasks if tasks is not None else (task,),
        drones=drones,
        candidate_detections=(),
    )

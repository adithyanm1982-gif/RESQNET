from pathlib import Path

import pytest

from app.simulation.engine import SimulationEngine
from app.simulation.loader import (
    DatasetError,
    DroneDefinition,
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

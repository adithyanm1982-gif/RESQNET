from fastapi.testclient import TestClient

from app.api.routes import simulations
from app.main import app
from app.simulation.loader import IncompatibleFailureScenario

client = TestClient(app)


def _custom_controller_plan(start_tick: int = 2, restore_tick: int = 4) -> dict:
    return {
        "custom_plan": {
            "events": [
                {
                    "type": "controller_outage",
                    "start_tick": start_tick,
                    "restore_tick": restore_tick,
                    "reconnection": {
                        "detect_timeout_ticks": 1,
                        "reconnect_delay_ticks": 1,
                        "resync_time_ticks": 1,
                    },
                }
            ]
        }
    }


def test_list_scenarios_returns_real_dataset() -> None:
    response = client.get("/api/simulations/scenarios")

    assert response.status_code == 200
    assert {scenario["scenario_id"] for scenario in response.json()} == {
        "earthquake",
        "cyclone",
        "flood",
    }


def test_frontend_dataset_endpoints_and_production_cors() -> None:
    dataset = client.get("/api/datasets/drone-config")
    assert dataset.status_code == 200
    assert isinstance(dataset.json()["fleets"], list)

    preflight = client.options(
        "/api/health",
        headers={
            "Origin": "https://resqnet-eight-psi.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == (
        "https://resqnet-eight-psi.vercel.app"
    )
    assert preflight.headers["access-control-allow-credentials"] == "true"


def test_create_advance_and_retrieve_run() -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake"},
    )

    assert created.status_code == 201
    initial_state = created.json()
    assert len(initial_state["drones"]) == 6
    assert initial_state["tick"] == 0

    advanced = client.post(
        f"/api/simulations/{initial_state['run_id']}/ticks",
        json={"ticks": 1},
    )
    retrieved = client.get(f"/api/simulations/{initial_state['run_id']}")

    assert advanced.status_code == 200
    assert advanced.json()["tick"] == 1
    assert retrieved.json()["tick"] == 1


def test_create_simulation_passes_mode_to_engine_and_returns_it() -> None:
    response = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake", "mode": "hybrid"},
    )

    assert response.status_code == 201
    run_id = response.json()["run_id"]
    assert response.json()["coordination_mode"] == "hybrid"
    assert simulations.runs._get(run_id).coordination_mode.value == "hybrid"


def test_create_simulation_rejects_unknown_coordination_mode() -> None:
    response = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake", "mode": "unsupported"},
    )

    assert response.status_code == 422
    assert "centralized" in response.json()["detail"][0]["ctx"]["expected"]


def test_create_simulation_defaults_to_centralized_mode() -> None:
    response = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake"},
    )

    assert response.status_code == 201
    assert response.json()["coordination_mode"] == "centralized"


def test_decentralized_route_advances_and_returns_task_claims() -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake", "mode": "decentralized"},
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    advanced = client.post(
        f"/api/simulations/{run_id}/ticks",
        json={"ticks": 10},
    )
    state = client.get(f"/api/simulations/{run_id}").json()

    assert advanced.status_code == 200
    assert state["coordination_mode"] == "decentralized"
    assert state["tick"] == 10
    assert any(task["claims"] for task in state["tasks"])
    assert all(
        len(task["assigned_to"]) <= task["required_drones"]
        or task["status"] == "completed"
        for task in state["tasks"]
    )


def test_hybrid_route_exposes_outage_reconciliation_and_recovery() -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake", "mode": "hybrid"},
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]
    installed = client.post(
        f"/api/simulations/{run_id}/failures",
        json={"failure_scenario_id": "controller_failure"},
    )
    assert installed.status_code == 200

    outage = client.post(
        f"/api/simulations/{run_id}/ticks",
        json={"ticks": 60},
    )
    assert outage.status_code == 200
    assert outage.json()["operational_strategy"] == "decentralized_fallback"
    assert outage.json()["controller_available"] is False
    assert outage.json()["failure_events"][0]["status"] == "active"
    assert any(task["claims"] for task in outage.json()["tasks"])

    recovery = client.post(
        f"/api/simulations/{run_id}/ticks",
        json={"ticks": 93},
    )
    assert recovery.status_code == 200
    assert recovery.json()["tick"] == 153
    assert recovery.json()["operational_strategy"] == "reconciliation"
    assert recovery.json()["controller_reachable"] is True
    assert recovery.json()["reconciliation_history"]

    recovered = client.post(
        f"/api/simulations/{run_id}/ticks",
        json={"ticks": 4},
    )
    assert recovered.status_code == 200
    assert recovered.json()["tick"] == 157
    assert recovered.json()["operational_strategy"] == "centralized_allocation"
    assert recovered.json()["failure_events"][0]["status"] == "resolved"


def test_unknown_scenario_and_run_are_not_found() -> None:
    assert client.post(
        "/api/simulations",
        json={"scenario_id": "not-a-scenario"},
    ).status_code == 404
    assert client.get("/api/simulations/not-a-run").status_code == 404


def test_invalid_tick_request_is_rejected() -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "flood"},
    )

    response = client.post(
        f"/api/simulations/{created.json()['run_id']}/ticks",
        json={"ticks": 0},
    )

    assert response.status_code == 422


def test_install_failure_schedule_and_advance_lifecycle() -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake"},
    )
    run_id = created.json()["run_id"]

    installed = client.post(
        f"/api/simulations/{run_id}/failures",
        json={"failure_scenario_id": "demo_core"},
    )

    assert installed.status_code == 200
    assert installed.json()["failure_scenario_id"] == "demo_core"
    assert installed.json()["failure_test_matrix_entry"]["scenario_id"] == "earthquake"
    assert [event["status"] for event in installed.json()["failure_events"]] == [
        "scheduled",
        "scheduled",
    ]
    assert client.get(f"/api/simulations/{run_id}").json()["failure_scenario_id"] == "demo_core"

    advanced = client.post(
        f"/api/simulations/{run_id}/ticks",
        json={"ticks": 60},
    )
    assert advanced.status_code == 200
    assert advanced.json()["tick"] == 60
    assert advanced.json()["failure_events"][0]["status"] == "active"


def test_failure_schedule_validation_does_not_change_run_state() -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "cyclone"},
    )
    run_id = created.json()["run_id"]

    unknown = client.post(
        f"/api/simulations/{run_id}/failures",
        json={"failure_scenario_id": "not-a-failure"},
    )
    assert unknown.status_code == 404
    assert client.get(f"/api/simulations/{run_id}").json()["failure_scenario_id"] is None

    extra_field = client.post(
        f"/api/simulations/{run_id}/failures",
        json={"failure_scenario_id": "demo_core", "type": "controller_outage"},
    )
    assert extra_field.status_code == 422
    assert client.get(f"/api/simulations/{run_id}").json()["failure_scenario_id"] is None

    missing_run = client.post(
        "/api/simulations/not-a-run/failures",
        json={"failure_scenario_id": "demo_core"},
    )
    assert missing_run.status_code == 404

    advanced = client.post(
        f"/api/simulations/{run_id}/ticks",
        json={"ticks": 1},
    )
    assert advanced.status_code == 200
    too_late = client.post(
        f"/api/simulations/{run_id}/failures",
        json={"failure_scenario_id": "demo_core"},
    )
    assert too_late.status_code == 409
    assert client.get(f"/api/simulations/{run_id}").json()["failure_scenario_id"] is None


def test_failure_schedule_request_requires_identifier() -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "flood"},
    )
    response = client.post(
        f"/api/simulations/{created.json()['run_id']}/failures",
        json={},
    )
    assert response.status_code == 422


def test_incompatible_failure_schedule_does_not_change_run_state(monkeypatch) -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "flood"},
    )
    run_id = created.json()["run_id"]

    def reject_pair(failure_scenario_id: str, scenario_id: str):
        raise IncompatibleFailureScenario("No matrix pair.")

    monkeypatch.setattr(simulations.loader, "load_failure_scenario", reject_pair)
    response = client.post(
        f"/api/simulations/{run_id}/failures",
        json={"failure_scenario_id": "demo_core"},
    )

    assert response.status_code == 422
    state = client.get(f"/api/simulations/{run_id}").json()
    assert state["failure_scenario_id"] is None
    assert state["failure_events"] == []


def test_custom_plan_is_installed_on_run_and_restores_hybrid_controller() -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake", "mode": "hybrid"},
    )
    run_id = created.json()["run_id"]

    installed = client.post(
        f"/api/simulations/{run_id}/failures",
        json=_custom_controller_plan(),
    )

    assert installed.status_code == 200
    assert installed.json()["failure_schedule_type"] == "custom"
    assert installed.json()["failure_scenario_id"] is None
    assert installed.json()["failure_test_matrix_entry"] is None
    assert installed.json()["tick"] == 0
    assert installed.json()["failure_events"][0]["start_s"] == 4
    assert installed.json()["failure_events"][0]["end_s"] == 8
    assert installed.json()["failure_events"][0]["status"] == "scheduled"

    active = client.post(f"/api/simulations/{run_id}/ticks", json={"ticks": 2})
    assert active.status_code == 200
    assert active.json()["failure_events"][0]["status"] == "active"
    assert active.json()["operational_strategy"] == "decentralized_fallback"
    assert active.json()["controller_available"] is False

    restoring = client.post(f"/api/simulations/{run_id}/ticks", json={"ticks": 2})
    assert restoring.json()["failure_events"][0]["status"] == "recovering"

    resync = client.post(f"/api/simulations/{run_id}/ticks", json={"ticks": 1})
    assert resync.json()["operational_strategy"] == "reconciliation"
    assert resync.json()["reconciliation_history"]

    restored = client.post(f"/api/simulations/{run_id}/ticks", json={"ticks": 1})
    assert restored.json()["failure_events"][0]["status"] == "resolved"
    assert restored.json()["operational_strategy"] == "centralized_allocation"


def test_custom_plan_does_not_leak_between_runs_and_compares_across_modes() -> None:
    plans = []
    runs = []
    for mode in ("centralized", "decentralized", "hybrid"):
        created = client.post(
            "/api/simulations",
            json={"scenario_id": "earthquake", "mode": mode},
        )
        assert created.status_code == 201
        run_id = created.json()["run_id"]
        runs.append(run_id)
        installed = client.post(
            f"/api/simulations/{run_id}/failures",
            json=_custom_controller_plan(),
        )
        assert installed.status_code == 200
        plans.append(installed.json()["failure_events"])

    assert plans[0] == plans[1] == plans[2]
    untouched = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake"},
    ).json()
    assert untouched["failure_schedule_type"] is None
    assert untouched["failure_events"] == []
    assert all(client.get(f"/api/simulations/{run_id}").json()["tick"] == 0 for run_id in runs)


def test_custom_unresponsive_drone_uses_existing_disconnected_status() -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake", "mode": "decentralized"},
    )
    run_id = created.json()["run_id"]
    installed = client.post(
        f"/api/simulations/{run_id}/failures",
        json={"custom_plan": {"events": [{
            "type": "drone_unresponsive",
            "start_tick": 1,
            "restore_tick": None,
            "drone_id": "D3",
        }]}},
    )
    assert installed.status_code == 200
    assert installed.json()["failure_events"][0]["end_s"] is None

    advanced = client.post(f"/api/simulations/{run_id}/ticks", json={"ticks": 1})
    drone = next(item for item in advanced.json()["drones"] if item["drone_id"] == "D3")
    assert drone["status"] == "disconnected"

    recovering_run = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake", "mode": "decentralized"},
    ).json()["run_id"]
    recovering_install = client.post(
        f"/api/simulations/{recovering_run}/failures",
        json={"custom_plan": {"events": [{
            "type": "drone_unresponsive",
            "start_tick": 1,
            "restore_tick": 3,
            "drone_id": "D3",
        }]}},
    )
    assert recovering_install.status_code == 200
    client.post(f"/api/simulations/{recovering_run}/ticks", json={"ticks": 1})
    restored = client.post(f"/api/simulations/{recovering_run}/ticks", json={"ticks": 2})
    restored_drone = next(item for item in restored.json()["drones"] if item["drone_id"] == "D3")
    assert restored.json()["failure_events"][0]["status"] == "resolved"
    assert restored_drone["status"] != "disconnected"


def test_custom_network_partition_uses_declared_groups_for_hybrid_fallback() -> None:
    created = client.post(
        "/api/simulations",
        json={"scenario_id": "earthquake", "mode": "hybrid"},
    )
    run_id = created.json()["run_id"]
    installed = client.post(
        f"/api/simulations/{run_id}/failures",
        json={"custom_plan": {"events": [{
            "type": "network_partition",
            "start_tick": 1,
            "restore_tick": 3,
            "groups": [
                {"group_id": "controller", "drone_ids": ["D1", "D2", "D3"], "has_controller_link": True},
                {"group_id": "local", "drone_ids": ["D4", "D5", "D6"], "has_controller_link": False},
            ],
            "reconnection": {
                "detect_timeout_ticks": 1,
                "reconnect_delay_ticks": 1,
                "resync_time_ticks": 1,
            },
        }]}},
    )
    assert installed.status_code == 200

    active = client.post(f"/api/simulations/{run_id}/ticks", json={"ticks": 1})
    state = active.json()
    assert state["failure_events"][0]["status"] == "active"
    assert state["operational_strategy"] == "decentralized_fallback"
    assert state["partition_state"][0]["groups"][1]["drone_ids"] == ["D4", "D5", "D6"]


def test_custom_failure_plan_rejects_unsupported_invalid_and_conflicting_events() -> None:
    created = client.post("/api/simulations", json={"scenario_id": "earthquake"})
    run_id = created.json()["run_id"]
    invalid_requests = [
        {"custom_plan": {"events": [{"type": "packet_loss", "start_tick": 1, "restore_tick": 2}]}},
        {"custom_plan": {"events": [{"type": "controller_outage", "start_tick": 2, "restore_tick": 2, "reconnection": {"detect_timeout_ticks": 1, "reconnect_delay_ticks": 1, "resync_time_ticks": 1}}]}},
        {"custom_plan": {"events": [{"type": "drone_unresponsive", "start_tick": 1, "restore_tick": 2, "drone_id": "D99"}]}},
        {"custom_plan": {"events": [{"type": "network_partition", "start_tick": 1, "restore_tick": 4, "groups": [{"group_id": "A", "drone_ids": ["D1", "D2"], "has_controller_link": True}, {"group_id": "B", "drone_ids": ["D3", "D4", "D5"], "has_controller_link": False}], "reconnection": {"detect_timeout_ticks": 1, "reconnect_delay_ticks": 1, "resync_time_ticks": 1}}]}},
        {"custom_plan": {"events": [
            {"type": "controller_outage", "start_tick": 2, "restore_tick": 8, "reconnection": {"detect_timeout_ticks": 1, "reconnect_delay_ticks": 1, "resync_time_ticks": 1}},
            {"type": "controller_outage", "start_tick": 7, "restore_tick": 10, "reconnection": {"detect_timeout_ticks": 1, "reconnect_delay_ticks": 1, "resync_time_ticks": 1}},
        ]}},
    ]
    for payload in invalid_requests:
        response = client.post(f"/api/simulations/{run_id}/failures", json=payload)
        assert response.status_code == 422
        assert client.get(f"/api/simulations/{run_id}").json()["failure_schedule_type"] is None


def test_custom_plan_rejects_too_many_events_and_oversized_payload() -> None:
    created = client.post("/api/simulations", json={"scenario_id": "earthquake"})
    run_id = created.json()["run_id"]
    event = {
        "type": "drone_unresponsive",
        "start_tick": 1,
        "restore_tick": None,
        "drone_id": "D1",
    }
    too_many = client.post(
        f"/api/simulations/{run_id}/failures",
        json={"custom_plan": {"events": [event] * 11}},
    )
    assert too_many.status_code == 422

    body = b" " * 65_537 + (
        b'{"custom_plan":{"events":[{"type":"drone_unresponsive",'
        b'"start_tick":1,"restore_tick":null,"drone_id":"D1"}]}}'
    )
    oversized = client.post(
        f"/api/simulations/{run_id}/failures",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert oversized.status_code == 413

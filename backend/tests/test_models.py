from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models import Base, Scenario, SimulationRun


def test_initial_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {"scenarios", "simulation_runs"}


def test_scenario_metadata_has_unique_id_jsonb_and_relationship() -> None:
    scenario_table = Scenario.__table__

    assert scenario_table.c.id.primary_key
    assert scenario_table.c.scenario_id.unique
    assert isinstance(scenario_table.c.configuration.type, JSONB)
    assert scenario_table.c.created_at.server_default is not None
    assert "ix_scenarios_disaster_type" in {
        index.name for index in scenario_table.indexes
    }
    assert Scenario.simulation_runs.property.back_populates == "scenario"


def test_simulation_run_metadata_has_constraints_and_relationship() -> None:
    run_table = SimulationRun.__table__
    coordination_check = next(
        constraint
        for constraint in run_table.constraints
        if isinstance(constraint, CheckConstraint)
    )

    assert run_table.c.id.primary_key
    assert run_table.c.run_id.unique
    scenario_foreign_key = next(iter(run_table.c.scenario_id.foreign_keys))
    assert scenario_foreign_key.target_fullname == "scenarios.id"
    assert "centralized" in str(coordination_check.sqltext)
    assert "decentralized" in str(coordination_check.sqltext)
    assert "hybrid" in str(coordination_check.sqltext)
    assert run_table.c.random_seed.nullable is False
    assert run_table.c.started_at.nullable is True
    assert run_table.c.completed_at.nullable is True
    assert SimulationRun.scenario.property.back_populates == "simulation_runs"

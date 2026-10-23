from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.scenario import Scenario


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    __table_args__ = (
        CheckConstraint(
            "coordination_mode IN ('centralized', 'decentralized', 'hybrid')",
            name="ck_simulation_runs_coordination_mode",
        ),
        Index("ix_simulation_runs_scenario_id", "scenario_id"),
        Index("ix_simulation_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenarios.id"),
        nullable=False,
    )
    coordination_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    scenario: Mapped[Scenario] = relationship(back_populates="simulation_runs")

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.simulation_run import SimulationRun


class Scenario(Base):
    __tablename__ = "scenarios"
    __table_args__ = (Index("ix_scenarios_disaster_type", "disaster_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    disaster_type: Mapped[str] = mapped_column(String(100), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    simulation_runs: Mapped[list["SimulationRun"]] = relationship(
        back_populates="scenario",
    )

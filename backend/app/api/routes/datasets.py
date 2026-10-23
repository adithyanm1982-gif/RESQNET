"""Read-only access to the three dataset JSON files, so the frontend gets ALL its data from this backend.
The files live in the repository root (same folder the simulation loader reads)."""
import json

from fastapi import APIRouter, HTTPException, status

from app.simulation.loader import PROJECT_ROOT

router = APIRouter()
FILES = {
    "disaster-scenarios": "disaster_scenarios.json",
    "drone-config": "drone_config.json",
    "failure-scenarios": "failure_scenarios.json",
}


@router.get("/{name}")
def get_dataset(name: str):
    filename = FILES.get(name)
    if filename is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown dataset.")
    try:
        with (PROJECT_ROOT / filename).open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dataset file is missing or invalid.",
        ) from None

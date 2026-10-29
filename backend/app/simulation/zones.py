
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ZoneBounds:
    """Inclusive rectangular boundaries for one drone's operating zone."""

    drone_id: str
    zone_number: int
    x_min: int
    x_max: int
    y_min: int
    y_max: int

    def contains(self, x: int, y: int) -> bool:
        """Return True when a grid cell belongs to this zone."""
        return (
            self.x_min <= x <= self.x_max
            and self.y_min <= y <= self.y_max
        )


def drone_number(drone_id: str) -> int | None:
    """
    Extract a drone number from IDs such as:
    D1, D2, DRONE_01, drone-02, or DRONE 03.
    """
    match = re.search(r"(\d+)", drone_id)
    if match is None:
        return None

    number = int(match.group(1))
    return number if 1 <= number <= 6 else None


def get_drone_zone(
    drone_id: str,
    grid_width: int = 20,
    grid_height: int = 20,
) -> ZoneBounds | None:
    """
    Divide a grid into six fixed zones.

    D1, D2, D3: upper row, left to right.
    D4, D5, D6: lower row, left to right.

    The boundaries are calculated from the actual grid dimensions,
    so scenarios do not have to be exactly 20 x 20.
    """
    if grid_width < 3 or grid_height < 2:
        raise ValueError(
            "Grid must be at least 3 cells wide and 2 cells high."
        )

    number = drone_number(drone_id)
    if number is None:
        return None

    # D1-D3 occupy the upper row; D4-D6 occupy the lower row.
    zone_index = number - 1
    column = zone_index % 3
    row = zone_index // 3

    # Integer division distributes any remainder across the columns.
    x_min = column * grid_width // 3
    x_max = (column + 1) * grid_width // 3 - 1

    y_min = row * grid_height // 2
    y_max = (row + 1) * grid_height // 2 - 1

    return ZoneBounds(
        drone_id=drone_id,
        zone_number=number,
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
    )


def is_inside_drone_zone(
    drone_id: str,
    x: int,
    y: int,
    grid_width: int = 20,
    grid_height: int = 20,
) -> bool:
    """Check whether a cell is inside the specified drone's zone."""
    zone = get_drone_zone(drone_id, grid_width, grid_height)

    if zone is None:
        return False

    return zone.contains(x, y)


def get_all_drone_zones(
    grid_width: int = 20,
    grid_height: int = 20,
) -> list[dict[str, int | str]]:
    """Return zone boundaries for D1 through D6."""
    zones: list[dict[str, int | str]] = []

    for number in range(1, 7):
        drone_id = f"D{number}"
        zone = get_drone_zone(
            drone_id,
            grid_width,
            grid_height,
        )

        if zone is None:
            continue

        zones.append(
            {
                "drone_id": zone.drone_id,
                "zone_number": zone.zone_number,
                "x_min": zone.x_min,
                "x_max": zone.x_max,
                "y_min": zone.y_min,
                "y_max": zone.y_max,
            }
        )

    return zones

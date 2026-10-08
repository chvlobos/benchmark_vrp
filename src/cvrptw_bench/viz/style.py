"""Shared visual vocabulary for maps, Gantt charts and the report.

Colour encodes *vehicle type* (three categorical slots, fixed order), never the
rank of a route: a small van is always blue, a medium truck always orange, a
large truck always aqua, in every figure of the benchmark. Unserved customers
use the reserved status red. Text and grids stay in neutral ink.
"""

from __future__ import annotations

from cvrptw_bench.core.instance import Instance

# Categorical slots (validated palette, light surface): blue, orange, aqua.
TYPE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]
# Lighter / darker steps of each hue, used to tell neighbouring routes of the same type apart.
TYPE_SHADES = {
    "#2a78d6": ["#2a78d6", "#5598e7", "#184f95"],
    "#eb6834": ["#eb6834", "#f29470", "#b84a1f"],
    "#1baf7a": ["#1baf7a", "#5cc9a0", "#117a54"],
    "#eda100": ["#eda100", "#f4bf4d", "#b07700"],
    "#e87ba4": ["#e87ba4", "#f0a5c1", "#c04f7a"],
    "#4a3aa7": ["#4a3aa7", "#7a6fc7", "#33287a"],
}
UNSERVED_COLOR = "#e34948"  # status: critical
DEPOT_COLOR = "#0b0b0b"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8985"
GRID = "#e6e5e1"
SURFACE = "#fcfcfb"
WAIT_COLOR = "#d9d8d3"
TRAVEL_COLOR = "#9d9c97"


def type_color_map(instance: Instance) -> dict[str, str]:
    """Vehicle type name -> base colour, in the instance's type order."""
    return {t.type: TYPE_COLORS[k % len(TYPE_COLORS)] for k, t in enumerate(instance.vehicle_types)}


def route_shade(base: str, k: int) -> str:
    shades = TYPE_SHADES.get(base, [base])
    return shades[k % len(shades)]


def hhmm(seconds: int | float) -> str:
    s = int(round(seconds))
    h, m = divmod(s // 60, 60)
    return f"{h:02d}:{m:02d}"


def fmt_int(x: int | float) -> str:
    return f"{int(round(x)):,}".replace(",", " ")

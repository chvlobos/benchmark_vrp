"""Maps and x-t (Gantt) plots for evaluated solutions (PLAN.md §8.3)."""

from __future__ import annotations

from pathlib import Path

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.solution import Solution
from cvrptw_bench.viz.gantt import plot_gantt
from cvrptw_bench.viz.map_html import plot_map_html
from cvrptw_bench.viz.map_static import BASEMAPS, DEFAULT_BASEMAP, plot_map


def plot_all(
    instance: Instance,
    solution: Solution,
    out_dir: str | Path,
    basemap: str | bool = DEFAULT_BASEMAP,
    dpi: int = 300,
    html: bool = True,
) -> dict[str, Path]:
    """Write map.png, map.html and gantt.png into out_dir; return their paths.

    ``basemap``: one of :data:`BASEMAPS` ("esri-gray" default, "osm", "esri-street",
    "carto", "none"); True/False are accepted as default/none.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "map_png": plot_map(instance, solution, out / "map.png", basemap=basemap, dpi=dpi),
        "gantt_png": plot_gantt(instance, solution, out / "gantt.png", dpi=dpi),
    }
    if html:
        bm = (
            DEFAULT_BASEMAP
            if basemap is True
            else ("none" if basemap in (False, None) else basemap)
        )
        paths["map_html"] = plot_map_html(instance, solution, out / "map.html", basemap=bm)
    return paths


__all__ = ["BASEMAPS", "DEFAULT_BASEMAP", "plot_all", "plot_gantt", "plot_map", "plot_map_html"]

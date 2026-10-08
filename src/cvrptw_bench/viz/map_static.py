"""Static route map (PNG) with an optional web-tile basemap.

Routes are straight segments between consecutive stops (the instance's own
travel model is great-circle × detour, so drawing roads would be misleading).
Colour = vehicle type; neighbouring routes of the same type alternate three
shades of that hue. Unserved customers are hollow red markers.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from cvrptw_bench.core.instance import Instance  # noqa: E402
from cvrptw_bench.core.solution import Solution  # noqa: E402
from cvrptw_bench.viz.style import (  # noqa: E402
    DEPOT_COLOR,
    GRID,
    INK,
    INK_SECONDARY,
    SURFACE,
    UNSERVED_COLOR,
    fmt_int,
    route_shade,
    type_color_map,
)

log = logging.getLogger(__name__)
TILE_CACHE = ".tile_cache"

# Keyless tile providers, tried in order. CartoDB (the usual light basemap) started
# requiring an API key in 2026 and answers with watermarked tiles instead of an error,
# so it is not in the default chain.
BASEMAPS: dict[str, list[str]] = {
    "esri-gray": ["Esri.WorldGrayCanvas", "OpenStreetMap.Mapnik"],
    "osm": ["OpenStreetMap.Mapnik", "Esri.WorldGrayCanvas"],
    "esri-street": ["Esri.WorldStreetMap", "OpenStreetMap.Mapnik"],
    "carto": ["CartoDB.Positron"],  # needs an API key; kept for people who have one
    "none": [],
}
DEFAULT_BASEMAP = "esri-gray"


def _provider(name: str):
    import contextily as cx

    p = cx.providers
    for part in name.split("."):
        p = p[part]
    return p


def _add_basemap(ax, basemap: str = DEFAULT_BASEMAP, zoom: int | None = None) -> str | None:
    """Draw web tiles under the axes; return the provider used, or None when none worked."""
    if basemap not in BASEMAPS:
        raise ValueError(f"unknown basemap '{basemap}', expected one of {sorted(BASEMAPS)}")
    try:
        import contextily as cx
    except ImportError:  # pragma: no cover
        return None
    cx.set_cache_dir(TILE_CACHE)
    for name in BASEMAPS[basemap]:
        try:
            kwargs = {"crs": "EPSG:4326", "source": _provider(name), "attribution_size": 5}
            if zoom is not None:
                kwargs["zoom"] = zoom
            cx.add_basemap(ax, **kwargs)
            return name
        except Exception as exc:  # noqa: BLE001 - offline, rate-limited, provider down: next one
            log.warning("basemap %s unavailable (%s)", name, type(exc).__name__)
    return None


def _draw_polygon_outline(ax) -> None:
    try:
        from cvrptw_bench.generator.geo import load_polygon

        x, y = load_polygon().exterior.xy
        ax.plot(x, y, color=INK_SECONDARY, lw=0.6, alpha=0.6, zorder=1)
    except Exception:  # noqa: BLE001
        pass


def plot_map(
    instance: Instance,
    solution: Solution,
    path: str | Path,
    basemap: str | bool = DEFAULT_BASEMAP,
    dpi: int = 300,
    title: str | None = None,
) -> Path:
    if basemap is True:
        basemap = DEFAULT_BASEMAP
    if basemap is False or basemap is None:
        basemap = "none"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lat = {c.id: c.lat for c in instance.customers}
    lon = {c.id: c.lon for c in instance.customers}
    demand = {c.id: c.demand for c in instance.customers}
    colors = type_color_map(instance)

    # figure shape follows the extent of the instance (in km), so tall layouts are not padded
    all_lon = [instance.depot.lon, *lon.values()]
    all_lat = [instance.depot.lat, *lat.values()]
    dx = (max(all_lon) - min(all_lon)) * math.cos(math.radians(instance.depot.lat)) + 1e-6
    dy = (max(all_lat) - min(all_lat)) + 1e-6
    ratio = min(max(dy / dx, 0.6), 1.6)
    fig, ax = plt.subplots(figsize=(10, 10 * ratio + 0.6))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    # routes, one shade rotation per vehicle type
    shade_idx: dict[str, int] = {}
    for r in sorted(solution.routes, key=lambda r: r.vehicle_id):
        base = colors[r.vehicle_type]
        k = shade_idx.get(r.vehicle_type, 0)
        shade_idx[r.vehicle_type] = k + 1
        col = route_shade(base, k)
        xs = [instance.depot.lon, *[lon[s.customer] for s in r.stops], instance.depot.lon]
        ys = [instance.depot.lat, *[lat[s.customer] for s in r.stops], instance.depot.lat]
        ax.plot(xs, ys, color=col, lw=1.3, alpha=0.85, zorder=3, solid_capstyle="round")
        ax.scatter(
            xs[1:-1],
            ys[1:-1],
            s=[10 + demand[s.customer] / 25 for s in r.stops],
            color=col,
            edgecolors=SURFACE,
            linewidths=0.5,
            zorder=4,
        )

    if solution.unserved:
        ax.scatter(
            [lon[u.customer] for u in solution.unserved],
            [lat[u.customer] for u in solution.unserved],
            s=[22 + u.demand / 25 for u in solution.unserved],
            facecolors="none",
            edgecolors=UNSERVED_COLOR,
            linewidths=1.4,
            zorder=5,
        )
    ax.scatter(
        [instance.depot.lon],
        [instance.depot.lat],
        marker="s",
        s=90,
        color=DEPOT_COLOR,
        edgecolors=SURFACE,
        linewidths=1.0,
        zorder=6,
    )

    # extent with a margin, aspect corrected for the latitude
    pad_x = (max(all_lon) - min(all_lon)) * 0.06 + 0.005
    pad_y = (max(all_lat) - min(all_lat)) * 0.06 + 0.005
    ax.set_xlim(min(all_lon) - pad_x, max(all_lon) + pad_x)
    ax.set_ylim(min(all_lat) - pad_y, max(all_lat) + pad_y)
    ax.set_aspect(1.0 / math.cos(math.radians(instance.depot.lat)))

    used_provider = _add_basemap(ax, basemap) if basemap != "none" else None
    if used_provider is None:
        _draw_polygon_outline(ax)
        ax.grid(True, color=GRID, lw=0.5)
    ax.tick_params(labelsize=7, colors=INK_SECONDARY)
    for sp in ax.spines.values():
        sp.set_color(GRID)

    # legend: vehicle types (used/available) + unserved + depot
    m = solution.metrics
    handles = []
    for t in instance.vehicle_types:
        used = m.get("vehicles_used", {}).get(t.type, 0)
        handles.append(
            Line2D(
                [0],
                [0],
                color=colors[t.type],
                lw=2,
                label=f"{t.type} (cap {fmt_int(t.capacity)}): {used}/{t.count} used",
            )
        )
    if solution.unserved:
        handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markeredgecolor=UNSERVED_COLOR,
                markerfacecolor="none",
                markersize=8,
                label=f"unserved: {len(solution.unserved)}",
            )
        )
    handles.append(
        Line2D(
            [0],
            [0],
            marker="s",
            color="none",
            markerfacecolor=DEPOT_COLOR,
            markersize=8,
            label="depot",
        )
    )
    ax.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.92, edgecolor=GRID)

    served, cost = solution.objective
    ttl = title or (
        f"{instance.name} · {solution.solver} · served {served}/{instance.n} · "
        f"cost {fmt_int(cost)} CLP · {m.get('distance_km', 0):.0f} km · "
        f"{m.get('vehicles_used_total', 0)} vehicles"
    )
    ax.set_title(ttl, fontsize=10, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, facecolor=SURFACE)
    plt.close(fig)
    return path

"""x-t diagram: one row per used vehicle, time of day on the x axis.

Per stop: a thin grey travel bar, a hatched waiting bar, a solid service bar in
the vehicle type's colour, and above them a thin bracket spanning the
customer's time window — so where the windows bite is visible at a glance.
Unserved customers appear at the bottom as red window segments packed into
lanes.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator  # noqa: E402

from cvrptw_bench.core.instance import Instance  # noqa: E402
from cvrptw_bench.core.solution import Solution  # noqa: E402
from cvrptw_bench.viz.style import (  # noqa: E402
    GRID,
    INK,
    INK_MUTED,
    INK_SECONDARY,
    SURFACE,
    TRAVEL_COLOR,
    UNSERVED_COLOR,
    WAIT_COLOR,
    fmt_int,
    hhmm,
    type_color_map,
)


def _pack_lanes(intervals: list[tuple[int, int, int]], max_lanes: int = 12) -> list[int]:
    """Greedy interval packing: lane index per interval (start, end, id), sorted by start."""
    lane_end: list[int] = []
    lanes: list[int] = []
    for s, e, _ in intervals:
        placed = False
        for k, end in enumerate(lane_end):
            if s >= end:
                lane_end[k] = e
                lanes.append(k)
                placed = True
                break
        if not placed:
            if len(lane_end) < max_lanes:
                lane_end.append(e)
                lanes.append(len(lane_end) - 1)
            else:  # overflow: reuse the lane that frees up first (overlap accepted)
                k = min(range(len(lane_end)), key=lambda k: lane_end[k])
                lane_end[k] = e
                lanes.append(k)
    return lanes


def plot_gantt(
    instance: Instance,
    solution: Solution,
    path: str | Path,
    dpi: int = 300,
    title: str | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cust = {c.id: c for c in instance.customers}
    colors = type_color_map(instance)
    type_rank = {t.type: k for k, t in enumerate(instance.vehicle_types)}
    h0, h1 = instance.horizon.start, instance.horizon.end
    routes = sorted(solution.routes, key=lambda r: (type_rank[r.vehicle_type], r.vehicle_id))

    # unserved windows packed into lanes
    unserved = sorted(
        ((u.tw_start, u.tw_end, u.customer) for u in solution.unserved), key=lambda x: (x[0], x[1])
    )
    lanes = _pack_lanes(unserved) if unserved else []
    n_lanes = (max(lanes) + 1) if lanes else 0

    n_rows = len(routes)
    row_h = 0.34
    lane_h = 0.16
    fig_h = 1.6 + row_h * max(n_rows, 1) + lane_h * n_lanes + (0.5 if n_lanes else 0)
    fig, ax = plt.subplots(figsize=(14, min(fig_h, 40)))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    yticks, ylabels = [], []
    for i, r in enumerate(routes):
        y = n_rows - 1 - i  # first vehicle on top
        col = colors[r.vehicle_type]
        prev_dep = r.depart
        for j, s in enumerate(r.stops):
            c = cust[s.customer]
            yb = y + (
                0.37 if j % 2 == 0 else 0.47
            )  # alternate bracket heights so neighbours don't merge
            ax.broken_barh(
                [(prev_dep, s.arrival - prev_dep)], (y - 0.10, 0.20), color=TRAVEL_COLOR, lw=0
            )
            if s.wait > 0:
                ax.broken_barh(
                    [(s.arrival, s.wait)],
                    (y - 0.26, 0.52),
                    facecolor=WAIT_COLOR,
                    edgecolor=INK_MUTED,
                    hatch="////",
                    lw=0.3,
                )
            ax.broken_barh(
                [(s.service_start, s.departure - s.service_start)],
                (y - 0.30, 0.60),
                color=col,
                lw=0,
            )
            # time window bracket above the bar, tied to its service bar by a thin connector
            ax.plot([c.tw_start, c.tw_end], [yb, yb], color=INK_SECONDARY, lw=0.8)
            ax.plot([c.tw_start, c.tw_start], [yb - 0.05, yb + 0.05], color=INK_SECONDARY, lw=0.8)
            ax.plot([c.tw_end, c.tw_end], [yb - 0.05, yb + 0.05], color=INK_SECONDARY, lw=0.8)
            ax.plot(
                [s.service_start, s.service_start], [y + 0.30, yb], color=col, lw=0.6, alpha=0.9
            )
            prev_dep = s.departure
        ax.broken_barh(
            [(prev_dep, r.return_time - prev_dep)], (y - 0.10, 0.20), color=TRAVEL_COLOR, lw=0
        )
        ax.plot([r.depart, r.return_time], [y, y], marker="|", color=INK, ms=9, lw=0, mew=1.2)
        yticks.append(y)
        ylabels.append(
            f"v{r.vehicle_id:02d} {r.vehicle_type}  ·  {len(r.stops)} stops  ·  "
            f"{100 * r.load / r.capacity:.0f}% load"
        )

    if unserved:
        lane_step = 0.5  # row units between unserved lanes
        base = -1.2
        for (s, e, cid), lane in zip(unserved, lanes, strict=True):
            y = base - lane * lane_step
            ax.plot([s, e], [y, y], color=UNSERVED_COLOR, lw=1.6, solid_capstyle="butt")
            ax.plot([s, s], [y - 0.12, y + 0.12], color=UNSERVED_COLOR, lw=1.0)
            ax.plot([e, e], [y - 0.12, y + 0.12], color=UNSERVED_COLOR, lw=1.0)
            if len(unserved) <= 40:
                ax.text(
                    (s + e) / 2,
                    y + 0.06,
                    str(cid),
                    color=UNSERVED_COLOR,
                    fontsize=5.5,
                    ha="center",
                    va="bottom",
                )
        yticks.append(base - (n_lanes - 1) * lane_step / 2)
        ylabels.append(f"unserved windows ({len(unserved)})")
        ax.axhline(-0.6, color=GRID, lw=0.8)
        y_min = base - (n_lanes - 1) * lane_step - 0.5
    else:
        y_min = -0.7

    ax.set_ylim(y_min, n_rows - 0.3)
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=7, color=INK)
    ax.axvline(h0, color=INK_SECONDARY, lw=0.8, ls="--")
    ax.axvline(h1, color=INK_SECONDARY, lw=0.8, ls="--")
    ax.set_xlim(h0 - 900, h1 + 900)
    ax.xaxis.set_major_locator(MultipleLocator(3600))
    ax.xaxis.set_minor_locator(MultipleLocator(900))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: hhmm(x)))
    ax.tick_params(axis="x", labelsize=8, colors=INK_SECONDARY)
    ax.grid(True, axis="x", which="major", color=GRID, lw=0.6)
    ax.grid(True, axis="x", which="minor", color=GRID, lw=0.3, alpha=0.6)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="y", length=0)

    handles = [
        Patch(color=colors[t.type], label=f"service · {t.type}") for t in instance.vehicle_types
    ]
    handles += [
        Patch(color=TRAVEL_COLOR, label="travel"),
        Patch(facecolor=WAIT_COLOR, edgecolor=INK_MUTED, hatch="////", label="waiting"),
        plt.Line2D([0], [0], color=INK_SECONDARY, lw=1, label="customer window"),
    ]
    if unserved:
        handles.append(plt.Line2D([0], [0], color=UNSERVED_COLOR, lw=1.6, label="unserved window"))
    fig_h_actual = fig.get_size_inches()[1]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=len(handles),
        fontsize=7.5,
        frameon=False,
        bbox_to_anchor=(0.5, 0.0),
    )

    served, cost = solution.objective
    m = solution.metrics
    ttl = title or (
        f"{instance.name} · {solution.solver} · served {served}/{instance.n} · "
        f"cost {fmt_int(cost)} CLP · wait {m.get('wait_h', 0):.1f} h · "
        f"route time {m.get('route_time_h', 0):.1f} h"
    )
    ax.set_title(ttl, fontsize=10, color=INK, loc="left")
    fig.tight_layout(rect=(0, 0.45 / fig_h_actual, 1, 1))
    fig.savefig(path, dpi=dpi, facecolor=SURFACE)
    plt.close(fig)
    return path

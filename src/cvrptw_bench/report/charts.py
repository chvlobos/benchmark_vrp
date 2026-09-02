"""Plotly figures for the report. One visual system: solver colours are fixed
(never cycled), neutral ink for text and grids, a legend whenever there are
two or more series, hover tooltips on every mark."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from cvrptw_bench.report.aggregate import SEED_NAME, SOLVER_LABEL

SOLVER_COLOR = {
    "ortools": "#2a78d6",  # blue
    "cw_ls": "#eb6834",  # orange
    "cw": "#1baf7a",  # aqua
    "hexaly": "#4a3aa7",  # violet
    SEED_NAME: "#8a8985",  # neutral: a reference, not a contender
}
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e6e5e1"

LAYOUT = dict(
    paper_bgcolor=SURFACE,
    plot_bgcolor=SURFACE,
    font=dict(
        family="Inter, -apple-system, Segoe UI, Helvetica, Arial, sans-serif", size=12, color=INK
    ),
    margin=dict(l=50, r=20, t=96, b=50),
    legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=11)),
    hoverlabel=dict(bgcolor="#ffffff", font_size=12),
)
AXIS = dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont=dict(color=INK_SECONDARY))


def _solvers(df: pd.DataFrame, include_seed: bool = False) -> list[str]:
    cats = list(df["solver"].cat.categories)
    return [s for s in cats if include_seed or s != SEED_NAME]


def _apply(
    fig: go.Figure, title: str, xtitle: str = "", ytitle: str = "", height: int = 380
) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, y=0.985, yanchor="top", font=dict(size=14)),
        height=height,
        **LAYOUT,
    )
    fig.update_xaxes(title_text=xtitle, **AXIS)
    fig.update_yaxes(title_text=ytitle, **AXIS)
    return fig


def cost_gap_box(df: pd.DataFrame, factor: str, factor_title: str) -> go.Figure:
    """Cost gap (%) to the best known cost, among results at best coverage, by factor level."""
    fig = go.Figure()
    d = df[df["cost_gap"].notna()]
    for s in _solvers(df):
        ds = d[d["solver"] == s]
        fig.add_trace(
            go.Box(
                x=ds[factor].astype(str),
                y=100 * ds["cost_gap"],
                name=SOLVER_LABEL.get(s, s),
                marker_color=SOLVER_COLOR.get(s, "#999"),
                line=dict(width=1.5),
                boxpoints="all",
                jitter=0.35,
                pointpos=0,
                marker=dict(size=4, opacity=0.6),
                hovertemplate="%{x}: %{y:.1f} %<extra>" + SOLVER_LABEL.get(s, s) + "</extra>",
            )
        )
    fig.update_layout(boxmode="group")
    levels = sorted(df[factor].dropna().unique(), key=lambda v: (str(type(v)), v))
    fig.update_xaxes(categoryorder="array", categoryarray=[str(v) for v in levels])
    return _apply(fig, f"Cost gap to best known, by {factor_title}", factor_title, "gap (%)")


def coverage_deficit_bars(df: pd.DataFrame) -> go.Figure:
    """Total customers missed vs the best known coverage, per solver and stress level."""
    fig = go.Figure()
    d = df[df["solver"] != SEED_NAME]
    for s in _solvers(df):
        ds = d[d["solver"] == s].groupby("capacity_stress", observed=True)["coverage_deficit"].sum()
        fig.add_trace(
            go.Bar(
                x=[f"{k} %" for k in ds.index],
                y=ds.values,
                name=SOLVER_LABEL.get(s, s),
                marker_color=SOLVER_COLOR.get(s, "#999"),
                marker_line_width=0,
                hovertemplate="stress %{x}: %{y} customers<extra>"
                + SOLVER_LABEL.get(s, s)
                + "</extra>",
            )
        )
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(rangemode="tozero")
    return _apply(
        fig,
        "Customers missed vs the best known coverage (sum over instances)",
        "capacity stress",
        "customers",
    )


def performance_profile_fig(pp: pd.DataFrame, cp: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for s in pp["solver"].unique():
        d = pp[pp["solver"] == s]
        fig.add_trace(
            go.Scatter(
                x=d["tau"],
                y=100 * d["fraction"],
                mode="lines",
                line=dict(shape="hv", width=2, color=SOLVER_COLOR.get(s, "#999")),
                name=SOLVER_LABEL.get(s, s),
                hovertemplate="within %{x:.2f}x of best: %{y:.0f} % of instances<extra>"
                + SOLVER_LABEL.get(s, s)
                + "</extra>",
            )
        )
    fig.update_xaxes(range=[1.0, float(pp["tau"].max())])
    fig.update_yaxes(range=[0, 101])
    return _apply(
        fig,
        "Performance profile: instances within τ × best known cost (at best coverage)",
        "τ (cost ratio to best known)",
        "% of instances",
    )


def time_to_best_box(df: pd.DataFrame, limits: str = "") -> go.Figure:
    fig = go.Figure()
    d = df[df["solver"] != SEED_NAME]
    for s in _solvers(df):
        ds = d[d["solver"] == s]
        fig.add_trace(
            go.Box(
                x=ds["n"].astype(str),
                y=ds["time_to_best_s"],
                name=SOLVER_LABEL.get(s, s),
                marker_color=SOLVER_COLOR.get(s, "#999"),
                line=dict(width=1.5),
                boxpoints="all",
                jitter=0.35,
                pointpos=0,
                marker=dict(size=4, opacity=0.6),
                hovertemplate="n=%{x}: best found at %{y:.1f} s<extra>"
                + SOLVER_LABEL.get(s, s)
                + "</extra>",
            )
        )
    fig.update_layout(boxmode="group")
    fig.update_xaxes(
        categoryorder="array", categoryarray=[str(v) for v in sorted(df["n"].unique())]
    )
    title = "Time to best solution, by instance size"
    if limits:
        title += f" (limits: {limits})"
    return _apply(fig, title, "customers", "seconds")


def convergence_fig(
    traces: dict[str, list[tuple[float, int, int]]], instance: str, n: int
) -> go.Figure:
    """Best cost so far vs time, per solver, on the points where the solver had reached its final coverage."""
    fig = go.Figure()
    for s, tr in traces.items():
        if not tr:
            continue
        final_served = tr[-1][1]
        pts = [(t, c) for t, sv, c in tr if sv == final_served]
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines+markers",
                line=dict(shape="hv", width=2, color=SOLVER_COLOR.get(s, "#999")),
                marker=dict(size=4),
                name=f"{SOLVER_LABEL.get(s, s)} ({final_served}/{n} served)",
                hovertemplate="%{x:.1f} s: %{y:,.0f} CLP<extra>"
                + SOLVER_LABEL.get(s, s)
                + "</extra>",
            )
        )
    fig.update_xaxes(type="log")
    return _apply(
        fig,
        f"Convergence on {instance}: best cost vs time (log scale)",
        "seconds",
        "cost (CLP)",
        340,
    )


def wins_bar(df: pd.DataFrame) -> go.Figure:
    d = df[df["solver"] != SEED_NAME]
    g = d.groupby("solver", observed=True)
    wins = g["is_best"].sum()
    at_best = g["cost_gap"].count()
    total = df["instance"].nunique()
    fig = go.Figure()
    order = [s for s in _solvers(df)]
    fig.add_trace(
        go.Bar(
            x=[SOLVER_LABEL.get(s, s) for s in order],
            y=[at_best.get(s, 0) for s in order],
            name="reached best known coverage",
            marker_color="#d9d8d3",
            marker_line_width=0,
            hovertemplate="%{y} of " + str(total) + " instances<extra>best coverage</extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=[SOLVER_LABEL.get(s, s) for s in order],
            y=[wins.get(s, 0) for s in order],
            name="best known cost (ties included)",
            marker_color=[SOLVER_COLOR.get(s, "#999") for s in order],
            marker_line_width=0,
            hovertemplate="%{y} of " + str(total) + " instances<extra>best cost</extra>",
        )
    )
    fig.update_layout(barmode="overlay", bargap=0.35)
    return _apply(
        fig,
        f"Out of {total} instances: at best known coverage, and with the best known cost",
        "",
        "instances",
        340,
    )


def fmt_pct(x: float) -> str:
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.1f} %"

"""Collect a run's solutions into tables: per-instance results, gaps, factor aggregates,
performance profiles (PLAN.md §8.4).

Gap definition: per instance, ``best_served`` is the maximum served among valid
results (the generator's seed solution counts as a method row); a result with
fewer customers gets ``coverage_deficit = best_served − served`` and no cost
gap; among results at ``best_served``, ``cost_gap = cost / best_cost − 1``.
Invalid results are excluded from every "best" and flagged.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from cvrptw_bench.core.solution import Solution

SEED_NAME = "seed"
SOLVER_ORDER = ["ortools", "hexaly", "cw_ls", "cw", SEED_NAME]
SOLVER_LABEL = {
    "ortools": "OR-Tools",
    "hexaly": "Hexaly",
    "cw_ls": "CW + local search",
    "cw": "Clarke-Wright",
    SEED_NAME: "generator seed",
}


def _row_from_solution(sol: Solution, factors: dict, n: int) -> dict:
    m = sol.metrics
    return {
        "instance": sol.instance,
        "n": n,
        "family": factors.get("family"),
        "tw_profile": factors.get("tw_profile"),
        "capacity_stress": factors.get("capacity_stress"),
        "solver": sol.solver,
        "status": sol.status,
        "valid": bool(sol.validation.valid),
        "served": m.get("served", 0),
        "unserved": m.get("unserved", 0),
        "unserved_demand": m.get("unserved_demand", 0),
        "unserved_capacity": (m.get("unserved_by_reason") or {}).get("capacity", 0),
        "unserved_time_window": (m.get("unserved_by_reason") or {}).get("time_window", 0),
        "unserved_insertable": (m.get("unserved_by_reason") or {}).get("insertable", 0),
        "total_cost": m.get("total_cost", 0),
        "fixed_cost": m.get("fixed_cost", 0),
        "distance_km": m.get("distance_km", 0.0),
        "vehicles_used": m.get("vehicles_used_total", 0),
        "route_time_h": m.get("route_time_h", 0.0),
        "wait_h": m.get("wait_h", 0.0),
        "capacity_utilisation": m.get("capacity_utilisation_mean", 0.0),
        "wall_time_s": sol.compute.wall_time_s,
        "time_to_best_s": sol.compute.time_to_best_s,
        "time_limit_s": sol.config.get("time_limit_s"),
        "n_trace": len(sol.trace),
    }


def collect(run_dir: str | Path, instances_dir: str | Path | None = None) -> pd.DataFrame:
    """One row per (instance, solver) found under run_dir, plus the seed rows if available."""
    run_dir = Path(run_dir)
    inst_dir = Path(instances_dir) if instances_dir else None
    rows: list[dict] = []
    factors_by_name: dict[str, tuple[dict, int]] = {}
    if inst_dir is not None:
        for p in inst_dir.glob("*.json"):
            if p.name.endswith(".seed.json"):
                continue
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
            factors_by_name[d["name"]] = (d.get("meta", {}).get("factors", {}), len(d["customers"]))
    for sol_path in sorted(run_dir.glob("*/*/solution.json")):
        sol = Solution.load(sol_path)
        factors, n = factors_by_name.get(sol.instance, ({}, None))
        if n is None:
            n = sol.metrics.get("served", 0) + sol.metrics.get("unserved", 0)
        rows.append(_row_from_solution(sol, factors, n))
    if inst_dir is not None:
        names = {r["instance"] for r in rows}
        for name in sorted(names):
            seed_path = inst_dir / f"{name}.seed.json"
            if seed_path.exists():
                sol = Solution.load(seed_path)
                factors, n = factors_by_name.get(name, ({}, None))
                row = _row_from_solution(sol, factors, n or 0)
                row["solver"] = SEED_NAME
                rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["solver"] = pd.Categorical(
        df["solver"],
        categories=[s for s in SOLVER_ORDER if s in set(df["solver"])]
        + sorted(set(df["solver"]) - set(SOLVER_ORDER)),
    )
    return df.sort_values(["n", "instance", "solver"]).reset_index(drop=True)


def add_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """coverage_deficit, cost_gap (fraction), best flags; invalid rows are never 'best'."""
    df = df.copy()
    valid = df[df["valid"]]
    best_served = valid.groupby("instance")["served"].max().rename("best_served")
    df = df.merge(best_served, on="instance", how="left")
    at_best = valid.merge(best_served, on="instance")
    at_best = at_best[at_best["served"] == at_best["best_served"]]
    best_cost = at_best.groupby("instance")["total_cost"].min().rename("best_cost")
    df = df.merge(best_cost, on="instance", how="left")
    df["coverage_deficit"] = (df["best_served"] - df["served"]).where(df["valid"])
    same = df["valid"] & (df["served"] == df["best_served"])
    df["cost_gap"] = np.where(same, df["total_cost"] / df["best_cost"] - 1.0, np.nan)
    df["is_best"] = same & (df["total_cost"] == df["best_cost"])
    df["coverage_pct"] = 100.0 * df["served"] / df["n"]
    return df


def per_instance_table(df: pd.DataFrame) -> pd.DataFrame:
    """Wide table: one row per instance, served/cost/gap/time per solver."""
    solvers = [s for s in df["solver"].cat.categories]
    wide = df.pivot_table(
        index=["instance", "n", "family", "tw_profile", "capacity_stress"],
        columns="solver",
        values=[
            "served",
            "total_cost",
            "cost_gap",
            "coverage_deficit",
            "wall_time_s",
            "time_to_best_s",
            "valid",
        ],
        aggfunc="first",
        observed=True,
    )
    wide = wide.reindex(columns=pd.MultiIndex.from_product([wide.columns.levels[0], solvers]))
    return wide.reset_index()


def by_factor(df: pd.DataFrame, factor: str) -> pd.DataFrame:
    """Per solver and factor level: mean coverage %, mean cost gap %, best-cost wins, mean wall."""
    d = df[df["solver"] != SEED_NAME] if SEED_NAME in df["solver"].cat.categories else df
    g = d.groupby([factor, "solver"], observed=True)
    out = pd.DataFrame(
        {
            "instances": g.size(),
            "valid": g["valid"].sum(),
            "coverage_pct_mean": g["coverage_pct"].mean().round(2),
            "coverage_deficit_sum": g["coverage_deficit"].sum(),
            "at_best_coverage": g["cost_gap"].count(),
            "cost_gap_pct_mean": (100 * g["cost_gap"].mean()).round(2),
            "cost_gap_pct_max": (100 * g["cost_gap"].max()).round(2),
            "best_cost_wins": g["is_best"].sum(),
            "wall_time_s_mean": g["wall_time_s"].mean().round(1),
            "time_to_best_s_mean": g["time_to_best_s"].mean().round(1),
        }
    ).reset_index()
    return out


def overall(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["_all"] = "all"
    return by_factor(d, "_all").drop(columns="_all")


def performance_profile(df: pd.DataFrame, taus: np.ndarray | None = None) -> pd.DataFrame:
    """Dolan–Moré profile on cost among max-coverage results; below-coverage = never solved.

    Returns a long table (solver, tau, fraction): fraction of instances where the
    solver's cost is within factor tau of the best known cost *and* it reached the
    best known coverage.
    """
    taus = np.linspace(1.0, 1.5, 251) if taus is None else taus
    solvers = [s for s in df["solver"].cat.categories if s != SEED_NAME]
    n_inst = df["instance"].nunique()
    rows = []
    for s in solvers:
        d = df[df["solver"] == s]
        ratio = (1.0 + d["cost_gap"]).to_numpy()
        ratio = np.where(np.isnan(ratio), np.inf, ratio)
        for tau in taus:
            rows.append(
                {"solver": s, "tau": float(tau), "fraction": float((ratio <= tau).sum() / n_inst)}
            )
    return pd.DataFrame(rows)


def coverage_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Fraction of instances with coverage deficit <= k, k = 0..max, per solver."""
    solvers = [s for s in df["solver"].cat.categories if s != SEED_NAME]
    n_inst = df["instance"].nunique()
    kmax = int(np.nan_to_num(df["coverage_deficit"].max(), nan=0))
    rows = []
    for s in solvers:
        d = df[df["solver"] == s]
        deficit = d["coverage_deficit"].fillna(np.inf).to_numpy()
        for k in range(kmax + 1):
            rows.append({"solver": s, "k": k, "fraction": float((deficit <= k).sum() / n_inst)})
    return pd.DataFrame(rows)


def write_tables(df: pd.DataFrame, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    df.to_csv(out / "results_long.csv", index=False)
    paths["results_long"] = out / "results_long.csv"
    per_instance_table(df).to_csv(out / "results_by_instance.csv", index=False)
    paths["results_by_instance"] = out / "results_by_instance.csv"
    for f in ("n", "family", "tw_profile", "capacity_stress"):
        by_factor(df, f).to_csv(out / f"by_{f}.csv", index=False)
        paths[f"by_{f}"] = out / f"by_{f}.csv"
    overall(df).to_csv(out / "overall.csv", index=False)
    paths["overall"] = out / "overall.csv"
    return paths

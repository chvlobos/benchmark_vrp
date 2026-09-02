"""Solve one instance with one solver and write its artefacts (used by ``bench solve``
and, from Phase 6 on, by the resumable ``bench run``)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import build_matrices
from cvrptw_bench.core.solution import Solution
from cvrptw_bench.core.validator import evaluate
from cvrptw_bench.solvers.base import SolverConfig, get_solver

DEFAULT_RUN_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "run.default.yaml"


def load_run_config(path: str | Path | None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_RUN_CONFIG
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def time_limit_for(n: int, cfg: dict[str, Any]) -> float:
    """Wall-clock limit by instance size: tiers are 'up to n' -> seconds, plus 'default'."""
    tiers = cfg.get("time_limits_s", {}) or {}
    numeric = sorted((int(k), float(v)) for k, v in tiers.items() if str(k).isdigit())
    for upper, limit in numeric:
        if n <= upper:
            return limit
    return float(tiers.get("default", 300))


def solver_params(solver: str, cfg: dict[str, Any]) -> dict[str, Any]:
    params = dict(cfg.get(solver, {}) or {})
    if solver == "cw_ls":  # the constructive part of cw_ls uses the cw block too
        params = {**(cfg.get("cw", {}) or {}), **params}
    return params


def solve_one(
    instance: Instance,
    solver_name: str,
    cfg: dict[str, Any],
    out_dir: str | Path | None = None,
    seed: int | None = None,
    time_limit_s: float | None = None,
    threads: int | None = None,
    plots: bool | None = None,
    basemap: str | None = None,
    dpi: int = 300,
    log=None,
) -> Solution:
    m = build_matrices(instance)
    config = SolverConfig(
        time_limit_s=time_limit_s if time_limit_s is not None else time_limit_for(instance.n, cfg),
        seed=seed if seed is not None else int(cfg.get("seed", 42)),
        threads=threads if threads is not None else int(cfg.get("threads", 1)),
        params=solver_params(solver_name, cfg),
    )
    solver = get_solver(solver_name)
    t0 = time.perf_counter()
    plan, run = solver.solve(instance, m, config)
    solution = evaluate(instance, plan, run, m)
    if log:
        served, cost = solution.objective
        log(
            f"{instance.name:<14} {solver_name:<8} served={served}/{instance.n} cost={cost} "
            f"km={solution.metrics['distance_km']} "
            f"vehicles={solution.metrics['vehicles_used_total']} "
            f"valid={solution.validation.valid} wall={run.wall_time_s}s "
            f"({time.perf_counter() - t0:.1f}s incl. evaluation)"
        )
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        solution.save(out / "solution.json")
        outputs = cfg.get("outputs", {}) or {}
        do_plots = plots if plots is not None else bool(outputs.get("plots", True))
        if do_plots:
            from cvrptw_bench.viz import plot_all

            bm = basemap or outputs.get("basemap", "esri-gray")
            plot_all(instance, solution, out, basemap=bm, dpi=dpi)
    return solution

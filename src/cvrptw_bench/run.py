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


# ----------------------------------------------------------------- bench run
def _job(args: tuple) -> dict[str, Any]:
    """One (instance, solver) job in a worker process; returns a summary row."""
    instance_path, solver_name, cfg, out_dir, plots, basemap = args
    instance = Instance.load(instance_path)
    t0 = time.perf_counter()
    try:
        sol = solve_one(
            instance, solver_name, cfg, out_dir=out_dir, plots=plots, basemap=basemap, log=None
        )
        row = summary_row(sol, instance)
    except Exception as exc:  # noqa: BLE001 - one failing job must not stop the run
        row = {
            "instance": instance.name,
            "solver": solver_name,
            "status": "error",
            "message": f"{type(exc).__name__}: {exc}",
            "valid": False,
        }
    row["job_wall_s"] = round(time.perf_counter() - t0, 3)
    return row


def summary_row(sol: Solution, instance: Instance) -> dict[str, Any]:
    m = sol.metrics
    f = instance.meta.get("factors", {})
    return {
        "instance": instance.name,
        "n": instance.n,
        "family": f.get("family"),
        "tw_profile": f.get("tw_profile"),
        "capacity_stress": f.get("capacity_stress"),
        "solver": sol.solver,
        "solver_version": sol.solver_version,
        "status": sol.status,
        "message": sol.message,
        "valid": sol.validation.valid,
        "served": m.get("served"),
        "unserved": m.get("unserved"),
        "unserved_demand": m.get("unserved_demand"),
        "total_cost": m.get("total_cost"),
        "fixed_cost": m.get("fixed_cost"),
        "distance_km": m.get("distance_km"),
        "vehicles_used_total": m.get("vehicles_used_total"),
        "route_time_h": m.get("route_time_h"),
        "wait_h": m.get("wait_h"),
        "capacity_utilisation_mean": m.get("capacity_utilisation_mean"),
        "wall_time_s": sol.compute.wall_time_s,
        "time_to_best_s": sol.compute.time_to_best_s,
        "time_limit_s": sol.config.get("time_limit_s"),
        "seed": sol.seed,
    }


def _burn(n: int) -> float:
    t = time.perf_counter()
    x = 0
    for i in range(n):
        x += i * i
    return time.perf_counter() - t


def cpu_probe(workers: int, n: int = 6_000_000) -> dict[str, float]:
    """How much CPU the machine really gives to ``workers`` concurrent jobs.

    Runs one CPU-bound loop alone and then ``workers`` copies at once; the ratio of
    the two times is the slowdown a job suffers from its neighbours (1.0 = a full
    core each, 2.0 = two jobs sharing one core). Recorded in run_meta.json because
    "cpu_count" alone does not say it: a container can report 2 logical CPUs and
    deliver the throughput of one.
    """
    from concurrent.futures import ProcessPoolExecutor

    single = _burn(n)
    if workers <= 1:
        return {"single_s": round(single, 3), "parallel_s": round(single, 3), "slowdown": 1.0}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        parallel = max(pool.map(_burn, [n] * workers))
    return {
        "single_s": round(single, 3),
        "parallel_s": round(parallel, 3),
        "slowdown": round(parallel / single, 2),
        "effective_cores": round(workers * single / parallel, 2),
    }


def _existing_valid(path: Path) -> dict[str, Any] | None:
    """Summary of an existing solution.json if it is a finished, feasible run."""
    if not path.exists():
        return None
    try:
        sol = Solution.load(path)
    except Exception:  # noqa: BLE001 - half-written or old schema: redo the job
        return None
    if sol.status != "feasible":
        return None
    inst_name = sol.instance
    return {
        "instance": inst_name,
        "solver": sol.solver,
        "status": "skipped",
        "valid": sol.validation.valid,
    }


def run_benchmark(
    cfg: dict[str, Any],
    instances_dir: str | Path,
    solvers: list[str],
    out_dir: str | Path,
    workers: int = 1,
    plots: bool | None = None,
    basemap: str | None = None,
    names: list[str] | None = None,
    sizes: list[int] | None = None,
    resume: bool = True,
    log=print,
) -> list[dict[str, Any]]:
    """Solve every instance with every solver, resumably; write log.jsonl and run_meta.json.

    Jobs are ordered by instance size then name, solvers in the given order, so a
    partial run always holds complete instances first. A job whose solution.json
    already exists with status 'feasible' is skipped (resume). ``workers > 1``
    runs jobs in parallel processes — each solver is single-threaded, but timings
    are only strictly comparable when workers <= physical cores; the run
    metadata records the choice.
    """
    import json
    import os
    import platform
    import sys
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from datetime import UTC, datetime
    from importlib import metadata as importlib_metadata

    from cvrptw_bench import __version__

    inst_dir = Path(instances_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted(p for p in inst_dir.glob("*.json") if not p.name.endswith(".seed.json"))
    if names:
        wanted = set(names)
        paths = [p for p in paths if p.stem in wanted]
    metas = []
    for p in paths:
        inst = Instance.load(p)
        if sizes and inst.n not in sizes:
            continue
        metas.append((inst.n, inst.name, p))
    metas.sort()

    pk = {}
    for name in ("numpy", "ortools", "hexaly"):
        try:
            pk[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            pass
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "started": now,
        "resumed": [],
        "cpu_probe": cpu_probe(workers),
        "package_version": __version__,
        "solvers": solvers,
        "instances": [n for _, n, _ in metas],
        "config": cfg,
        "workers": workers,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "python": sys.version.split()[0],
            "packages": pk,
        },
    }
    meta_path = out / "run_meta.json"
    if resume and meta_path.exists():
        # a resumed run keeps the original start and the union of solvers seen so far
        try:
            prev = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["started"] = prev.get("started", now)
            meta["resumed"] = list(prev.get("resumed", [])) + [now]
            meta["solvers"] = list(dict.fromkeys(list(prev.get("solvers", [])) + solvers))
        except (OSError, ValueError):
            pass
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)

    jobs = []
    rows: list[dict[str, Any]] = []
    for _, name, p in metas:
        for s in solvers:
            job_dir = out / name / s
            if resume:
                prev = _existing_valid(job_dir / "solution.json")
                if prev is not None:
                    rows.append(prev)
                    continue
            jobs.append((str(p), s, cfg, str(job_dir), plots, basemap))
    total = len(jobs)
    skipped = len(rows)
    log(
        f"run: {len(metas)} instances x {solvers} -> {total} jobs "
        f"({skipped} already done), workers={workers}"
    )

    def _record(row: dict[str, Any], k: int) -> None:
        rows.append(row)
        with open(out / "log.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        if row.get("status") == "error":
            log(
                f"[{k}/{total}] {row['instance']:<14} {row['solver']:<8} ERROR {row.get('message')}"
            )
        else:
            log(
                f"[{k}/{total}] {row['instance']:<14} {row['solver']:<8} "
                f"served={row['served']}/{row.get('n')} cost={row['total_cost']} "
                f"valid={row['valid']} wall={row['wall_time_s']}s"
            )

    if workers <= 1:
        for k, job in enumerate(jobs, 1):
            _record(_job(job), k)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_job, job): job for job in jobs}
            for k, fut in enumerate(as_completed(futures), 1):
                _record(fut.result(), k)
    return rows

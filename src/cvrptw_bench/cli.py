"""``bench`` command line interface.

Phase 0 commands: ``info``, ``validate``, ``version``.
Later phases add ``generate``, ``solve``, ``run``, ``plot`` and ``report``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from cvrptw_bench import __version__
from cvrptw_bench.core.instance import Instance, seconds_to_hhmm
from cvrptw_bench.core.matrices import build_matrices
from cvrptw_bench.core.solution import Solution
from cvrptw_bench.core.validator import revalidate

BASEMAP_CHOICES = ["esri-gray", "osm", "esri-street", "carto", "none"]


def _not_yet(phase: str):
    def _handler(_: argparse.Namespace) -> int:
        print(f"not implemented yet: scheduled for {phase}", file=sys.stderr)
        return 2

    return _handler


# ------------------------------------------------------------------- info
def cmd_info(args: argparse.Namespace) -> int:
    inst = Instance.load(args.instance)
    m = build_matrices(inst)
    tri = m.dist_m[np.triu_indices(inst.n + 1, k=1)] if inst.n > 0 else np.array([0])
    print(f"instance        {inst.name}")
    print(f"customers       {inst.n}")
    print(
        f"horizon         {seconds_to_hhmm(inst.horizon.start)}-{seconds_to_hhmm(inst.horizon.end)}"
        f" ({inst.horizon.length / 3600:.1f} h)"
    )
    print(f"travel          haversine x {inst.travel.detour_factor} @ {inst.travel.speed_kmh} km/h")
    print(f"depot           ({inst.depot.lat:.5f}, {inst.depot.lon:.5f})")
    print(f"total demand    {inst.total_demand}")
    stress = inst.total_demand / inst.fleet_capacity
    print(f"fleet capacity  {inst.fleet_capacity}  -> capacity stress {stress:.3f}")
    for t in inst.vehicle_types:
        print(
            f"  {t.type:<8} x{t.count:<3} cap {t.capacity:<6} "
            f"fixed {t.fixed_cost:<7} {t.cost_per_km} CLP/km"
        )
    widths = [(c.tw_end - c.tw_start) / 60 for c in inst.customers]
    mean_w = sum(widths) / len(widths)
    print(f"tw width (min)  min {min(widths):.0f}  mean {mean_w:.0f}  max {max(widths):.0f}")
    print(f"pair distance   mean {tri.mean() / 1000:.2f} km  max {tri.max() / 1000:.2f} km")
    depot_km = m.dist_m[0, 1:] / 1000
    print(f"depot->customer mean {depot_km.mean():.2f} km  max {depot_km.max():.2f} km")
    if "factors" in inst.meta:
        print("factors         " + json.dumps(inst.meta["factors"]))
    if "stats" in inst.meta:
        st = dict(inst.meta["stats"])
        seed_stats = st.pop("seed_solution", None)
        print("stats           " + json.dumps(st))
        if seed_stats:
            print("seed solution   " + json.dumps(seed_stats))
    elif inst.meta:
        print("meta            " + json.dumps(inst.meta, ensure_ascii=False)[:300])
    return 0


# --------------------------------------------------------------- validate
def cmd_validate(args: argparse.Namespace) -> int:
    inst = Instance.load(args.instance)
    sol = Solution.load(args.solution)
    if sol.instance != inst.name:
        print(f"warning: solution is for '{sol.instance}', instance file is '{inst.name}'")
    fresh, diffs = revalidate(inst, sol)
    served, cost = fresh.objective
    verdict = "VALID" if fresh.validation.valid else "INVALID"
    print(
        f"{verdict}  solver={fresh.solver}  served={served}/{inst.n}  cost={cost}  "
        f"km={fresh.metrics['distance_km']}  vehicles={fresh.metrics['vehicles_used_total']}"
    )
    for v in fresh.validation.violations:
        print(f"  violation: {v}")
    for d in diffs:
        print(f"  discrepancy: {d}")
    if fresh.unserved:
        by = fresh.metrics["unserved_by_reason"]
        print("  unserved by reason: " + ", ".join(f"{k}={v}" for k, v in by.items() if v))
    if args.write:
        out = Path(args.write)
        fresh.save(out)
        print(f"  re-evaluated solution written to {out}")
    return 0 if fresh.validation.valid and not diffs else 1


def cmd_version(_: argparse.Namespace) -> int:
    print(f"cvrptw-bench {__version__}")
    return 0


# --------------------------------------------------------------- generate
def cmd_generate(args: argparse.Namespace) -> int:
    from cvrptw_bench.generator import GeneratorConfig, InstanceSpec, design_specs, generate_set

    cfg = GeneratorConfig.load(args.config)
    if args.seed is not None:
        cfg.global_seed = args.seed
    if args.sizes:
        cfg.design.sizes = [int(x) for x in args.sizes.split(",")]
    if args.families:
        cfg.design.families = args.families.split(",")
    if args.profiles:
        cfg.design.tw_profiles = args.profiles.split(",")
    if args.stress:
        cfg.design.capacity_stress = [int(x) for x in args.stress.split(",")]
    specs = [InstanceSpec.parse(args.only)] if args.only else design_specs(cfg)
    t0 = time.perf_counter()
    instances = generate_set(cfg, args.out, specs)
    print(f"{len(instances)} instances written to {args.out} in {time.perf_counter() - t0:.1f} s")
    return 0


# ------------------------------------------------------------------- plot
def cmd_plot(args: argparse.Namespace) -> int:
    from cvrptw_bench.viz import plot_all

    inst = Instance.load(args.instance)
    sol = Solution.load(args.solution)
    out = args.out or Path(args.solution).with_suffix("").parent / f"plots_{sol.solver}"
    paths = plot_all(
        inst, sol, out, basemap=not args.no_basemap, dpi=args.dpi, html=not args.no_html
    )
    for k, p in paths.items():
        print(f"{k:<9} {p}")
    return 0


# ------------------------------------------------------------------ solve
def cmd_solve(args: argparse.Namespace) -> int:
    from cvrptw_bench.run import load_run_config, solve_one

    inst = Instance.load(args.instance)
    cfg = load_run_config(args.config)
    out = args.out or Path("results") / "solve" / inst.name / args.solver
    sol = solve_one(
        inst,
        args.solver,
        cfg,
        out_dir=out,
        seed=args.seed,
        time_limit_s=args.time_limit,
        threads=args.threads,
        plots=not args.no_plots,
        basemap=args.basemap,
        dpi=args.dpi,
        log=print,
    )
    if sol.status != "feasible":
        print(f"solver status: {sol.status} — {sol.message}")
    print(f"written to {out}")
    return 0 if sol.validation.valid and sol.status == "feasible" else 1


# -------------------------------------------------------------------- run
def cmd_run(args: argparse.Namespace) -> int:
    from cvrptw_bench.run import load_run_config, run_benchmark

    cfg = load_run_config(args.config)
    solvers = (
        args.solvers.split(",")
        if args.solvers
        else list(cfg.get("solvers", ["cw", "cw_ls", "ortools"]))
    )
    sizes = [int(x) for x in args.sizes.split(",")] if args.sizes else None
    names = args.only.split(",") if args.only else None
    t0 = time.perf_counter()
    rows = run_benchmark(
        cfg,
        args.instances,
        solvers,
        args.out,
        workers=args.workers,
        plots=False if args.no_plots else None,
        basemap=args.basemap,
        names=names,
        sizes=sizes,
        resume=not args.no_resume,
    )
    errors = sum(1 for r in rows if r.get("status") == "error")
    elapsed = time.perf_counter() - t0
    print(f"done: {len(rows)} results, {errors} errors, {elapsed:.0f} s -> {args.out}")
    return 1 if errors else 0


# ----------------------------------------------------------------- report
def cmd_report(args: argparse.Namespace) -> int:
    from cvrptw_bench.report import build_report

    build_report(
        args.run_dir,
        instances_dir=args.instances,
        out_path=args.out,
        gallery=args.gallery,
        basemap=args.basemap or "esri-gray",
        dpi=args.dpi,
    )
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from cvrptw_bench.report.compare import compare_runs

    out = compare_runs(
        args.base_dir,
        args.exp_dir,
        instances_dir=args.instances,
        suffix=args.suffix,
        title=args.title or f"{args.exp_dir} vs {args.base_dir}",
        description=args.description or "",
        out_path=args.out,
    )
    print(f"comparison written to {out}")
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bench", description="CVRPTW heterogeneous-fleet benchmark")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("info", help="print a summary of an instance")
    s.add_argument("instance", type=Path)
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("validate", help="re-evaluate a solution file against its instance")
    s.add_argument("solution", type=Path)
    s.add_argument("--instance", type=Path, required=True)
    s.add_argument("--write", type=Path, help="write the re-evaluated solution to this path")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("version", help="print the package version")
    s.set_defaults(func=cmd_version)

    s = sub.add_parser("generate", help="generate the benchmark instance set")
    s.add_argument("--config", type=Path, default=None, help="generator YAML (default: built-in)")
    s.add_argument("--out", type=Path, default=Path("instances"), help="output directory")
    s.add_argument("--seed", type=int, default=None, help="override global_seed")
    s.add_argument("--sizes", type=str, default=None, help="comma-separated sizes, e.g. 100,200")
    s.add_argument("--families", type=str, default=None, help="e.g. R,C,RC")
    s.add_argument("--profiles", type=str, default=None, help="e.g. L,M,T")
    s.add_argument("--stress", type=str, default=None, help="e.g. 60,85,105")
    s.add_argument("--only", type=str, default=None, help="one instance name, e.g. RC-400-T-105")
    s.set_defaults(func=cmd_generate)

    s = sub.add_parser("plot", help="map (PNG + HTML) and x-t Gantt of a solution")
    s.add_argument("solution", type=Path)
    s.add_argument("--instance", type=Path, required=True)
    s.add_argument(
        "--out", type=Path, default=None, help="output directory (default: next to the solution)"
    )
    s.add_argument(
        "--basemap",
        choices=BASEMAP_CHOICES,
        default="esri-gray",
        help="tile provider for the maps (keyless: esri-gray, osm, esri-street; "
        "carto needs an API key); default esri-gray",
    )
    s.add_argument("--no-basemap", action="store_true", help="same as --basemap none")
    s.add_argument("--no-html", action="store_true", help="skip the interactive HTML map")
    s.add_argument("--dpi", type=int, default=300)
    s.set_defaults(func=cmd_plot)

    s = sub.add_parser("solve", help="solve one instance with one solver")
    s.add_argument("instance", type=Path)
    s.add_argument("--solver", required=True, help="cw | cw_ls | ortools | hexaly")
    s.add_argument("--config", type=Path, default=None, help="run YAML (default: run.default)")
    s.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output dir (default results/solve/<instance>/<solver>)",
    )
    s.add_argument("--time-limit", type=float, default=None, help="seconds (default: tier by size)")
    s.add_argument("--seed", type=int, default=None)
    s.add_argument("--threads", type=int, default=None)
    s.add_argument("--no-plots", action="store_true")
    s.add_argument("--basemap", default=None, choices=BASEMAP_CHOICES)
    s.add_argument("--dpi", type=int, default=300)
    s.set_defaults(func=cmd_solve)

    s = sub.add_parser("run", help="solve a whole instance set with several solvers (resumable)")
    s.add_argument("--instances", type=Path, default=Path("instances"))
    s.add_argument("--solvers", default=None, help="comma-separated (default: config)")
    s.add_argument("--out", type=Path, required=True, help="run directory, e.g. results/run1")
    s.add_argument("--config", type=Path, default=None)
    s.add_argument("--workers", type=int, default=1, help="parallel processes (1 = clean timings)")
    s.add_argument("--no-plots", action="store_true", help="skip map/gantt per solution")
    s.add_argument("--basemap", default=None, choices=BASEMAP_CHOICES)
    s.add_argument("--sizes", default=None, help="e.g. 100,200")
    s.add_argument("--only", default=None, help="comma-separated instance names")
    s.add_argument("--no-resume", action="store_true", help="redo jobs even if a solution exists")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser(
        "report", help="aggregate a run into tables and a self-contained HTML report"
    )
    s.add_argument("run_dir", type=Path)
    s.add_argument("--instances", type=Path, default=Path("instances"))
    s.add_argument("--out", type=Path, default=None, help="default <run_dir>/report.html")
    s.add_argument(
        "--gallery", type=int, default=3, help="instances shown with maps and Gantts (0 = none)"
    )
    s.add_argument("--basemap", default=None, choices=BASEMAP_CHOICES)
    s.add_argument("--dpi", type=int, default=110, help="dpi of the gallery figures")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser(
        "compare", help="judge a secondary run against a base run (markdown + CSV tables)"
    )
    s.add_argument("base_dir", type=Path)
    s.add_argument("exp_dir", type=Path)
    s.add_argument("--instances", type=Path, default=Path("instances"))
    s.add_argument("--suffix", required=True, help="appended to the variant's solver names")
    s.add_argument("--title", default=None)
    s.add_argument("--description", default=None, help="one paragraph on what the variant is")
    s.add_argument("--out", type=Path, default=None, help="default <exp_dir>/comparison.md")
    s.set_defaults(func=cmd_compare)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

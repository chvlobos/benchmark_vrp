"""``bench`` command line interface.

Phase 0 commands: ``info``, ``validate``, ``version``.
Later phases add ``generate``, ``solve``, ``run``, ``plot`` and ``report``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from cvrptw_bench import __version__
from cvrptw_bench.core.instance import Instance, seconds_to_hhmm
from cvrptw_bench.core.matrices import build_matrices
from cvrptw_bench.core.solution import Solution
from cvrptw_bench.core.validator import revalidate


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
    if inst.meta:
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

    for name, phase in (
        ("generate", "Phase 1"),
        ("plot", "Phase 2"),
        ("solve", "Phase 3"),
        ("run", "Phase 6"),
        ("report", "Phase 6"),
    ):
        s = sub.add_parser(name, help=f"({phase}) not implemented yet")
        s.add_argument("args", nargs=argparse.REMAINDER)
        s.set_defaults(func=_not_yet(phase))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

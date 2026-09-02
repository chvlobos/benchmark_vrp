"""Instance generation: one instance from a spec, or the whole factorial set."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from cvrptw_bench import __version__
from cvrptw_bench.core.instance import Customer, Depot, Horizon, Instance, Travel
from cvrptw_bench.core.matrices import build_matrices, haversine_km
from cvrptw_bench.core.solution import RoutePlan, Solution, SolverRun
from cvrptw_bench.core.validator import evaluate
from cvrptw_bench.generator.config import GeneratorConfig
from cvrptw_bench.generator.demand import sample_demands, service_times, size_fleet
from cvrptw_bench.generator.geo import Region, bbox_polygon, load_polygon
from cvrptw_bench.generator.sampling import sample_layout
from cvrptw_bench.generator.seed_solution import build_seed_solution, post_window_repair
from cvrptw_bench.generator.windows import assign_classes, make_windows


@dataclass(frozen=True)
class InstanceSpec:
    n: int
    family: str
    tw_profile: str
    capacity_stress: int

    @property
    def name(self) -> str:
        return f"{self.family}-{self.n}-{self.tw_profile}-{self.capacity_stress}"

    @classmethod
    def parse(cls, name: str) -> InstanceSpec:
        fam, n, prof, stress = name.split("-")
        return cls(int(n), fam, prof, int(stress))


def instance_seed(global_seed: int, name: str) -> int:
    """Stable per-instance seed (independent of Python's hash randomisation)."""
    h = hashlib.sha256(f"{global_seed}:{name}".encode()).digest()
    return int.from_bytes(h[:8], "big") % (2**63 - 1)


def design_specs(cfg: GeneratorConfig) -> list[InstanceSpec]:
    d = cfg.design
    return [
        InstanceSpec(n, fam, prof, stress)
        for n in d.sizes
        for fam in d.families
        for prof in d.tw_profiles
        for stress in d.capacity_stress
    ]


def make_region(cfg: GeneratorConfig) -> Region:
    g = cfg.geography
    if g.bbox is not None:
        return Region(bbox_polygon(*g.bbox))
    return Region(load_polygon(g.polygon))


def generate_instance(
    spec: InstanceSpec, cfg: GeneratorConfig, region: Region | None = None
) -> tuple[Instance, Solution]:
    """Build one instance and its seed solution (evaluated with the validator)."""
    region = region or make_region(cfg)
    seed = instance_seed(cfg.global_seed, spec.name)
    rng = np.random.default_rng(seed)
    n = spec.n
    h0, h1 = cfg.horizon.start, cfg.horizon.end

    layout = sample_layout(rng, region, n, spec.family, cfg.geography)
    max_cap = max(t.capacity for t in cfg.fleet.types)
    demand = sample_demands(rng, n, cfg.demand, max_cap)
    service = service_times(demand, cfg.service_time)
    fleet = size_fleet(int(demand.sum()), spec.capacity_stress, cfg.fleet)

    # provisional instance with full-horizon windows: gives the matrices for the sweep
    customers = [
        Customer(
            id=i + 1,
            lat=float(layout.customers[i, 1]),
            lon=float(layout.customers[i, 0]),
            demand=int(demand[i]),
            service_time=int(service[i]),
            tw_start=h0,
            tw_end=h1,
        )
        for i in range(n)
    ]
    base = Instance(
        name=spec.name,
        horizon=Horizon(start=h0, end=h1),
        travel=Travel(
            speed_kmh=cfg.travel.speed_kmh,
            detour_factor=cfg.travel.detour_factor,
            distance=cfg.travel.distance,
        ),
        depot=Depot(lat=float(layout.depot[1]), lon=float(layout.depot[0])),
        customers=customers,
        vehicle_types=fleet,
    )
    m = build_matrices(base)
    seed_sol = build_seed_solution(
        base, m, rng, cfg.fleet.mix, cfg.seed_solution.duration_margin_frac
    )

    classes = assign_classes(rng, n, spec.tw_profile, cfg.time_windows)
    e, late = make_windows(rng, m, seed_sol.arrival, classes, cfg.time_windows, h0, h1)
    for c in customers:
        c.tw_start, c.tw_end, c.tw_class = int(e[c.id]), int(late[c.id]), classes[c.id - 1]

    # with the windows in place, try once more to fit virtual customers into the real fleet
    m_final = build_matrices(
        Instance(
            name=spec.name,
            horizon=base.horizon,
            travel=base.travel,
            depot=base.depot,
            customers=customers,
            vehicle_types=fleet,
        )
    )
    real_routes, virtual_customers, busy_s = post_window_repair(base, m_final, seed_sol)

    # metadata
    fleet_capacity = sum(t.capacity * t.count for t in fleet)
    n_vehicles = sum(t.count for t in fleet)
    cen_lat, cen_lon = (
        float(np.mean(layout.customers[:, 1])),
        float(np.mean(layout.customers[:, 0])),
    )
    widths = (late[1:] - e[1:]) / 60.0
    meta: dict[str, Any] = {
        "seed": seed,
        "global_seed": cfg.global_seed,
        "generator_version": __version__,
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "factors": {
            "n": n,
            "family": spec.family,
            "tw_profile": spec.tw_profile,
            "capacity_stress": spec.capacity_stress,
        },
        "stats": {
            "total_demand": int(demand.sum()),
            "n_large_orders": int((demand > cfg.demand.small_range[1]).sum()),
            "fleet_capacity": fleet_capacity,
            "n_vehicles": n_vehicles,
            "capacity_stress_achieved": round(int(demand.sum()) / fleet_capacity, 4),
            "time_stress_est": round(busy_s / (n_vehicles * (h1 - h0)), 4),
            "n_clusters": layout.n_clusters,
            "depot_to_centroid_km": round(
                float(haversine_km(m.lat[0], m.lon[0], cen_lat, cen_lon)), 3
            ),
            "tw_width_min": {
                "mean": round(float(widths.mean()), 1),
                "min": round(float(widths.min()), 1),
                "max": round(float(widths.max()), 1),
            },
            "tw_class_counts": {k: classes.count(k) for k in ("wide", "medium", "tight")},
        },
    }
    instance = Instance(
        name=spec.name,
        meta=meta,
        horizon=base.horizon,
        travel=base.travel,
        depot=base.depot,
        customers=customers,
        vehicle_types=fleet,
    )

    # the seed solution on the real fleet, judged by the validator (must be valid)
    plan = RoutePlan(routes=real_routes)
    run = SolverRun(
        solver="seed_sweep",
        solver_version=__version__,
        seed=seed,
        config={
            "virtual_customers": sorted(virtual_customers),
            "duration_margin_frac": cfg.seed_solution.duration_margin_frac,
        },
    )
    seed_solution = evaluate(instance, plan, run, m_final)
    if not seed_solution.validation.valid:
        raise RuntimeError(
            f"{spec.name}: seed solution is invalid: {seed_solution.validation.violations[:3]}"
        )
    instance.meta["stats"]["seed_solution"] = {
        "served": seed_solution.metrics["served"],
        "unserved": seed_solution.metrics["unserved"],
        "unserved_by_reason": {
            k: v for k, v in seed_solution.metrics["unserved_by_reason"].items() if v
        },
        "cost": seed_solution.metrics["total_cost"],
        "distance_km": seed_solution.metrics["distance_km"],
        "vehicles_used": seed_solution.metrics["vehicles_used_total"],
    }
    return instance, seed_solution


INDEX_COLUMNS = [
    "name",
    "n",
    "family",
    "tw_profile",
    "capacity_stress",
    "capacity_stress_achieved",
    "time_stress_est",
    "total_demand",
    "fleet_capacity",
    "n_vehicles",
    "n_clusters",
    "depot_to_centroid_km",
    "tw_width_mean_min",
    "seed_served",
    "seed_unserved",
    "seed_cost",
    "seed_vehicles_used",
    "seed",
]


def index_row(inst: Instance) -> dict[str, Any]:
    f, s = inst.meta["factors"], inst.meta["stats"]
    ss = s["seed_solution"]
    return {
        "name": inst.name,
        "n": f["n"],
        "family": f["family"],
        "tw_profile": f["tw_profile"],
        "capacity_stress": f["capacity_stress"],
        "capacity_stress_achieved": s["capacity_stress_achieved"],
        "time_stress_est": s["time_stress_est"],
        "total_demand": s["total_demand"],
        "fleet_capacity": s["fleet_capacity"],
        "n_vehicles": s["n_vehicles"],
        "n_clusters": s["n_clusters"],
        "depot_to_centroid_km": s["depot_to_centroid_km"],
        "tw_width_mean_min": s["tw_width_min"]["mean"],
        "seed_served": ss["served"],
        "seed_unserved": ss["unserved"],
        "seed_cost": ss["cost"],
        "seed_vehicles_used": ss["vehicles_used"],
        "seed": inst.meta["seed"],
    }


def generate_set(
    cfg: GeneratorConfig,
    out_dir: str | Path,
    specs: list[InstanceSpec] | None = None,
    log=print,
) -> list[Instance]:
    """Generate all specs (default: the factorial design) into out_dir + index.csv."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    region = make_region(cfg)
    specs = specs if specs is not None else design_specs(cfg)
    instances: list[Instance] = []
    for k, spec in enumerate(specs, 1):
        inst, seed_sol = generate_instance(spec, cfg, region)
        inst.save(out / f"{spec.name}.json")
        seed_sol.save(out / f"{spec.name}.seed.json")
        instances.append(inst)
        s = inst.meta["stats"]
        log(
            f"[{k:>3}/{len(specs)}] {spec.name:<14} vehicles={s['n_vehicles']:<3} "
            f"cap_stress={s['capacity_stress_achieved']:.3f} "
            f"time_stress={s['time_stress_est']:.3f} "
            f"seed: served={s['seed_solution']['served']}/{inst.n} "
            f"unserved={s['seed_solution']['unserved_by_reason']}"
        )
    with open(out / "index.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=INDEX_COLUMNS)
        w.writeheader()
        for inst in instances:
            w.writerow(index_row(inst))
    return instances

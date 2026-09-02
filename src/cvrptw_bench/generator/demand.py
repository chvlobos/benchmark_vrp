"""Loads, service times and fleet sizing.

Fleet sizing (PLAN.md §4.3): demands are drawn first; the fleet is then built
from *blocks* (default 3 small + 2 medium + 1 large = 8 800 units) plus a
partial block, so that the total capacity matches ``total_demand / stress``:

* candidates are ``b`` full blocks (b >= 0) plus any partial block (up to the
  block's count of each type), keeping only fleets with at least one vehicle
  of the largest type so the biggest order always has a vehicle for it;
* for stress <= 100 % the candidate closest to the target among those with
  capacity >= total demand is chosen (feasible by capacity);
* for stress > 100 % the closest among those with capacity < total demand is
  chosen, so an over-subscribed cell really is over-subscribed even for small
  instances (where the granularity of a 5-vehicle fleet is coarse).

The achieved ratio is stored in the instance metadata; the analysis uses it.
"""

from __future__ import annotations

import numpy as np

from cvrptw_bench.core.instance import VehicleType
from cvrptw_bench.generator.config import DemandCfg, FleetCfg, ServiceTimeCfg


def sample_demands(
    rng: np.random.Generator, n: int, cfg: DemandCfg, max_capacity: int
) -> np.ndarray:
    """Mixture of small and large orders; the number of large orders is exactly round(share*n)."""
    n_large = int(round(cfg.large_share * n))
    lo_s, hi_s = cfg.small_range
    lo_l, hi_l = cfg.large_range
    if hi_l > max_capacity:
        raise ValueError(f"large orders up to {hi_l} exceed the largest capacity {max_capacity}")
    d = np.empty(n, dtype=np.int64)
    d[:] = rng.integers(lo_s, hi_s + 1, n)
    if n_large:
        idx = rng.choice(n, n_large, replace=False)
        d[idx] = rng.integers(lo_l, hi_l + 1, n_large)
    return d


def service_times(demand: np.ndarray, cfg: ServiceTimeCfg) -> np.ndarray:
    return np.rint(cfg.base_s + cfg.per_unit_s * demand).astype(np.int64)


def fleet_candidates(fleet: FleetCfg, max_blocks: int) -> list[tuple[int, list[int]]]:
    """(capacity, counts per type) for b full blocks plus any partial block, b = 0..max_blocks.

    A partial block is any combination with at most ``mix[k]`` extra vehicles of type k
    (granularity = smallest capacity). Candidates without a vehicle of the largest type
    are dropped so the biggest order always fits somewhere.
    """
    import itertools

    T = len(fleet.types)
    largest = max(range(T), key=lambda k: fleet.types[k].capacity)
    out: list[tuple[int, list[int]]] = []
    seen: set[tuple[int, ...]] = set()
    for b in range(max_blocks + 1):
        for extra in itertools.product(*(range(fleet.mix[k] + 1) for k in range(T))):
            counts = [b * fleet.mix[k] + extra[k] for k in range(T)]
            key = tuple(counts)
            if key in seen or counts[largest] < 1 or sum(counts) == 0:
                continue
            seen.add(key)
            cap = sum(fleet.types[k].capacity * c for k, c in enumerate(counts))
            out.append((cap, counts))
    return out


def size_fleet(total_demand: int, stress_pct: int, fleet: FleetCfg) -> list[VehicleType]:
    """Vehicle counts per type whose total capacity best matches total_demand / stress."""
    target = total_demand / (stress_pct / 100.0)
    max_blocks = int(target // fleet.block_capacity) + 1
    cands = fleet_candidates(fleet, max_blocks)
    if stress_pct > 100:
        pool = [c for c in cands if c[0] < total_demand]  # really over-subscribed
    else:
        pool = [c for c in cands if c[0] >= total_demand]  # feasible by capacity
    chosen = min(pool or cands, key=lambda c: abs(c[0] - target))
    _, counts = chosen
    return [
        VehicleType(
            type=t.type,
            capacity=t.capacity,
            count=c,
            fixed_cost=t.fixed_cost,
            cost_per_km=t.cost_per_km,
        )
        for t, c in zip(fleet.types, counts, strict=True)
    ]

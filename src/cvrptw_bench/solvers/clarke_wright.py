"""Clarke-Wright savings for the CVRPTW with a heterogeneous, limited fleet.

Plain-language version: start with one route per customer (depot → i → depot).
For every pair (i, j) where i is the last stop of one route and j the first
stop of another, compute how much we save by driving i → j instead of going
back to the depot in between. Take the pairs from the largest saving down and
join the two routes whenever the joined route still fits in *some* vehicle
type and every stop can still be reached inside its window (an O(1) check
thanks to the earliest departure from i and the latest feasible start at j).

Two departures from the textbook, both forced by the problem:

* **Coverage first.** While there are more routes than vehicles, every feasible
  merge is taken (even with a negative saving) because fewer routes means more
  customers on the limited fleet. Once routes ≤ vehicles, a merge is taken only
  if it lowers the real cost (fixed cost + per-km cost of the vehicle types the
  loads imply), so distance savings cannot push two cheap vans into one
  expensive truck.
* **Types and availability come after the merges.** Each final route gets the
  smallest available type that fits its load, largest routes (in customers)
  first; routes left without a vehicle are dismantled and their customers are
  re-inserted at the cheapest feasible position (possibly upgrading a route's
  vehicle, or opening a route on a spare vehicle). What still does not fit is
  unserved.

Multi-start: run 0 is the deterministic classic (λ = 1); the others draw
λ ~ U[lo, hi] and perturb every saving by U[1−ε, 1+ε]; the best plan by
(served, −cost) wins. ``cw`` runs a fixed number of starts (20) within the
common time limit and usually finishes in seconds — its wall time is reported
as such; the limit is a cap shared by every solver, not a target.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import Matrices
from cvrptw_bench.core.solution import RoutePlan
from cvrptw_bench.solvers.base import ProgressCallback, Solver, SolverConfig, register
from cvrptw_bench.solvers.routes import Fleet, VehicleRoute

DEFAULTS = {
    "multistart_runs": 20,
    "lambda_range": (0.6, 1.4),
    "savings_noise": 0.10,
    "neighbours": 30,
}


# ------------------------------------------------------------- merge phase
@dataclass
class _Route:
    seq: list[int]
    load: int
    dist: int  # depot -> ... -> depot, meters
    dep_last: int  # earliest departure from the last stop (departure from depot at h0)
    L_first: int  # latest feasible service start at the first stop


@dataclass
class CWState:
    """Result of one constructive run: assigned routes, fleet ledger, unserved."""

    routes: list[VehicleRoute]
    fleet: Fleet
    unserved: list[int]
    lam: float
    seed: int

    @property
    def served(self) -> int:
        return sum(len(r.seq) for r in self.routes)

    @property
    def cost(self) -> int:
        return sum(r.cost() for r in self.routes)

    def plan(self) -> RoutePlan:
        return RoutePlan(routes={r.vehicle_id: list(r.seq) for r in self.routes if r.seq})


def _savings_pairs(m: Matrices, k: int, lam: float, rng: np.random.Generator | None, noise: float):
    """Directed candidate pairs (i, j) ordered by decreasing (perturbed) saving."""
    n = m.n
    nb = m.neighbours(k)[1:]  # (n, k_eff)
    k_eff = nb.shape[1]
    i_idx = np.repeat(np.arange(1, n + 1), k_eff)
    j_idx = nb.ravel()
    pairs = np.unique(
        np.concatenate([np.stack([i_idx, j_idx], 1), np.stack([j_idx, i_idx], 1)]), axis=0
    )
    ii, jj = pairs[:, 0], pairs[:, 1]
    d = m.dist_m
    sav = d[0, ii] + d[jj, 0] - lam * d[ii, jj]
    if rng is not None and noise > 0:
        sav = sav * rng.uniform(1.0 - noise, 1.0 + noise, sav.shape[0])
    order = np.argsort(-sav, kind="stable")
    return ii[order], jj[order]


def _smallest_type(fleet: Fleet, load: int) -> int | None:
    for kk in fleet.by_capacity:
        if fleet.capacity[kk] >= load:
            return kk
    return None


def _approx_cost(fleet: Fleet, rate: list[float], load: int, dist: int) -> float:
    """Fixed + per-km cost with the smallest type that fits the load (ignores availability)."""
    kk = _smallest_type(fleet, load)
    if kk is None:
        return float("inf")
    return fleet.fixed[kk] + rate[kk] * dist / 1000.0


def merge_routes(
    instance: Instance,
    m: Matrices,
    fleet: Fleet,
    lam: float,
    rng: np.random.Generator | None,
    noise: float,
    k: int,
) -> list[_Route]:
    n = m.n
    h0, h1 = instance.horizon.start, instance.horizon.end
    t = m.time_s
    d = m.dist_m
    cap_max = max(fleet.capacity)
    rate = [tp.cost_per_km for tp in instance.vehicle_types]
    n_vehicles = fleet.total_free()

    routes: dict[int, _Route] = {}
    route_of = [0] * (n + 1)
    for c in range(1, n + 1):
        dep_last = max(h0 + int(t[0, c]), int(m.tw_start[c])) + int(m.service[c])
        L_first = min(int(m.tw_end[c]), h1 - int(m.service[c]) - int(t[c, 0]))
        if dep_last + int(t[c, 0]) > h1 or L_first < m.tw_start[c]:
            # unreachable even alone (cannot happen with the generator); keep it as a route,
            # the repair step will drop it
            pass
        routes[c] = _Route([c], int(m.demand[c]), int(d[0, c] + d[c, 0]), dep_last, L_first)
        route_of[c] = c
    n_routes = n

    ii, jj = _savings_pairs(m, k, lam, rng, noise)
    for i, j in zip(ii.tolist(), jj.tolist(), strict=True):
        ra, rb = route_of[i], route_of[j]
        if ra == rb:
            continue
        A, B = routes[ra], routes[rb]
        if A.seq[-1] != i or B.seq[0] != j:
            continue
        load = A.load + B.load
        if load > cap_max:
            continue
        if A.dep_last + int(t[i, j]) > B.L_first:
            continue
        dist = A.dist + B.dist - int(d[i, 0]) - int(d[0, j]) + int(d[i, j])
        if n_routes <= n_vehicles:
            # fleet already suffices: merge only if the real cost goes down
            before = _approx_cost(fleet, rate, A.load, A.dist) + _approx_cost(
                fleet, rate, B.load, B.dist
            )
            if _approx_cost(fleet, rate, load, dist) >= before:
                continue
        # --- merge B after A
        tt = A.dep_last
        prev = i
        for c in B.seq:
            tt = max(tt + int(t[prev, c]), int(m.tw_start[c])) + int(m.service[c])
            prev = c
        limit = B.L_first
        nxt = j
        for c in reversed(A.seq):
            limit = min(int(m.tw_end[c]), limit - int(m.service[c]) - int(t[c, nxt]))
            nxt = c
        A.seq.extend(B.seq)
        A.load = load
        A.dist = dist
        A.dep_last = tt
        A.L_first = limit
        for c in B.seq:
            route_of[c] = ra
        del routes[rb]
        n_routes -= 1
    return list(routes.values())


# ------------------------------------------------------ assignment & repair
def assign_and_repair(
    instance: Instance, m: Matrices, raw_routes: list[list[int]], fleet: Fleet | None = None
) -> tuple[list[VehicleRoute], Fleet, list[int]]:
    """Give every route the smallest available type that fits; re-insert what is left over.

    Routes are served largest-first (customers, then load) because the primary
    objective is coverage. Leftover customers, largest demand first, go to the
    cheapest feasible option among: insertion into an assigned route (with its
    current vehicle, or upgraded to the smallest free type that fits), or a new
    route on the smallest free vehicle that fits. Whatever finds no option is
    unserved.
    """
    fleet = fleet or Fleet(instance)
    h0, h1 = instance.horizon.start, instance.horizon.end
    loads = [int(m.demand[seq].sum()) for seq in raw_routes]
    order = sorted(range(len(raw_routes)), key=lambda r: (-len(raw_routes[r]), -loads[r]))
    routes: list[VehicleRoute] = []
    leftover: list[int] = []
    for r in order:
        kk = fleet.smallest_free_type(loads[r])
        if kk is None:
            leftover.extend(raw_routes[r])
            continue
        vid = fleet.take(kk)
        vr = VehicleRoute(m, raw_routes[r], vid, kk, fleet.capacity[kk], fleet.fixed[kk], h0, h1)
        if not vr.feasible:  # should not happen: merges preserve feasibility
            fleet.release(vid)
            leftover.extend(raw_routes[r])
            continue
        routes.append(vr)
    unserved = insert_leftovers(instance, m, routes, fleet, leftover)
    return routes, fleet, unserved


def insert_leftovers(
    instance: Instance,
    m: Matrices,
    routes: list[VehicleRoute],
    fleet: Fleet,
    leftover: list[int],
) -> list[int]:
    h0, h1 = instance.horizon.start, instance.horizon.end
    unserved: list[int] = []
    for c in sorted(leftover, key=lambda c: (-int(m.demand[c]), int(m.tw_end[c] - m.tw_start[c]))):
        dc = int(m.demand[c])
        best: tuple[int, str, int, int, int] | None = None  # (delta, kind, route idx, pos, type)
        for r_idx, r in enumerate(routes):
            if r.load + dc <= r.capacity:
                res = r.best_insertion(c, m.cost[r.type_index])
                if res is not None and (best is None or res[0] < best[0]):
                    best = (res[0], "insert", r_idx, res[1], r.type_index)
                continue
            # capacity short: would a bigger free vehicle make it fit?
            kk = fleet.smallest_free_type(r.load + dc)
            if kk is None:
                continue
            saved_cap = r.capacity
            r.capacity = fleet.capacity[kk]
            res = r.best_insertion(c, m.cost[kk])
            r.capacity = saved_cap
            if res is None:
                continue
            path = [0, *r.seq, 0]
            new_cost = fleet.fixed[kk] + int(m.cost[kk, path[:-1], path[1:]].sum()) + res[0]
            delta = new_cost - r.cost()
            if best is None or delta < best[0]:
                best = (delta, "upgrade", r_idx, res[1], kk)
        kk = fleet.smallest_free_type(dc)
        if kk is not None:
            start = max(h0 + int(m.time_s[0, c]), int(m.tw_start[c]))
            if start <= m.tw_end[c] and start + int(m.service[c]) + int(m.time_s[c, 0]) <= h1:
                delta = fleet.fixed[kk] + int(m.cost[kk, 0, c] + m.cost[kk, c, 0])
                if best is None or delta < best[0]:
                    best = (delta, "new", -1, 0, kk)
        if best is None:
            unserved.append(c)
            continue
        _, kind, r_idx, pos, kk = best
        if kind == "insert":
            routes[r_idx].insert(c, pos)
        elif kind == "upgrade":
            r = routes[r_idx]
            fleet.release(r.vehicle_id)
            r.assign_vehicle(fleet, fleet.take(kk))
            r.insert(c, pos)
        else:
            vid = fleet.take(kk)
            routes.append(
                VehicleRoute(m, [c], vid, kk, fleet.capacity[kk], fleet.fixed[kk], h0, h1)
            )
    return unserved


# -------------------------------------------------------------- multi-start
def construct(
    instance: Instance,
    m: Matrices,
    lam: float = 1.0,
    seed: int | None = None,
    noise: float = 0.0,
    k: int = 30,
) -> CWState:
    rng = np.random.default_rng(seed) if seed is not None else None
    fleet = Fleet(instance)
    merged = merge_routes(instance, m, fleet, lam, rng, noise, k)
    routes, fleet, unserved = assign_and_repair(instance, m, [r.seq for r in merged], fleet)
    return CWState(routes, fleet, unserved, lam, seed if seed is not None else -1)


def multistart(
    instance: Instance,
    m: Matrices,
    config: SolverConfig,
    report: ProgressCallback | None = None,
    t0: float | None = None,
    keep_all: bool = False,
) -> CWState | list[CWState]:
    """Best constructive state (or, with ``keep_all``, all of them sorted best first)."""
    p = {**DEFAULTS, **config.params}
    runs = int(p["multistart_runs"])
    budget = float(config.time_limit_s)  # the same cap every solver gets
    lo, hi = p["lambda_range"]
    noise = float(p["savings_noise"])
    k = int(p["neighbours"])
    t0 = time.perf_counter() if t0 is None else t0
    rng = np.random.default_rng(config.seed)

    best: CWState | None = None
    states: list[CWState] = []
    for run in range(max(1, runs)):
        if run > 0 and time.perf_counter() - t0 > budget:
            break
        if run == 0:
            state = construct(instance, m, lam=1.0, seed=None, noise=0.0, k=k)
        else:
            lam = float(rng.uniform(lo, hi))
            state = construct(
                instance, m, lam=lam, seed=int(rng.integers(2**31 - 1)), noise=noise, k=k
            )
        states.append(state)
        key = (state.served, -state.cost)
        if best is None or key > (best.served, -best.cost):
            best = state
            if report is not None:
                report(time.perf_counter() - t0, state.served, state.cost)
    assert best is not None
    if keep_all:
        return sorted(states, key=lambda s: (-s.served, s.cost))
    return best


@register
class ClarkeWrightSolver(Solver):
    name = "cw"
    version = "0.1.0"

    def _solve(self, instance, matrices, config, report):
        state = multistart(instance, matrices, config, report)
        return state.plan()

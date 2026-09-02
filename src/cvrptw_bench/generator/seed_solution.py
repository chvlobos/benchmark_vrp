"""Reference ("seed") solution used to place time windows.

A sweep heuristic builds routes on the *real* fleet, then on *virtual* large
vehicles for whatever does not fit. Windows are later centred on the arrival
times of these routes, so a customer is never unreachable by construction, a
full-coverage solution exists whenever the real fleet took everybody, and the
customers on virtual vehicles are infeasible only because of the fleet.

Steps (PLAN.md §4.4):

A. Sweep: customers sorted by angle around the depot from a random start;
   real vehicles taken in a repeating pattern mirroring the fleet mix, smallest
   type first inside each block (small, small, small, medium, medium, large,
   ...) so that small vehicles fill up on small orders and the big orders are
   deferred to medium/large vehicles; each vehicle takes consecutive customers
   while capacity and a route-duration cap hold. Every route is then re-ordered
   with nearest-neighbour + 2-opt (angular order zigzags radially).
B. Repair (no windows yet): deferred and remaining customers, largest first,
   go to the cheapest feasible insertion in a real route, else open a route on
   an unused real vehicle, else they are virtual.
C. Virtual customers are swept onto virtual large vehicles under the same cap.
D. Every route gets a random departure offset within its slack so the windows
   spread over the day; arrivals are computed without waiting.

After the windows exist, :func:`post_window_repair` tries once more to insert
virtual customers into real routes, now against the actual windows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from cvrptw_bench.core.insertion import RouteSchedule
from cvrptw_bench.core.instance import Instance, Vehicle
from cvrptw_bench.core.matrices import Matrices
from cvrptw_bench.generator.geo import KM_PER_DEG_LAT, km_per_deg_lon


@dataclass
class SeedRoute:
    vehicle_id: int  # real vehicle id, or -1 for virtual
    type_index: int
    capacity: int
    seq: list[int] = field(default_factory=list)
    load: int = 0
    travel_s: int = 0  # depot -> ... -> last (no return)
    service_s: int = 0

    def duration_with_return(self, m: Matrices) -> int:
        last = self.seq[-1] if self.seq else 0
        return self.travel_s + int(m.time_s[last, 0]) + self.service_s


@dataclass
class SeedSolution:
    routes: list[SeedRoute]  # real then virtual
    departures: dict[int, int]  # route index -> departure time
    arrival: np.ndarray  # (n+1,) arrival time per customer in the seed schedule
    n_virtual: int
    busy_s: int  # total travel + service over all routes (real + virtual)

    def real_routes(self) -> list[SeedRoute]:
        return [r for r in self.routes if r.vehicle_id >= 0]

    def virtual_routes(self) -> list[SeedRoute]:
        return [r for r in self.routes if r.vehicle_id < 0]


# ------------------------------------------------------------------ helpers
def _vehicle_pattern(instance: Instance, mix: list[int], large_first: bool) -> list[Vehicle]:
    """Real vehicles ordered in repeating blocks that mirror the fleet mix."""
    by_type: dict[int, list[Vehicle]] = {}
    for v in instance.vehicles():
        by_type.setdefault(v.type_index, []).append(v)
    sign = -1 if large_first else 1
    order = sorted(by_type, key=lambda k: sign * instance.vehicle_types[k].capacity)
    out: list[Vehicle] = []
    while any(by_type[k] for k in order):
        for k in order:
            take = mix[k] if k < len(mix) else 1
            for _ in range(take):
                if by_type[k]:
                    out.append(by_type[k].pop(0))
    return out


def _fits(route: SeedRoute, c: int, m: Matrices, t_max: int) -> bool:
    if route.load + int(m.demand[c]) > route.capacity:
        return False
    last = route.seq[-1] if route.seq else 0
    dur = (
        route.travel_s
        + int(m.time_s[last, c])
        + int(m.time_s[c, 0])
        + route.service_s
        + int(m.service[c])
    )
    return dur <= t_max


def _append(route: SeedRoute, c: int, m: Matrices) -> None:
    last = route.seq[-1] if route.seq else 0
    route.travel_s += int(m.time_s[last, c])
    route.service_s += int(m.service[c])
    route.load += int(m.demand[c])
    route.seq.append(c)


def _cheapest_insertion(
    route: SeedRoute, c: int, m: Matrices, t_max: int
) -> tuple[int, int] | None:
    """(delta_travel, position) of the cheapest insertion within the duration cap, or None."""
    if route.load + int(m.demand[c]) > route.capacity:
        return None
    path = [0, *route.seq, 0]
    best: tuple[int, int] | None = None
    for pos in range(len(route.seq) + 1):
        a, b = path[pos], path[pos + 1]
        delta = int(m.time_s[a, c] + m.time_s[c, b] - m.time_s[a, b])
        if best is None or delta < best[0]:
            best = (delta, pos)
    assert best is not None
    if route.duration_with_return(m) + best[0] + int(m.service[c]) > t_max:
        return None
    return best


def _insert(route: SeedRoute, c: int, pos: int, m: Matrices) -> None:
    route.seq.insert(pos, c)
    route.load += int(m.demand[c])
    route.service_s += int(m.service[c])
    path = [0, *route.seq]
    route.travel_s = int(sum(m.time_s[path[i], path[i + 1]] for i in range(len(path) - 1)))


def improve_order(seq: list[int], m: Matrices) -> list[int]:
    """Nearest-neighbour from the depot, then 2-opt (first improvement) on travel time."""
    if len(seq) < 3:
        return list(seq)
    t = m.time_s
    remaining = set(seq)
    cur = 0
    out: list[int] = []
    while remaining:
        nxt = min(remaining, key=lambda c: t[cur, c])
        out.append(nxt)
        remaining.remove(nxt)
        cur = nxt
    path = [0, *out, 0]
    improved = True
    while improved:
        improved = False
        for i in range(1, len(path) - 2):
            for j in range(i + 1, len(path) - 1):
                a, b, c, d = path[i - 1], path[i], path[j], path[j + 1]
                if t[a, c] + t[b, d] < t[a, b] + t[c, d]:
                    path[i : j + 1] = path[i : j + 1][::-1]
                    improved = True
    return path[1:-1]


def _reorder(route: SeedRoute, m: Matrices) -> None:
    route.seq = improve_order(route.seq, m)
    path = [0, *route.seq]
    route.travel_s = int(sum(m.time_s[path[i], path[i + 1]] for i in range(len(path) - 1)))


def angular_order(m: Matrices, rng: np.random.Generator) -> list[int]:
    dlat = (m.lat[1:] - m.lat[0]) * KM_PER_DEG_LAT
    dlon = (m.lon[1:] - m.lon[0]) * km_per_deg_lon(float(m.lat[0]))
    ang = np.arctan2(dlat, dlon)
    start = rng.uniform(-math.pi, math.pi)
    return [int(i) + 1 for i in np.argsort((ang - start) % (2 * math.pi), kind="stable")]


# ------------------------------------------------------------------- build
def build_seed_solution(
    instance: Instance,
    m: Matrices,
    rng: np.random.Generator,
    mix: list[int],
    duration_margin_frac: float,
    large_first: bool = False,
) -> SeedSolution:
    n = instance.n
    h0, h1 = instance.horizon.start, instance.horizon.end
    horizon = h1 - h0
    t_max = int((1.0 - duration_margin_frac) * horizon)
    order = angular_order(m, rng)
    vehicles = _vehicle_pattern(instance, mix, large_first)
    largest = max(
        range(len(instance.vehicle_types)), key=lambda k: instance.vehicle_types[k].capacity
    )
    largest_cap = instance.vehicle_types[largest].capacity

    # A. sweep over the real fleet
    routes: list[SeedRoute] = []
    leftover: list[int] = []
    ptr = 0
    for v in vehicles:
        if ptr >= n:
            break
        route = SeedRoute(v.id, v.type_index, v.capacity)
        while ptr < n:
            c = order[ptr]
            if int(m.demand[c]) > route.capacity:
                leftover.append(c)
                ptr += 1
                continue
            if not _fits(route, c, m, t_max):
                if not route.seq:
                    leftover.append(c)
                    ptr += 1
                    continue
                break
            _append(route, c, m)
            ptr += 1
        if route.seq:
            routes.append(route)
    leftover.extend(order[ptr:])
    for r in routes:
        _reorder(r, m)  # sweep sectors visited in angular order zigzag radially; fix that
    used = {r.vehicle_id for r in routes}
    unused = [v for v in vehicles if v.id not in used]

    # B. repair: cheapest insertion, else a new route on an unused vehicle, else virtual
    virtual_customers: list[int] = []
    for c in sorted(leftover, key=lambda c: -int(m.demand[c])):
        best: tuple[int, int, int] | None = None
        for r_idx, r in enumerate(routes):
            res = _cheapest_insertion(r, c, m, t_max)
            if res is not None and (best is None or res[0] < best[0]):
                best = (res[0], r_idx, res[1])
        if best is not None:
            _insert(routes[best[1]], c, best[2], m)
            continue
        cand = [v for v in unused if v.capacity >= int(m.demand[c])]
        if cand:
            v = min(cand, key=lambda v: v.capacity)
            unused.remove(v)
            r = SeedRoute(v.id, v.type_index, v.capacity)
            _append(r, c, m)
            routes.append(r)
            continue
        virtual_customers.append(c)
    for r in routes:
        _reorder(r, m)

    # C. virtual customers on virtual large vehicles, in angular order
    n_virtual = 0
    pos_in_order = {c: i for i, c in enumerate(order)}
    virtual_customers.sort(key=lambda c: pos_in_order[c])
    ptr = 0
    while ptr < len(virtual_customers):
        r = SeedRoute(-1, largest, largest_cap)
        n_virtual += 1
        while ptr < len(virtual_customers):
            c = virtual_customers[ptr]
            if not _fits(r, c, m, t_max) and r.seq:
                break
            _append(r, c, m)
            ptr += 1
        _reorder(r, m)
        routes.append(r)

    return _schedule(routes, m, rng, h0, horizon, n, n_virtual)


def _schedule(
    routes: list[SeedRoute],
    m: Matrices,
    rng: np.random.Generator,
    h0: int,
    horizon: int,
    n: int,
    n_virtual: int,
) -> SeedSolution:
    """D. departure offsets and arrival times (no waiting: there are no windows yet)."""
    arrival = np.zeros(n + 1, dtype=np.int64)
    departures: dict[int, int] = {}
    busy = 0
    for r_idx, r in enumerate(routes):
        dur = r.duration_with_return(m)
        busy += dur
        slack = max(0, horizon - dur)
        dep = h0 + int(rng.integers(0, slack + 1))
        departures[r_idx] = dep
        t = dep
        prev = 0
        for c in r.seq:
            t += int(m.time_s[prev, c])
            arrival[c] = t
            t += int(m.service[c])
            prev = c
    return SeedSolution(routes, departures, arrival, n_virtual, busy)


# -------------------------------------------------------- post-window pass
def post_window_repair(
    instance: Instance, m: Matrices, seed: SeedSolution
) -> tuple[dict[int, list[int]], list[int], int]:
    """Insert virtual customers into real routes against the actual windows.

    Returns (real routes by vehicle id, remaining virtual customers, busy seconds
    of the final real routes + a dedicated round trip per remaining customer).
    """
    h0, h1 = instance.horizon.start, instance.horizon.end
    vehicles = {v.id: v for v in instance.vehicles()}
    real: dict[int, RouteSchedule] = {
        r.vehicle_id: RouteSchedule(m, r.seq, r.capacity, h0, h1) for r in seed.real_routes()
    }
    unused = [v for vid, v in vehicles.items() if vid not in real]
    remaining: list[int] = []
    virtual = [c for r in seed.virtual_routes() for c in r.seq]
    for c in sorted(virtual, key=lambda c: -int(m.demand[c])):
        best: tuple[int, int, int] | None = None
        for vid, rs in real.items():
            res = rs.best_insertion(c)
            if res is not None and (best is None or res[0] < best[0]):
                best = (res[0], vid, res[1])
        if best is not None:
            real[best[1]].insert(c, best[2])
            continue
        cand = [v for v in unused if v.capacity >= int(m.demand[c])]
        if cand:
            v = min(cand, key=lambda v: v.capacity)
            rs = RouteSchedule(m, [c], v.capacity, h0, h1)
            if rs.feasible:
                unused.remove(v)
                real[v.id] = rs
                continue
        remaining.append(c)
    busy = 0
    for rs in real.values():
        path = [0, *rs.seq, 0]
        busy += int(m.time_s[path[:-1], path[1:]].sum()) + int(m.service[rs.seq].sum())
    busy += sum(int(m.service[c]) + int(m.time_s[0, c]) + int(m.time_s[c, 0]) for c in remaining)
    return {vid: rs.seq for vid, rs in real.items() if rs.seq}, remaining, busy

"""Integer matrices shared by every solver and by the validator.

This module is the single source of distances, travel times and arc costs.
Rounding happens exactly once, here, so that Clarke-Wright, OR-Tools and
Hexaly optimise — and are judged on — identical numbers:

* ``dist_m[i, j]``  = round(haversine_km(i, j) * detour_factor * 1000)
* ``time_s[i, j]``  = round(dist_m[i, j] * 3.6 / speed_kmh)
* ``cost[t, i, j]`` = round(cost_per_km[t] * dist_m[i, j] / 1000)

Node 0 is the depot; node k (1..n) is customer with ``id == k``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from cvrptw_bench.core.instance import Instance

EARTH_RADIUS_KM = 6371.0088  # mean Earth radius (IUGG)


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km. Accepts scalars or broadcastable numpy arrays."""
    lat1, lon1, lat2, lon2 = (
        np.radians(np.asarray(x, dtype=float)) for x in (lat1, lon1, lat2, lon2)
    )
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


@dataclass
class Matrices:
    """Precomputed per-instance arrays. Index 0 is the depot."""

    n: int
    lat: np.ndarray  # (n+1,)
    lon: np.ndarray  # (n+1,)
    demand: np.ndarray  # (n+1,) int64, demand[0] = 0
    service: np.ndarray  # (n+1,) int64 seconds, service[0] = 0
    tw_start: np.ndarray  # (n+1,) int64, tw_start[0] = horizon.start
    tw_end: np.ndarray  # (n+1,) int64, tw_end[0] = horizon.end
    dist_m: np.ndarray  # (n+1, n+1) int64
    time_s: np.ndarray  # (n+1, n+1) int64
    cost: np.ndarray  # (T, n+1, n+1) int64, one matrix per vehicle type
    type_names: list[str] = field(default_factory=list)
    _neighbours: dict[int, np.ndarray] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------ accessors
    def arc_cost(self, type_index: int, i: int, j: int) -> int:
        return int(self.cost[type_index, i, j])

    def route_distance_m(self, seq: list[int]) -> int:
        """Depot -> seq -> depot distance in meters (0 for an empty route)."""
        if not seq:
            return 0
        path = [0, *seq, 0]
        return int(self.dist_m[path[:-1], path[1:]].sum())

    def route_arc_cost(self, type_index: int, seq: list[int]) -> int:
        if not seq:
            return 0
        path = [0, *seq, 0]
        return int(self.cost[type_index, path[:-1], path[1:]].sum())

    def neighbours(self, k: int) -> np.ndarray:
        """k nearest customers (by travel time) of every node, shape (n+1, k).

        Row 0 (depot) is included for convenience. Cached per k.
        """
        if k not in self._neighbours:
            k_eff = min(k, self.n - 1)
            t = self.time_s.astype(float).copy()
            np.fill_diagonal(t, np.inf)
            t[:, 0] = np.inf  # never propose the depot as a neighbour
            order = np.argsort(t, axis=1, kind="stable")[:, :k_eff]
            self._neighbours[k] = order.astype(np.int64)
        return self._neighbours[k]


def build_matrices(instance: Instance) -> Matrices:
    """Build the shared integer matrices for an instance (a few ms for n <= 600)."""
    n = instance.n
    lat = np.empty(n + 1)
    lon = np.empty(n + 1)
    demand = np.zeros(n + 1, dtype=np.int64)
    service = np.zeros(n + 1, dtype=np.int64)
    tw_start = np.empty(n + 1, dtype=np.int64)
    tw_end = np.empty(n + 1, dtype=np.int64)

    lat[0], lon[0] = instance.depot.lat, instance.depot.lon
    tw_start[0], tw_end[0] = instance.horizon.start, instance.horizon.end
    for c in instance.customers:
        lat[c.id], lon[c.id] = c.lat, c.lon
        demand[c.id] = c.demand
        service[c.id] = c.service_time
        tw_start[c.id], tw_end[c.id] = c.tw_start, c.tw_end

    km = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    dist_m = np.rint(km * instance.travel.detour_factor * 1000.0).astype(np.int64)
    np.fill_diagonal(dist_m, 0)
    time_s = np.rint(dist_m * 3.6 / instance.travel.speed_kmh).astype(np.int64)

    types = instance.vehicle_types
    cost = np.empty((len(types), n + 1, n + 1), dtype=np.int64)
    for k, t in enumerate(types):
        cost[k] = np.rint(t.cost_per_km * dist_m / 1000.0).astype(np.int64)

    return Matrices(
        n=n,
        lat=lat,
        lon=lon,
        demand=demand,
        service=service,
        tw_start=tw_start,
        tw_end=tw_end,
        dist_m=dist_m,
        time_s=time_s,
        cost=cost,
        type_names=[t.type for t in types],
    )

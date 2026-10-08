"""Solver-side bookkeeping: a fleet ledger and a vehicle-aware route.

Shared by the Clarke-Wright repair step and by the local search. The validator
has its own independent implementation of every rule used here.
"""

from __future__ import annotations

from cvrptw_bench.core.insertion import RouteSchedule
from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import Matrices


class Fleet:
    """Which vehicles are free, by type. Types are indexed in instance order."""

    def __init__(self, instance: Instance):
        self.types = instance.vehicle_types
        self.capacity = [t.capacity for t in self.types]
        self.fixed = [t.fixed_cost for t in self.types]
        self.type_of: dict[int, int] = {}
        self.free: dict[int, list[int]] = {k: [] for k in range(len(self.types))}
        for v in instance.vehicles():
            self.type_of[v.id] = v.type_index
            self.free[v.type_index].append(v.id)
        # types sorted by capacity ascending: "smallest that fits" scans this list
        self.by_capacity = sorted(range(len(self.types)), key=lambda k: self.capacity[k])

    def free_count(self, type_index: int) -> int:
        return len(self.free[type_index])

    def smallest_free_type(self, load: int, exclude: int | None = None) -> int | None:
        for k in self.by_capacity:
            if k == exclude or self.capacity[k] < load:
                continue
            if self.free[k]:
                return k
        return None

    def take(self, type_index: int) -> int:
        return self.free[type_index].pop()

    def release(self, vehicle_id: int) -> None:
        self.free[self.type_of[vehicle_id]].append(vehicle_id)

    def total_free(self) -> int:
        return sum(len(v) for v in self.free.values())


class VehicleRoute(RouteSchedule):
    """A RouteSchedule that knows which vehicle drives it and what it costs."""

    __slots__ = ("vehicle_id", "type_index", "fixed_cost")

    def __init__(
        self,
        m: Matrices,
        seq: list[int],
        vehicle_id: int,
        type_index: int,
        capacity: int,
        fixed_cost: int,
        h0: int,
        h1: int,
    ):
        self.vehicle_id = vehicle_id
        self.type_index = type_index
        self.fixed_cost = fixed_cost
        super().__init__(m, seq, capacity, h0, h1)

    def arc_cost(self) -> int:
        return self.m.route_arc_cost(self.type_index, self.seq)

    def cost(self) -> int:
        return (self.fixed_cost + self.arc_cost()) if self.seq else 0

    def assign_vehicle(self, fleet: Fleet, vehicle_id: int) -> None:
        k = fleet.type_of[vehicle_id]
        self.vehicle_id = vehicle_id
        self.type_index = k
        self.capacity = fleet.capacity[k]
        self.fixed_cost = fleet.fixed[k]


def segment_cost(m: Matrices, type_index: int, path: list[int]) -> int:
    """Sum of arc costs along ``path`` (consecutive pairs) for a vehicle type."""
    if len(path) < 2:
        return 0
    return int(m.cost[type_index, path[:-1], path[1:]].sum())

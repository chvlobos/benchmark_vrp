"""OR-Tools Routing adapter (solver ``ortools``).

Model (PLAN.md §7.1), on the shared integer matrices:

* nodes: 0 = depot, 1..n = customers; vehicles: the fleet expanded to individual
  vehicles, all starting and ending at the depot;
* cost: one transit matrix per vehicle type (``cost[t]``, CLP) registered in C++
  (no Python callbacks in the hot loop) and set per vehicle with
  ``SetArcCostEvaluatorOfVehicle``; ``SetFixedCostOfVehicle`` charges the fixed
  cost only if the vehicle is used — exactly the benchmark's cost model;
* capacity: one dimension, per-vehicle capacities from the type;
* time: cumul at a node = service start (seconds since midnight); transit
  i → j = service_i + travel_ij; slack = waiting (unbounded up to the horizon);
  customer cumuls inside their windows, vehicle start and end inside
  [opening, closing], start free (late departure allowed);
* unserved: one disjunction per customer with a uniform penalty larger than any
  possible routing cost, which makes "maximise served, then minimise cost"
  exact for the solver's objective;
* search: PATH_CHEAPEST_ARC + GUIDED_LOCAL_SEARCH, wall-clock limit = the common
  benchmark time limit; ``AddAtSolutionCallback`` records (elapsed, served, cost)
  for time-to-best and the convergence trace.
"""

from __future__ import annotations

import time

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import Matrices
from cvrptw_bench.core.solution import RoutePlan
from cvrptw_bench.solvers.base import ProgressCallback, Solver, SolverConfig, register

OT_DEFAULTS = {
    "first_solution": "PATH_CHEAPEST_ARC",
    "metaheuristic": "GUIDED_LOCAL_SEARCH",
    "log_search": False,
}


def drop_penalty(instance: Instance, m: Matrices) -> int:
    """A penalty per dropped customer that exceeds any achievable total routing cost.

    Upper bound on the routing cost of any plan: every vehicle's fixed cost, plus
    for every customer its most expensive outgoing arc, plus for every vehicle
    the most expensive arc out of the depot — all with the most expensive type.
    Twice that, plus one, so serving one more customer always beats any detour.
    """
    t_max = max(
        range(len(instance.vehicle_types)), key=lambda k: instance.vehicle_types[k].cost_per_km
    )
    c = m.cost[t_max]
    fixed = sum(t.fixed_cost * t.count for t in instance.vehicle_types)
    arcs = int(c[1:, :].max(axis=1).sum()) + instance.n_vehicles * int(c[0, :].max())
    return 2 * (fixed + arcs) + 1


def build_model(instance: Instance, m: Matrices):
    """Return (manager, routing, penalty)."""
    n = instance.n
    vehicles = instance.vehicles()
    V = len(vehicles)
    h0, h1 = instance.horizon.start, instance.horizon.end

    manager = pywrapcp.RoutingIndexManager(n + 1, V, 0)
    routing = pywrapcp.RoutingModel(manager)

    # --- cost per vehicle type (C++-side matrices) + fixed costs
    cost_cb = {}
    for k in range(len(instance.vehicle_types)):
        cost_cb[k] = routing.RegisterTransitMatrix(m.cost[k].tolist())
    for v in vehicles:
        routing.SetArcCostEvaluatorOfVehicle(cost_cb[v.type_index], v.id)
        routing.SetFixedCostOfVehicle(int(v.fixed_cost), v.id)

    # --- capacity
    demand_cb = routing.RegisterUnaryTransitVector(m.demand.tolist())
    routing.AddDimensionWithVehicleCapacity(
        demand_cb, 0, [int(v.capacity) for v in vehicles], True, "Capacity"
    )

    # --- time: transit = service at origin + travel; cumul = service start
    time_matrix = (m.time_s + m.service[:, None]).tolist()
    time_cb = routing.RegisterTransitMatrix(time_matrix)
    horizon = h1 - h0
    routing.AddDimension(time_cb, horizon, h1, False, "Time")
    time_dim = routing.GetDimensionOrDie("Time")
    for c in range(1, n + 1):
        idx = manager.NodeToIndex(c)
        time_dim.CumulVar(idx).SetRange(int(m.tw_start[c]), int(m.tw_end[c]))
    for v in vehicles:
        time_dim.CumulVar(routing.Start(v.id)).SetRange(h0, h1)
        time_dim.CumulVar(routing.End(v.id)).SetRange(h0, h1)
        # keep schedules tidy: leave as late as needed, come back as early as possible
        routing.AddVariableMaximizedByFinalizer(time_dim.CumulVar(routing.Start(v.id)))
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.End(v.id)))

    # --- optional customers, uniform penalty (lexicographic objective)
    penalty = drop_penalty(instance, m)
    for c in range(1, n + 1):
        routing.AddDisjunction([manager.NodeToIndex(c)], penalty)
    return manager, routing, penalty


def extract_plan(manager, routing, assignment, instance: Instance) -> RoutePlan:
    routes: dict[int, list[int]] = {}
    for v in range(instance.n_vehicles):
        idx = routing.Start(v)
        seq: list[int] = []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node != 0:
                seq.append(int(node))
            idx = assignment.Value(routing.NextVar(idx))
        if seq:
            routes[v] = seq
    return RoutePlan(routes=routes)


@register
class ORToolsSolver(Solver):
    name = "ortools"
    version = "0.1.0"

    def _solve(
        self,
        instance: Instance,
        matrices: Matrices,
        config: SolverConfig,
        report: ProgressCallback,
    ) -> RoutePlan:
        p = {**OT_DEFAULTS, **config.params}
        t0 = time.perf_counter()
        manager, routing, penalty = build_model(instance, matrices)
        n = instance.n

        # progress: served = customers whose next is not themselves; cost = objective - penalties
        node_index = [manager.NodeToIndex(c) for c in range(1, n + 1)]
        next_vars = [routing.NextVar(i) for i in node_index]

        best = {"obj": None}

        def on_solution() -> None:
            # fires for every accepted solution (GLS accepts worse ones too): keep improvements
            objective = routing.CostVar().Value()
            if best["obj"] is not None and objective >= best["obj"]:
                return
            best["obj"] = objective
            dropped = sum(1 for i, nv in zip(node_index, next_vars, strict=True) if nv.Value() == i)
            report(time.perf_counter() - t0, n - dropped, int(objective - penalty * dropped))

        routing.AddAtSolutionCallback(on_solution)

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = getattr(
            routing_enums_pb2.FirstSolutionStrategy, str(p["first_solution"])
        )
        params.local_search_metaheuristic = getattr(
            routing_enums_pb2.LocalSearchMetaheuristic, str(p["metaheuristic"])
        )
        budget = max(1.0, float(config.time_limit_s) - (time.perf_counter() - t0))
        params.time_limit.FromMilliseconds(int(budget * 1000))
        params.log_search = bool(p["log_search"])

        assignment = routing.SolveWithParameters(params)
        if assignment is None:
            raise RuntimeError(f"OR-Tools found no solution (status {routing.status()})")
        self.last_objective = int(assignment.ObjectiveValue())
        self.last_penalty = penalty
        return extract_plan(manager, routing, assignment, instance)

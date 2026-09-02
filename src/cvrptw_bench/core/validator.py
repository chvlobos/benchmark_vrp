"""Independent validator and evaluator.

A solver hands back a :class:`RoutePlan`; this module recomputes *everything*
from the instance and the shared matrices: schedules, loads, distances, costs,
metrics, and a diagnostic reason for every unserved customer. It is the only
judge used by the report, so a bug or an optimistic rounding inside a solver
can never show up as a better result.

Feasibility of a visiting order
-------------------------------
Waiting is free and unlimited and the departure time is free inside the
horizon, so a route is feasible iff the *earliest* forward schedule (leave the
depot at opening, wait when early) respects every deadline and returns before
closing. The reported departure time is then normalised (``departure_policy``):

* ``"min_wait"`` (default): the earliest departure that attains the minimum
  total waiting for that order — delay the departure by ``min(slack, waiting)``
  where ``slack`` is the forward time slack of the route (Savelsbergh). No
  pointless waiting at the first stops, and as much buffer as possible kept.
* ``"latest"``: the latest feasible departure (zero buffer at the binding stop).
* ``"earliest"``: leave at opening, wait wherever early.

Total waiting decreases one-for-one with the departure delay until it is
exhausted, so the ``min_wait`` delay is exact in one step.
"""

from __future__ import annotations

import platform
import sys
from collections import Counter
from dataclasses import dataclass
from importlib import metadata as importlib_metadata

import numpy as np

from cvrptw_bench.core.instance import Instance, Vehicle
from cvrptw_bench.core.matrices import Matrices, build_matrices
from cvrptw_bench.core.solution import (
    Compute,
    Route,
    RoutePlan,
    Solution,
    SolverRun,
    Stop,
    Unserved,
    Validation,
)

UNSERVED_REASONS = ("oversized", "unreachable_window", "insertable", "capacity", "time_window")


# ------------------------------------------------------------------ schedules
@dataclass
class Schedule:
    """Forward schedule of one route for a given departure time."""

    depart: int
    arrival: np.ndarray
    wait: np.ndarray
    start: np.ndarray
    departure: np.ndarray
    return_time: int
    travel_s: int


def forward_schedule(m: Matrices, seq: list[int], depart: int) -> Schedule:
    """Earliest schedule when leaving the depot at ``depart`` (waits when early)."""
    k = len(seq)
    arrival = np.empty(k, dtype=np.int64)
    wait = np.empty(k, dtype=np.int64)
    start = np.empty(k, dtype=np.int64)
    departure = np.empty(k, dtype=np.int64)
    t = depart
    prev = 0
    travel = 0
    for idx, c in enumerate(seq):
        leg = int(m.time_s[prev, c])
        travel += leg
        a = t + leg
        s = max(a, int(m.tw_start[c]))
        arrival[idx] = a
        wait[idx] = s - a
        start[idx] = s
        t = s + int(m.service[c])
        departure[idx] = t
        prev = c
    leg = int(m.time_s[prev, 0]) if k else 0
    travel += leg
    return Schedule(depart, arrival, wait, start, departure, t + leg, travel)


def latest_starts(m: Matrices, seq: list[int], horizon_end: int) -> np.ndarray:
    """Latest feasible service start at each stop (backward pass).

    ``L[k] = min(tw_end[c_k], L[k+1] - service[c_k] - travel(c_k, c_{k+1}))`` with
    the depot closing time as the anchor. If ``L[k] < tw_start[c_k]`` the order is
    infeasible from stop k onwards. Used for O(1) insertion feasibility checks.
    """
    k = len(seq)
    L = np.empty(k, dtype=np.int64)
    nxt_limit = horizon_end  # latest arrival at the next node (the depot)
    nxt = 0
    for idx in range(k - 1, -1, -1):
        c = seq[idx]
        L[idx] = min(int(m.tw_end[c]), nxt_limit - int(m.service[c]) - int(m.time_s[c, nxt]))
        nxt_limit = L[idx]
        nxt = c
    return L


def latest_departure(m: Matrices, seq: list[int], horizon_start: int, horizon_end: int) -> int:
    """Latest depot departure keeping the order feasible (may be < horizon_start if infeasible)."""
    if not seq:
        return horizon_start
    L = latest_starts(m, seq, horizon_end)
    return min(horizon_end, int(L[0]) - int(m.time_s[0, seq[0]]))


def is_feasible_order(m: Matrices, seq: list[int], horizon_start: int, horizon_end: int) -> bool:
    return latest_departure(m, seq, horizon_start, horizon_end) >= horizon_start


DEPARTURE_POLICIES = ("min_wait", "latest", "earliest")


def normalised_departure(
    m: Matrices, seq: list[int], horizon_start: int, horizon_end: int, policy: str = "min_wait"
) -> int:
    """Departure time to report for a feasible order, according to ``policy``."""
    if policy == "earliest" or not seq:
        return horizon_start
    latest = latest_departure(m, seq, horizon_start, horizon_end)
    if policy == "latest":
        return max(horizon_start, latest)
    if policy == "min_wait":
        waiting = int(forward_schedule(m, seq, horizon_start).wait.sum())
        return horizon_start + max(0, min(latest - horizon_start, waiting))
    raise ValueError(f"unknown departure policy '{policy}', expected one of {DEPARTURE_POLICIES}")


# ----------------------------------------------------------------- evaluation
@dataclass
class _RouteState:
    vehicle: Vehicle
    seq: list[int]
    load: int
    sched: Schedule  # earliest schedule (departure at opening)
    L: np.ndarray  # latest starts
    feasible: bool


def _host_info() -> tuple[str, str, dict[str, str]]:
    host = f"{platform.system()} {platform.machine()} ({platform.processor() or 'cpu'})"
    py = sys.version.split()[0]
    pk: dict[str, str] = {}
    for name in ("numpy", "ortools", "hexaly"):
        try:
            pk[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            pass
    return host, py, pk


def evaluate(
    instance: Instance,
    plan: RoutePlan,
    run: SolverRun | None = None,
    matrices: Matrices | None = None,
    departure_policy: str = "min_wait",
) -> Solution:
    """Turn a plan into a fully evaluated, validated :class:`Solution`."""
    if departure_policy not in DEPARTURE_POLICIES:
        raise ValueError(f"departure_policy must be one of {DEPARTURE_POLICIES}")
    m = matrices if matrices is not None else build_matrices(instance)
    run = run or SolverRun(solver="unknown")
    vehicles = instance.vehicles()
    h0, h1 = instance.horizon.start, instance.horizon.end
    n = instance.n

    violations: list[str] = []
    seen: Counter[int] = Counter()
    states: list[_RouteState] = []

    for vid in sorted(plan.routes):
        raw = plan.routes[vid]
        if not raw:
            continue
        if vid < 0 or vid >= len(vehicles):
            violations.append(
                f"unknown_vehicle: vehicle {vid} does not exist (fleet has {len(vehicles)})"
            )
            continue
        seq: list[int] = []
        for c in raw:
            if c < 1 or c > n:
                violations.append(f"unknown_customer: vehicle {vid} visits customer {c} (n={n})")
                continue
            seen[c] += 1
            seq.append(int(c))
        if not seq:
            continue
        veh = vehicles[vid]
        load = int(m.demand[seq].sum())
        if load > veh.capacity:
            violations.append(
                f"capacity: vehicle {vid} ({veh.type}) carries {load} > capacity {veh.capacity}"
            )
        sched = forward_schedule(m, seq, h0)
        feasible = True
        for idx, c in enumerate(seq):
            if sched.start[idx] > m.tw_end[c]:
                feasible = False
                violations.append(
                    f"time_window: vehicle {vid} starts service at customer {c} at "
                    f"{int(sched.start[idx])} > tw_end {int(m.tw_end[c])}"
                )
        if sched.return_time > h1:
            feasible = False
            violations.append(
                f"horizon: vehicle {vid} returns at {sched.return_time} > closing {h1}"
            )
        states.append(_RouteState(veh, seq, load, sched, latest_starts(m, seq, h1), feasible))

    for c, k in seen.items():
        if k > 1:
            violations.append(f"duplicate_customer: customer {c} visited {k} times")

    # ------------------------------------------------------------- routes out
    routes_out: list[Route] = []
    tot_travel = tot_wait = tot_service = tot_route = 0
    tot_dist = tot_fixed = tot_var = 0
    slack_min: list[float] = []
    used_by_type: Counter[str] = Counter()
    utilisation: list[float] = []
    for st in states:
        sched = st.sched
        if st.feasible:
            dep = normalised_departure(m, st.seq, h0, h1, departure_policy)
            if dep > h0:
                sched = forward_schedule(m, st.seq, dep)
        dist = m.route_distance_m(st.seq)
        var = m.route_arc_cost(st.vehicle.type_index, st.seq)
        fixed = st.vehicle.fixed_cost
        stops = [
            Stop(
                customer=c,
                arrival=int(sched.arrival[i]),
                wait=int(sched.wait[i]),
                service_start=int(sched.start[i]),
                departure=int(sched.departure[i]),
            )
            for i, c in enumerate(st.seq)
        ]
        routes_out.append(
            Route(
                vehicle_id=st.vehicle.id,
                vehicle_type=st.vehicle.type,
                depart=sched.depart,
                return_time=sched.return_time,
                load=st.load,
                capacity=st.vehicle.capacity,
                distance_m=dist,
                fixed_cost=fixed,
                variable_cost=var,
                cost=fixed + var,
                stops=stops,
            )
        )
        tot_travel += sched.travel_s
        tot_wait += int(sched.wait.sum())
        tot_service += int(m.service[st.seq].sum())
        tot_route += sched.return_time - sched.depart
        tot_dist += dist
        tot_fixed += fixed
        tot_var += var
        used_by_type[st.vehicle.type] += 1
        utilisation.append(st.load / st.vehicle.capacity)
        slack_min.extend(((m.tw_end[st.seq] - sched.start) / 60.0).tolist())

    # --------------------------------------------------------------- unserved
    served_ids = set(seen)
    unserved_ids = [c for c in range(1, n + 1) if c not in served_ids]
    unserved_out = [
        Unserved(
            customer=c,
            demand=int(m.demand[c]),
            tw_start=int(m.tw_start[c]),
            tw_end=int(m.tw_end[c]),
            reason=_classify_unserved(instance, m, states, vehicles, c),
        )
        for c in unserved_ids
    ]
    reason_counts = Counter(u.reason for u in unserved_out)

    served = len(served_ids)
    total_cost = tot_fixed + tot_var
    metrics = {
        "served": served,
        "unserved": len(unserved_ids),
        "served_demand": int(m.demand[list(served_ids)].sum()) if served_ids else 0,
        "unserved_demand": int(m.demand[unserved_ids].sum()) if unserved_ids else 0,
        "unserved_by_reason": {r: reason_counts.get(r, 0) for r in UNSERVED_REASONS},
        "total_cost": total_cost,
        "fixed_cost": tot_fixed,
        "variable_cost": tot_var,
        "distance_km": round(tot_dist / 1000.0, 3),
        "vehicles_used": {t.type: used_by_type.get(t.type, 0) for t in instance.vehicle_types},
        "vehicles_available": {t.type: t.count for t in instance.vehicle_types},
        "vehicles_used_total": len(states),
        "route_time_h": round(tot_route / 3600.0, 3),
        "travel_h": round(tot_travel / 3600.0, 3),
        "wait_h": round(tot_wait / 3600.0, 3),
        "service_h": round(tot_service / 3600.0, 3),
        "capacity_utilisation_mean": round(float(np.mean(utilisation)), 4) if utilisation else 0.0,
        "stops_per_vehicle_mean": round(served / len(states), 3) if states else 0.0,
        "tw_slack_mean_min": round(float(np.mean(slack_min)), 2) if slack_min else 0.0,
        "objective": [served, total_cost],
    }

    host, py, pk = _host_info()
    return Solution(
        instance=instance.name,
        solver=run.solver,
        solver_version=run.solver_version,
        config=run.config,
        seed=run.seed,
        status=run.status,
        message=run.message,
        compute=Compute(
            wall_time_s=run.wall_time_s,
            time_to_best_s=run.time_to_best_s,
            threads=run.threads,
            host=host,
            python=py,
            packages=pk,
        ),
        plan_routes={int(v): [int(c) for c in seq] for v, seq in plan.routes.items() if seq},
        routes=routes_out,
        unserved=unserved_out,
        metrics=metrics,
        validation=Validation(valid=not violations, violations=violations),
        trace=run.trace,
    )


def _classify_unserved(
    instance: Instance,
    m: Matrices,
    states: list[_RouteState],
    vehicles: list[Vehicle],
    c: int,
) -> str:
    """Post-hoc diagnosis of why customer ``c`` is not in the solution.

    Order of the tests matters; see PLAN.md §8.2.
    """
    h0, h1 = instance.horizon.start, instance.horizon.end
    d = int(m.demand[c])
    if d > max(v.capacity for v in vehicles):
        return "oversized"

    # Can the customer be served alone by a dedicated vehicle, ignoring the fleet?
    start_alone = max(h0 + int(m.time_s[0, c]), int(m.tw_start[c]))
    if start_alone > m.tw_end[c] or start_alone + int(m.service[c]) + int(m.time_s[c, 0]) > h1:
        return "unreachable_window"

    used = {st.vehicle.id for st in states}
    if any(v.capacity >= d for v in vehicles if v.id not in used):
        return "insertable"  # a spare vehicle could do a dedicated route

    any_capacity_room = False
    for st in states:
        if not st.feasible or st.load + d > st.vehicle.capacity:
            continue
        any_capacity_room = True
        seq, sched, L = st.seq, st.sched, st.L
        k = len(seq)
        for pos in range(k + 1):
            prev_dep = h0 if pos == 0 else int(sched.departure[pos - 1])
            prev = 0 if pos == 0 else seq[pos - 1]
            arrival = prev_dep + int(m.time_s[prev, c])
            start = max(arrival, int(m.tw_start[c]))
            if start > m.tw_end[c]:
                continue
            leave = start + int(m.service[c])
            if pos == k:
                ok = leave + int(m.time_s[c, 0]) <= h1
            else:
                ok = leave + int(m.time_s[c, seq[pos]]) <= L[pos]
            if ok:
                return "insertable"
    return "time_window" if any_capacity_room else "capacity"


# -------------------------------------------------------------- re-validation
def revalidate(
    instance: Instance, solution: Solution, matrices: Matrices | None = None
) -> tuple[Solution, list[str]]:
    """Re-evaluate a stored solution from its visiting orders only.

    Returns the freshly evaluated solution and a list of discrepancies between
    the stored numbers and the recomputed ones (empty when they agree).
    """
    run = SolverRun(
        solver=solution.solver,
        solver_version=solution.solver_version,
        config=solution.config,
        seed=solution.seed,
        wall_time_s=solution.compute.wall_time_s,
        time_to_best_s=solution.compute.time_to_best_s,
        threads=solution.compute.threads,
        status=solution.status,
        message=solution.message,
        trace=solution.trace,
    )
    fresh = evaluate(instance, solution.plan(), run, matrices)
    diffs: list[str] = []
    for key in ("served", "total_cost", "distance_km", "fixed_cost", "variable_cost"):
        old, new = solution.metrics.get(key), fresh.metrics.get(key)
        if old is not None and old != new:
            diffs.append(f"{key}: stored {old} != recomputed {new}")
    if solution.validation.valid != fresh.validation.valid:
        diffs.append(
            f"validation.valid: stored {solution.validation.valid} "
            f"!= recomputed {fresh.validation.valid}"
        )
    return fresh, diffs

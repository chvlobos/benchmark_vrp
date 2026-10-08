"""Hexaly Optimizer adapter (solver ``hexaly``), PLAN.md §7.2.

Model, on the shared integer matrices (customers are 0..n-1 inside the lists,
i.e. matrix index minus one; the depot is handled by separate arrays):

* one list variable per vehicle (the fleet expanded to individual vehicles) plus,
  by default, one extra uncosted list that collects the unserved customers, under a
  ``partition`` constraint (``unserved: dummy_list``); the alternative
  ``unserved: disjoint`` drops the extra list and posts ``disjoint`` over the
  vehicle lists, as Hexaly's template would. Same feasible set either way;
* capacity: sum of the demands in the list ≤ the vehicle's capacity;
* time: recursive array of service starts, ``start_0 = max(e, opening + t_dep)``,
  ``start_i = max(e_i, start_{i-1} + s_{i-1} + t_{i-1,i})`` — free departure,
  free waiting. Windows ``start_i ≤ l_i`` and the return
  ``start_last + s_last + t_last,depot ≤ closing`` are enforced one of two ways
  (``time_windows`` parameter): ``soft`` (default) follows Hexaly's own CVRPTW
  template — total lateness is a first-priority objective driven to zero, which
  keeps the search space connected; ``hard`` posts them as constraints. Either
  way the validator only accepts zero lateness;
* cost per vehicle: fixed cost if the list is not empty + arc costs from the cost
  matrix of the vehicle's type (depot legs from two vectors);
* objectives, in order (Hexaly treats them lexicographically): [minimise total
  lateness, in ``soft`` mode,] maximise the number of customers served, minimise
  total cost — the benchmark's objective, recomputed by the validator afterwards;
* search: Hexaly's own, ``nb_threads`` from the config (1 for the primary
  comparison), ``seed`` from the config, wall-clock limit = the common
  benchmark limit; a ``TIME_TICKED`` callback records (elapsed, served, cost)
  whenever the incumbent improves, for time-to-best and the convergence trace.

License: Hexaly looks for ``license.dat`` in its default location or in
``HX_LICENSE_PATH`` (``HX_LICENSE_CONTENT`` holds the text itself); the config
key ``hexaly.license_path`` is an alternative that calls
``hexaly.optimizer.version.set_license_path`` before the optimizer is created.
"""

from __future__ import annotations

import time

import hexaly.optimizer as hx

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import Matrices
from cvrptw_bench.core.solution import RoutePlan
from cvrptw_bench.solvers.base import ProgressCallback, Solver, SolverConfig, register

HX_DEFAULTS = {
    "nb_threads": 1,
    "license_path": None,
    "verbosity": 0,
    "time_between_ticks": 1,
    "time_windows": "soft",  # soft: lateness as first objective (Hexaly's template) | hard
    # lexicographic: maximise served, then minimise cost (the benchmark's objective as two
    # Hexaly objectives) | penalised: one scalar, cost + P x unserved with P above any routing
    # cost (the shape OR-Tools optimises); same optimum, different search landscape
    "objective": "lexicographic",
    # dummy_list (default): partition(vehicle lists + one uncosted "unserved" list) |
    # disjoint: one list per vehicle, disjoint(lists), a customer may be in no list (the
    # template idiom). Same feasible set and objective; measured on this benchmark, the
    # partition form is maintained ~2.8x faster and is the only one Hexaly 15 parallelises
    "unserved": "dummy_list",
}


def _configure_license(path: str | None) -> None:
    if path:
        hx.version.set_license_path(str(path))


def build_model(
    optimizer,
    instance: Instance,
    m: Matrices,
    time_windows: str = "soft",
    objective: str = "lexicographic",
    unserved: str = "dummy_list",
) -> dict:
    """Build the model on an open optimizer. Returns the expressions needed later."""
    if time_windows not in ("soft", "hard"):
        raise ValueError(f"time_windows must be 'soft' or 'hard', got {time_windows!r}")
    if objective not in ("lexicographic", "penalised"):
        raise ValueError(f"objective must be 'lexicographic' or 'penalised', got {objective!r}")
    if unserved not in ("disjoint", "dummy_list"):
        raise ValueError(f"unserved must be 'disjoint' or 'dummy_list', got {unserved!r}")
    model = optimizer.model
    n = instance.n
    vehicles = instance.vehicles()
    h0, h1 = int(instance.horizon.start), int(instance.horizon.end)

    # --- data in list-index space (customer c <-> matrix index c + 1)
    demand = model.array(m.demand[1:].tolist())
    service = model.array(m.service[1:].tolist())
    tw_start = model.array(m.tw_start[1:].tolist())
    tw_end = model.array(m.tw_end[1:].tolist())
    time_cc = model.array(m.time_s[1:, 1:].tolist())
    time_dep = model.array(m.time_s[0, 1:].tolist())  # depot -> customer
    time_ret = model.array(m.time_s[1:, 0].tolist())  # customer -> depot
    n_types = len(instance.vehicle_types)
    cost_cc = [model.array(m.cost[t][1:, 1:].tolist()) for t in range(n_types)]
    cost_dep = [model.array(m.cost[t][0, 1:].tolist()) for t in range(n_types)]
    cost_ret = [model.array(m.cost[t][1:, 0].tolist()) for t in range(n_types)]

    # --- decisions
    seqs = [model.list(n) for _ in vehicles]
    pool = None
    if unserved == "dummy_list":
        pool = model.list(n)  # the customers nobody serves; no cost, no time, no capacity
        model.constraint(model.partition([*seqs, pool]))
    else:
        model.constraint(model.disjoint(seqs))

    # NB: Hexaly counts a lambda's parameters with inspect.signature, so lambdas must
    # not capture through default arguments; each vehicle gets its own closure scope.
    def add_vehicle(v, seq):
        t = v.type_index
        c = model.count(seq)
        used = c > 0

        # capacity
        load = model.sum(seq, model.lambda_function(lambda j: demand[j]))
        model.constraint(load <= int(v.capacity))

        # service start of the i-th stop (free departure, waiting allowed); the
        # i == 0 branch guards the out-of-range seq[i - 1] as in Hexaly's own example
        def start_fn(i, prev):
            arrive_first = h0 + time_dep[seq[0]]
            arrive_next = prev + service[seq[i - 1]] + model.at(time_cc, seq[i - 1], seq[i])
            return model.max(tw_start[seq[i]], model.iif(i == 0, arrive_first, arrive_next))

        start = model.array(model.range(0, c), model.lambda_function(start_fn), 0)

        # windows and return before closing: soft (lateness, template idiom) or hard
        back = start[c - 1] + service[seq[c - 1]] + time_ret[seq[c - 1]]
        if time_windows == "soft":
            late_fn = model.lambda_function(lambda i: model.max(0, start[i] - tw_end[seq[i]]))
            lateness = model.sum(model.range(0, c), late_fn) + model.iif(
                used, model.max(0, back - h1), 0
            )
        else:
            in_window = model.lambda_function(lambda i: start[i] <= tw_end[seq[i]])
            model.constraint(model.and_(model.range(0, c), in_window))
            model.constraint(model.iif(used, back, h0) <= h1)
            lateness = 0

        # cost of the route with this vehicle's type
        arc_cost = model.lambda_function(lambda i: model.at(cost_cc[t], seq[i - 1], seq[i]))
        arcs = model.sum(model.range(1, c), arc_cost)
        depot_legs = model.iif(used, cost_dep[t][seq[0]] + cost_ret[t][seq[c - 1]], 0)
        return c, model.iif(used, int(v.fixed_cost), 0) + arcs + depot_legs, lateness

    served_terms = []
    cost_terms = []
    late_terms = []
    for v, seq in zip(vehicles, seqs, strict=True):
        c, route_cost, lateness = add_vehicle(v, seq)
        served_terms.append(c)
        cost_terms.append(route_cost)
        late_terms.append(lateness)

    served = model.sum(served_terms) if pool is None else n - model.count(pool)
    total_cost = model.sum(cost_terms)
    total_lateness = model.sum(late_terms) if time_windows == "soft" else None
    if total_lateness is not None:
        model.minimize(total_lateness)  # first priority: a plan is only valid at zero
    penalty = None
    if objective == "penalised":
        from cvrptw_bench.solvers.ortools_solver import drop_penalty

        penalty = drop_penalty(instance, m)
        model.minimize(total_cost + penalty * (n - served))
    else:
        model.maximize(served)
        model.minimize(total_cost)
    model.close()
    return {
        "seqs": seqs,
        "served": served,
        "total_cost": total_cost,
        "lateness": total_lateness,
        "penalty": penalty,
        "vehicles": vehicles,
    }


def extract_plan(exprs: dict) -> RoutePlan:
    routes: dict[int, list[int]] = {}
    for v, seq in zip(exprs["vehicles"], exprs["seqs"], strict=True):
        stops = [int(j) + 1 for j in seq.value]
        if stops:
            routes[v.id] = stops
    return RoutePlan(routes=routes)


@register
class HexalySolver(Solver):
    name = "hexaly"
    version = "0.2.0"

    def _solve(
        self,
        instance: Instance,
        matrices: Matrices,
        config: SolverConfig,
        report: ProgressCallback,
    ) -> RoutePlan:
        p = {**HX_DEFAULTS, **config.params}
        _configure_license(p.get("license_path"))
        t0 = time.perf_counter()
        with hx.HexalyOptimizer() as optimizer:
            exprs = build_model(
                optimizer,
                instance,
                matrices,
                str(p["time_windows"]),
                str(p["objective"]),
                str(p["unserved"]),
            )
            served, total_cost = exprs["served"], exprs["total_cost"]
            lateness = exprs["lateness"]

            best = {"key": None}

            def on_tick(opt, _cb_type) -> None:
                sol = opt.solution
                if sol.status not in (hx.HxSolutionStatus.FEASIBLE, hx.HxSolutionStatus.OPTIMAL):
                    return
                if lateness is not None and int(lateness.value) > 0:
                    return  # a late incumbent is not a benchmark solution yet
                key = (int(served.value), -int(total_cost.value))
                if best["key"] is not None and key <= best["key"]:
                    return
                best["key"] = key
                report(time.perf_counter() - t0, key[0], -key[1])

            optimizer.add_callback(hx.HxCallbackType.TIME_TICKED, on_tick)

            param = optimizer.param
            param.nb_threads = int(p.get("nb_threads") or config.threads or 1)
            param.seed = int(config.seed) % 2_000_000_000
            param.verbosity = int(p["verbosity"])
            param.time_between_ticks = int(p["time_between_ticks"])
            budget = max(1, int(round(float(config.time_limit_s) - (time.perf_counter() - t0))))
            param.time_limit = budget

            optimizer.solve()

            status = optimizer.solution.status
            if status not in (hx.HxSolutionStatus.FEASIBLE, hx.HxSolutionStatus.OPTIMAL):
                raise RuntimeError(f"Hexaly ended with status {status}")
            self.last_status = str(status)
            self.last_lateness = 0 if lateness is None else int(lateness.value)
            self.last_objective = (int(served.value), int(total_cost.value))
            if self.last_lateness > 0:
                # cannot happen once a zero-lateness incumbent exists (lexicographic
                # order); if it does, the validator will reject the plan — say why
                raise RuntimeError(
                    f"Hexaly ended with total lateness {self.last_lateness} s (no valid plan)"
                )
            plan = extract_plan(exprs)
            # the final incumbent is always in the trace, even if it arrived between ticks
            on_tick(optimizer, None)
            return plan

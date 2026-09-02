from pathlib import Path

import pytest

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import build_matrices
from cvrptw_bench.core.validator import evaluate
from cvrptw_bench.solvers.base import SolverConfig, get_solver
from cvrptw_bench.solvers.ortools_solver import ORToolsSolver, build_model, drop_penalty

INSTANCES = Path("instances")


def test_drop_penalty_dominates_any_cost(toy_instance, toy_matrices):
    P = drop_penalty(toy_instance, toy_matrices)
    # bigger than every vehicle used at the most expensive rate over the longest arcs
    worst = sum(t.fixed_cost * t.count for t in toy_instance.vehicle_types)
    worst += int(toy_matrices.cost[1].max()) * (toy_instance.n + toy_instance.n_vehicles)
    assert P > worst


def test_build_model_dimensions(toy_instance, toy_matrices):
    manager, routing, penalty = build_model(toy_instance, toy_matrices)
    assert routing.vehicles() == 3 and manager.GetNumberOfNodes() == 7
    assert routing.GetDimensionOrDie("Capacity") is not None
    assert routing.GetDimensionOrDie("Time") is not None
    assert penalty == drop_penalty(toy_instance, toy_matrices)


def test_ortools_toy_matches_validator(toy_instance, toy_matrices):
    solver = ORToolsSolver()
    plan, run = solver.solve(toy_instance, toy_matrices, SolverConfig(time_limit_s=2, seed=1))
    sol = evaluate(toy_instance, plan, run, toy_matrices)
    assert run.status == "feasible" and sol.validation.valid
    assert sol.metrics["served"] == 6
    # the solver's objective is exactly the benchmark's cost model (+ penalties for drops)
    dropped = toy_instance.n - sol.metrics["served"]
    assert solver.last_objective == sol.metrics["total_cost"] + solver.last_penalty * dropped
    # both heuristics reach the same optimum on this toy
    assert sol.metrics["total_cost"] == 119546
    assert run.time_to_best_s is not None and run.trace[-1][1:] == (6, 119546)


@pytest.mark.skipif(not INSTANCES.exists(), reason="instance set not generated")
def test_ortools_small_instance_cross_check():
    inst = Instance.load(INSTANCES / "RC-100-T-105.json")
    m = build_matrices(inst)
    solver = ORToolsSolver()
    plan, run = solver.solve(inst, m, SolverConfig(time_limit_s=6, seed=1))
    sol = evaluate(inst, plan, run, m)
    assert run.status == "feasible", run.message
    assert sol.validation.valid, sol.validation.violations[:3]
    dropped = inst.n - sol.metrics["served"]
    assert solver.last_objective == sol.metrics["total_cost"] + solver.last_penalty * dropped
    assert sol.metrics["unserved_by_reason"]["insertable"] == 0
    assert 5.0 <= run.wall_time_s <= 8.0  # the common time limit is honoured


def test_registry_has_ortools():
    assert isinstance(get_solver("ortools"), ORToolsSolver)

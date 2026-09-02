import pytest

from cvrptw_bench.core.solution import RoutePlan
from cvrptw_bench.core.validator import evaluate
from cvrptw_bench.solvers.base import SOLVERS, Solver, SolverConfig, get_solver, register


class _FixedSolver(Solver):
    name = "fixed_for_tests"
    version = "0.0.1"

    def _solve(self, instance, matrices, config, report):
        report(0.01, 4, 100000)
        report(0.02, 6, 139708)
        return RoutePlan(routes={0: [1, 3], 1: [2, 5], 2: [6, 4]})


class _CrashingSolver(Solver):
    name = "crash_for_tests"

    def _solve(self, instance, matrices, config, report):
        raise RuntimeError("boom")


def test_solver_run_bookkeeping(toy_instance, toy_matrices):
    plan, run = _FixedSolver().solve(
        toy_instance, toy_matrices, SolverConfig(time_limit_s=1, seed=7)
    )
    assert run.solver == "fixed_for_tests" and run.status == "feasible" and run.seed == 7
    assert run.time_to_best_s == 0.02 and [t[1:] for t in run.trace] == [(4, 100000), (6, 139708)]
    assert run.wall_time_s >= 0
    sol = evaluate(toy_instance, plan, run, toy_matrices)
    assert sol.validation.valid and sol.solver == "fixed_for_tests" and sol.trace == run.trace
    assert sol.config["time_limit_s"] == 1 and sol.compute.time_to_best_s == 0.02


def test_solver_errors_are_captured(toy_instance, toy_matrices):
    plan, run = _CrashingSolver().solve(toy_instance, toy_matrices, SolverConfig())
    assert run.status == "error" and "boom" in (run.message or "")
    assert plan.routes == {}
    sol = evaluate(toy_instance, plan, run, toy_matrices)
    assert sol.status == "error" and sol.metrics["served"] == 0


def test_registry():
    register(_FixedSolver)
    assert isinstance(get_solver("fixed_for_tests"), _FixedSolver)
    with pytest.raises(KeyError):
        get_solver("does_not_exist")
    SOLVERS.pop("fixed_for_tests", None)

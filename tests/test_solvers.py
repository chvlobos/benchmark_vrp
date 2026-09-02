from pathlib import Path

import pytest

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import build_matrices
from cvrptw_bench.core.solution import RoutePlan, Solution
from cvrptw_bench.core.validator import evaluate
from cvrptw_bench.solvers.base import SolverConfig, get_solver
from cvrptw_bench.solvers.clarke_wright import assign_and_repair, construct, merge_routes
from cvrptw_bench.solvers.local_search import LocalSearch
from cvrptw_bench.solvers.routes import Fleet, VehicleRoute

INSTANCES = Path("instances")
FAST = {"multistart_runs": 5}


def _load(name):
    inst = Instance.load(INSTANCES / f"{name}.json")
    return inst, build_matrices(inst)


# ------------------------------------------------------------------- fleet
def test_fleet_ledger(toy_instance):
    f = Fleet(toy_instance)
    assert f.total_free() == 3 and f.by_capacity == [0, 1]
    assert f.smallest_free_type(90) == 0 and f.smallest_free_type(150) == 1
    assert f.smallest_free_type(999) is None
    v = f.take(0)
    assert f.free_count(0) == 1
    f.release(v)
    assert f.free_count(0) == 2


def test_vehicle_route_cost(toy_instance, toy_matrices):
    r = VehicleRoute(toy_matrices, [1, 3], 0, 0, 100, 20000, 36000, 64800)
    assert r.arc_cost() == 1512 + 2286 + 3798 and r.cost() == 27596
    assert r.feasible and r.load == 90 and list(r.cumload) == [40, 90]
    assert not r.segment_insertion_feasible([2], 1)  # 90 + 30 > 100 units
    assert r.segment_insertion_feasible([2], 1, check_capacity=False)  # time-wise it fits
    assert not r.segment_insertion_feasible([4], 2)  # Maipu 120 units > 100
    assert r.replace_feasible(0, 2)  # Nunoa opens 11:00: waiting is allowed
    assert not r.replace_feasible(1, 4)  # Maipu 120 units > 100


# ----------------------------------------------------------- constructive
def test_merge_routes_toy(toy_instance, toy_matrices):
    routes = merge_routes(toy_instance, toy_matrices, Fleet(toy_instance), 1.0, None, 0.0, 5)
    seqs = [r.seq for r in routes]
    assert sorted(c for s in seqs for c in s) == [1, 2, 3, 4, 5, 6]
    for r in routes:  # every merged route respects the largest capacity and its windows
        assert r.load <= 250
        vr = VehicleRoute(toy_matrices, r.seq, 0, 1, 250, 45000, 36000, 64800)
        assert vr.feasible


def test_assign_and_repair_drops_when_fleet_is_short(toy_instance, toy_matrices):
    # four single-customer routes but only three vehicles: one customer must be re-inserted
    routes, fleet, unserved = assign_and_repair(toy_instance, toy_matrices, [[1], [2], [3], [4]])
    served = sorted(c for r in routes for c in r.seq)
    assert served + sorted(unserved) == [1, 2, 3, 4]
    assert all(r.feasible and r.load <= r.capacity for r in routes)
    assert fleet.total_free() + len(routes) == 3


def test_construct_toy_full_coverage(toy_instance, toy_matrices):
    st = construct(toy_instance, toy_matrices)
    assert st.served == 6 and st.unserved == []
    sol = evaluate(toy_instance, st.plan(), None, toy_matrices)
    assert sol.validation.valid


@pytest.mark.parametrize("solver", ["cw", "cw_ls"])
def test_solvers_toy(toy_instance, toy_matrices, solver):
    plan, run = get_solver(solver).solve(
        toy_instance, toy_matrices, SolverConfig(time_limit_s=2, seed=1, params=FAST)
    )
    sol = evaluate(toy_instance, plan, run, toy_matrices)
    assert run.status == "feasible" and sol.validation.valid and sol.metrics["served"] == 6
    assert sol.metrics["unserved_by_reason"]["insertable"] == 0


@pytest.mark.skipif(not INSTANCES.exists(), reason="instance set not generated")
@pytest.mark.parametrize("name", ["R-100-L-60", "C-100-T-85", "RC-100-M-105"])
def test_solvers_on_small_instances(name):
    inst, m = _load(name)
    seed = Solution.load(INSTANCES / f"{name}.seed.json")
    results = {}
    for solver in ("cw", "cw_ls"):
        plan, run = get_solver(solver).solve(
            inst, m, SolverConfig(time_limit_s=8, seed=7, params=FAST)
        )
        sol = evaluate(inst, plan, run, m)
        assert run.status == "feasible", run.message
        assert sol.validation.valid, sol.validation.violations[:3]
        assert sol.metrics["unserved_by_reason"]["insertable"] == 0
        results[solver] = sol
    cw, ls = results["cw"], results["cw_ls"]
    # the local search never loses coverage and never costs more than its start
    assert ls.metrics["served"] >= cw.metrics["served"]
    if ls.metrics["served"] == cw.metrics["served"]:
        assert ls.metrics["total_cost"] <= cw.metrics["total_cost"]
    if inst.meta["factors"]["capacity_stress"] == 60:
        assert cw.metrics["served"] == inst.n and ls.metrics["served"] == inst.n
    # and beats the generator's reference on the lexicographic objective
    assert (ls.metrics["served"], -ls.metrics["total_cost"]) >= (
        seed.metrics["served"],
        -seed.metrics["total_cost"],
    )


@pytest.mark.skipif(not INSTANCES.exists(), reason="instance set not generated")
def test_solver_is_deterministic():
    inst, m = _load("C-100-M-85")
    a, _ = get_solver("cw").solve(inst, m, SolverConfig(time_limit_s=5, seed=3, params=FAST))
    b, _ = get_solver("cw").solve(inst, m, SolverConfig(time_limit_s=5, seed=3, params=FAST))
    assert a.routes == b.routes


@pytest.mark.skipif(not INSTANCES.exists(), reason="instance set not generated")
def test_local_search_moves_keep_feasibility():
    inst, m = _load("RC-100-T-105")
    st = construct(inst, m, lam=1.2, seed=5, noise=0.1)
    ls = LocalSearch(inst, m, st, k=15, time_budget_s=5, seed=5)
    for move in (
        ls.relocate,
        ls.swap,
        ls.two_opt_star,
        lambda: ls.or_opt(2),
        ls.two_opt,
        ls.split,
        ls.eliminate,
        ls.retype,
        ls.insert_unserved,
    ):
        move()
        sol = evaluate(inst, ls.plan(), None, m)
        assert sol.validation.valid, sol.validation.violations[:3]
        # bookkeeping stays consistent with the fleet ledger
        used = {r.vehicle_id for r in ls.routes}
        free = {v for vs in ls.fleet.free.values() for v in vs}
        assert not (used & free) and len(used) + len(free) == inst.n_vehicles
        assert sorted(ls.route_of) == sorted(c for r in ls.routes for c in r.seq)


def test_cli_solve(tmp_path, capsys):
    from cvrptw_bench.cli import main

    rc = main(
        [
            "solve",
            "tests/data/toy_instance.json",
            "--solver",
            "cw_ls",
            "--out",
            str(tmp_path),
            "--time-limit",
            "2",
            "--no-plots",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0 and "served=6/6" in out and (tmp_path / "solution.json").exists()
    sol = Solution.load(tmp_path / "solution.json")
    assert sol.solver == "cw_ls" and sol.validation.valid


def test_plan_roundtrip_through_solution(toy_instance, toy_matrices):
    st = construct(toy_instance, toy_matrices)
    sol = evaluate(toy_instance, st.plan(), None, toy_matrices)
    assert RoutePlan(routes=sol.plan_routes).served() == set(range(1, 7))

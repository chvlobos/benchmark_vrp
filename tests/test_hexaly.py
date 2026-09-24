"""Hexaly adapter, both time-window modes. Everything that needs the optimizer is
skipped unless the ``hexaly`` package is installed *and* a license is found
(HX_LICENSE_PATH, the default license.dat location, or ``hexaly.license_path`` in
configs/run.default.yaml)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import build_matrices
from cvrptw_bench.core.validator import evaluate
from cvrptw_bench.run import load_run_config
from cvrptw_bench.solvers.base import SolverConfig, get_solver

hx = pytest.importorskip("hexaly.optimizer", reason="hexaly package not installed")

from cvrptw_bench.solvers.hexaly_solver import (  # noqa: E402 - after importorskip
    HexalySolver,
    _configure_license,
    build_model,
)

INSTANCES = Path("instances")
LICENSE_PATH = (load_run_config(None).get("hexaly") or {}).get("license_path")


def _licensed() -> bool:
    _configure_license(LICENSE_PATH)
    try:
        with hx.HexalyOptimizer():
            return True
    except hx.HxError:
        return False


needs_license = pytest.mark.skipif(not _licensed(), reason="no Hexaly license found")


def test_registry_has_hexaly():
    assert isinstance(get_solver("hexaly"), HexalySolver)


@needs_license
@pytest.mark.parametrize(
    "mode,objective,unserved,n_obj",
    [
        ("soft", "lexicographic", "disjoint", 3),
        ("hard", "lexicographic", "disjoint", 2),
        ("soft", "penalised", "disjoint", 2),
        ("soft", "lexicographic", "dummy_list", 3),
    ],
)
def test_build_model_shape(toy_instance, toy_matrices, mode, objective, unserved, n_obj):
    with hx.HexalyOptimizer() as optimizer:
        exprs = build_model(optimizer, toy_instance, toy_matrices, mode, objective, unserved)
        assert len(exprs["seqs"]) == toy_instance.n_vehicles == 3
        assert optimizer.model.nb_decisions == 3 + (unserved == "dummy_list")
        assert optimizer.model.nb_objectives == n_obj
        assert (exprs["lateness"] is None) == (mode == "hard")
        assert (exprs["penalty"] is None) == (objective == "lexicographic")
        assert optimizer.model.is_closed()


@needs_license
@pytest.mark.parametrize(
    "mode,objective,unserved",
    [
        ("soft", "lexicographic", "disjoint"),
        ("hard", "lexicographic", "disjoint"),
        ("soft", "penalised", "disjoint"),
        ("soft", "lexicographic", "dummy_list"),
    ],
)
def test_hexaly_toy_matches_validator(toy_instance, toy_matrices, mode, objective, unserved):
    solver = HexalySolver()
    cfg = SolverConfig(
        time_limit_s=3,
        seed=1,
        params={
            "license_path": LICENSE_PATH,
            "time_windows": mode,
            "objective": objective,
            "unserved": unserved,
        },
    )
    plan, run = solver.solve(toy_instance, toy_matrices, cfg)
    assert run.status == "feasible", run.message
    sol = evaluate(toy_instance, plan, run, toy_matrices)
    assert sol.validation.valid, sol.validation.violations[:3]
    assert sol.metrics["served"] == 6
    # Hexaly's own objective values are exactly the validator's numbers
    assert solver.last_objective == (sol.metrics["served"], sol.metrics["total_cost"])
    assert solver.last_lateness == 0
    # the toy optimum that cw_ls and OR-Tools both reach
    assert sol.metrics["total_cost"] == 119546
    assert run.time_to_best_s is not None and run.trace[-1][1:] == (6, 119546)


@needs_license
@pytest.mark.skipif(not INSTANCES.exists(), reason="instance set not generated")
def test_hexaly_small_instance_cross_check():
    inst = Instance.load(INSTANCES / "RC-100-T-105.json")
    m = build_matrices(inst)
    solver = HexalySolver()
    cfg = SolverConfig(time_limit_s=8, seed=1, params={"license_path": LICENSE_PATH})
    plan, run = solver.solve(inst, m, cfg)
    assert run.status == "feasible", run.message
    sol = evaluate(inst, plan, run, m)
    assert sol.validation.valid, sol.validation.violations[:3]
    assert solver.last_objective == (sol.metrics["served"], sol.metrics["total_cost"])
    assert sol.metrics["unserved_by_reason"]["insertable"] == 0
    assert sol.metrics["served"] >= 95
    assert 6.0 <= run.wall_time_s <= 12.0  # the common time limit is honoured

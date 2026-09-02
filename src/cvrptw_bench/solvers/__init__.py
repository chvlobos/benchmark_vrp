"""Solver adapters. Every solver implements :class:`cvrptw_bench.solvers.base.Solver`.

Registered names (filled in by later phases):

* ``cw``       Clarke-Wright savings, randomised multi-start (Phase 3)
* ``cw_ls``    Clarke-Wright + local search (Phase 3)
* ``ortools``  OR-Tools Routing, PATH_CHEAPEST_ARC + GLS (Phase 4)
* ``hexaly``   Hexaly Optimizer, list-variable model (Phase 5)
"""

from cvrptw_bench.solvers.base import SOLVERS, ProgressCallback, Solver, SolverConfig, get_solver

__all__ = ["SOLVERS", "ProgressCallback", "Solver", "SolverConfig", "get_solver"]

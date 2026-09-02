"""Shared core: data model, integer matrices and the independent validator.

Every solver, the plots and the report go through this package. In particular:

* :func:`cvrptw_bench.core.matrices.build_matrices` is the *only* place where
  distances, travel times and arc costs are computed. Solvers never call
  Haversine themselves, so all methods are compared on identical numbers.
* :func:`cvrptw_bench.core.validator.evaluate` is the *only* place where a
  solution's schedule, cost and metrics are computed. A solver returns a
  :class:`cvrptw_bench.core.solution.RoutePlan` (which vehicle visits which
  customers, in which order) and nothing else is trusted.
"""

from cvrptw_bench.core.instance import Customer, Instance, Vehicle, VehicleType
from cvrptw_bench.core.matrices import Matrices, build_matrices
from cvrptw_bench.core.solution import RoutePlan, Solution, SolverRun
from cvrptw_bench.core.validator import evaluate, revalidate

__all__ = [
    "Customer",
    "Instance",
    "Vehicle",
    "VehicleType",
    "Matrices",
    "build_matrices",
    "RoutePlan",
    "Solution",
    "SolverRun",
    "evaluate",
    "revalidate",
]

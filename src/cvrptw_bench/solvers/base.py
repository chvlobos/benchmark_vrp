"""Common solver interface.

A solver receives the instance, the shared matrices, a config, a seed and a
time limit, and returns a :class:`RoutePlan` plus a :class:`SolverRun` with its
bookkeeping (wall time, time-to-best, trace). It must not compute metrics or
claim feasibility: :func:`cvrptw_bench.core.validator.evaluate` does that.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import Matrices
from cvrptw_bench.core.solution import RoutePlan, SolverRun

# (elapsed_seconds, served, cost) -> None ; solvers call it whenever they improve
ProgressCallback = Callable[[float, int, int], None]


@dataclass
class SolverConfig:
    time_limit_s: float = 60.0
    seed: int = 42
    threads: int = 1
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "time_limit_s": self.time_limit_s,
            "seed": self.seed,
            "threads": self.threads,
            **self.params,
        }


class Solver(ABC):
    """Base class. Subclasses set ``name`` and implement :meth:`_solve`."""

    name: str = "abstract"
    version: str = "0.0.0"

    def solve(
        self,
        instance: Instance,
        matrices: Matrices,
        config: SolverConfig,
        progress: ProgressCallback | None = None,
    ) -> tuple[RoutePlan, SolverRun]:
        """Run the solver with uniform timing and error handling."""
        trace: list[tuple[float, int, int]] = []
        t0 = time.perf_counter()
        best_t: float | None = None

        def _cb(elapsed: float, served: int, cost: int) -> None:
            nonlocal best_t
            best_t = elapsed
            trace.append((round(elapsed, 3), int(served), int(cost)))
            if progress is not None:
                progress(elapsed, served, cost)

        run = SolverRun(
            solver=self.name,
            solver_version=self.version,
            config=config.as_dict(),
            seed=config.seed,
            threads=config.threads,
        )
        try:
            plan = self._solve(instance, matrices, config, _cb)
            run.status = "feasible"
        except Exception as exc:  # noqa: BLE001 - a failing solver must not kill the run
            plan = RoutePlan()
            run.status = "error"
            run.message = f"{type(exc).__name__}: {exc}"
        run.wall_time_s = round(time.perf_counter() - t0, 3)
        run.time_to_best_s = None if best_t is None else round(best_t, 3)
        run.trace = trace
        return plan, run

    @abstractmethod
    def _solve(
        self,
        instance: Instance,
        matrices: Matrices,
        config: SolverConfig,
        report: ProgressCallback,
    ) -> RoutePlan:
        """Return the plan. Call ``report(elapsed, served, cost)`` on every improvement."""


SOLVERS: dict[str, type[Solver]] = {}


def register(cls: type[Solver]) -> type[Solver]:
    SOLVERS[cls.name] = cls
    return cls


def get_solver(name: str) -> Solver:
    # Import adapters lazily so that a missing optional dependency (e.g. hexaly)
    # only breaks the solver that needs it.
    if name not in SOLVERS:
        _import_adapters()
    try:
        return SOLVERS[name]()
    except KeyError as exc:
        raise KeyError(f"unknown solver '{name}'. Known: {sorted(SOLVERS)}") from exc


def _import_adapters() -> None:
    import importlib

    for mod in ("clarke_wright", "local_search", "ortools_solver", "hexaly_solver"):
        try:
            importlib.import_module(f"cvrptw_bench.solvers.{mod}")
        except ImportError:
            pass

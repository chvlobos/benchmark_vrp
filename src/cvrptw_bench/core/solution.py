"""Solution data model (schema v1).

Two layers:

* :class:`RoutePlan` is what a solver produces: for each vehicle id, the ordered
  list of customer ids it visits. Nothing else a solver says is trusted.
* :class:`Solution` is what the validator produces from a plan: schedules,
  loads, costs, metrics, unserved diagnostics and the validation verdict.
  This is what gets written to ``solution.json`` and read by plots and report.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


# ----------------------------------------------------------------- solver side
class SolverRun(BaseModel):
    """Bookkeeping a solver hands back together with its plan."""

    model_config = ConfigDict(extra="forbid")
    solver: str
    solver_version: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    wall_time_s: float = 0.0
    time_to_best_s: float | None = None
    threads: int = 1
    status: str = "feasible"  # feasible | error | timeout | unknown
    message: str | None = None
    # convergence trace: (elapsed_s, served, cost) as reported by the solver
    trace: list[tuple[float, int, int]] = Field(default_factory=list)


class RoutePlan(BaseModel):
    """Which vehicle visits which customers, in which order. Solver output."""

    model_config = ConfigDict(extra="forbid")
    routes: dict[int, list[int]] = Field(default_factory=dict)  # vehicle_id -> customer ids

    def served(self) -> set[int]:
        return {c for seq in self.routes.values() for c in seq}

    def non_empty(self) -> dict[int, list[int]]:
        return {v: seq for v, seq in self.routes.items() if seq}


# -------------------------------------------------------------- evaluated side
class Stop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer: int
    arrival: int
    wait: int
    service_start: int
    departure: int


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    vehicle_id: int
    vehicle_type: str
    depart: int
    return_time: int = Field(alias="return")
    load: int
    capacity: int
    distance_m: int
    fixed_cost: int
    variable_cost: int
    cost: int
    stops: list[Stop]


class Unserved(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer: int
    demand: int
    tw_start: int
    tw_end: int
    reason: str  # oversized | unreachable_window | capacity | time_window | insertable


class Compute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wall_time_s: float = 0.0
    time_to_best_s: float | None = None
    threads: int = 1
    host: str | None = None
    python: str | None = None
    packages: dict[str, str] = Field(default_factory=dict)


class Validation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid: bool
    violations: list[str] = Field(default_factory=list)


class Solution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    instance: str
    solver: str
    solver_version: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    status: str = "feasible"
    message: str | None = None
    compute: Compute = Field(default_factory=Compute)
    # the raw plan exactly as the solver returned it (kept even when invalid, for auditing)
    plan_routes: dict[int, list[int]] = Field(default_factory=dict)
    # evaluated view of the plan: only routes on existing vehicles with existing customers
    routes: list[Route] = Field(default_factory=list)
    unserved: list[Unserved] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    validation: Validation = Field(default_factory=lambda: Validation(valid=False))
    trace: list[tuple[float, int, int]] = Field(default_factory=list)

    # ---------------------------------------------------------------- helpers
    def plan(self) -> RoutePlan:
        """The raw plan (vehicle -> ordered customers) the solver returned."""
        if self.plan_routes:
            return RoutePlan(routes={int(k): list(v) for k, v in self.plan_routes.items()})
        return RoutePlan(routes={r.vehicle_id: [s.customer for s in r.stops] for r in self.routes})

    @property
    def objective(self) -> tuple[int, int]:
        """Lexicographic objective (served, cost). Higher served, then lower cost."""
        return int(self.metrics.get("served", 0)), int(self.metrics.get("total_cost", 0))

    @classmethod
    def load(cls, path: str | Path) -> Solution:
        with open(path, encoding="utf-8") as fh:
            return cls.model_validate(json.load(fh))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.model_dump(mode="json", by_alias=True), fh, indent=1)
            fh.write("\n")
        tmp.replace(path)  # atomic on POSIX: a run interrupted mid-write never leaves a half file

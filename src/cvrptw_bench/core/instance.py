"""Instance data model (schema v1) and I/O.

Conventions used everywhere in the package:

* node 0 is the depot, customers are nodes 1..n (``Customer.id`` == node index);
* times are integer seconds since midnight;
* loads are integers in "units" (think kg); money is integer CLP;
* vehicles are expanded from the types into individual vehicles with ids
  0..V-1, ordered by vehicle type (all vehicles of the first type first).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1


class Horizon(BaseModel):
    """Operating window of the depot: departures >= start, returns <= end."""

    model_config = ConfigDict(extra="forbid")
    start: int = Field(ge=0, le=86400)
    end: int = Field(ge=0, le=86400 * 2)

    @model_validator(mode="after")
    def _check(self) -> Horizon:
        if self.end <= self.start:
            raise ValueError("horizon.end must be greater than horizon.start")
        return self

    @property
    def length(self) -> int:
        return self.end - self.start


class Travel(BaseModel):
    """How distances and travel times are derived from coordinates."""

    model_config = ConfigDict(extra="forbid")
    speed_kmh: float = Field(gt=0, default=30.0)
    detour_factor: float = Field(gt=0, default=1.3)
    distance: str = "haversine"

    @model_validator(mode="after")
    def _check(self) -> Travel:
        if self.distance != "haversine":
            raise ValueError("only 'haversine' distances are supported")
        return self


class Depot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Customer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(ge=1)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    demand: int = Field(gt=0)
    service_time: int = Field(ge=0)
    tw_start: int = Field(ge=0)
    tw_end: int = Field(ge=0)
    tw_class: str | None = None  # wide | medium | tight (informative only)

    @model_validator(mode="after")
    def _check(self) -> Customer:
        if self.tw_end < self.tw_start:
            raise ValueError(f"customer {self.id}: tw_end < tw_start")
        return self


class VehicleType(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    capacity: int = Field(gt=0)
    count: int = Field(ge=0)
    fixed_cost: int = Field(ge=0)
    cost_per_km: int = Field(ge=0)


class Vehicle(BaseModel):
    """One physical vehicle, obtained by expanding the fleet."""

    model_config = ConfigDict(frozen=True)
    id: int
    type_index: int
    type: str
    capacity: int
    fixed_cost: int
    cost_per_km: int


class Instance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    name: str
    meta: dict[str, Any] = Field(default_factory=dict)
    horizon: Horizon
    travel: Travel = Field(default_factory=Travel)
    depot: Depot
    customers: list[Customer]
    vehicle_types: list[VehicleType]

    # ------------------------------------------------------------------ checks
    @model_validator(mode="after")
    def _check(self) -> Instance:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version}")
        n = len(self.customers)
        if n == 0:
            raise ValueError("instance has no customers")
        ids = [c.id for c in self.customers]
        if ids != list(range(1, n + 1)):
            raise ValueError("customer ids must be exactly 1..n in order")
        if not self.vehicle_types:
            raise ValueError("instance has no vehicle types")
        names = [t.type for t in self.vehicle_types]
        if len(set(names)) != len(names):
            raise ValueError("vehicle type names must be unique")
        max_cap = max(t.capacity for t in self.vehicle_types)
        for c in self.customers:
            if c.demand > max_cap:
                raise ValueError(
                    f"customer {c.id}: demand {c.demand} exceeds the largest capacity {max_cap}"
                )
            if c.tw_start < self.horizon.start or c.tw_end > self.horizon.end:
                raise ValueError(f"customer {c.id}: time window outside the operating horizon")
        return self

    # --------------------------------------------------------------- helpers
    @property
    def n(self) -> int:
        """Number of customers."""
        return len(self.customers)

    @property
    def n_vehicles(self) -> int:
        return sum(t.count for t in self.vehicle_types)

    @property
    def total_demand(self) -> int:
        return sum(c.demand for c in self.customers)

    @property
    def fleet_capacity(self) -> int:
        return sum(t.capacity * t.count for t in self.vehicle_types)

    def type_index(self, type_name: str) -> int:
        for k, t in enumerate(self.vehicle_types):
            if t.type == type_name:
                return k
        raise KeyError(type_name)

    def vehicles(self) -> list[Vehicle]:
        """Expand the fleet into individual vehicles, ids 0..V-1 grouped by type."""
        out: list[Vehicle] = []
        vid = 0
        for k, t in enumerate(self.vehicle_types):
            for _ in range(t.count):
                out.append(
                    Vehicle(
                        id=vid,
                        type_index=k,
                        type=t.type,
                        capacity=t.capacity,
                        fixed_cost=t.fixed_cost,
                        cost_per_km=t.cost_per_km,
                    )
                )
                vid += 1
        return out

    # -------------------------------------------------------------------- I/O
    @classmethod
    def load(cls, path: str | Path) -> Instance:
        with open(path, encoding="utf-8") as fh:
            return cls.model_validate(json.load(fh))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.model_dump(mode="json"), fh, indent=1)
            fh.write("\n")


def seconds_to_hhmm(t: int) -> str:
    """Format seconds since midnight as HH:MM (may exceed 24:00 for late returns)."""
    h, m = divmod(int(round(t / 60)), 60)
    return f"{h:02d}:{m:02d}"

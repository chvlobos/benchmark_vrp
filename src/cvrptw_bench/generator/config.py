"""Generator configuration (mirrors ``configs/generator.default.yaml``)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

FAMILIES = ("R", "C", "RC")
TW_CLASSES = ("wide", "medium", "tight")


class DesignCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sizes: list[int] = [100, 200, 400, 600]
    families: list[str] = ["R", "C", "RC"]
    tw_profiles: list[str] = ["L", "M", "T"]
    capacity_stress: list[int] = [60, 85, 105]

    @model_validator(mode="after")
    def _check(self) -> DesignCfg:
        for f in self.families:
            if f not in FAMILIES:
                raise ValueError(f"unknown family {f}")
        return self


class HorizonCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: int = 36000
    end: int = 64800


class TravelCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speed_kmh: float = 30.0
    detour_factor: float = 1.3
    distance: str = "haversine"


class ClustersCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customers_per_cluster: int = 40
    sigma_km: float = 1.2


class GeographyCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    polygon: str = "santiago_urban.geojson"
    bbox: list[float] | None = None  # [min_lon, min_lat, max_lon, max_lat] overrides polygon
    clusters: ClustersCfg = Field(default_factory=ClustersCfg)
    rc_cluster_share: float = 0.5


class DemandCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    large_share: float = 0.10
    small_range: list[int] = [10, 60]
    large_range: list[int] = [200, 1000]


class ServiceTimeCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_s: int = 180
    per_unit_s: float = 3.0


class TimeWindowsCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    widths_s: dict[str, list[int]] = {
        "wide": [14400, 28800],
        "medium": [5400, 10800],
        "tight": [1800, 3600],
    }
    profiles: dict[str, list[float]] = {
        "L": [0.70, 0.20, 0.10],
        "M": [0.33, 0.33, 0.34],
        "T": [0.10, 0.20, 0.70],
    }
    center_jitter_frac: float = 0.10

    @model_validator(mode="after")
    def _check(self) -> TimeWindowsCfg:
        for c in TW_CLASSES:
            if c not in self.widths_s:
                raise ValueError(f"widths_s must define {c}")
        for name, shares in self.profiles.items():
            if len(shares) != 3 or abs(sum(shares) - 1.0) > 1e-6:
                raise ValueError(f"profile {name}: shares must be 3 numbers summing to 1")
        return self


class VehicleTypeCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    capacity: int
    fixed_cost: int
    cost_per_km: int


class FleetCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    types: list[VehicleTypeCfg]
    mix: list[int]

    @model_validator(mode="after")
    def _check(self) -> FleetCfg:
        if len(self.mix) != len(self.types):
            raise ValueError("fleet.mix must have one entry per vehicle type")
        return self

    @property
    def block_capacity(self) -> int:
        return sum(t.capacity * k for t, k in zip(self.types, self.mix, strict=True))


class SeedSolutionCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration_margin_frac: float = 0.10


class GeneratorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    global_seed: int = 42
    design: DesignCfg = Field(default_factory=DesignCfg)
    horizon: HorizonCfg = Field(default_factory=HorizonCfg)
    travel: TravelCfg = Field(default_factory=TravelCfg)
    geography: GeographyCfg = Field(default_factory=GeographyCfg)
    demand: DemandCfg = Field(default_factory=DemandCfg)
    service_time: ServiceTimeCfg = Field(default_factory=ServiceTimeCfg)
    time_windows: TimeWindowsCfg = Field(default_factory=TimeWindowsCfg)
    fleet: FleetCfg = Field(
        default_factory=lambda: FleetCfg(
            types=[
                VehicleTypeCfg(type="small", capacity=800, fixed_cost=20000, cost_per_km=350),
                VehicleTypeCfg(type="medium", capacity=1600, fixed_cost=30000, cost_per_km=500),
                VehicleTypeCfg(type="large", capacity=3200, fixed_cost=45000, cost_per_km=700),
            ],
            mix=[3, 2, 1],
        )
    )
    seed_solution: SeedSolutionCfg = Field(default_factory=SeedSolutionCfg)

    @classmethod
    def load(cls, path: str | Path | None) -> GeneratorConfig:
        if path is None:
            return cls()
        with open(path, encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh) or {})

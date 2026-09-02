import json

import numpy as np
import pytest
from shapely.geometry import Point

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import build_matrices
from cvrptw_bench.core.solution import Solution
from cvrptw_bench.core.validator import revalidate
from cvrptw_bench.generator import (
    GeneratorConfig,
    InstanceSpec,
    design_specs,
    generate_instance,
    generate_set,
    instance_seed,
)
from cvrptw_bench.generator.demand import fleet_candidates, sample_demands, size_fleet
from cvrptw_bench.generator.generate import make_region
from cvrptw_bench.generator.geo import Region, load_polygon
from cvrptw_bench.generator.sampling import sample_layout
from cvrptw_bench.generator.windows import assign_classes

LANDMARKS_INSIDE = {
    "Plaza de Armas": (-33.4372, -70.6506),
    "Costanera Center": (-33.4175, -70.6063),
    "Plaza Maipu": (-33.5108, -70.7581),
    "Plaza Puente Alto": (-33.6117, -70.5758),
    "Quilicura": (-33.3667, -70.7333),
    "San Bernardo": (-33.5928, -70.7047),
    "La Dehesa": (-33.355, -70.52),
}
LANDMARKS_OUTSIDE = {
    "Aeropuerto SCL": (-33.393, -70.786),
    "Colina": (-33.20, -70.675),
    "Pirque": (-33.635, -70.55),
    "Farellones": (-33.35, -70.30),
    "Buin": (-33.73, -70.74),
}


@pytest.fixture(scope="module")
def cfg() -> GeneratorConfig:
    return GeneratorConfig.load("configs/generator.default.yaml")


@pytest.fixture(scope="module")
def region(cfg) -> Region:
    return make_region(cfg)


# ------------------------------------------------------------------ geography
def test_polygon_landmarks():
    poly = load_polygon()
    for name, (lat, lon) in LANDMARKS_INSIDE.items():
        assert poly.contains(Point(lon, lat)), name
    for name, (lat, lon) in LANDMARKS_OUTSIDE.items():
        assert not poly.contains(Point(lon, lat)), name


def test_sampling_inside_polygon(region, cfg):
    rng = np.random.default_rng(1)
    for fam in ("R", "C", "RC"):
        lay = sample_layout(rng, region, 300, fam, cfg.geography)
        assert lay.customers.shape == (300, 2)
        assert region.contains(*lay.depot)
        assert all(region.contains(x, y) for x, y in lay.customers)
        if fam == "R":
            assert lay.n_clusters == 0 and (lay.cluster_of == -1).all()
        else:
            assert lay.n_clusters >= 2
            share = (lay.cluster_of >= 0).mean()
            assert share == 1.0 if fam == "C" else abs(share - 0.5) < 0.05


# ------------------------------------------------------------- demand & fleet
def test_demand_mixture(cfg):
    rng = np.random.default_rng(3)
    d = sample_demands(rng, 400, cfg.demand, 3200)
    assert d.min() >= 10 and d.max() <= 1000
    large = d > 60
    assert large.sum() == 40  # exactly 10 %
    assert (d[large] >= 200).all() and (d[large] > 800).any()  # some exceed the small vehicle


def test_fleet_sizing_hits_target(cfg):
    for D in (8470, 9150, 18000, 36510, 55000):
        for stress in (60, 85, 105):
            fleet = size_fleet(D, stress, cfg.fleet)
            cap = sum(t.capacity * t.count for t in fleet)
            achieved = D / cap
            assert next(t for t in fleet if t.type == "large").count >= 1
            if stress > 100:
                assert achieved > 1.0
            else:
                assert achieved <= 1.0
                assert abs(achieved - stress / 100) < 0.05


def test_fleet_candidates_always_have_a_large(cfg):
    for cap, counts in fleet_candidates(cfg.fleet, 2):
        assert counts[2] >= 1 and cap > 0


# ------------------------------------------------------------------- windows
def test_assign_classes_exact_counts(cfg):
    rng = np.random.default_rng(0)
    cl = assign_classes(rng, 200, "T", cfg.time_windows)
    assert len(cl) == 200
    assert cl.count("wide") == 20 and cl.count("medium") == 40 and cl.count("tight") == 140


# -------------------------------------------------------------- full instance
@pytest.mark.parametrize(
    "spec", [InstanceSpec(100, "R", "L", 60), InstanceSpec(200, "RC", "T", 105)]
)
def test_generate_instance_is_consistent(cfg, region, spec):
    inst, seed = generate_instance(spec, cfg, region)
    assert inst.name == spec.name and inst.n == spec.n
    # schema round trip and metadata
    again = Instance.model_validate(json.loads(json.dumps(inst.model_dump(mode="json"))))
    assert again == inst
    st = inst.meta["stats"]
    assert st["fleet_capacity"] == inst.fleet_capacity and st["total_demand"] == inst.total_demand
    assert (st["capacity_stress_achieved"] > 1.0) == (spec.capacity_stress > 100)
    assert 0 < st["time_stress_est"] < 3
    assert sum(st["tw_class_counts"].values()) == spec.n
    # windows: whole minutes, inside the horizon, never unreachable
    m = build_matrices(inst)
    for c in inst.customers:
        assert c.tw_start % 60 == 0 and c.tw_end % 60 == 0
        assert inst.horizon.start <= c.tw_start <= c.tw_end <= inst.horizon.end
        assert c.tw_start + c.service_time + m.time_s[c.id, 0] <= inst.horizon.end
        assert c.tw_class in ("wide", "medium", "tight")
    # seed solution: valid, and at 60 % stress it serves everybody
    assert seed.solver == "seed_sweep" and seed.validation.valid
    fresh, diffs = revalidate(inst, seed)
    assert diffs == [] and fresh.validation.valid
    if spec.capacity_stress == 60:
        assert seed.metrics["served"] == spec.n
    assert seed.metrics["unserved_by_reason"]["insertable"] == 0
    assert seed.metrics["unserved_by_reason"]["unreachable_window"] == 0


def test_generation_is_deterministic(cfg, region):
    spec = InstanceSpec(100, "C", "M", 85)
    a, sa = generate_instance(spec, cfg, region)
    b, sb = generate_instance(spec, cfg, region)
    a.meta.pop("created")
    b.meta.pop("created")
    assert a == b and sa.plan().routes == sb.plan().routes
    assert instance_seed(42, spec.name) == a.meta["seed"]
    assert instance_seed(43, spec.name) != a.meta["seed"]


def test_design_and_set(cfg, tmp_path):
    assert len(design_specs(cfg)) == 4 * 3 * 3 * 3
    small = cfg.model_copy(deep=True)
    small.design.sizes = [100]
    small.design.families = ["R"]
    small.design.tw_profiles = ["M"]
    insts = generate_set(small, tmp_path, log=lambda *_: None)
    assert [i.name for i in insts] == ["R-100-M-60", "R-100-M-85", "R-100-M-105"]
    assert (tmp_path / "index.csv").exists()
    for i in insts:
        assert (tmp_path / f"{i.name}.json").exists()
        s = Solution.load(tmp_path / f"{i.name}.seed.json")
        assert s.instance == i.name and s.validation.valid
    rows = (tmp_path / "index.csv").read_text().strip().splitlines()
    assert len(rows) == 4 and rows[0].startswith("name,n,family")


def test_cli_generate(tmp_path, capsys):
    from cvrptw_bench.cli import main

    rc = main(["generate", "--out", str(tmp_path), "--only", "C-100-L-85"])
    assert rc == 0 and (tmp_path / "C-100-L-85.json").exists()
    assert main(["info", str(tmp_path / "C-100-L-85.json")]) == 0
    out = capsys.readouterr().out
    assert "factors" in out and "seed solution" in out

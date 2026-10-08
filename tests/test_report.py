"""Phase 6: resumable runner, result collection, coverage-first gaps, HTML report."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cvrptw_bench.report.aggregate import (
    SEED_NAME,
    add_gaps,
    by_factor,
    collect,
    overall,
    per_instance_table,
    performance_profile,
)
from cvrptw_bench.report.build_html import _complete_instances, _ranked, build_report
from cvrptw_bench.run import run_benchmark

CFG = {
    "time_limits_s": {"default": 1},
    "cw": {"multistart_runs": 3},
    "cw_ls": {},
    "ortools": {},
}
SOLVERS = ["cw", "cw_ls", "ortools"]


@pytest.fixture(scope="module")
def mini_instances(tmp_path_factory, toy_instance_dict) -> Path:
    """Two copies of the toy instance with benchmark factors, plus a seed solution."""
    d = tmp_path_factory.mktemp("instances")
    for name, fac in (
        ("T-6-L-60", {"n": 6, "family": "T", "tw_profile": "L", "capacity_stress": 60}),
        ("T-6-T-85", {"n": 6, "family": "T", "tw_profile": "T", "capacity_stress": 85}),
    ):
        inst = dict(toy_instance_dict)
        inst["name"] = name
        inst["meta"] = {**inst.get("meta", {}), "factors": fac}
        (d / f"{name}.json").write_text(json.dumps(inst), encoding="utf-8")
    # the seed of the first instance: the hand-checked toy solution under the new name
    from tests.conftest import DATA

    seed = json.loads((DATA / "toy_solution.json").read_text(encoding="utf-8"))
    seed["instance"] = "T-6-L-60"
    (d / "T-6-L-60.seed.json").write_text(json.dumps(seed), encoding="utf-8")
    return d


@pytest.fixture(scope="module")
def mini_run(mini_instances, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("run")
    rows = run_benchmark(
        CFG, mini_instances, SOLVERS, out, workers=1, plots=False, log=lambda *_: None
    )
    assert len(rows) == 6
    return out


def test_run_writes_artefacts_and_log(mini_run):
    assert (mini_run / "run_meta.json").exists()
    meta = json.loads((mini_run / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["solvers"] == SOLVERS and meta["instances"] == ["T-6-L-60", "T-6-T-85"]
    assert meta["host"]["cpu_count"] >= 1 and "ortools" in meta["host"]["packages"]
    log = [json.loads(line) for line in (mini_run / "log.jsonl").read_text().splitlines()]
    assert len(log) == 6 and all(r["status"] == "feasible" and r["valid"] for r in log)
    for name in ("T-6-L-60", "T-6-T-85"):
        for s in SOLVERS:
            assert (mini_run / name / s / "solution.json").exists()
            assert not (mini_run / name / s / "map.png").exists()  # plots=False


def test_run_resume_skips_finished_jobs(mini_run, mini_instances):
    started = json.loads((mini_run / "run_meta.json").read_text(encoding="utf-8"))["started"]
    rows = run_benchmark(
        CFG, mini_instances, SOLVERS, mini_run, workers=1, plots=False, log=lambda *_: None
    )
    assert len(rows) == 6 and all(r["status"] == "skipped" for r in rows)
    meta = json.loads((mini_run / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["started"] == started and len(meta["resumed"]) == 1  # original start is kept
    # a broken solution file is redone, not trusted
    p = mini_run / "T-6-T-85" / "cw" / "solution.json"
    p.write_text("{not json", encoding="utf-8")
    rows = run_benchmark(
        CFG, mini_instances, ["cw"], mini_run, workers=1, plots=False, log=lambda *_: None
    )
    assert [r["status"] for r in rows] == ["skipped", "feasible"]
    assert json.loads(p.read_text(encoding="utf-8"))["status"] == "feasible"


def test_run_filters_by_name_and_reports_errors(mini_instances, tmp_path):
    rows = run_benchmark(
        CFG,
        mini_instances,
        ["cw", "no_such_solver"],
        tmp_path,
        names=["T-6-T-85"],
        plots=False,
        log=lambda *_: None,
    )
    assert len(rows) == 2
    by_solver = {r["solver"]: r for r in rows}
    assert by_solver["cw"]["status"] == "feasible"
    assert by_solver["no_such_solver"]["status"] == "error"
    assert "no_such_solver" in by_solver["no_such_solver"]["message"]


def test_collect_reads_results_and_seed(mini_run, mini_instances):
    df = collect(mini_run, mini_instances)
    assert set(df["solver"].cat.categories) == set(SOLVERS) | {SEED_NAME}
    assert len(df) == 7  # 6 results + 1 seed
    assert list(df["solver"].cat.categories)[:1] == ["ortools"]  # fixed display order
    assert (df["n"] == 6).all() and set(df["capacity_stress"]) == {60, 85}
    assert df["valid"].all()
    seed = df[df["solver"] == SEED_NAME].iloc[0]
    assert seed["instance"] == "T-6-L-60" and seed["total_cost"] == 139708  # the hand-made plan


def test_add_gaps_is_coverage_first():
    rows = [
        # instance A: b serves fewer -> deficit, no cost gap; a and c at best coverage
        dict(instance="A", n=10, solver="a", valid=True, served=10, total_cost=100),
        dict(instance="A", n=10, solver="b", valid=True, served=9, total_cost=50),
        dict(instance="A", n=10, solver="c", valid=True, served=10, total_cost=120),
        # instance B: the invalid result is never 'best' even though it is cheapest
        dict(instance="B", n=10, solver="a", valid=False, served=10, total_cost=10),
        dict(instance="B", n=10, solver="b", valid=True, served=10, total_cost=200),
        dict(instance="B", n=10, solver="c", valid=True, served=10, total_cost=200),
    ]
    df = pd.DataFrame(rows)
    df["solver"] = pd.Categorical(df["solver"], categories=["a", "b", "c"])
    g = add_gaps(df).set_index(["instance", "solver"])
    assert g.loc[("A", "a"), "cost_gap"] == 0 and g.loc[("A", "a"), "is_best"]
    assert g.loc[("A", "c"), "cost_gap"] == pytest.approx(0.2)
    assert np.isnan(g.loc[("A", "b"), "cost_gap"]) and g.loc[("A", "b"), "coverage_deficit"] == 1
    assert np.isnan(g.loc[("B", "a"), "cost_gap"]) and not g.loc[("B", "a"), "is_best"]
    assert g.loc[("B", "b"), "is_best"] and g.loc[("B", "c"), "is_best"]  # ties both count
    assert g.loc[("B", "a"), "best_cost"] == 200
    pp = performance_profile(g.reset_index(), taus=np.array([1.0, 1.25]))
    frac = pp.set_index(["solver", "tau"])["fraction"]
    assert frac[("a", 1.0)] == 0.5 and frac[("c", 1.25)] == 1.0 and frac[("b", 1.25)] == 0.5


def test_tables_and_ranking(mini_run, mini_instances):
    df = add_gaps(collect(mini_run, mini_instances))
    ov = overall(df)
    assert set(ov["solver"]) == set(SOLVERS)  # the seed is a reference, not a contender
    assert (ov["instances"] == 2).all()
    bf = by_factor(df, "tw_profile")
    assert set(bf["tw_profile"]) == {"L", "T"}
    wide = per_instance_table(df)
    assert len(wide) == 2 and ("served", "ortools") in wide.columns
    stats = {
        "x": {"deficit": 0, "best_cost": 1, "gap_mean": 2.0},
        "y": {"deficit": 0, "best_cost": 3, "gap_mean": 5.0},
        "z": {"deficit": 2, "best_cost": 9, "gap_mean": 0.0},
    }
    assert _ranked(["x", "y", "z"], stats) == ["y", "x", "z"]  # coverage first, then wins


def test_complete_instances_filter(mini_run, mini_instances):
    df = collect(mini_run, mini_instances)
    kept, dropped = _complete_instances(df)
    assert dropped == [] and kept["instance"].nunique() == 2
    partial = df[~((df["instance"] == "T-6-T-85") & (df["solver"] == "ortools"))]
    kept, dropped = _complete_instances(partial)
    assert dropped == ["T-6-T-85"] and set(kept["instance"]) == {"T-6-L-60"}


def test_build_report_html(mini_run, mini_instances, tmp_path):
    out = build_report(
        mini_run, mini_instances, out_path=tmp_path / "report.html", gallery=0, log=lambda *_: None
    )
    html = out.read_text(encoding="utf-8")
    assert out.exists() and len(html) > 100_000  # plotly.js is inlined
    for needle in ("6. Conclusions", "Which tool when", "Hexaly (pending)", "T-6-T-85", "OR-Tools"):
        assert needle in html
    assert "`" not in html.split("6. Conclusions")[1].split("7. Every")[0]  # no raw markdown
    tables = tmp_path / "tables"
    assert (tables / "overall.csv").exists() and (tables / "results_by_instance.csv").exists()
    assert len(pd.read_csv(tables / "results_long.csv")) == 7


def test_compare_runs_joins_variant_to_base(mini_run, mini_instances, tmp_path):
    from cvrptw_bench.report.compare import combine, compare_runs

    exp = tmp_path / "exp"
    rows = run_benchmark(
        {**CFG, "cw": {"multistart_runs": 2}},
        mini_instances,
        ["cw"],
        exp,
        workers=1,
        plots=False,
        log=lambda *_: None,
    )
    assert len(rows) == 2
    df = combine(mini_run, exp, mini_instances, "_v2")
    cats = list(df["solver"].cat.categories)
    assert "cw_v2" in cats and cats.index("cw_v2") == cats.index("cw") + 1
    assert df["instance"].nunique() == 2 and (df["solver"] == "cw_v2").sum() == 2
    assert df["best_served"].notna().all()  # gaps computed over base + variant together
    out = compare_runs(mini_run, exp, mini_instances, "_v2", "T", "d", tmp_path / "c.md")
    text = out.read_text(encoding="utf-8")
    assert "Clarke-Wright v2 vs Clarke-Wright" in text and "Clarke-Wright v2 vs OR-Tools" in text
    assert (tmp_path / "comparison_by_instance.csv").exists()

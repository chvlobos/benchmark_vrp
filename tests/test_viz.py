from pathlib import Path

import pytest

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.solution import RoutePlan, Solution
from cvrptw_bench.core.validator import evaluate
from cvrptw_bench.viz import plot_all, plot_gantt, plot_map, plot_map_html
from cvrptw_bench.viz.gantt import _pack_lanes
from cvrptw_bench.viz.style import hhmm, route_shade, type_color_map

INSTANCES = Path("instances")


def _png_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 5_000 and p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_plot_all_toy(tmp_path, toy_instance, toy_solution):
    paths = plot_all(toy_instance, toy_solution, tmp_path, basemap=False, dpi=60)
    assert _png_ok(paths["map_png"]) and _png_ok(paths["gantt_png"])
    html = paths["map_html"].read_text(encoding="utf-8")
    assert "toy-6" in html and "v02 large" in html and "Depot" in html


def test_plots_with_unserved(tmp_path, toy_instance, toy_matrices):
    sol = evaluate(toy_instance, RoutePlan(routes={0: [1, 3], 1: [2, 5]}), None, toy_matrices)
    assert len(sol.unserved) == 2
    assert _png_ok(plot_map(toy_instance, sol, tmp_path / "m.png", basemap=False, dpi=60))
    assert _png_ok(plot_gantt(toy_instance, sol, tmp_path / "g.png", dpi=60))
    html = plot_map_html(toy_instance, sol, tmp_path / "m.html").read_text(encoding="utf-8")
    assert "unserved (2)" in html


def test_empty_solution_plots(tmp_path, toy_instance, toy_matrices):
    sol = evaluate(toy_instance, RoutePlan(), None, toy_matrices)  # nothing served
    assert _png_ok(plot_map(toy_instance, sol, tmp_path / "m.png", basemap=False, dpi=60))
    assert _png_ok(plot_gantt(toy_instance, sol, tmp_path / "g.png", dpi=60))


@pytest.mark.skipif(not INSTANCES.exists(), reason="instance set not generated")
def test_plot_seed_solution_large(tmp_path):
    name = "RC-600-T-105"
    inst = Instance.load(INSTANCES / f"{name}.json")
    sol = Solution.load(INSTANCES / f"{name}.seed.json")
    paths = plot_all(inst, sol, tmp_path, basemap=False, dpi=50, html=False)
    assert _png_ok(paths["map_png"]) and _png_ok(paths["gantt_png"])


def test_pack_lanes():
    iv = [(0, 10, 1), (5, 15, 2), (10, 20, 3), (16, 30, 4)]
    lanes = _pack_lanes(iv)
    assert lanes == [0, 1, 0, 1]
    many = [(i, i + 100, i) for i in range(30)]
    assert max(_pack_lanes(many, max_lanes=5)) == 4


def test_style_helpers(toy_instance):
    cm = type_color_map(toy_instance)
    assert list(cm) == ["small", "large"] and cm["small"] != cm["large"]
    assert route_shade(cm["small"], 0) == cm["small"] and route_shade(cm["small"], 1) != cm["small"]
    assert hhmm(36000) == "10:00" and hhmm(45088) == "12:31"


def test_cli_plot(tmp_path, capsys):
    from cvrptw_bench.cli import main

    rc = main(
        [
            "plot",
            "tests/data/toy_solution.json",
            "--instance",
            "tests/data/toy_instance.json",
            "--out",
            str(tmp_path),
            "--no-basemap",
            "--dpi",
            "60",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0 and "map_png" in out and (tmp_path / "gantt.png").exists()

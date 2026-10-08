from pathlib import Path

import pytest

from cvrptw_bench.cli import main
from tests.conftest import DATA

INST = str(DATA / "toy_instance.json")


def test_version(capsys):
    assert main(["version"]) == 0
    assert "cvrptw-bench" in capsys.readouterr().out


def test_info(capsys):
    assert main(["info", INST]) == 0
    out = capsys.readouterr().out
    assert "toy-6" in out and "capacity stress" in out


def test_validate_valid(capsys, tmp_path):
    out_path = tmp_path / "re.json"
    rc = main(
        ["validate", str(DATA / "toy_solution.json"), "--instance", INST, "--write", str(out_path)]
    )
    out = capsys.readouterr().out
    assert rc == 0 and out.startswith("VALID") and out_path.exists()


@pytest.mark.parametrize("name", sorted(p.stem for p in DATA.glob("broken_*.json")))
def test_validate_broken(capsys, name):
    rc = main(["validate", str(DATA / f"{name}.json"), "--instance", INST])
    out = capsys.readouterr().out
    assert rc == 1 and out.startswith("INVALID") and "violation:" in out


def test_fixture_files_present():
    assert Path(INST).exists()
    assert len(list(DATA.glob("broken_*.json"))) >= 5

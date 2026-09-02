from __future__ import annotations

import json
from pathlib import Path

import pytest

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import build_matrices
from cvrptw_bench.core.solution import RoutePlan, Solution

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def toy_instance() -> Instance:
    return Instance.load(DATA / "toy_instance.json")


@pytest.fixture(scope="session")
def toy_matrices(toy_instance):
    return build_matrices(toy_instance)


@pytest.fixture(scope="session")
def toy_solution() -> Solution:
    return Solution.load(DATA / "toy_solution.json")


@pytest.fixture(scope="session")
def valid_plan() -> RoutePlan:
    return RoutePlan(routes={0: [1, 3], 1: [2, 5], 2: [6, 4]})


@pytest.fixture(scope="session")
def toy_instance_dict() -> dict:
    with open(DATA / "toy_instance.json", encoding="utf-8") as fh:
        return json.load(fh)

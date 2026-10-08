import copy

import pytest

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import build_matrices
from cvrptw_bench.core.solution import RoutePlan, Solution, SolverRun
from cvrptw_bench.core.validator import (
    evaluate,
    forward_schedule,
    is_feasible_order,
    latest_departure,
    latest_starts,
    revalidate,
)
from tests.make_fixtures import BROKEN_PLANS

H0, H1 = 36000, 64800


# ------------------------------------------------------------ valid solution
def test_valid_solution_hand_checked(toy_instance, toy_matrices, valid_plan):
    sol = evaluate(toy_instance, valid_plan, SolverRun(solver="t"), toy_matrices)
    assert sol.validation.valid and sol.validation.violations == []
    assert sol.metrics["served"] == 6 and sol.unserved == []
    r0 = next(r for r in sol.routes if r.vehicle_id == 0)
    # vehicle 0: depot 10:00 -> Providencia (519 s) -> Las Condes (784 s) -> depot (1302 s)
    assert r0.depart == H0
    assert [s.customer for s in r0.stops] == [1, 3]
    assert r0.stops[0].arrival == 36519 and r0.stops[0].wait == 0 and r0.stops[0].departure == 37119
    assert r0.stops[1].arrival == 37903 and r0.stops[1].service_start == 37903
    assert r0.return_time == 38803 + 1302
    assert r0.distance_m == 4321 + 6531 + 10851
    assert r0.variable_cost == 1512 + 2286 + 3798 and r0.fixed_cost == 20000 and r0.cost == 27596
    assert r0.load == 90 and r0.capacity == 100
    # totals
    assert sol.metrics["fixed_cost"] == 2 * 20000 + 45000
    assert sol.metrics["total_cost"] == sum(r.cost for r in sol.routes)
    assert sol.metrics["vehicles_used"] == {"small": 2, "large": 1}
    assert sol.objective == (6, sol.metrics["total_cost"])


def test_min_wait_departure_removes_avoidable_waiting(toy_instance, toy_matrices, valid_plan):
    sol = evaluate(toy_instance, valid_plan, None, toy_matrices)  # default policy: min_wait
    r1 = next(r for r in sol.routes if r.vehicle_id == 1)
    # Nunoa opens at 11:00; leaving at 10:00 would mean waiting 2759 s there
    assert r1.depart == H0 + 2759
    assert r1.stops[0].arrival == 39600 and r1.stops[0].wait == 0
    r2 = next(r for r in sol.routes if r.vehicle_id == 2)
    # Quilicura closes at 13:00 and Maipu opens at 16:00: the first wait is avoidable,
    # the second is not, and the slack caps the delay at the latest departure
    assert r2.depart == 46800 - 1712
    assert r2.stops[0].wait == 0 and r2.stops[1].wait == 57600 - 49929


def test_departure_policies(toy_instance, toy_matrices, valid_plan):
    earliest = evaluate(toy_instance, valid_plan, None, toy_matrices, departure_policy="earliest")
    assert all(r.depart == H0 for r in earliest.routes)
    latest = evaluate(toy_instance, valid_plan, None, toy_matrices, departure_policy="latest")
    r0 = next(r for r in latest.routes if r.vehicle_id == 0)
    assert r0.depart == latest_departure(toy_matrices, [1, 3], H0, H1) > H0
    # cost and coverage never depend on the policy
    for s in (earliest, latest):
        assert s.metrics["total_cost"] == 139708 and s.metrics["served"] == 6
    with pytest.raises(ValueError):
        evaluate(toy_instance, valid_plan, None, toy_matrices, departure_policy="whenever")


# ----------------------------------------------------------- broken solutions
@pytest.mark.parametrize("name", sorted(BROKEN_PLANS))
def test_broken_plans_are_rejected(toy_instance, toy_matrices, name):
    sol = evaluate(toy_instance, RoutePlan(routes=BROKEN_PLANS[name]), None, toy_matrices)
    assert not sol.validation.valid
    assert any(v.startswith(name + ":") for v in sol.validation.violations), (
        sol.validation.violations
    )


def test_broken_fixtures_on_disk_match(toy_instance):
    from tests.conftest import DATA

    for name in BROKEN_PLANS:
        stored = Solution.load(DATA / f"broken_{name}.json")
        assert not stored.validation.valid
        fresh, diffs = revalidate(toy_instance, stored)
        assert diffs == [] and not fresh.validation.valid


def test_revalidate_detects_tampered_cost(toy_instance, toy_solution):
    tampered = toy_solution.model_copy(deep=True)
    tampered.metrics["total_cost"] = 1  # a solver "reporting" a better cost than it has
    fresh, diffs = revalidate(toy_instance, tampered)
    assert fresh.metrics["total_cost"] == 139708
    assert any(d.startswith("total_cost") for d in diffs)


# ------------------------------------------------------- schedule primitives
def test_schedule_primitives(toy_matrices):
    seq = [1, 3]
    s = forward_schedule(toy_matrices, seq, H0)
    assert (
        list(s.arrival) == [36519, 37903]
        and s.return_time == 40105
        and s.travel_s == 519 + 784 + 1302
    )
    L = latest_starts(toy_matrices, seq, H1)
    # last stop: min(tw_end=43200, 64800 - 900 - 1302) = 43200
    # first stop: min(38700, 43200 - 600 - 784) = 38700
    assert list(L) == [38700, 43200]
    assert latest_departure(toy_matrices, seq, H0, H1) == 38700 - 519
    assert is_feasible_order(toy_matrices, [1, 3], H0, H1)
    assert not is_feasible_order(toy_matrices, [3, 1], H0, H1)
    assert forward_schedule(toy_matrices, [], H0).return_time == H0


# ------------------------------------------------------ unserved diagnostics
def test_unserved_insertable_when_vehicle_spare(toy_instance, toy_matrices):
    plan = RoutePlan(routes={0: [1, 3], 1: [2, 5]})  # large vehicle idle, 4 and 6 dropped
    sol = evaluate(toy_instance, plan, None, toy_matrices)
    assert sol.validation.valid  # dropping customers is not a violation
    assert {u.customer: u.reason for u in sol.unserved} == {4: "insertable", 6: "insertable"}
    assert sol.metrics["unserved_by_reason"]["insertable"] == 2
    assert sol.metrics["unserved_demand"] == 165


def test_unserved_capacity_reason(toy_instance, toy_matrices):
    # all vehicles used, no room anywhere for customer 4 (120 units)
    plan = RoutePlan(routes={0: [1, 3], 1: [2, 5], 2: [6]})
    inst = toy_instance.model_copy(deep=True)
    inst.vehicle_types[1].capacity = 150  # large now 150: 45 + 120 > 150
    m = build_matrices(inst)
    sol = evaluate(inst, plan, None, m)
    assert [u.reason for u in sol.unserved] == ["capacity"]


def test_unserved_time_window_reason(toy_instance_dict):
    # customer 6 window is 12:00-13:00; make the large vehicle busy far away at that time
    d = copy.deepcopy(toy_instance_dict)
    d["customers"][3]["tw_start"], d["customers"][3]["tw_end"] = 43200, 45000  # Maipu 12:00-12:30
    d["customers"][3]["service_time"] = 3600
    inst = Instance.model_validate(d)
    m = build_matrices(inst)
    plan = RoutePlan(routes={0: [1, 3], 1: [2, 5], 2: [4]})
    sol = evaluate(inst, plan, None, m)
    assert sol.validation.valid
    (u,) = sol.unserved
    assert u.customer == 6 and u.reason == "time_window"


def test_unserved_unreachable_window(toy_instance_dict):
    d = copy.deepcopy(toy_instance_dict)
    d["customers"][3]["tw_start"], d["customers"][3]["tw_end"] = 36000, 36600  # Maipu 10:00-10:10
    inst = Instance.model_validate(d)
    sol = evaluate(inst, RoutePlan(routes={0: [1, 3], 1: [2, 5], 2: [6]}), None)
    (u,) = sol.unserved
    assert u.customer == 4 and u.reason == "unreachable_window"


def test_solution_roundtrip(tmp_path, toy_instance, toy_solution):
    p = tmp_path / "s.json"
    toy_solution.save(p)
    again = Solution.load(p)
    assert again == toy_solution
    assert again.plan().routes == {0: [1, 3], 1: [2, 5], 2: [6, 4]}
    assert not p.with_suffix(".json.tmp").exists()

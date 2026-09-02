"""Regenerate the toy fixtures under tests/data (run: python tests/make_fixtures.py).

The toy instance has 6 customers around Santiago, 2 small vehicles (capacity
100) and 1 large vehicle (capacity 250). The hand-checked feasible solution is

    vehicle 0 (small): 1 -> 3            load 90
    vehicle 1 (small): 2 -> 5            load 90
    vehicle 2 (large): 6 -> 4            load 165 (customer 4 needs the large one)

and each broken solution violates exactly one rule (plus, where unavoidable,
the consequences of that single change).
"""

from __future__ import annotations

from pathlib import Path

from cvrptw_bench.core.instance import Instance
from cvrptw_bench.core.matrices import build_matrices
from cvrptw_bench.core.solution import RoutePlan, SolverRun
from cvrptw_bench.core.validator import evaluate

DATA = Path(__file__).parent / "data"

POINTS = {
    1: ("Providencia", -33.4264, -70.6172, 40, 600, 36000, 38700),  # 10:00-10:45
    2: ("Nunoa", -33.4569, -70.5975, 30, 600, 39600, 64200),  # 11:00-17:50
    3: ("Las Condes", -33.4089, -70.5673, 50, 900, 37800, 43200),  # 10:30-12:00
    4: ("Maipu", -33.5110, -70.7580, 120, 1500, 57600, 63000),  # 16:00-17:30
    5: ("La Florida", -33.5227, -70.5987, 60, 900, 39600, 63000),  # 11:00-17:30
    6: ("Quilicura", -33.3667, -70.7333, 45, 600, 43200, 46800),  # 12:00-13:00
}


def toy_instance() -> Instance:
    return Instance.model_validate(
        {
            "name": "toy-6",
            "meta": {
                "note": "hand-made fixture for validator tests",
                "labels": {k: v[0] for k, v in POINTS.items()},
            },
            "horizon": {"start": 36000, "end": 64800},
            "travel": {"speed_kmh": 30, "detour_factor": 1.3, "distance": "haversine"},
            "depot": {"lat": -33.4372, "lon": -70.6506},
            "customers": [
                {
                    "id": k,
                    "lat": v[1],
                    "lon": v[2],
                    "demand": v[3],
                    "service_time": v[4],
                    "tw_start": v[5],
                    "tw_end": v[6],
                }
                for k, v in POINTS.items()
            ],
            "vehicle_types": [
                {
                    "type": "small",
                    "capacity": 100,
                    "count": 2,
                    "fixed_cost": 20000,
                    "cost_per_km": 350,
                },
                {
                    "type": "large",
                    "capacity": 250,
                    "count": 1,
                    "fixed_cost": 45000,
                    "cost_per_km": 700,
                },
            ],
        }
    )


VALID_PLAN = {0: [1, 3], 1: [2, 5], 2: [6, 4]}

BROKEN_PLANS = {
    # customer 4 (120 units) on a small vehicle (capacity 100)
    "capacity": {0: [1, 3], 1: [2, 5, 4], 2: [6]},
    # visiting 3 before 1 reaches customer 1 at ~10:58 > 10:45
    "time_window": {0: [3, 1], 1: [2, 5], 2: [6, 4]},
    # 4 -> 5 -> 2 ends at ~18:05 > 18:00 closing (every window respected)
    "horizon": {0: [1, 3], 1: [6], 2: [4, 5, 2]},
    # vehicle 7 does not exist (fleet has vehicles 0..2)
    "unknown_vehicle": {0: [1, 3], 1: [2, 5], 7: [6, 4]},
    # customer 3 visited by two vehicles
    "duplicate_customer": {0: [1, 3], 1: [3, 2, 5], 2: [6, 4]},
    # customer 9 does not exist
    "unknown_customer": {0: [1, 3], 1: [2, 5, 9], 2: [6, 4]},
}


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    inst = toy_instance()
    inst.save(DATA / "toy_instance.json")
    m = build_matrices(inst)
    run = SolverRun(solver="handmade", solver_version="fixture", wall_time_s=0.0)
    sol = evaluate(inst, RoutePlan(routes=VALID_PLAN), run, m)
    assert sol.validation.valid, sol.validation.violations
    sol.save(DATA / "toy_solution.json")
    for name, plan in BROKEN_PLANS.items():
        broken = evaluate(inst, RoutePlan(routes=plan), run, m)
        assert not broken.validation.valid, name
        broken.save(DATA / f"broken_{name}.json")
        print(f"{name:<20} {broken.validation.violations}")
    print("valid solution:", sol.metrics["objective"], sol.metrics["distance_km"], "km")


if __name__ == "__main__":
    main()

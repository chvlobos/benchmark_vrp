import math

import numpy as np

from cvrptw_bench.core.matrices import EARTH_RADIUS_KM, build_matrices, haversine_km


def _reference_haversine_km(lat1, lon1, lat2, lon2):
    """Independent scalar implementation (spherical law of cosines form)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    cos_c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return EARTH_RADIUS_KM * math.acos(max(-1.0, min(1.0, cos_c)))


def test_haversine_matches_reference():
    depot = (-33.4372, -70.6506)
    prov = (-33.4264, -70.6172)
    got = float(haversine_km(*depot, *prov))
    ref = _reference_haversine_km(*depot, *prov)
    assert abs(got - ref) < 1e-6
    assert 3.2 < got < 3.4  # Plaza de Armas -> Providencia is about 3.3 km


def test_matrices_rounding_and_shape(toy_instance, toy_matrices):
    m = toy_matrices
    n = toy_instance.n
    assert m.dist_m.shape == (n + 1, n + 1)
    assert m.dist_m.dtype == np.int64 and m.time_s.dtype == np.int64 and m.cost.dtype == np.int64
    assert np.all(np.diag(m.dist_m) == 0)
    assert np.array_equal(m.dist_m, m.dist_m.T)
    # rounding rules, checked on one arc against the raw formula
    km = float(haversine_km(m.lat[0], m.lon[0], m.lat[1], m.lon[1]))
    assert m.dist_m[0, 1] == int(np.rint(km * 1.3 * 1000))
    assert m.time_s[0, 1] == int(np.rint(m.dist_m[0, 1] * 3.6 / 30))
    assert m.cost[0, 0, 1] == int(np.rint(350 * m.dist_m[0, 1] / 1000))
    assert m.cost[1, 0, 1] == int(np.rint(700 * m.dist_m[0, 1] / 1000))
    # hand-checked value from the fixture (depot -> Providencia)
    assert m.dist_m[0, 1] == 4321 and m.time_s[0, 1] == 519


def test_node_arrays(toy_instance, toy_matrices):
    m = toy_matrices
    assert m.demand[0] == 0 and m.service[0] == 0
    assert m.tw_start[0] == toy_instance.horizon.start and m.tw_end[0] == toy_instance.horizon.end
    assert m.demand[4] == 120 and m.service[4] == 1500


def test_route_helpers(toy_matrices):
    m = toy_matrices
    assert m.route_distance_m([]) == 0 and m.route_arc_cost(0, []) == 0
    assert m.route_distance_m([1, 3]) == 4321 + 6531 + 10851
    assert m.route_arc_cost(0, [1, 3]) == 1512 + 2286 + 3798


def test_neighbours_exclude_self_and_depot(toy_matrices):
    nb = toy_matrices.neighbours(3)
    assert nb.shape == (7, 3)
    for i in range(7):
        assert i not in nb[i]
        assert 0 not in nb[i]
    # Providencia's nearest neighbour by time is Nunoa (601 s)
    assert nb[1][0] == 2


def test_build_is_deterministic(toy_instance):
    a, b = build_matrices(toy_instance), build_matrices(toy_instance)
    assert np.array_equal(a.dist_m, b.dist_m) and np.array_equal(a.cost, b.cost)

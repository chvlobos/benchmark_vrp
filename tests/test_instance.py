import copy

import pytest
from pydantic import ValidationError

from cvrptw_bench.core.instance import Instance, seconds_to_hhmm


def test_roundtrip(tmp_path, toy_instance):
    p = tmp_path / "i.json"
    toy_instance.save(p)
    again = Instance.load(p)
    assert again == toy_instance


def test_derived_quantities(toy_instance):
    assert toy_instance.n == 6
    assert toy_instance.n_vehicles == 3
    assert toy_instance.total_demand == 345
    assert toy_instance.fleet_capacity == 2 * 100 + 250
    vs = toy_instance.vehicles()
    assert [v.id for v in vs] == [0, 1, 2]
    assert [v.type for v in vs] == ["small", "small", "large"]
    assert vs[2].capacity == 250 and vs[2].cost_per_km == 700
    assert toy_instance.type_index("large") == 1


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["customers"][2].__setitem__("id", 9), "ids must be exactly 1..n"),
        (lambda d: d["customers"][0].__setitem__("demand", 999), "exceeds the largest capacity"),
        (lambda d: d["customers"][0].__setitem__("tw_end", 70000), "outside the operating horizon"),
        (lambda d: d["customers"][0].__setitem__("tw_start", 40000), "tw_end < tw_start"),
        (lambda d: d["vehicle_types"][1].__setitem__("type", "small"), "must be unique"),
        (lambda d: d["horizon"].__setitem__("end", 36000), "greater than horizon.start"),
        (lambda d: d.__setitem__("customers", []), "no customers"),
        (lambda d: d.__setitem__("schema_version", 7), "unsupported schema_version"),
    ],
)
def test_schema_rejections(toy_instance_dict, mutate, message):
    d = copy.deepcopy(toy_instance_dict)
    mutate(d)
    with pytest.raises(ValidationError) as exc:
        Instance.model_validate(d)
    assert message in str(exc.value)


def test_extra_fields_rejected(toy_instance_dict):
    d = copy.deepcopy(toy_instance_dict)
    d["customers"][0]["priority"] = 1
    with pytest.raises(ValidationError):
        Instance.model_validate(d)


def test_hhmm():
    assert seconds_to_hhmm(36000) == "10:00"
    assert seconds_to_hhmm(64800) == "18:00"
    assert seconds_to_hhmm(45088) == "12:31"

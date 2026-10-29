"""Extracted catalogue equations preserve native values and physical units."""

import pytest
import pyomo.environ as pyo
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language.standard.compressor_map import (
    build_compressor_map,
    get_catalogue,
    get_performance_map,
)


def native_polynomial(c, et, ct):
    # Written explicitly to independently check coefficient order and cross terms.
    return (
        c[0]
        + c[1] * et
        + c[2] * ct
        + c[3] * et**2
        + c[4] * et * ct
        + c[5] * ct**2
        + c[6] * et**3
        + c[7] * et**2 * ct
        + c[8] * et * ct**2
        + c[9] * ct**3
    )


@pytest.mark.parametrize("map_id", [item["id"] for item in get_catalogue()["maps"]])
@pytest.mark.parametrize("speed", [20, 60, 120])
@pytest.mark.parametrize("et,ct", [(-20, 35), (7.2, 54.4), (15, 65)])
def test_map_equations_match_native_catalogue(map_id, speed, et, ct):
    model = pyo.ConcreteModel()
    mapped = build_compressor_map(
        model, {"performance_map": map_id, "speed_rps": speed}
    )
    assert_units_consistent(model)
    model.evaporating_temperature.set_value(et + 273.15)
    model.condensing_temperature.set_value(ct + 273.15)
    coefficients = get_performance_map(map_id)["speed_maps"][str(speed)]["coefficients"]
    for output, source, divisor in (
        ("mass_flow", "mass_flow", 3600),
        ("electrical_power", "electrical_input", 1),
        ("capacity", "capacity", 1),
        ("current", "current", 1),
    ):
        expected = native_polynomial(coefficients[source], et, ct) / divisor
        mapped[f"performance.{output}"].set_value(expected)
    model.rated_cop.set_value(pyo.value(model.capacity / model.electrical_power))
    rating = get_performance_map(map_id)["rating"]
    model.superheat.set_value(rating["superheat_k"])
    model.subcooling.set_value(rating["subcooling_k"])
    for equation in model.equations.values():
        assert pyo.value(equation.body - equation.lower) == pytest.approx(0, abs=1e-8)


def test_defaults_and_fresh_unfixed_occurrences():
    model = pyo.ConcreteModel()
    model.first = pyo.Block()
    model.second = pyo.Block()
    first = build_compressor_map(model.first, {})
    second = build_compressor_map(model.second, {})
    assert set(first) == {
        "temperatures.evaporating",
        "temperatures.condensing",
        "performance.mass_flow",
        "performance.electrical_power",
        "performance.capacity",
        "performance.current",
        "performance.rated_cop",
        "rating.superheat",
        "rating.subcooling",
    }
    assert all(first[name] is not second[name] for name in first)
    assert all(
        not v.fixed and v.value is None for v in model.component_data_objects(pyo.Var)
    )
    assert get_performance_map()["refrigerant"] == "propane"
    assert get_performance_map()["rating"]["superheat_k"] == 11.1
    assert get_performance_map()["rating"]["subcooling_k"] == 8.4
    assert (
        get_performance_map()["provenance"]["application_envelope_available"] is False
    )


def test_catalogue_inspection_returns_independent_metadata():
    get_performance_map()["rating"]["superheat_k"] = -1
    assert get_performance_map()["rating"]["superheat_k"] == 11.1


def test_default_rating_matches_upstream_reference_values():
    # Reference values evaluated from Ahuora's source catalogue at 60 rps,
    # ET=7.2 C and CT=54.4 C; native mass flow is kg/hour.
    coefficients = get_performance_map()["speed_maps"]["60"]["coefficients"]
    expected = {
        "capacity": 3110.311326881739,
        "electrical_input": 883.8508203054206,
        "current": 4.174794896934372,
        "mass_flow": 40.28950867832506,
    }
    for name, reference in expected.items():
        assert native_polynomial(coefficients[name], 7.2, 54.4) == pytest.approx(
            reference
        )


@pytest.mark.parametrize(
    "config,match",
    [
        ({"performance_map": "missing"}, "Unknown compressor performance map"),
        ({"speed_rps": 65}, "Unknown compressor speed"),
    ],
)
def test_unknown_map_and_speed_are_descriptive(config, match):
    with pytest.raises(ValueError, match=match):
        build_compressor_map(pyo.ConcreteModel(), config)

"""EN 12900 catalogue equations, independent of any thermodynamic package.

Coefficients and provenance are copied from Ahuora's developer-managed
catalogue. Temperatures are dew-point temperatures in kelvin; the native
correlations use numerical degrees Celsius and mass flow in kg/hour.
"""

from __future__ import annotations

from importlib.resources import files
import json
from typing import Any


DEFAULT_PERFORMANCE_MAP = "spb172fnkmt_cooling_pcs661ab"
DEFAULT_SPEED_RPS = 60


def get_catalogue() -> dict[str, Any]:
    """Return catalogue data, including rating conditions and source provenance.

    Each call returns fresh data so callers cannot mutate later constructions.
    Inspection does not import Pyomo or Ahuora packages.
    """
    resource = files(__package__).joinpath("data/en12900_compressor_maps.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def get_performance_map(map_id: str = DEFAULT_PERFORMANCE_MAP) -> dict[str, Any]:
    """Return a map and its available discrete speeds (string keys)."""
    maps = get_catalogue()["maps"]
    for performance_map in maps:
        if performance_map["id"] == map_id:
            return performance_map
    available = ", ".join(item["id"] for item in maps)
    raise ValueError(
        f"Unknown compressor performance map {map_id!r}; choose {available}"
    )


def evaluate_en12900_polynomial(
    coefficients, evaporating_temperature_c, condensing_temperature_c
):
    """Evaluate the native ten-term polynomial, numerically or symbolically."""
    et, ct = evaporating_temperature_c, condensing_temperature_c
    basis = (1, et, ct, et**2, et * ct, ct**2, et**3, et**2 * ct, et * ct**2, ct**3)
    return sum(coefficient * term for coefficient, term in zip(coefficients, basis))


def build_compressor_map(block, config):
    """Build scalar map equations and return public-to-internal variable bindings.

    ``performance_map`` selects a catalogue family; ``speed_rps`` selects an
    exact discrete speed (no interpolation). All bundled maps are for propane.
    Rated capacity/COP retain the catalogue's cooling or heating convention;
    neither is the actual compressor energy balance. No envelope is supplied
    by the manufacturer, so extrapolation validity is not established.
    """
    import pyomo.environ as pyo

    performance_map = get_performance_map(
        config.get("performance_map", DEFAULT_PERFORMANCE_MAP)
    )
    speed = config.get("speed_rps", DEFAULT_SPEED_RPS)
    try:
        coefficients = performance_map["speed_maps"][str(speed)]["coefficients"]
    except KeyError:
        available = ", ".join(performance_map["speed_maps"])
        raise ValueError(
            f"Unknown compressor speed {speed!r}; choose {available} rps"
        ) from None

    u = pyo.units
    block.evaporating_temperature = pyo.Var(units=u.K)
    block.condensing_temperature = pyo.Var(units=u.K)
    et = block.evaporating_temperature / u.K - 273.15
    ct = block.condensing_temperature / u.K - 273.15
    block.equations = pyo.ConstraintList()
    mapping = {
        "temperatures.evaporating": block.evaporating_temperature,
        "temperatures.condensing": block.condensing_temperature,
    }
    outputs = (
        ("mass_flow", "mass_flow", u.kg / u.s, u.kg / u.hour),
        ("electrical_power", "electrical_input", u.W, u.W),
        ("capacity", "capacity", u.W, u.W),
        ("current", "current", u.A, u.A),
    )
    for name, source, unit, native_unit in outputs:
        variable = pyo.Var(units=unit)
        block.add_component(name, variable)
        polynomial = evaluate_en12900_polynomial(coefficients[source], et, ct)
        block.equations.add(
            variable == u.convert(polynomial * native_unit, to_units=unit)
        )
        mapping[f"performance.{name}"] = variable

    block.rated_cop = pyo.Var(units=u.dimensionless)
    block.equations.add(block.rated_cop * block.electrical_power == block.capacity)
    mapping["performance.rated_cop"] = block.rated_cop
    for name in ("superheat", "subcooling"):
        variable = pyo.Var(units=u.K)
        block.add_component(name, variable)
        block.equations.add(variable == performance_map["rating"][f"{name}_k"] * u.K)
        mapping[f"rating.{name}"] = variable
    return mapping

"""Run from the repository root: .venv/bin/python examples/custom_models/build.py."""

from pathlib import Path

from pyomo.environ import Constraint, Var, units

from multifidelity.model_language import Library, build_model, required_inputs


HERE = Path(__file__).parent


def build_density(block, config):
    block.density = Var(units=units.kg / units.m**3)
    block.constant = Constraint(
        expr=block.density == config.get("density_kg_m3", 997) * units.kg / units.m**3
    )
    return {"properties.density": block.density}


def initialize_density(block, config):
    """Seed the existing native equation without fixing its output."""
    if not block.density.fixed:
        block.density.set_value(config.get("density_kg_m3", 997))


def build_pump(block, config):
    # Native pressure and power units differ from the public interface.
    block.flow = Var(units=units.kg / units.s)
    block.density = Var(units=units.kg / units.m**3)
    block.pressure_rise = Var(units=units.kPa)
    block.efficiency = Var()
    block.work = Var(units=units.kW)
    block.power_balance = Constraint(
        expr=block.work * block.efficiency
        == block.flow * block.pressure_rise / block.density
    )
    return {
        "inlet.flow": block.flow,
        "inlet.density": block.density,
        "parameters.pressure_rise": block.pressure_rise,
        "parameters.efficiency": block.efficiency,
        "performance.work": block.work,
    }


def make_library():
    library = Library(HERE / "models")
    library.register_provider("example.liquid_density", build_density,
                              initializer=initialize_density)
    library.register_provider("example.pump", build_pump)
    return library


if __name__ == "__main__":
    library = make_library()
    selection = HERE / "implementation.json"
    model = build_model("pump_flowsheet", selection, library=library)
    print("Built pump with external density and pump providers; no solver called.")
    print("Required inputs:")
    for name, variable in required_inputs(
        "pump_flowsheet", selection, library=library
    ).items():
        print(f"  {name}: {variable.unit}")

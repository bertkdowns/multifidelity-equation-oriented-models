"""Predict compressor electrical power: uv run python examples/heat_pump.py."""

from idaes.core import FlowsheetBlock
from pyomo.environ import ConcreteModel, value

from multifidelity import HeatPump, LinearWater, WaterParameterBlock


def build_model():
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    m.fs.properties = WaterParameterBlock(fidelities={"linear": LinearWater()})
    m.fs.hp = HeatPump(
        source_property_package=m.fs.properties,
        sink_property_package=m.fs.properties,
    )
    hp = m.fs.hp
    for port, temperature in ((hp.source_inlet, 300), (hp.sink_inlet, 320)):
        port.flow_mass.fix(1)
        port.temperature.fix(temperature)
        port.pressure.fix(300000)
    hp.fidelities["cop"].COP.fix(3)
    hp.sink_outlet.temperature.fix(330)
    return m


if __name__ == "__main__":
    m = build_model()
    m.fs.hp.initialize(solver="ipopt")
    print(f"Electrical power: {value(m.fs.hp.electrical_power[0]):.3f} W")

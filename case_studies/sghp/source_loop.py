"""Reduced source loop retaining the valve/pump/thermal recycle coupling."""

import json
from pathlib import Path

from idaes.core import FlowsheetBlock
from pyomo.environ import (
    ConcreteModel,
    Constraint,
    Param,
    TransformationFactory,
    units as u,
    value,
)
from pyomo.network import Arc

from multifidelity import (
    HelmholtzWater,
    LinearWater,
    Pump,
    ThermalConditioner,
    Valve,
    WaterParameterBlock,
)


def reference_case():
    return json.loads(
        (Path(__file__).parent / "data" / "reference_case.json").read_text()
    )


def build_source_loop(
    *,
    property_fidelity="linear",
    flow_factor=1.0,
    pressure_Pa=None,
    duty_factor=1.0,
    pump_power_factor=1.0,
):
    data = reference_case()
    specs = data["specifications"]
    ref = data["reference_solution"]
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    builder = {"linear": LinearWater, "helmholtz": HelmholtzWater}[property_fidelity]()
    m.fs.water = WaterParameterBlock(fidelities={property_fidelity: builder})
    m.fs.valve = Valve(property_package=m.fs.water)
    m.fs.pump = Pump(property_package=m.fs.water)
    for name in ("evaporator", "heater", "tank"):
        m.fs.add_component(name, ThermalConditioner(property_package=m.fs.water))
    for name, source, destination in (
        ("tank_to_valve", m.fs.tank.outlet, m.fs.valve.inlet),
        ("valve_to_pump", m.fs.valve.outlet, m.fs.pump.inlet),
        ("pump_to_evaporator", m.fs.pump.outlet, m.fs.evaporator.inlet),
        ("evaporator_to_heater", m.fs.evaporator.outlet, m.fs.heater.inlet),
        ("heater_to_tank", m.fs.heater.outlet, m.fs.tank.inlet),
    ):
        m.fs.add_component(name, Arc(source=source, destination=destination))
    TransformationFactory("network.expand_arcs").apply_to(m)
    # A closed single-stream circuit has one redundant continuity equation.
    # The remaining balances and arcs still enforce flow through the tank.
    m.fs.tank.balances[0].material.deactivate()
    m.fs.flow_target = Param(
        initialize=specs["mass_flow_kg_s"] * flow_factor, units=u.kg / u.s
    )
    m.fs.flow_control = Constraint(
        expr=m.fs.heater.outlet.flow_mass[0] == m.fs.flow_target
    )
    m.fs.tank.outlet.temperature.fix(specs["tank_temperature_K"])
    m.fs.tank.outlet.pressure.fix(
        specs["tank_pressure_Pa"] if pressure_Pa is None else pressure_Pa
    )
    m.fs.tank.heat_duty.fix(0)
    m.fs.evaporator.heat_duty.fix(-specs["evaporator_heat_removed_W"] * duty_factor)
    m.fs.pump.work.fix(specs["pump_power_W"] * pump_power_factor)
    m.fs.pump.efficiency.fix(specs["pump_efficiency"])
    valve = m.fs.valve
    valve.Cv.fix(specs["valve_coefficient_m3_s_Pa_half"])
    valve.alpha.set_value(specs["equal_percentage_alpha"])
    valve.nominal_Cv.set_value(specs["valve_coefficient_m3_s_Pa_half"])
    valve.nominal_pressure_drop.set_value(ref["valve_pressure_drop_Pa"])
    valve.nominal_density.set_value(ref["valve_inlet_density_kg_m3"])
    valve.nominal_opening.set_value(ref["valve_opening"])
    return m


def loop_states(model):
    """The public process states in the reduced loop."""
    for name in ("valve", "pump", "evaporator", "heater", "tank"):
        unit = getattr(model.fs, name)
        yield unit.inlet_state[0]
        yield unit.outlet_state[0]


def set_initial_guesses(model, name="near_reference"):
    """Apply a documented start without solving or changing specifications."""
    guess = reference_case()["initial_guesses"][name]
    specs = reference_case()["specifications"]
    pressure = value(model.fs.tank.outlet.pressure[0])
    for state in loop_states(model):
        low_pressure = (
            state is model.fs.valve.outlet_state[0]
            or state is model.fs.pump.inlet_state[0]
        )
        T = specs["tank_temperature_K"] - (
            10
            if state is model.fs.evaporator.outlet_state[0]
            or state is model.fs.heater.inlet_state[0]
            else 0
        )
        for variable, val in (
            (state.flow_mass, value(model.fs.flow_target) * guess["flow_fraction"]),
            (state.temperature, T),
            (
                state.pressure,
                pressure * guess["suction_pressure_fraction"]
                if low_pressure
                else pressure,
            ),
        ):
            if not variable.fixed:
                variable.set_value(val)
        # Identical elementary thermodynamic guesses for both strategies and
        # property fidelities; no unreported initialization solves.
        state.enth_mass.set_value(104920.1198085 + 4180 * (T - 298.15))
        state.entr_mass.set_value(367.1996421 + (4180 / 298.15) * (T - 298.15))
        state.dens_mass.set_value(985)
        state.cp_mass.set_value(4180)
    model.fs.valve.opening[0].set_value(guess["opening"])


def public_variables(model):
    for state in loop_states(model):
        yield from state.define_state_vars().values()
    yield model.fs.valve.Cv
    yield from model.fs.valve.opening.values()
    yield model.fs.pump.efficiency
    yield from model.fs.pump.work.values()
    for name in ("heater", "evaporator", "tank"):
        yield from getattr(model.fs, name).heat_duty.values()

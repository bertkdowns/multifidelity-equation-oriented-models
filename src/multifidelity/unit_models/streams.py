"""State construction and stream balances using IDAES property packages."""

from pyomo.environ import Constraint, units as u, value


def states(package, *indexes, inlet=False):
    return package.build_state_block(
        *indexes, defined_state=inlet, has_phase_equilibrium=False
    )


def enthalpy_flow(state):
    return sum(state.get_enthalpy_flow_terms(p) for p in state.phase_list)


def convert(source, target):
    return u.convert(source, to_units=u.get_units(target))


def add_stream_ports(unit, package):
    """Create the two public state blocks of a stream-processing unit."""
    for name in ("inlet", "outlet"):
        state = states(package, unit.flowsheet().time, inlet=name == "inlet")
        unit.add_component(f"{name}_state", state)
        unit.add_port(name, state)


def stream_balance(
    block, inlet, outlet, heat=None, *, preserve_pressure=True, pressure_drop=None
):
    """Steady stream balance: heat is positive into the stream."""
    block.material = Constraint(
        inlet.component_list,
        rule=lambda b, j: (
            sum(inlet.get_material_flow_terms(p, j) for p in inlet.phase_list)
            == sum(outlet.get_material_flow_terms(p, j) for p in outlet.phase_list)
        ),
    )
    if preserve_pressure:
        block.pressure = Constraint(
            expr=outlet.pressure
            == convert(inlet.pressure, outlet.pressure)
            - (
                0 * outlet.pressure
                if pressure_drop is None
                else convert(pressure_drop, outlet.pressure)
            )
        )
    if heat is not None:
        block.energy = Constraint(
            expr=enthalpy_flow(outlet) - enthalpy_flow(inlet)
            == convert(heat, enthalpy_flow(outlet))
        )


def interpolate(state, inlet, outlet, fraction):
    """Seed independent state variables; leave fixed specifications alone."""
    for name, variable in state.define_state_vars().items():
        start = inlet.define_state_vars()[name]
        end = outlet.define_state_vars()[name]
        for key, dst in variable.items():
            if not dst.fixed:
                dst.set_value(
                    value(
                        convert((1 - fraction) * start[key] + fraction * end[key], dst)
                    )
                )

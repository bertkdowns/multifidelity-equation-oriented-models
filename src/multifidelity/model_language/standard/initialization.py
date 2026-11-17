"""Numerical guesses for the affine water examples; never fixes parameters."""

from pyomo.environ import Constraint, Var, value
from pyomo.util.calc_var_value import calculate_variable_from_constraint


def seed_affine_state(block, pressure, enthalpy, flow=1):
    """Seed a state block or direct configured water package from P/h guesses."""
    package = block.formulation.blocks.fluid if hasattr(block.formulation.blocks, 'fluid') else block
    water = package.formulation.blocks.water
    for equation in package.formulation.constraints.component_objects(Constraint):
        # Each configured coefficient equation supplies one scalar water parameter.
        if hasattr(water.structs.parameters, equation.local_name):
            calculate_variable_from_constraint(getattr(water.structs.parameters, equation.local_name), equation)
    for state in [package.structs.state, water.structs.state]:
        for t in state.pressure:
            if not state.pressure[t].fixed:
                state.pressure[t].set_value(pressure)
            if not state.enthalpy[t].fixed:
                state.enthalpy[t].set_value(enthalpy)
    for field in water.structs.properties.component_map(Var):
        for t in water.structs.state.pressure:
            calculated = getattr(water.structs.properties, field)[t]
            if not calculated.fixed:
                calculate_variable_from_constraint(calculated, getattr(water.formulation.constraints, field)[t])
            projected = getattr(package.structs.properties, field)[t]
            if not projected.fixed:
                projected.set_value(value(calculated))
    if package is not block:
        for t in block.structs.state.pressure:
            for field, guess in [("flow", flow), ("pressure", pressure), ("enthalpy", enthalpy)]:
                target = getattr(block.structs.state, field)[t]
                if not target.fixed:
                    target.set_value(guess)
            for field in block.structs.properties.component_map(Var):
                target = getattr(block.structs.properties, field)[t]
                if not target.fixed:
                    target.set_value(value(getattr(package.structs.properties, field)[t]))

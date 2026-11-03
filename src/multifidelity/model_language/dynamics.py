"""Construct steady or dynamic backend derivative equations."""

from pyomo.dae import DerivativeVar
from pyomo.environ import Block, Constraint, units

from .indexing import derivative_variables


def build_derivatives(active, resolved, relationship, variables, domains,
                      mode, time_unit, dependencies):
    active.derivatives = Block()
    for name, relation in relationship.derivatives.items():
        state_definition, _ = derivative_variables(resolved, relation)
        state, rate = variables[relation.state], variables[relation.rate]
        state_unit, rate_unit = units.get_units(state), units.get_units(rate)
        # Validate units even in steady mode, where the numerical rate is zero.
        units.convert(1 * state_unit / time_unit, to_units=rate_unit)
        block = Block()
        active.derivatives.add_component(name, block)
        if mode == "dynamic":
            # ContinuousSet coordinates are numerical, with no attached units.
            # Carry the time unit in the binding, so discretization equations
            # also remain dimensionally consistent and scaled units work.
            block.coordinate_rate = DerivativeVar(
                state, wrt=domains[relation.with_respect_to], units=state_unit
            )

        def rule(b, *indices, state=state, rate=rate, relation=relation,
                 rate_unit=rate_unit):
            if mode == "dynamic":
                expression = units.convert(b.coordinate_rate[indices] / time_unit,
                                           to_units=rate_unit)
            else:
                expression = 0 * rate_unit
            target = state[indices] if relation.determines == relation.state else rate[indices]
            source = rate[indices] if relation.determines == relation.state else state[indices]
            dependencies[id(target)] = {id(source)} if mode == "dynamic" else set()
            return rate[indices] == expression

        block.equation = Constraint(
            *(domains[d] for d in state_definition.dimensions), rule=rule
        )

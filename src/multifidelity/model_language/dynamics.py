"""Backend derivative relations and instance-level initial specifications."""

import math

from pydantic import Field, FiniteFloat
from pyomo.common.collections import ComponentSet
from pyomo.dae import DerivativeVar
from pyomo.environ import Block, Constraint, units

from .definitions import Definition, Name
from .indexing import derivative_variables


class InitialValue(Definition):
    """A value at the start of time; optional selectors address other axes."""

    variable_path: str
    value: FiniteFloat
    unit: str | None = None
    at: dict[Name, int | float | str] = Field(default_factory=dict)


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


def apply_initial_values(registry, time, specifications, parse_unit):
    """Validate all specifications before fixing any initial entries.

    Registry paths are root-relative. Unselected non-time axes receive a uniform
    value; use selectors for individual entries of an initial profile.
    """
    prepared = []
    seen = ComponentSet()
    for item in specifications:
        spec = item if isinstance(item, InitialValue) else InitialValue.model_validate(item)
        if spec.variable_path not in registry:
            raise ValueError(f"Unknown initial variable {spec.variable_path!r}")
        component, definition, domains = registry[spec.variable_path]
        axes = definition.dimensions
        time_axes = [i for i, d in enumerate(axes) if domains[d] is time]
        if len(time_axes) != 1:
            raise ValueError(f"{spec.variable_path}: initial values require a time-indexed variable")
        time_axis = time_axes[0]
        if set(spec.at) - (set(axes) - {axes[time_axis]}):
            raise ValueError(f"{spec.variable_path}: initial selectors must name non-time dimensions")
        source_unit = parse_unit(spec.unit) if spec.unit is not None else units.get_units(component)
        value = units.convert_value(spec.value, from_units=source_unit,
                                    to_units=units.get_units(component))
        if not math.isfinite(value):
            raise ValueError(f"{spec.variable_path}: converted initial value must be finite")
        selected = []
        for key, variable in component.items():
            index = key if isinstance(key, tuple) else (key,)
            if index[time_axis] != time.first():
                continue
            if any(index[axes.index(d)] != member for d, member in spec.at.items()):
                continue
            if variable in seen:
                raise ValueError(f"Overlapping initial specifications for {spec.variable_path!r}")
            if ((variable.lb is not None and value < variable.lb)
                    or (variable.ub is not None and value > variable.ub)):
                raise ValueError(f"{spec.variable_path}: initial value is outside variable bounds")
            seen.add(variable)
            selected.append(variable)
        if not selected:
            raise ValueError(f"{spec.variable_path}: initial selectors match no entries")
        prepared.extend((variable, value) for variable in selected)
    for variable, value in prepared:
        variable.fix(value)

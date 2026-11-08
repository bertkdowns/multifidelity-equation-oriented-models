"""Example-only saved-state guesses and native property evaluation; no fixity changes."""
import json
from pathlib import Path
from pyomo.environ import Block, Constraint, value, units
from pyomo.core.expr.visitor import identify_variables
from pyomo.util.calc_var_value import calculate_variable_from_constraint


def seed_snapshot(model, path):
    snapshot = json.loads(Path(path).read_text())
    for row in snapshot['variables']:
        family = model._model_language_variables.get(row['variable_path'])
        if family is None:
            continue
        for entry in row['entries']:
            index = tuple(entry['index'])
            index = index[0] if len(index) == 1 else index if index else None
            v = family[index]
            if not v.fixed and entry['value'] is not None:
                v.set_value(entry['value'])


def refresh_properties(model):
    for _ in range(3):
        for block in model.component_data_objects(Block):
            if block.local_name != 'connections':
                continue
            for c in block.component_data_objects(Constraint):
                variables = list(identify_variables(c.expr.arg(1)))
                if len(variables) == 1 and not variables[0].fixed:
                    calculate_variable_from_constraint(variables[0], c)
        for active in model.component_data_objects(Block):
            metadata = getattr(active, '_model_language_initialization', None)
            if metadata is None:
                continue
            _, _, public, native, outputs = metadata
            for key in public.keys() - outputs:
                native[key].set_value(units.convert_value(value(public[key]),
                    from_units=units.get_units(public[key]), to_units=units.get_units(native[key])))
            if hasattr(active.provider, 'flow_closure'):
                calculate_variable_from_constraint(active.provider.states[0].flow_mass, active.provider.flow_closure)
            for key in outputs:
                variable = native[key]
                equation = getattr(active.provider, variable.local_name + '_equation', None)
                if equation is not None:
                    calculate_variable_from_constraint(variable, equation)
                if not public[key].fixed:
                    public[key].set_value(units.convert_value(value(variable),
                        from_units=units.get_units(variable), to_units=units.get_units(public[key])))

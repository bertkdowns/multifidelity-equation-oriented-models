"""Replay the calibrated SGHP unit with the local 2 bar source-pressure override.

This uses Helmholtz inlet states and an optional equilibrium phase separator.
It does not independently validate the calibrated COP or close the plant recycles.
"""

import argparse
import json
from pathlib import Path

from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.environ import Var, assert_optimal_termination, value

from multifidelity.model_language import (
    InformationDocument, SpecificationDocument, apply_specification,
    build_model, get_variable, Library, register_standard_providers, pair_specification, export_workspace,
)

HERE = Path(__file__).resolve().parent


def replay(solver=None):
    implementation = json.loads((HERE / 'aggregate_aggregate.json').read_text())
    library = Library()
    register_standard_providers(library)
    model = build_model('steam_generating_heat_pump_unit', implementation['submodels']['sghp'], library=library)
    information = InformationDocument.load_json(HERE / 'sghp_replay_information.json')
    specification = SpecificationDocument.load_json(HERE / 'sghp_replay_specification.json')
    apply_specification(model, specification, information)
    if degrees_of_freedom(model) != 0:
        raise RuntimeError('The captured SGHP unit replay must have zero degrees of freedom')
    # Numerical guesses only; none of the outlet reference values is fixed.
    for variable in model.component_data_objects(Var):
        if not variable.fixed:
            variable.set_value(1)
    from idaes.models.properties.general_helmholtz import HelmholtzThermoExpressions, AmountBasis
    from pyomo.environ import units as u
    from pyomo.util.calc_var_value import calculate_variable_from_constraint
    for side in ['source', 'hot', 'warm']:
        state_block = getattr(model.fs.root.relationship.models, side + '_inlet_state')
        fluid = state_block.relationship.models.fluid
        provider = fluid.relationship.slices[0].provider
        pressure = value(get_variable(model, f'{side}_inlet.pressure')[0])
        temperature = value(get_variable(model, f'{side}_inlet_state.properties.temperature')[0])
        expressions = HelmholtzThermoExpressions(provider, provider.parameters, amount_basis=AmountBasis.MASS)
        guess_h = value(expressions.h(T=temperature * u.K, p=pressure * u.Pa, x=0))
        # TP is used only to seed PH variables; temperature remains the actual
        # fixed specification and the solver determines enthalpy.
        for path, guess in [(f'{side}_inlet.enthalpy', guess_h),
                            (f'{side}_inlet_state.state.flow', value(get_variable(model, f'{side}_inlet.flow')[0])),
                            (f'{side}_inlet_state.state.pressure', pressure),
                            (f'{side}_inlet_state.state.enthalpy', guess_h)]:
            get_variable(model, path)[0].set_value(guess)
        fluid.structs.state.pressure[0].set_value(pressure)
        fluid.structs.state.enthalpy[0].set_value(guess_h)
        provider.states[0].pressure.set_value(pressure)
        provider.states[0].enth_mass.set_value(guess_h)
        for field in ['temperature', 'density', 'heat_capacity', 'entropy', 'vapor_fraction',
                      'temperature_bubble', 'temperature_dew', 'viscosity']:
            calculate_variable_from_constraint(getattr(provider, field), getattr(provider, field + '_equation'))
            public = getattr(fluid.structs.properties, field)[0]
            if not public.fixed:
                public.set_value(value(getattr(provider, field)))
            block_properties = state_block.structs.properties
            if hasattr(block_properties, field):
                projected = getattr(block_properties, field)[0]
                if not projected.fixed:
                    projected.set_value(value(getattr(provider, field)))
        for field in ['flow', 'pressure', 'enthalpy']:
            inlet = value(get_variable(model, f'{side}_inlet.{field}')[0])
            get_variable(model, f'{side}_outlet.{field}')[0].set_value(inlet)
    solver = solver if solver is not None else get_solver('ipopt')
    if not solver.available(False):
        raise RuntimeError('IPOPT is required for the SGHP unit replay')
    result = solver.solve(model)
    assert_optimal_termination(result)
    paths = [f'{side}_outlet.{field}' for side in ['source', 'hot', 'warm']
             for field in ['flow', 'pressure', 'enthalpy']]
    paths += [f'performance.{name}' for name in [
        'electrical_power', 'cop', 'heating_duty', 'cooling_duty',
    ]]
    outputs = {path: value(get_variable(model, path)[0]) for path in paths}
    return model, result, outputs


def replay_flash(sghp_outputs, solver=None, *, workspace_path=None, phase_fractions=None,
                 property_model="helmholtz_water_ph"):
    """Isenthalpic letdown and flash downstream of the solved hot-water outlet.

    Helmholtz calculates phase enthalpies; specified per-phase routing sends
    liquid to condensate and vapor to steam. The surrounding recycle is open.
    """
    library = Library()
    register_standard_providers(library)
    library.get('flash_flowsheet').relationships['flowsheet'].models['flash_separator'].model_arguments['FluidProperties'].model = property_model
    model = build_model('flash_flowsheet', HERE.parent / 'model_language/flash_flowsheet.json', library=library)
    information = InformationDocument.load_json(HERE / 'flash_replay_information.json')
    if phase_fractions is not None:
        replacements = dict(zip(['flash_separator.parameters.liquid_to_liquid',
                                 'flash_separator.parameters.vapor_to_liquid'],
                                phase_fractions, strict=True))
        information = InformationDocument.model_validate([
            {**r.model_dump(), 'value': replacements.get(r.variable_path, r.value)}
            for r in information.records
        ])
    for field in ['flow', 'enthalpy']:
        information.add({
            'id': f'solved_hot_outlet_{field}', 'tag': f'replay.hot_outlet.{field}',
            'information_type': 'assumption', 'variable_path': f'flash_separator.inlet.{field}',
            'value': sghp_outputs[f'hot_outlet.{field}'],
            'unit': 'kg/s' if field == 'flow' else 'J/kg', 'trust_rank': 2,
        })
    specification = pair_specification(model, {"specifications": [r.id for r in information.records]}, information)
    apply_specification(model, specification, information)
    if degrees_of_freedom(model) != 0:
        raise RuntimeError('The flash replay must have zero degrees of freedom')
    flash = model.fs.root.relationship.models.flash_separator
    inlet = flash.structs.inlet
    pressure, enthalpy, flow = (value(getattr(inlet, f)[0]) for f in ['pressure', 'enthalpy', 'flow'])
    from pyomo.util.calc_var_value import calculate_variable_from_constraint

    def seed(state, h):
        provider = state.relationship.slices[0].provider
        state.structs.state.pressure[0].set_value(pressure)
        state.structs.state.enthalpy[0].set_value(h)
        provider.states[0].pressure.set_value(pressure)
        provider.states[0].enth_mass.set_value(h)
        for field in state.structs.properties.component_map(Var):
            variable = getattr(provider, field)
            calculate_variable_from_constraint(variable, getattr(provider, field + '_equation'))
            getattr(state.structs.properties, field)[0].set_value(value(variable))

    seed(flash.relationship.models.inlet_state, enthalpy)
    props = flash.relationship.models.inlet_state.structs.properties
    x = value(props.vapor_fraction[0])
    phase_flows = [flow * (1-x), flow*x]
    phase_enthalpies = [value(props.enthalpy_liquid[0]), value(props.enthalpy_vapor[0])]
    fractions = [value(getattr(flash.structs.parameters, name)[0])
                 for name in ['liquid_to_liquid', 'vapor_to_liquid']]
    for outlet in ['liquid', 'vapor']:
        routing = fractions if outlet == 'liquid' else [1-f for f in fractions]
        routed = [m*f for m,f in zip(phase_flows, routing)]
        outlet_flow = sum(routed)
        fallback = 0 if outlet == 'liquid' else 1
        outlet_h = sum(m*h for m,h in zip(routed, phase_enthalpies)) / outlet_flow if outlet_flow else phase_enthalpies[fallback]
        mixture = getattr(flash.relationship.models, outlet + '_mixture')
        mixture_provider = mixture.relationship.slices[0].provider
        for field, guess in [('liquid_flow', routed[0]), ('vapor_flow', routed[1]),
                             ('liquid_enthalpy', phase_enthalpies[0]),
                             ('vapor_enthalpy', phase_enthalpies[1]), ('fallback_vapor', fallback)]:
            getattr(mixture.structs.phases, field)[0].set_value(guess)
            getattr(mixture_provider, field).set_value(guess)
        for field, guess in [('flow', outlet_flow), ('enthalpy', outlet_h)]:
            getattr(mixture.structs.stream, field)[0].set_value(guess)
            getattr(mixture_provider, field).set_value(guess)
        for field, guess in [('flow', outlet_flow), ('enthalpy', outlet_h), ('pressure', pressure)]:
            getattr(getattr(flash.structs, outlet), field)[0].set_value(guess)
        state = getattr(flash.relationship.models, outlet + '_state')
        seed(state, outlet_h)
        for field in ['temperature', 'vapor_fraction']:
            getattr(getattr(flash.structs, outlet + '_properties'), field)[0].set_value(
                value(getattr(state.structs.properties, field)[0]))
    solver = solver if solver is not None else get_solver('ipopt')
    if not solver.available(False):
        raise RuntimeError('IPOPT is required for the flash replay')
    result = solver.solve(model)
    assert_optimal_termination(result)
    outputs = {
        'steam_flow_kg_h': value(get_variable(model, 'flash_separator.vapor.flow')[0]) * 3600,
        'condensate_flow_kg_s': value(get_variable(model, 'flash_separator.liquid.flow')[0]),
    }
    if workspace_path is not None:
        export_workspace(model, information, status='optimal', solver='ipopt',
                         termination_condition=str(result.solver.termination_condition),
                         specification=specification).write_json(workspace_path)
    return model, result, outputs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-flash', action='store_true')
    args = parser.parse_args()
    model, result, outputs = replay()
    export_workspace(model, HERE / 'sghp_replay_information.json', status='optimal', solver='ipopt',
                     termination_condition=str(result.solver.termination_condition),
                     specification=HERE / 'sghp_replay_specification.json').write_json(HERE / 'replay_workspace.json')
    report = {
        'purpose': 'calibrated replay with source-pressure override; not predictive validation',
        'termination_condition': str(result.solver.termination_condition),
        'outputs_in_declared_SI_units': outputs,
    }
    if args.with_flash:
        _, flash_result, flash_outputs = replay_flash(outputs, workspace_path=HERE / 'flash_replay_workspace.json')
        report['flash'] = {
            'termination_condition': str(flash_result.solver.termination_condition),
            **flash_outputs,
        }
    print(json.dumps(report, indent=2))

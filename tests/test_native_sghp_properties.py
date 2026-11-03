"""Native refrigerant compression using three occurrences of one PH model."""

import pytest
from pyomo.environ import value, units as u, assert_optimal_termination
from pyomo.util.calc_var_value import calculate_variable_from_constraint
from pyomo.util.check_units import assert_units_consistent
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.properties.general_helmholtz import AmountBasis, HelmholtzThermoExpressions
from idaes.models.properties.general_helmholtz.components.parameters import get_parameter_path

from multifidelity.model_language import Library, build_model, register_standard_providers
from multifidelity.model_language.standard.thermo import _fluid_data


@pytest.mark.parametrize('fluid,package,temperature,pressure,outlet_pressure', [
    ('n-butane', 'helmholtz_butane_ph', 347.15, 808313.6, 2820000),
    ('propane', 'helmholtz_propane_ph', 300.0, 400000, 1400000),
])
@pytest.mark.parametrize('efficiency', [.75, 1.0])
def test_native_refrigerant_isentropic_compression(
    fluid, package, temperature, pressure, outlet_pressure, efficiency, solver,
):
    original_path = get_parameter_path()
    library = Library()
    register_standard_providers(library)
    ref = library.get('compressor_flowsheet').relationships['flowsheet'].models['compressor']
    ref.model_arguments['FluidProperties'].model = package
    selection = {'relationship': 'flowsheet', 'submodels': {'compressor': {
        'relationship': 'isentropic', 'submodels': {
            name: ({'relationship': 'helmholtz'} if name == 'isentropic_state' else
                   {'relationship': 'evaluate', 'submodels': {'fluid': {'relationship': 'helmholtz'}}})
            for name in ['inlet_state', 'isentropic_state', 'outlet_state']
        },
    }}}
    model = build_model('compressor_flowsheet', selection, library=library)
    compressor = model.fs.root.relationship.models.compressor
    states = compressor.relationship.models
    assert get_parameter_path() == original_path
    compressor.structs.inlet.flow[0].fix(.2)
    compressor.structs.inlet.pressure[0].fix(pressure)
    states.inlet_state.structs.properties.temperature[0].fix(temperature)
    compressor.structs.parameters.pressure_rise[0].fix(outlet_pressure - pressure)
    compressor.structs.parameters.efficiency[0].fix(efficiency)

    inlet_provider = states.inlet_state.relationship.models.fluid.relationship.slices[0].provider
    # The inverse EOS is used for an initial guess only. No PS block or entropy
    # input is constructed: the actual reference is a free-enthalpy PH state.
    with _fluid_data(fluid):
        writer = HelmholtzThermoExpressions(inlet_provider, inlet_provider.parameters,
                                           amount_basis=AmountBasis.MASS)
        h_in = value(writer.h(T=temperature*u.K, p=pressure*u.Pa, x=1))
        inlet_provider.states[0].pressure.set_value(pressure)
        inlet_provider.states[0].enth_mass.set_value(h_in)
        entropy = value(inlet_provider.states[0].entr_mass)
        h_reference = value(writer.h(s=entropy*u.J/u.kg/u.K, p=outlet_pressure*u.Pa))
    h_actual = h_in + (h_reference - h_in) / efficiency
    for name, p, h in [('inlet_state', pressure, h_in),
                       ('isentropic_state', outlet_pressure, h_reference),
                       ('outlet_state', outlet_pressure, h_actual)]:
        state = getattr(states, name)
        package = state.relationship.models.fluid if name != "isentropic_state" else state
        provider = package.relationship.slices[0].provider
        package.structs.state.pressure[0].set_value(p)
        package.structs.state.enthalpy[0].set_value(h)
        if name != "isentropic_state": state.structs.state.flow[0].set_value(.2)
        state.structs.state.pressure[0].set_value(p)
        state.structs.state.enthalpy[0].set_value(h)
        provider.states[0].pressure.set_value(p)
        provider.states[0].enth_mass.set_value(h)
        for field in package.structs.properties.component_map():
            variable = getattr(provider, field)
            if not getattr(package.structs.properties, field)[0].fixed:
                calculate_variable_from_constraint(variable, getattr(provider, field + '_equation'))
                getattr(package.structs.properties, field)[0].set_value(value(variable))
            if hasattr(state.structs.properties, field) and not getattr(state.structs.properties, field)[0].fixed:
                getattr(state.structs.properties, field)[0].set_value(value(variable))
    compressor.structs.inlet.enthalpy[0].set_value(h_in)
    compressor.structs.outlet.flow[0].set_value(.2)
    compressor.structs.outlet.pressure[0].set_value(outlet_pressure)
    compressor.structs.outlet.enthalpy[0].set_value(h_actual)
    compressor.structs.performance.isentropic_work[0].set_value(.2 * (h_reference - h_in))
    compressor.structs.performance.work[0].set_value(.2 * (h_actual - h_in))

    assert_units_consistent(model)
    assert degrees_of_freedom(model) == 0
    result = solver.solve(model)
    assert_optimal_termination(result)
    s_in = value(states.inlet_state.structs.properties.entropy[0])
    s_ref = value(states.isentropic_state.structs.properties.entropy[0])
    s_out = value(states.outlet_state.structs.properties.entropy[0])
    assert s_ref == pytest.approx(s_in, abs=1e-6)
    assert s_out >= s_in - 1e-6
    if efficiency == 1:
        assert s_out == pytest.approx(s_in, abs=1e-6)
    else:
        assert s_out > s_in
    work = value(compressor.structs.performance.work[0])
    work_s = value(compressor.structs.performance.isentropic_work[0])
    assert efficiency * work == pytest.approx(work_s)
    assert work == pytest.approx(.2 * (value(compressor.structs.outlet.enthalpy[0]) -
                                      value(compressor.structs.inlet.enthalpy[0])))
    assert not states.isentropic_state.structs.state.enthalpy[0].fixed
    assert get_parameter_path() == original_path


def test_system_refrigerants_resolve_to_one_package_per_fluid():
    library = Library()
    assert set(library.get('compressor').model_parameters) == {'FluidProperties'}
    system = library.resolve('steam_generating_heat_pump_system').relationships['flowsheet'].models
    for name, package in [('sghp', 'helmholtz_butane_ph'), ('phnix', 'helmholtz_propane_ph')]:
        states = system[name].relationships['cycle'].models['compressor'].relationships['isentropic'].models
        assert states['isentropic_state'].id == package
        for key in ['inlet_state', 'outlet_state']:
            assert states[key].id == 'state_block'
            assert states[key].model_arguments['FluidProperties'].id == package

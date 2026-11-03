"""Numerical checks for property-based exchanger driving forces and tank inventories."""

import math
from pathlib import Path

import pytest
from pyomo.environ import TransformationFactory, assert_optimal_termination, value
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import Library, build_model, register_standard_providers, get_variable
from multifidelity.model_language.standard.initialization import seed_affine_state

EXAMPLES = Path(__file__).parents[1] / 'examples/model_language'


@pytest.mark.parametrize('cold_flow', [1, 2])
def test_countercurrent_exchanger_matches_effectiveness_and_equal_end_limit(cold_flow, solver):
    library = Library()
    register_standard_providers(library)
    model = build_model('heat_exchanger_flowsheet', EXAMPLES / 'heat_exchanger_lumped.json', library=library)
    exchanger = model.fs.root.relationship.models.heat_exchanger
    b = exchanger.structs
    cp, pressure, conductance = 4180, 200000, 500
    h = lambda temperature: 104920.1198085 + cp*(temperature-298.15) + (pressure-101325)/997
    for side, flow, temperature in [('hot', 1, 370), ('cold', cold_flow, 290)]:
        inlet = getattr(b, side+'_inlet')
        inlet.flow[0].fix(flow)
        inlet.pressure[0].fix(pressure)
        inlet.enthalpy[0].fix(h(temperature))
        outlet = getattr(b, side+'_outlet')
        outlet.flow[0].set_value(flow)
        outlet.pressure[0].set_value(pressure)
        outlet.enthalpy[0].set_value(h(temperature))
        for end in ['inlet', 'outlet']:
            seed_affine_state(getattr(exchanger.relationship.models, side+'_'+end+'_state'),
                              pressure, h(temperature), flow=flow)
    b.parameters.conductance.fix(conductance)
    b.performance.heat_duty[0].set_value(30000)
    force = exchanger.relationship.models.driving_force
    force.structs.ends.hot[0].set_value(70)
    force.structs.ends.cold[0].set_value(70)
    force.structs.mean.temperature_difference[0].set_value(70)
    assert_units_consistent(model)
    assert_optimal_termination(solver.solve(model))
    ratio = 1/cold_flow
    ntu = conductance/cp
    effectiveness = ntu/(1+ntu) if ratio == 1 else (
        (1-math.exp(-ntu*(1-ratio))) / (1-ratio*math.exp(-ntu*(1-ratio))))
    duty = value(b.performance.heat_duty[0])
    assert duty == pytest.approx(effectiveness*cp*80, rel=1e-6)
    assert duty == pytest.approx(value(b.hot_inlet.flow[0]) *
                               (value(b.hot_inlet.enthalpy[0])-value(b.hot_outlet.enthalpy[0])))
    assert duty == pytest.approx(value(b.cold_inlet.flow[0]) *
                               (value(b.cold_outlet.enthalpy[0])-value(b.cold_inlet.enthalpy[0])))
    if cold_flow == 1:
        assert value(force.structs.ends.hot[0]) == pytest.approx(value(force.structs.ends.cold[0]))
        assert value(force.structs.mean.temperature_difference[0]) == pytest.approx(value(force.structs.ends.hot[0]))


def test_tank_variable_density_changes_level_without_creating_mass(solver):
    from examples.dynamic_tank.run import make_tank, specify_tank, set_initial_guesses

    library = Library()
    # A liquid approximation with temperature-dependent density, using the same
    # PH interface. This tests the tank's conservation independently of EOS data.
    library.get('water_state_ph').relationships['constant_properties'].constraints['density'].rhs = (
        'parameters.density * (1 - parameters.thermal_expansion * '
        '(properties.temperature[t] - parameters.reference_temperature))')
    model = make_tank(horizon=100, library=library)
    TransformationFactory('dae.finite_difference').apply_to(model, wrt=model.fs.time, nfe=10, scheme='BACKWARD')
    specify_tank(model, initial_values=['tank_level'])
    b = model.fs.root.relationship.models.tank.structs
    b.inventory.temperature[0].fix(303.15)
    set_initial_guesses(model)
    assert_optimal_termination(solver.solve(model))
    initial_mass = 997*(1-.000257*5)
    for t in model.fs.time:
        assert value(b.inventory.mass[t]) == pytest.approx(initial_mass)
        rho = value(model.fs.root.relationship.models.tank.relationship.models.contents_state.structs.properties.density[t])
        assert value(b.inventory.level[t])*rho == pytest.approx(initial_mass)
    assert value(b.inventory.level[100]) > value(b.inventory.level[0])
    for before, after in zip(list(model.fs.time), list(model.fs.time)[1:]):
        change = (value(b.inventory.energy[after])-value(b.inventory.energy[before]))/(after-before)
        flux = value(b.inlet.flow[after]*b.inlet.enthalpy[after] - b.outlet.flow[after]*b.outlet.enthalpy[after])
        assert change == pytest.approx(flux, rel=1e-7)


def test_simple_water_phase_metadata_matches_if97_reference_points(solver):
    library = Library()
    model = build_model('water_property_package', EXAMPLES / 'water_property_package_constant_properties.json', library=library)
    # Seed coefficients and the PH calculation before varying pressure.
    seed_affine_state(model.fs.root, 100000, 100000)
    model.fs.root.structs.state.enthalpy.fix(100000)
    # IAPWS-IF97 Table 36: Tsat(p), pressures in MPa, temperatures in K.
    for pressure, expected in [(100000, 372.755919), (1000000, 453.035632), (10000000, 584.149488)]:
        model.fs.root.structs.state.pressure.fix(pressure)
        assert_optimal_termination(solver.solve(model))
        properties = model.fs.root.structs.properties
        assert value(properties.vapor_fraction[0]) == 0
        assert value(properties.temperature_bubble[0]) == pytest.approx(expected, abs=1e-6)
        assert value(properties.temperature_dew[0]) == pytest.approx(expected, abs=1e-6)


def test_generic_flash_uses_propane_properties_and_conserves_energy(solver):
    from examples.steam_generating_heat_pump_system.replay import replay_flash

    library = Library()
    register_standard_providers(library)
    model = build_model('helmholtz_propane_ph', {'relationship': 'helmholtz'}, library=library)
    provider = model.fs.root.relationship.slices[0].provider
    provider.states[0].pressure.set_value(200000)
    # The property output variables are equations; evaluate the native expressions
    # here only to construct a known 50/50 feed for a different fluid.
    liquid_h = value(provider.states[0].enth_mass_sat_phase['Liq'])
    vapor_h = value(provider.states[0].enth_mass_sat_phase['Vap'])
    inlet_h = (liquid_h+vapor_h)/2
    result, _, _ = replay_flash({'hot_outlet.flow': 2, 'hot_outlet.enthalpy': inlet_h},
                                solver, property_model='helmholtz_propane_ph')
    flash = result.fs.root.relationship.models.flash_separator.structs
    assert value(flash.liquid.flow[0]) == pytest.approx(1, abs=1e-6)
    assert value(flash.vapor.flow[0]) == pytest.approx(1, abs=1e-6)
    assert value(flash.liquid.enthalpy[0]) == pytest.approx(liquid_h)
    assert value(flash.vapor.enthalpy[0]) == pytest.approx(vapor_h)
    assert value(flash.liquid.flow[0]*flash.liquid.enthalpy[0] +
                 flash.vapor.flow[0]*flash.vapor.enthalpy[0]) == pytest.approx(2*inlet_h)


@pytest.mark.parametrize('fractions,empty', [((0, 0), 'liquid'), ((1, 1), 'vapor')])
def test_generic_flash_empty_outlet_has_finite_state_without_energy_leakage(solver, fractions, empty):
    from examples.steam_generating_heat_pump_system.replay import replay_flash

    model, _, _ = replay_flash({'hot_outlet.flow': 2, 'hot_outlet.enthalpy': 700000},
                               solver, phase_fractions=fractions)
    b = model.fs.root.relationship.models.flash_separator.structs
    assert value(getattr(b, empty).flow[0]) == pytest.approx(0, abs=1e-8)
    assert math.isfinite(value(getattr(b, empty).enthalpy[0]))
    assert value(b.liquid.flow[0]*b.liquid.enthalpy[0] +
                 b.vapor.flow[0]*b.vapor.enthalpy[0]) == pytest.approx(1400000)

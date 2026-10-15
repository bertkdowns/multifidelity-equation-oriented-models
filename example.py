"""Run: python example.py (requires an available IPOPT executable)."""
import json
from pyomo.environ import ConcreteModel, check_optimal_termination, value
from idaes.core import FlowsheetBlock
from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.properties.activity_coeff_models.BTX_activity_coeff_VLE import BTXParameterBlock
from multifidelity_hx import MultiFidelityHeatExchanger


def build_model(finite_elements=10):
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    m.fs.properties = BTXParameterBlock(valid_phase='Liq', activity_coeff_model='Ideal')
    m.fs.hx = MultiFidelityHeatExchanger(
        hot_side_property_package=m.fs.properties,
        cold_side_property_package=m.fs.properties,
        finite_elements=finite_elements)
    hx = m.fs.hx
    # Every process specification belongs to the wrapper.
    hx.area.fix(10)                            # m2
    hx.overall_heat_transfer_coefficient.fix(500)  # W / m2 / K
    hx.length.set_value(5)                     # m; 1D only
    for port, flow, temperature in [(hx.hot_side_inlet, 100, 370),
                                    (hx.cold_side_inlet, 120, 300)]:
        port.flow_mol.fix(flow)                # mol / s
        port.temperature.fix(temperature)     # K
        port.pressure.fix(300000)             # Pa
        port.mole_frac_comp[0, 'benzene'].fix(0.5)
        port.mole_frac_comp[0, 'toluene'].fix(0.5)
    return m


def summarize(m):
    hx = m.fs.hx
    return {
        'fidelity': hx.active_fidelity.local_name,
        'degrees_of_freedom': degrees_of_freedom(m),
        'hot_outlet_K': value(hx.hot_side_outlet.temperature[0]),
        'cold_outlet_K': value(hx.cold_side_outlet.temperature[0]),
        'heat_duty_W': value(hx.heat_duty[0]),
    }


def run():
    m = build_model()
    hx = m.fs.hx
    solver = get_solver('ipopt', options={'tol': 1e-8, 'max_iter': 500})
    if not solver.available(False):
        raise RuntimeError('IPOPT unavailable. Install IDAES solver extensions (see README).')
    results = []
    for level in hx.levels:
        level.activate()  # Selects this model AND deactivates its sibling.
        assert degrees_of_freedom(m) == 0
        hx.initialize(solver='ipopt', optarg={'tol': 1e-6, 'max_iter': 500})
        status = solver.solve(m, tee=False)
        if not check_optimal_termination(status):
            raise RuntimeError(f'{level.name}: {status.solver.termination_condition}')
        results.append(summarize(m))
    # A meta-algorithm can return to 0D without changing ports or specifications.
    hx.fidelity_1.activate()
    status = solver.solve(m)
    assert check_optimal_termination(status)
    results.append(summarize(m))
    print(json.dumps(results, indent=2))
    return m, results


if __name__ == '__main__':
    run()

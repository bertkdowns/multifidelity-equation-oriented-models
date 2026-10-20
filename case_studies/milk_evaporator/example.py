"""One effect from SGHP Milk Effect (BOIPOPT paper), revision 20.

Run: uv run python -m case_studies.milk_evaporator.example
"""

import json
from pathlib import Path

from ahuora_property_packages.helmholtz.helmholtz_builder import build_helmholtz_package
from idaes.core import FlowsheetBlock
from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.environ import ConcreteModel, Constraint, Suffix, value, units as u
from pyomo.core.expr.visitor import identify_variables
from pyomo.core.base.units_container import UnitsError

from multifidelity import MilkEvaporator
from multifidelity.property_models.milk import milk_parameters

REFERENCE = Path(__file__).parent / "data" / "first_effect.json"


def seed(state, properties):
    def get(key, index=""):
        return properties[key]["values"][index]

    state.flow_mol.set_value(get("flow_mol"))
    state.pressure.set_value(get("pressure") * 1000)
    state.enth_mol.set_value(get("enth_mol"))
    if hasattr(state, "mole_frac_phase_comp") and "milk_solid" in state.component_list:
        state.temperature.set_value(get("temperature") + 273.15)
        z = properties["mole_frac_comp"]["values"]
        for j in state.component_list:
            state.mole_frac_comp[j].set_value(z[j])
        vapor = get("vapor_frac")
        for p, fraction in (("Vap", vapor), ("Liq", 1 - vapor)):
            state.flow_mol_phase[p].set_value(get("flow_mol") * fraction)
            state.phase_frac[p].set_value(fraction)
        state.mole_frac_phase_comp["Vap", "water"].set_value(1)
        solid = z["milk_solid"] / (1 - vapor)
        state.mole_frac_phase_comp["Liq", "milk_solid"].set_value(solid)
        state.mole_frac_phase_comp["Liq", "water"].set_value(1 - solid)


def scale_model(model):
    if not hasattr(model, "scaling_factor"):
        model.scaling_factor = Suffix(direction=Suffix.EXPORT)

    def scale(component):
        source = u.get_units(component)
        for target, factor in (
            (u.Pa, 1e-5),
            (u.J / u.mol, 1e-4),
            (u.W, 1e-4),
            (u.mol / u.s, 1),
            (u.K, 1e-2),
        ):
            try:
                return factor * u.convert_value(1, from_units=source, to_units=target)
            except UnitsError:
                pass
        return 1

    model.scaling_factor.clear()
    for constraint in model.component_data_objects(Constraint, active=True):
        model.scaling_factor[constraint] = scale(constraint.body)
        for variable in identify_variables(constraint.body, include_fixed=False):
            model.scaling_factor[variable] = scale(variable)


def build_model(fidelity="high"):
    reference = json.loads(REFERENCE.read_text())["objects"]

    def prop(name, key, index=""):
        return reference[name]["properties"][key]["values"][index]

    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    m.fs.milk = milk_parameters()
    m.fs.water = build_helmholtz_package(["water"])
    m.fs.effect = MilkEvaporator(
        milk_property_package=m.fs.milk,
        water_property_package=m.fs.water,
    )
    effect = m.fs.effect
    high = effect.fidelities["high"]
    for state, name in (
        (effect.milk_inlet_state[0], "S3"),
        (effect.milk_outlet_state[0], "S11"),
        (effect.water_outlet_state[0], "HS9"),
        (high.valve.control_volume.properties_in[0], "S3"),
        (high.valve.control_volume.properties_out[0], "S5"),
        (high.heat_exchanger.cold_side.properties_in[0], "S5"),
        (high.heat_exchanger.cold_side.properties_out[0], "CS8"),
        (high.separator.mixed_state[0], "CS8"),
        (high.separator.outlet_1_state[0], "S11"),
        (high.separator.outlet_2_state[0], "S12"),
        (high.translator.properties_in[0], "S12"),
        (high.translator.properties_out[0], "S14"),
        (high.mvr.control_volume.properties_in[0], "S14"),
        (high.mvr.control_volume.properties_out[0], "S16"),
        (high.mvr.properties_isentropic[0], "S16"),
        (high.heat_exchanger.hot_side.properties_in[0], "S16"),
        (high.heat_exchanger.hot_side.properties_out[0], "HS9"),
    ):
        seed(state, reference[name]["properties"])
    for variable in effect.milk_inlet.vars.values():
        variable.fix()
    effect.operating_pressure.fix(prop("S5", "pressure") * 1000)
    effect.mvr_power.fix(prop("E1MVR", "work_mechanical") * 1000)
    effect.heat_recovery_effectiveness.fix(0.75)
    effect.recompressed_enthalpy[0].set_value(prop("S16", "enth_mol"))
    high.mvr.efficiency_isentropic.fix(prop("E1MVR", "efficiency_isentropic"))
    # Area is a calculated design result under the shared effectiveness target.
    high.heat_exchanger.area.set_value(prop("E1HX", "area"))
    high.heat_exchanger.overall_heat_transfer_coefficient.fix(
        prop("E1HX", "overall_heat_transfer_coefficient")
    )
    high.heat_exchanger.heat_duty[0].set_value(137441.820809)
    effect.heat_duty[0].set_value(137441.820809)
    high.mvr.work_mechanical[0].set_value(4300)
    low = effect.fidelities["low"]
    low.reference_feed_enthalpy.set_value(prop("S3", "enth_mol"))
    low.product_enthalpy_reference.set_value(prop("S11", "enth_mol"))
    low.water_pressure_reference.set_value(prop("HS9", "pressure") * 1000)
    # Slopes are explicit starting assumptions, not a fitted predictive model.
    low.product_enthalpy_feed_slope.set_value(0.1)
    low.water_pressure_feed_slope.set_value(0.1)
    effect.select_fidelity(fidelity)
    scale_model(m)
    return m


def run():
    solver = get_solver(
        "ipopt",
        options={
            "tol": 1e-8,
            "max_iter": 500,
            "nlp_scaling_method": "user-scaling",
        },
    )
    results = []
    for fidelity in ("high", "low"):
        m = build_model(fidelity)
        effect = m.fs.effect
        effect.initialize(solver=solver)
        results.append(
            {
                "fidelity": fidelity,
                "degrees_of_freedom": degrees_of_freedom(m),
                "mvr_power_W": value(effect.mvr_power[0]),
                "heat_duty_W": value(effect.heat_duty[0]),
                "product_flow_kg_s": value(effect.milk_outlet_state[0].flow_mass),
                "product_solids_mass_fraction": value(
                    effect.product_solids_mass_fraction[0]
                ),
                "water_outlet_pressure_Pa": value(
                    effect.water_outlet_state[0].pressure
                ),
                "water_outlet_enthalpy_J_mol": value(
                    effect.water_outlet_state[0].enth_mol
                ),
                "effectiveness": value(effect.heat_recovery_effectiveness[0]),
                "heat_exchanger_area_m2": (
                    value(effect.fidelities["high"].heat_exchanger.area)
                    if fidelity == "high"
                    else None
                ),
                "energy_residual_W": value(effect.energy_residual[0]),
            }
        )
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    run()

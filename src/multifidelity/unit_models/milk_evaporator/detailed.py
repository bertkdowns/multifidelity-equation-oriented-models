"""Ahuora milk-effect topology, including its numerical phase carryover."""

from ahuora_builder.custom.custom_heat_exchanger import CustomHeatExchanger
from ahuora_builder.custom.custom_separator import CustomSeparator
from ahuora_builder.custom.translator import GenericTranslator
from ahuora_builder.custom.updated_pressure_changer import Compressor
from ahuora_builder.custom.valve_wrapper import ValveWrapper
from idaes.models.unit_models.separator import SplittingType
from pyomo.environ import Constraint, Expression, TransformationFactory
from pyomo.network import Arc

from ..streams import enthalpy_flow


class DetailedMilkEvaporator:
    def build(self, block, effect):
        milk = effect.config.milk_property_package
        water = effect.config.water_property_package
        block.valve = ValveWrapper(property_package=milk)
        block.heat_exchanger = CustomHeatExchanger(
            hot_side_name="shell",
            cold_side_name="tube",
            shell={"property_package": water, "has_pressure_change": True},
            tube={"property_package": milk, "has_pressure_change": True},
        )
        block.separator = CustomSeparator(
            property_package=milk,
            num_outlets=2,
            split_basis=SplittingType.phaseFlow,
        )
        block.translator = GenericTranslator(
            inlet_property_package=milk,
            outlet_property_package=water,
            translator_type="pressure_enthalpy",
        )
        block.mvr = Compressor(property_package=water)
        for name, source, destination in (
            ("feed", effect.milk_inlet, block.valve.inlet),
            ("letdown", block.valve.outlet, block.heat_exchanger.tube_inlet),
            ("heated", block.heat_exchanger.tube_outlet, block.separator.inlet),
            ("product", block.separator.outlet_1, effect.milk_outlet),
            ("separated", block.separator.outlet_2, block.translator.inlet),
            ("translated", block.translator.outlet, block.mvr.inlet),
            ("recompressed", block.mvr.outlet, block.heat_exchanger.shell_inlet),
            ("discharged", block.heat_exchanger.shell_outlet, effect.water_outlet),
        ):
            block.add_component(name, Arc(source=source, destination=destination))
        TransformationFactory("network.expand_arcs").apply_to(block)
        # Both connected outlet states normalize composition. Solids equality
        # therefore implies water equality; retaining both would add redundancy.
        for t in effect.flowsheet().time:
            block.product_expanded.mole_frac_comp_equality[t, "water"].deactivate()
        # These are the captured topology's numerical, rather than physical,
        # entrainment assumptions. The translator drops the carried solids.
        block.separator.split_fraction[:, "outlet_1", "Liq"].fix(0.99)
        block.separator.split_fraction[:, "outlet_1", "Vap"].fix(0.01)
        block.heat_exchanger.hot_side.deltaP.fix(0)
        block.heat_exchanger.cold_side.deltaP.fix(0)
        time = effect.flowsheet().time
        block.pressure_specification = Constraint(
            time,
            rule=lambda b, t: (
                b.valve.control_volume.properties_out[t].pressure
                == effect.operating_pressure[t]
            ),
        )
        block.power = Constraint(
            time,
            rule=lambda b, t: b.mvr.work_mechanical[t] == effect.mvr_power[t],
        )
        block.recovered_heat = Constraint(
            time,
            rule=lambda b, t: effect.heat_duty[t] == b.heat_exchanger.heat_duty[t],
        )
        block.discharge_enthalpy = Constraint(
            time,
            rule=lambda b, t: (
                effect.recompressed_enthalpy[t]
                == b.mvr.control_volume.properties_out[t].enth_mol
            ),
        )
        block.translator_energy_loss = Expression(
            time,
            rule=lambda b, t: (
                enthalpy_flow(b.translator.properties_in[t])
                - enthalpy_flow(b.translator.properties_out[t])
            ),
        )
        block.ignored_solids_flow = Expression(
            time,
            rule=lambda b, t: b.translator.properties_in[t].get_material_flow_terms(
                "Liq", "milk_solid"
            ),
        )
        block.separator_energy_residual = Expression(
            time,
            rule=lambda b, t: (
                enthalpy_flow(b.separator.mixed_state[t])
                - enthalpy_flow(b.separator.outlet_1_state[t])
                - enthalpy_flow(b.separator.outlet_2_state[t])
            ),
        )

    def initialize(self, block, effect, *, model, solver):
        return solver.solve(model)

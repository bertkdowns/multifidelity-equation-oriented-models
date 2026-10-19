"""Explicit vapour-compression cycle with subcooling and internal heat recovery."""

from pyomo.environ import Constraint, TransformationFactory, value
from pyomo.network import Arc

from ..compressor import Compressor
from ..heat_exchanger import ChenHX, HeatExchanger, SegmentedHX
from ..streams import convert, interpolate
from ..valve import BasicValve, PressureFlowValve, Valve


class CycleHeatPump:
    """Build the SGHP refrigerant topology; callers supply equipment specifications.

    The single sink stream passes through subcooler then condenser. Electrical
    input equals compressor shaft work (ideal motor, no auxiliary loads).
    """

    def __init__(self, finite_elements=4):
        self.finite_elements = finite_elements

    def build(self, block, hp):
        refrigerant = hp.config.refrigerant_property_package
        if refrigerant is None:
            raise ValueError("CycleHeatPump requires refrigerant_property_package")
        block.compressor = Compressor(property_package=refrigerant)
        for name, hot, cold in (
            ("condenser", refrigerant, hp.config.sink_property_package),
            ("subcooler", refrigerant, hp.config.sink_property_package),
            ("evaporator", hp.config.source_property_package, refrigerant),
            ("ihx", refrigerant, refrigerant),
        ):
            block.add_component(name, HeatExchanger(
                hot_side_property_package=hot,
                cold_side_property_package=cold,
                fidelities={"low": ChenHX(), "high": SegmentedHX(self.finite_elements)},
            ))
        block.expansion_valve = Valve(
            property_package=refrigerant,
            fidelities={"low": BasicValve(), "high": PressureFlowValve()},
            characteristic="linear",
        )
        connections = (
            ("discharge", block.compressor.outlet, block.condenser.hot_inlet),
            ("condensed", block.condenser.hot_outlet, block.subcooler.hot_inlet),
            ("subcooled", block.subcooler.hot_outlet, block.ihx.hot_inlet),
            ("liquid", block.ihx.hot_outlet, block.expansion_valve.inlet),
            ("expanded", block.expansion_valve.outlet, block.evaporator.cold_inlet),
            ("evaporated", block.evaporator.cold_outlet, block.ihx.cold_inlet),
            ("suction", block.ihx.cold_outlet, block.compressor.inlet),
            ("source_feed", hp.source_inlet, block.evaporator.hot_inlet),
            ("source_return", block.evaporator.hot_outlet, hp.source_outlet),
            ("sink_feed", hp.sink_inlet, block.subcooler.cold_inlet),
            ("sink_interstage", block.subcooler.cold_outlet, block.condenser.cold_inlet),
            ("sink_return", block.condenser.cold_outlet, hp.sink_outlet),
        )
        for name, source, destination in connections:
            block.add_component(name, Arc(source=source, destination=destination))
        TransformationFactory("network.expand_arcs").apply_to(block)
        # One material balance is redundant around the closed refrigerant loop.
        # Arc continuity still enforces the valve's inlet/outlet flow equality.
        for t in hp.flowsheet().time:
            block.expansion_valve.balances[t].material.deactivate()
        block.electrical_input = Constraint(
            hp.flowsheet().time,
            rule=lambda b, t: hp.electrical_power[t]
            == convert(b.compressor.work[t], hp.electrical_power[t]),
        )

    def initialize(self, block, hp, *, model, solver):
        # Use caller-supplied cycle guesses; seed only private exchanger interiors.
        # No speculative recycle initialization algorithm is introduced here.
        for name in ("condenser", "subcooler", "evaporator", "ihx"):
            hx = getattr(block, name)
            b = hx.fidelities["high"]
            n = self.finite_elements
            for t in hp.flowsheet().time:
                for x in b.interior:
                    interpolate(b.hot_states[t, x], hx.hot_inlet_state[t], hx.hot_outlet_state[t], x / n)
                    interpolate(b.cold_states[t, x], hx.cold_outlet_state[t], hx.cold_inlet_state[t], x / n)
                for x in b.cells:
                    b.cell_duty[t, x].set_value(value(hx.heat_duty[t]) / n)
        return solver.solve(model)

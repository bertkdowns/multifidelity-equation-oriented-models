"""Countercurrent mixed-cell exchanger suitable for large cell NTU.

Each cell transfers heat using its two outlet temperatures. Unlike midpoint
integration, the implicit mixed-cell closure does not oscillate at large NTU.
This is still a finite discretization, not a mesh-independent reference model.
"""

from typing import TYPE_CHECKING

from pyomo.core.base.block import BlockData

from .distributed import DistributedHX

if TYPE_CHECKING:
    from .model import HeatExchangerData
from ..streams import convert


class SegmentedHX(DistributedHX):
    def build(self, block: BlockData, hx: "HeatExchangerData") -> None:
        time = hx.flowsheet().time
        super().build(block, hx)
        n = self.finite_elements
        for t in time:
            for x in block.cells:
                hot = (
                    hx.hot_outlet_state[t] if x == n - 1 else block.hot_states[t, x + 1]
                )
                cold = hx.cold_outlet_state[t] if x == 0 else block.cold_states[t, x]
                block.heat_transfer[t, x].set_value(
                    block.cell_duty[t, x]
                    == hx.U[t]
                    * hx.area
                    / n
                    * (hot.temperature - convert(cold.temperature, hot.temperature))
                )

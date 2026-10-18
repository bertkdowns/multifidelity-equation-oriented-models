"""Countercurrent mixed-cell exchanger suitable for large cell NTU.

Each cell transfers heat using its two outlet temperatures. Unlike midpoint
integration, the implicit mixed-cell closure does not oscillate at large NTU.
This is still a finite discretization, not a mesh-independent reference model.
"""

from pyomo.core.base.block import BlockData

from .distributed import DistributedHX
from .interface import SharedHX
from ..streams import convert


class SegmentedHX(DistributedHX):
    def build(self, block: BlockData, shared: SharedHX) -> None:
        super().build(block, shared)
        n = self.finite_elements
        for t in shared.time:
            for x in block.cells:
                hot = shared.hot_outlet[t] if x == n - 1 else block.hot_states[t, x + 1]
                cold = shared.cold_outlet[t] if x == 0 else block.cold_states[t, x]
                block.heat_transfer[t, x].set_value(
                    block.cell_duty[t, x]
                    == shared.U[t]
                    * shared.area
                    / n
                    * (hot.temperature - convert(cold.temperature, hot.temperature))
                )

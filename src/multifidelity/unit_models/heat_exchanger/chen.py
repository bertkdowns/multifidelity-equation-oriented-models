"""Lumped phase-change exchanger with Chen's algebraic log-mean approximation.

Positive terminal differences are private variables so fractional powers remain
in their domain during solver iterations. Common balances come from LumpedHX.
"""

from typing import TYPE_CHECKING

from pyomo.core.base.block import BlockData
from pyomo.environ import Constraint, Var
from pyomo.environ import units as u

from .lumped import LumpedHX

if TYPE_CHECKING:
    from .model import HeatExchangerData


class ChenHX(LumpedHX):
    def build(self, block: BlockData, hx: "HeatExchangerData") -> None:
        time = hx.flowsheet().time
        super().build(block, hx)
        block.hot_approach = Var(time, initialize=10, bounds=(1e-6, None), units=u.K)
        block.cold_approach = Var(time, initialize=10, bounds=(1e-6, None), units=u.K)
        block.hot_approach_definition = Constraint(
            time, rule=lambda b, t: b.hot_approach[t] == b.delta_in[t]
        )
        block.cold_approach_definition = Constraint(
            time, rule=lambda b, t: b.cold_approach[t] == b.delta_out[t]
        )
        for t in time:
            a = block.hot_approach[t]
            b = block.cold_approach[t]
            block.delta_temperature[t].set_value((a * b * (a + b) / 2) ** (1 / 3))

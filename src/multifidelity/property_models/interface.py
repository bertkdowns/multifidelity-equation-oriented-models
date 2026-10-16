"""The shared, mass-based liquid-water state supplied to property builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyomo.core.base.var import ScalarVar

if TYPE_CHECKING:
    from .water import WaterParameterData


@dataclass(frozen=True)
class SharedWater:
    parameters: WaterParameterData
    flow_mass: ScalarVar
    temperature: ScalarVar
    pressure: ScalarVar
    enth_mass: ScalarVar
    entr_mass: ScalarVar
    dens_mass: ScalarVar
    cp_mass: ScalarVar

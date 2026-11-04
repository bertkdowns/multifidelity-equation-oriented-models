"""Python provider interface, without runtime imports of the solver backend."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

from pydantic import JsonValue

if TYPE_CHECKING:
    from pyomo.core.base.block import BlockData
    from pyomo.core.base.var import VarData


class Provider(Protocol):
    """Build fresh symbolic objects under block and map every public variable.

    Configuration contains JSON construction options, not operating inputs or
    model parameters. The provider must not solve or fix operating inputs.
    The backend repeats this scalar callable per time point for time-indexed
    public interfaces, including points inserted by DAE discretization.
    """

    def __call__(
        self, block: "BlockData", config: dict[str, JsonValue]
    ) -> Mapping[str, "VarData"]: ...


class Initializer(Protocol):
    """Seed or solve an existing native block after specification.

    Temporary fixes and constraint activation are restored by the framework.
    Do not change topology, components, bounds, or model parameters.
    """

    def __call__(self, block: "BlockData", config: dict[str, JsonValue]) -> None: ...


class Scaler(Protocol):
    """Assign multiplicative variable scaling factors without changing states.

    Use IDAES set_scaling_factor; automatic Jacobian row scaling supplies
    equation factors. Do not fix variables, solve, or change model equations.
    """

    def __call__(self, block: "BlockData", config: dict[str, JsonValue]) -> None: ...

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
    """

    def __call__(
        self, block: "BlockData", config: dict[str, JsonValue]
    ) -> Mapping[str, "VarData"]: ...

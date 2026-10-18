"""Reusable assembly and selection of named Pyomo formulation blocks."""

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Generic, Protocol, TypeVar

from pyomo.core.base.block import BlockData
from pyomo.core.base.var import VarData
from pyomo.environ import Block
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver


FidelitySharedT = TypeVar("FidelitySharedT", contravariant=True)


class Fidelity(Protocol[FidelitySharedT]):
    def build(self, block: BlockData, shared: FidelitySharedT, /) -> None: ...

    def initialize(
        self,
        block: BlockData,
        shared: FidelitySharedT,
        /,
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults: ...


@contextmanager
def fixed_inputs(variables: Iterable[VarData]) -> Iterator[None]:
    """Restore temporary input fixations, including on solver failure."""
    flags = [(v, v.fixed) for v in variables]
    try:
        for v, _ in flags:
            v.fix()
        yield
    finally:
        for v, was_fixed in flags:
            if not was_fixed:
                v.unfix()


SharedT = TypeVar("SharedT")


class MultiFidelityMixin(Generic[SharedT]):
    """Call build_fidelities() after constructing the model's shared interface.

    Each builder supplies build(block, shared). The shared object is passed
    through unchanged; its physical meaning belongs to the owning model.
    """

    _builders: dict[str, Fidelity[SharedT]]
    fidelities: dict[str, BlockData]

    def build_fidelities(
        self, builders: Mapping[str, Fidelity[SharedT]], shared: SharedT
    ) -> None:
        """Build the formulations and select the first supplied fidelity."""
        if not builders:
            raise ValueError("At least one fidelity is required")
        self._builders = dict(builders)
        self.formulations = Block(list(self._builders))
        self.fidelities = {name: self.formulations[name] for name in self._builders}
        for name, builder in self._builders.items():
            builder.build(self.fidelities[name], shared)
        self.select_fidelity(next(iter(self.fidelities)))

    @property
    def active_fidelity(self) -> str:
        names = [name for name, block in self.fidelities.items() if block.active]
        if len(names) != 1:
            raise RuntimeError("Expected exactly one active fidelity")
        return names[0]

    def select_fidelity(self, name: str) -> None:
        """Select equations while preserving all variable values and fixations."""
        if name not in self.fidelities:
            raise ValueError(
                f"Unknown fidelity {name!r}; choose from {tuple(self.fidelities)}"
            )
        for candidate, block in self.fidelities.items():
            if candidate == name:
                block.activate()
            else:
                block.deactivate()

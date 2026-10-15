"""Reusable assembly and selection of named Pyomo formulation blocks."""

from pyomo.environ import Block


class MultiFidelityMixin:
    """Call build_fidelities() after constructing the equipment's shared interface.

    Each builder supplies build(block, shared). The shared object is passed
    through unchanged; its physical meaning belongs to the equipment model.
    """

    def build_fidelities(self, builders, shared):
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
    def active_fidelity(self):
        names = [name for name, block in self.fidelities.items() if block.active]
        if len(names) != 1:
            raise RuntimeError("Expected exactly one active fidelity")
        return names[0]

    def select_fidelity(self, name):
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

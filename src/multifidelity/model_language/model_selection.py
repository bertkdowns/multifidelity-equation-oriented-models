"""Formulation choices; the root block is supplied separately by the caller."""

from pydantic import Field

from .definitions import Definition, Name


class FormulationSelection(Definition):
    """One formulation choice and recursive choices for its child aliases."""

    formulation: Name
    subblocks: dict[Name, "FormulationSelection"] = Field(default_factory=dict)


class ModelDocument(FormulationSelection):
    """Portable selection tree, interpreted against a separately supplied root block.

    Parsing checks shape. BlockRegistry-dependent selection checks remain in the
    builder and requirement queries. No block IDs or operating values are stored.
    """

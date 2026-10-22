"""Explicit relationship choices, independent of instance values and solver objects."""

from pydantic import Field

from .definitions import Definition, Name


class ImplementationSelection(Definition):
    """One relationship choice and the choices for its named child references.

    A nested model ID is optional because its containing model reference already
    determines the definition (including generic arguments). If supplied, the
    builder checks that it matches that reference.
    """

    model: str | None = Field(default=None, min_length=1)
    relationship: Name
    submodels: dict[Name, "ImplementationSelection"] = Field(default_factory=dict)


class Implementation(ImplementationSelection):
    """Root of a selection tree; the root model must be identified explicitly.

    Parsing checks shape, not agreement with a model library. Existence of the
    selected relationship and completeness of its child selections remain
    semantic checks. Values, fixation and initial guesses belong to instances.
    """

    model: str = Field(min_length=1)

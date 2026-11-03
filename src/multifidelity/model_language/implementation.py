"""Relationship choices; the root model is supplied separately by the caller."""

from pydantic import Field

from .definitions import Definition, Name


class ImplementationSelection(Definition):
    """One relationship choice and recursive choices for its child aliases."""

    relationship: Name
    submodels: dict[Name, "ImplementationSelection"] = Field(default_factory=dict)


class ImplementationDocument(ImplementationSelection):
    """Portable selection tree, interpreted against a separately supplied model.

    Parsing checks shape. Library-dependent selection checks remain in the
    builder and requirement queries. No model IDs or operating values are stored.
    """

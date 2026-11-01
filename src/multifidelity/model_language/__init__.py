"""Load declarative model definitions and build explicitly selected IDAES structures."""

from .resolution import Library, ResolvedModel, ResolvedRelationship
from .requirements import required_inputs, print_required_inputs
from .information import InformationRecord, InformationTable, InformationType
from .standard import register_standard_providers


def build_model(model_id, implementation, *, library=None, domain_values=None):
    """Convert a selected implementation using the Pyomo backend on demand."""
    from .builder import build_model as build

    return build(model_id, implementation, library=library, domain_values=domain_values)


__all__ = [
    "Library",
    "InformationRecord",
    "InformationTable",
    "InformationType",
    "ResolvedModel",
    "ResolvedRelationship",
    "build_model",
    "required_inputs",
    "print_required_inputs",
    "register_standard_providers",
]

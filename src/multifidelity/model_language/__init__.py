"""Load declarative model definitions and build explicitly selected IDAES structures."""

from .resolution import Library, ResolvedModel, ResolvedRelationship
from .requirements import required_inputs, print_required_inputs


def build_model(model_id, implementation, *, library=None):
    """Convert a selected implementation using the Pyomo backend on demand."""
    from .builder import build_model as build

    return build(model_id, implementation, library=library)


__all__ = [
    "Library",
    "ResolvedModel",
    "ResolvedRelationship",
    "build_model",
    "required_inputs",
    "print_required_inputs",
]

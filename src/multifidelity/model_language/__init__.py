"""Load declarative model definitions and build explicitly selected IDAES structures."""

from .definitions import ModelDocument
from .implementation import ImplementationDocument, ImplementationSelection
from .resolution import Library, ModelView, RelationshipView
from .requirements import required_inputs, print_required_inputs, required_initial_values
from .information import InformationRecord, InformationDocument, InformationType
from .standard import register_standard_providers


def build_model(model_id, implementation, *, library=None, domain_values=None,
                mode="steady", time_unit="s", initial_values=None):
    """Convert a selected implementation using the Pyomo backend on demand."""
    from .builder import build_model as build

    return build(model_id, implementation, library=library, domain_values=domain_values,
                 mode=mode, time_unit=time_unit, initial_values=initial_values)


__all__ = [
    "Library",
    "ModelDocument",
    "ImplementationDocument",
    "ImplementationSelection",
    "InformationRecord",
    "InformationDocument",
    "InformationType",
    "ModelView",
    "RelationshipView",
    "build_model",
    "required_inputs",
    "required_initial_values",
    "print_required_inputs",
    "register_standard_providers",
]

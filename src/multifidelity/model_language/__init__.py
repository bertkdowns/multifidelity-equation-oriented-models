"""Load declarative model definitions and build explicitly selected IDAES structures."""

from .definitions import ModelDocument
from .implementation import ImplementationDocument, ImplementationSelection
from .resolution import Library, ModelView, RelationshipView
from .requirements import required_inputs, print_required_inputs, required_initial_values
from .information import InformationRecord, InformationDocument, InformationType
from .specification import (
    SpecificationDocument,
    apply_specification,
)
from .selection import SpecificationSelection, select_specification
from .variables import get_variable
from .initialization import apply_starting_values, initialize_custom_models
from .hierarchical_initialization import initialize_model, InitializationResult, InitializationStage
from .scaling import apply_scaling, ScalingReport
from .reconciliation import relax_specifications, SpecificationRelaxation
from .results import ResultsDocument, export_results
from .standard import register_standard_providers


def build_model(model_id, implementation, *, library=None, domain_values=None,
                mode="steady", time_unit="s"):
    """Convert a selected implementation using the Pyomo backend on demand."""
    from .builder import build_model as build

    return build(model_id, implementation, library=library, domain_values=domain_values,
                 mode=mode, time_unit=time_unit)


__all__ = [
    "Library",
    "ModelDocument",
    "ImplementationDocument",
    "ImplementationSelection",
    "InformationRecord",
    "InformationDocument",
    "InformationType",
    "SpecificationDocument",
    "apply_specification",
    "apply_starting_values",
    "initialize_custom_models",
    "initialize_model",
    "InitializationResult",
    "InitializationStage",
    "apply_scaling",
    "ScalingReport",
    "relax_specifications",
    "SpecificationRelaxation",
    "SpecificationSelection",
    "select_specification",
    "ModelView",
    "RelationshipView",
    "build_model",
    "get_variable",
    "ResultsDocument",
    "export_results",
    "required_inputs",
    "required_initial_values",
    "print_required_inputs",
    "register_standard_providers",
]

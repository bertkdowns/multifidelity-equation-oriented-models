"""Load declarative block definitions and build explicitly selected IDAES structures."""

from .definitions import BlockCatalog
from .model_selection import ModelCatalog, FormulationSelection
from .resolution import BlockLibrary, BlockView, FormulationView
from .requirements import required_inputs, print_required_inputs, required_initial_values
from .resources import Resource, ResourceCatalog, ResourceType
from .feeds import Feed, FeedRegistry, FeedCatalog, FeedDescription
from .parameters import (
    ParameterCatalog,
    apply_parameters,
)
from .selection import ParameterSelection, select_parameters
from .replacement import canonical_inputs, pair_parameters, parameter_slots, audit_fixations
from .variables import get_variable
from .initialization import apply_starting_values, initialize_custom_models
from .hierarchical_initialization import initialize_model, InitializationResult, InitializationStage
from .scaling import apply_scaling, ScalingReport
from .reconciliation import relax_parameters, ParameterRelaxation
from .results import ResultsCatalog, export_results
from .workspace import WorkspaceCatalog, export_workspace
from .standard import register_standard_providers


def build_model(block_id, model_catalog, *, library=None, domain_values=None,
                mode="steady", time_unit="s"):
    """Convert a selected model using the Pyomo backend on demand."""
    from .builder import build_model as build

    return build(block_id, model_catalog, library=library, domain_values=domain_values,
                 mode=mode, time_unit=time_unit)


__all__ = [
    "BlockLibrary",
    "BlockCatalog",
    "ModelCatalog",
    "FormulationSelection",
    "Resource",
    "ResourceCatalog",
    "ResourceType",
    "Feed",
    "FeedRegistry",
    "FeedCatalog",
    "FeedDescription",
    "ParameterCatalog",
    "apply_parameters",
    "apply_starting_values",
    "initialize_custom_models",
    "initialize_model",
    "InitializationResult",
    "InitializationStage",
    "apply_scaling",
    "ScalingReport",
    "relax_parameters",
    "ParameterRelaxation",
    "ParameterSelection",
    "select_parameters",
    "canonical_inputs",
    "pair_parameters",
    "parameter_slots",
    "audit_fixations",
    "BlockView",
    "FormulationView",
    "build_model",
    "get_variable",
    "ResultsCatalog",
    "export_results",
    "WorkspaceCatalog",
    "export_workspace",
    "required_inputs",
    "required_initial_values",
    "print_required_inputs",
    "register_standard_providers",
]

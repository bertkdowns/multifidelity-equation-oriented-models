"""Internal selected-hierarchy traversal, without constructing numerical objects."""

from dataclasses import dataclass
from pathlib import Path

from .model_selection import ModelCatalog
from .resolution import BlockView, FormulationView
from ._validation import determination_sources


@dataclass(frozen=True)
class _Occurrence:
    block: BlockView
    formulation_id: str
    formulation: FormulationView
    prefix: str
    supplied: frozenset[str]


def _walk_model(root, model_catalog, enter, leave=None):
    """Validate and visit only selected occurrences, in one recursive traversal.

    enter(occurrence, parent_context, alias) prepares per-occurrence context.
    leave(occurrence, context, child_results) optionally runs after descendants.
    Requirements collect metadata on entry; the backend creates variables on
    entry and equations on exit. No selected tree or public model_catalog type
    is introduced, and unselected alternatives are never traversed.
    """
    if isinstance(model_catalog, (str, Path)):
        model_catalog = ModelCatalog.load_json(model_catalog)
    elif not isinstance(model_catalog, ModelCatalog):
        model_catalog = ModelCatalog.model_validate(model_catalog)

    def visit(model, selection, prefix, supplied, parent, alias):
        formulation_id = selection.formulation
        if formulation_id not in model.formulations:
            raise ValueError(f"{model.path}: unknown formulation {formulation_id!r}")
        formulation = model.formulations[formulation_id]
        references = formulation.blocks
        if set(selection.subblocks) != set(references):
            raise ValueError(f"{model.path}: subblocks must be exactly {sorted(references)}")
        sources = determination_sources(model, formulation_id)
        occurrence = _Occurrence(model, formulation_id, formulation, prefix, supplied)
        context = enter(occurrence, parent, alias)
        children = {}
        for name, child in references.items():
            child_prefix = name + "."
            child_supplied = frozenset(
                target[len(child_prefix):] for target in sources
                if target.startswith(child_prefix)
            )
            children[name] = visit(
                child, selection.subblocks[name], prefix + child_prefix,
                child_supplied, context, name,
            )
        return leave(occurrence, context, children) if leave is not None else context

    return visit(root, model_catalog, "", frozenset(), None, None)

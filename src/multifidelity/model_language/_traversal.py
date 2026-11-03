"""Internal selected-hierarchy traversal, without constructing numerical objects."""

from dataclasses import dataclass
from pathlib import Path

from .implementation import ImplementationDocument
from .resolution import ModelView, RelationshipView
from ._validation import determination_sources


@dataclass(frozen=True)
class _Occurrence:
    model: ModelView
    relationship_id: str
    relationship: RelationshipView
    prefix: str
    supplied: frozenset[str]


def _walk_implementation(root, implementation, enter, leave=None):
    """Validate and visit only selected occurrences, in one recursive traversal.

    enter(occurrence, parent_context, alias) prepares per-occurrence context.
    leave(occurrence, context, child_results) optionally runs after descendants.
    Requirements collect metadata on entry; the backend creates variables on
    entry and equations on exit. No selected tree or public implementation type
    is introduced, and unselected alternatives are never traversed.
    """
    if isinstance(implementation, (str, Path)):
        implementation = ImplementationDocument.load_json(implementation)
    elif not isinstance(implementation, ImplementationDocument):
        implementation = ImplementationDocument.model_validate(implementation)

    def visit(model, selection, prefix, supplied, parent, alias):
        relationship_id = selection.relationship
        if relationship_id not in model.relationships:
            raise ValueError(f"{model.path}: unknown relationship {relationship_id!r}")
        relationship = model.relationships[relationship_id]
        references = relationship.models
        if set(selection.submodels) != set(references):
            raise ValueError(f"{model.path}: submodels must be exactly {sorted(references)}")
        sources = determination_sources(model, relationship_id)
        occurrence = _Occurrence(model, relationship_id, relationship, prefix, supplied)
        context = enter(occurrence, parent, alias)
        children = {}
        for name, child in references.items():
            child_prefix = name + "."
            child_supplied = frozenset(
                target[len(child_prefix):] for target in sources
                if target.startswith(child_prefix)
            )
            children[name] = visit(
                child, selection.submodels[name], prefix + child_prefix,
                child_supplied, context, name,
            )
        return leave(occurrence, context, children) if leave is not None else context

    return visit(root, implementation, "", frozenset(), None, None)

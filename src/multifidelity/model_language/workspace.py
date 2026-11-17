"""A portable case: choices, resource records and one numerical snapshot."""

from pathlib import Path

from pydantic import Field, model_validator

from .feeds import FeedDocument
from .definitions import Definition
from .model_selection import ModelDocument
from .resources import ResourceDocument
from .results import ResultsDocument, export_results


class WorkspaceDocument(Definition):
    """No UI state or block definitions; root block identity stays in the snapshot."""

    model_document: ModelDocument
    resources: ResourceDocument
    results: ResultsDocument
    feeds: FeedDocument | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def matching_model_document(self):
        if self.model_document != self.results.model_document:
            raise ValueError("Workspace model_document must match the results snapshot")
        return self

    @classmethod
    def from_results(cls, results, resources, *, feeds=None):
        """Bundle a snapshot and optional feed document without changing run identity."""
        if isinstance(results, (str, Path)):
            results = ResultsDocument.load_json(results)
        else:
            results = ResultsDocument.model_validate(results).model_copy(deep=True)
        if isinstance(resources, (str, Path)):
            resources = ResourceDocument.load_json(resources)
        else:
            resources = ResourceDocument.model_validate(resources).model_copy(deep=True)
        return cls(model_document=results.model_document.model_copy(deep=True),
                   resources=resources, results=results,
                   feeds=FeedDocument.model_validate(feeds).model_copy(deep=True)
                   if feeds is not None else None)

    def write_json(self, path):
        Path(path).write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")


def export_workspace(model, resources, *, feeds=None, **result_options):
    """Snapshot a built model and its supplied resources; never solve it.

    Pass feeds=data.describe() to include portable input declarations.
    Result options are those of export_results, including explicit solve status
    and optional parameters metadata. Resource is not inferred from fixed
    variables: pass the actual records used for this case, including overrides.
    """
    return WorkspaceDocument.from_results(export_results(model, **result_options), resources,
                                          feeds=feeds)

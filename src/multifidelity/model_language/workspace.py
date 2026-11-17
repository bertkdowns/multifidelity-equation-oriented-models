"""A portable case: choices, resource records and one numerical snapshot."""

from pathlib import Path

from pydantic import Field, model_validator

from .feeds import FeedCatalog
from .definitions import Definition
from .model_selection import ModelCatalog
from .resources import ResourceCatalog
from .results import ResultsCatalog, export_results


class WorkspaceCatalog(Definition):
    """No UI state or block definitions; root block identity stays in the snapshot."""

    model_catalog: ModelCatalog
    resources: ResourceCatalog
    results: ResultsCatalog
    feeds: FeedCatalog | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def matching_model_catalog(self):
        if self.model_catalog != self.results.model_catalog:
            raise ValueError("Workspace model_catalog must match the results snapshot")
        return self

    @classmethod
    def from_results(cls, results, resources, *, feeds=None):
        """Bundle a snapshot and optional feed catalogue without changing run identity."""
        if isinstance(results, (str, Path)):
            results = ResultsCatalog.load_json(results)
        else:
            results = ResultsCatalog.model_validate(results).model_copy(deep=True)
        if isinstance(resources, (str, Path)):
            resources = ResourceCatalog.load_json(resources)
        else:
            resources = ResourceCatalog.model_validate(resources).model_copy(deep=True)
        return cls(model_catalog=results.model_catalog.model_copy(deep=True),
                   resources=resources, results=results,
                   feeds=FeedCatalog.model_validate(feeds).model_copy(deep=True)
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
    return WorkspaceCatalog.from_results(export_results(model, **result_options), resources,
                                          feeds=feeds)

"""A portable case: choices, information records and one numerical snapshot."""

from pathlib import Path

from pydantic import model_validator

from .definitions import Definition
from .implementation import ImplementationDocument
from .information import InformationDocument
from .results import ResultsDocument, export_results


class WorkspaceDocument(Definition):
    """No UI state or model definitions; model identity stays in the snapshot."""

    implementation: ImplementationDocument
    information: InformationDocument
    results: ResultsDocument

    @model_validator(mode="after")
    def matching_implementation(self):
        if self.implementation != self.results.implementation:
            raise ValueError("Workspace implementation must match the results snapshot")
        return self

    @classmethod
    def from_results(cls, results, information):
        """Bundle an existing snapshot without changing run identity or status."""
        if isinstance(results, (str, Path)):
            results = ResultsDocument.load_json(results)
        else:
            results = ResultsDocument.model_validate(results).model_copy(deep=True)
        if isinstance(information, (str, Path)):
            information = InformationDocument.load_json(information)
        else:
            information = InformationDocument.model_validate(information).model_copy(deep=True)
        return cls(implementation=results.implementation.model_copy(deep=True),
                   information=information, results=results)

    def write_json(self, path):
        Path(path).write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")


def export_workspace(model, information, **result_options):
    """Snapshot a built model and its supplied information; never solve it.

    Result options are those of export_results, including explicit solve status
    and optional specification metadata. Information is not inferred from fixed
    variables: pass the actual records used for this case, including overrides.
    """
    return WorkspaceDocument.from_results(export_results(model, **result_options), information)

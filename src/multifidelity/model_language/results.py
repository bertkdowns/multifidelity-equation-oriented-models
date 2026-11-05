"""Portable numerical snapshots, separate from information and specifications."""
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator
from .definitions import Definition
from .implementation import ImplementationDocument
from .specification import SpecificationDocument

Text = Annotated[str, Field(min_length=1)]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Coordinate = StrictInt | Annotated[StrictFloat, Field(allow_inf_nan=False)] | StrictStr


class ResultEntry(Definition):
    index: tuple[Coordinate, ...]
    value: Number | None
    fixed: StrictBool
    issue: Literal['unset', 'nonfinite'] | None = None

    @model_validator(mode='after')
    def unavailable_values_are_explicit(self):
        if (self.value is None) != (self.issue is not None):
            raise ValueError('Unavailable values require an issue; finite values cannot have an issue')
        return self


class VariableResult(Definition):
    variable_path: Text
    unit: Text
    dimensions: tuple[Text, ...]
    entries: tuple[ResultEntry, ...] = Field(min_length=1)

    @model_validator(mode='after')
    def coordinates_match_dimensions(self):
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError('Dimensions must be distinct')
        seen = set()
        for entry in self.entries:
            if len(entry.index) != len(self.dimensions):
                raise ValueError('Index length must match dimensions')
            if entry.index in seen:
                raise ValueError('Duplicate index coordinates')
            seen.add(entry.index)
        return self


class SolveMetadata(Definition):
    status: Literal['optimal', 'feasible', 'failed', 'not_solved']
    termination_condition: str | None = None
    solver: str | None = None
    message: str | None = None


class ResultsDocument(Definition):
    schema_version: Literal[1] = 1
    run_id: Text = Field(default_factory=lambda: str(uuid4()))
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_id: Text
    implementation: ImplementationDocument
    mode: Literal['steady', 'dynamic']
    time_unit: Text
    solve: SolveMetadata
    specification: SpecificationDocument | None = None
    variables: tuple[VariableResult, ...]

    @model_validator(mode='after')
    def unique_paths(self):
        paths = [v.variable_path for v in self.variables]
        if len(paths) != len(set(paths)):
            raise ValueError('Result variable paths must be unique')
        return self

    def write_json(self, path):
        Path(path).write_text(self.model_dump_json(indent=2) + '\n', encoding='utf-8')


def export_results(model, *, status='not_solved', termination_condition=None,
                   solver=None, message=None, specification=None):
    """Snapshot every declared public variable after solving/loading values.

    Status is explicit: this function does not solve, infer convergence, validate
    physical applicability or modify values. Native implementation internals are
    excluded. Coordinates follow declared dimension order and include the actual
    post-discretization grid. Missing/nonfinite values are represented explicitly.
    Units are the numerical model's units; no display conversion is performed.
    """
    from pyomo.environ import units
    if not hasattr(model, '_model_language_model_id'):
        raise ValueError('Model must be constructed by model_language.build_model')
    variables = []
    for path, family in sorted(model._model_language_variables.items()):
        dimensions = family._model_language_dimensions
        entries = []
        for index, variable in family.items():
            coordinate = (() if not dimensions else
                          (index,) if len(dimensions) == 1 else tuple(index))
            current = variable.value
            issue = 'unset' if current is None else 'nonfinite' if not math.isfinite(current) else None
            entries.append(ResultEntry(index=coordinate,
                                       value=float(current) if issue is None else None,
                                       fixed=variable.fixed, issue=issue))
        variables.append(VariableResult(variable_path=path, unit=str(units.get_units(family)),
                                        dimensions=dimensions, entries=entries))
    if specification is not None:
        if isinstance(specification, (str, Path)):
            specification = SpecificationDocument.load_json(specification)
        else:
            specification = SpecificationDocument.model_validate(specification).model_copy(deep=True)
    return ResultsDocument(
        model_id=model._model_language_model_id,
        implementation=model._model_language_implementation.model_copy(deep=True),
        mode='dynamic' if model.fs.config.dynamic else 'steady',
        time_unit=str(model.fs.config.time_units),
        solve=SolveMetadata(status=status, termination_condition=termination_condition,
                            solver=solver, message=message),
        specification=specification, variables=variables)

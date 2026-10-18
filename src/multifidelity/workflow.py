"""Small flowsheet-level fidelity searches, independent of equipment equations.

These are research baselines, not guarantees of a globally best representation.
A solve callback owns numerical acceptance and diagnostics. Failed refinements
restore the last accepted state, including private formulation variables.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pyomo.core.base.block import BlockData
from pyomo.environ import Var
from .base import MultiFidelityMixin


@dataclass(frozen=True)
class FidelityChoice:
    name: str
    unit: MultiFidelityMixin[Any]
    low: str = "low"
    high: str = "high"


@dataclass
class SolveOutcome:
    accepted: bool
    termination: str
    elapsed_seconds: float
    iterations: int | None
    metrics: dict[str, float]
    unit_residuals: dict[str, float] = field(default_factory=dict)


@dataclass
class SelectionResult:
    accepted: bool
    assignment: dict[str, str]
    attempts: list[dict]
    metrics: dict[str, float]


def run_selection(
    model: BlockData,
    choices: Sequence[FidelityChoice],
    solve: Callable[[BlockData], SolveOutcome],
    *,
    strategy: str,
    groups: Sequence[Sequence[str]] = (),
    coarse_units: Sequence[str] = (),
) -> SelectionResult:
    """Run a baseline, greedy refinement, or greedy relaxation search.

    ``manual`` and ``context`` use declared coarse_units. ``structure`` relaxes
    the coupled group containing the largest-residual candidate. Groups come
    from a caller's structural analysis; numerical residuals are only hints.
    """
    valid = {
        "all_high",
        "all_low",
        "manual",
        "context",
        "progressive",
        "failure_driven",
        "residual",
        "structure",
        "grouped_refinement",
    }
    if strategy not in valid:
        raise ValueError(f"Unknown strategy {strategy!r}")
    by_name = {c.name: c for c in choices}
    attempts = []
    refining = strategy in {"progressive", "grouped_refinement"}
    for c in choices:
        low = (
            refining
            or strategy == "all_low"
            or (strategy in {"manual", "context"} and c.name in coarse_units)
        )
        c.unit.select_fidelity(c.low if low else c.high)

    def assignment():
        return {c.name: c.unit.active_fidelity for c in choices}

    def attempt():
        outcome = solve(model)
        attempts.append(
            {
                "assignment": assignment(),
                "accepted": outcome.accepted,
                "termination": outcome.termination,
                "elapsed_seconds": outcome.elapsed_seconds,
                "iterations": outcome.iterations,
                "metrics": outcome.metrics,
                "unit_residuals": outcome.unit_residuals,
            }
        )
        return outcome

    def checkpoint():
        return [(v, v.value) for v in model.component_data_objects(Var, active=None)]

    def restore(saved):
        for v, val in saved:
            if not v.fixed and val is not None:
                v.set_value(val, skip_validation=True)

    initial_state = checkpoint()
    outcome = attempt()
    if refining and outcome.accepted:
        upgrade_groups = (
            groups if strategy == "grouped_refinement" else [(c.name,) for c in choices]
        )
        for group in upgrade_groups:
            saved = checkpoint()
            previous = assignment()
            for name in group:
                by_name[name].unit.select_fidelity(by_name[name].high)
            candidate = attempt()
            if candidate.accepted:
                outcome = candidate
            else:
                restore(saved)
                for name, fidelity in previous.items():
                    by_name[name].unit.select_fidelity(fidelity)
    elif strategy in {"failure_driven", "residual", "structure"}:
        while not outcome.accepted:
            candidates = [c for c in choices if c.unit.active_fidelity == c.high]
            if not candidates:
                break
            chosen = (
                candidates[0]
                if strategy == "failure_driven"
                else max(
                    candidates, key=lambda c: outcome.unit_residuals.get(c.name, 0)
                )
            )
            group = (
                next((g for g in groups if chosen.name in g), (chosen.name,))
                if strategy == "structure"
                else (chosen.name,)
            )
            # Failed iterates can be far outside useful property states. Rank
            # their residuals, then retry the new representation from the same
            # original guesses rather than propagating that failed point.
            restore(initial_state)
            for name in group:
                by_name[name].unit.select_fidelity(by_name[name].low)
            outcome = attempt()
    return SelectionResult(outcome.accepted, assignment(), attempts, outcome.metrics)

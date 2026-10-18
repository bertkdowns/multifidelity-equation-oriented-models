"""DM determinacy and coupled equipment groups from the active equation graph."""

from pyomo.contrib.incidence_analysis import IncidenceGraphInterface
from pyomo.contrib.incidence_analysis.config import IncidenceMethod

from .full_flowsheet import selectable_units


def structural_report(model):
    units = selectable_units(model)
    graph = IncidenceGraphInterface(
        model, include_inequality=False, method=IncidenceMethod.identify_variables
    )
    variables, constraints = graph.dulmage_mendelsohn()
    report = {
        "variables": {k: len(getattr(variables, k)) for k in variables._fields},
        "constraints": {k: len(getattr(constraints, k)) for k in constraints._fields},
    }

    def belongs(constraint, unit):
        parent = constraint.parent_block()
        while parent is not None:
            if parent is unit:
                return True
            parent = parent.parent_block()
        return False

    groups = []
    if not variables.unmatched and not constraints.unmatched:
        _, blocks = graph.block_triangularize()
        # A unit can contribute equations to several SCCs. Merge intersecting
        # equipment groups so each switching choice belongs to one group.
        for block in blocks:
            names = {
                name
                for name, unit in units.items()
                if any(belongs(c, unit) for c in block)
            }
            if not names:
                continue
            overlaps = [g for g in groups if names & g]
            for g in overlaps:
                names |= g
                groups.remove(g)
            groups.append(names)
    covered = set().union(*groups) if groups else set()
    groups.extend({name} for name in units if name not in covered)
    report["equipment_groups"] = [sorted(g) for g in groups]
    return report

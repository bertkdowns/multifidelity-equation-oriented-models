"""Structural input replacement, using incidence and occurrence distance only."""

from collections import deque


def canonical_inputs(model):
    """Return the selected implementation's unsupplied public input families."""
    paths = getattr(model, '_model_language_canonical_inputs', None)
    if paths is None:
        raise ValueError('Model must be constructed by model_language.build_model')
    return {path: model._model_language_variables[path] for path in paths}


def _same_grid(a, b):
    if a.is_indexed() != b.is_indexed():
        return False
    if not a.is_indexed():
        return True
    return (tuple(a) == tuple(b)
            and tuple(id(d) for d in a.index_set().subsets())
            == tuple(id(d) for d in b.index_set().subsets()))


def _entries(family):
    return {id(v) for v in family.values()}


def _occurrence(path):
    return path.split('.')[:-2]


def _hierarchy_distance(a, b):
    a, b = _occurrence(a), _occurrence(b)
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    return len(a) + len(b) - 2 * common


class _ReplacementGraph:
    """One cached incidence graph; trial closures change column sets, not fixity."""

    def __init__(self, model):
        import networkx as nx
        from pyomo.environ import Constraint, Var
        from pyomo.core.expr.visitor import identify_variables

        self.model = model
        self.canonical = canonical_inputs(model)
        self.variables = {id(v): v for v in model.component_data_objects(Var, active=True)}
        self.fixed = {i for i, v in self.variables.items() if v.fixed}
        self.graph = nx.Graph()
        self.graph.add_nodes_from(self.variables)
        self.rows = []
        for i, constraint in enumerate(model.component_data_objects(Constraint, active=True)):
            if not constraint.equality:
                continue
            row = ('equation', i)
            self.rows.append(row)
            self.graph.add_node(row)
            for v in identify_variables(constraint.body):
                if id(v) in self.variables:
                    self.graph.add_edge(row, id(v))
        self.canonical_ids = set().union(*(_entries(v) for v in self.canonical.values())) if self.canonical else set()
        self._signatures = {}

    def signature(self, fixed):
        """DM deficiency and unmatched-equation count for a virtual fixation set."""
        import networkx as nx
        key = frozenset(fixed)
        if key not in self._signatures:
            free = self.variables.keys() - fixed
            graph = self.graph.subgraph([*self.rows, *free])
            matching = nx.algorithms.bipartite.maximum_matching(graph, top_nodes=self.rows)
            rank = len(matching) // 2
            self._signatures[key] = (len(free) - rank, len(self.rows) - rank)
        return self._signatures[key]

    def distances(self, family):
        distance = {i: 0 for i in _entries(family)}
        if any(i not in self.graph for i in distance):
            raise ValueError('Replacement target is outside the active model scope')
        pending = deque(distance)
        while pending:
            node = pending.popleft()
            for other in self.graph[node]:
                if other not in distance:
                    distance[other] = distance[node] + 1
                    pending.append(other)
        return distance

    def assign(self, targets, *, requested=None):
        """Pair all targets together, reserving direct inputs before any exchange.

        A complete canonical reference must remain complete under each exchange.
        A deficient reference may improve but cannot worsen its DM counts. No
        numerical values are needed for these virtual reference fixations.
        """
        registry = self.model._model_language_variables
        requested = requested if requested is not None else {}
        state = getattr(self.model, '_model_language_specification_slots', {})
        used = set(state)
        fixed = self.fixed | self.canonical_ids
        for slot, entry in state.items():
            if slot != entry['variable_path']:
                fixed -= _entries(self.canonical[slot])
        # All direct selections are reserved first, so late information can move
        # an earlier inferred pair to another input without losing either record.
        for record_id, path in targets.items():
            if path in self.canonical:
                if record_id in requested:
                    raise ValueError(f'{record_id}: a canonical input must be specified directly')
                if path in used:
                    raise ValueError(f'Canonical input {path!r} is already specified')
                used.add(path)
        reference = self.signature(fixed)
        result = {}

        def check_partner(path, slot, distances):
            if slot not in self.canonical:
                return f'{slot!r} is not an unsupplied input'
            family = self.canonical[slot]
            if slot in used or any(v.fixed for v in family.values()):
                return f'canonical input {slot!r} is already specified'
            if not _same_grid(registry[path], family):
                return f'{slot!r} has different index domains or scope'
            if not all(i in distances for i in _entries(family)):
                return f'{slot!r} is not structurally connected to {path!r}'
            return None

        noncanonical = {i: p for i, p in targets.items() if p not in self.canonical}
        # User-specified pairs are a joint assignment, not an ordered history.
        # In particular, swapping two pairs must not depend on JSON key order.
        pinned = fixed.copy()
        for record_id, slot in requested.items():
            path = targets[record_id]
            error = check_partner(path, slot, self.distances(registry[path]))
            if error:
                raise ValueError(f'{path} ({record_id}): cannot assign replacement: {error}')
            pinned = (pinned - _entries(self.canonical[slot])) | _entries(registry[path])
            used.add(slot)
            result[record_id] = slot
        pinned_signature = self.signature(pinned)
        if any(after > before for after, before in zip(pinned_signature, reference)):
            raise ValueError('Specified pairs are not a structurally admissible replacement assignment')
        fixed, reference = pinned, pinned_signature
        for record_id, path in noncanonical.items():
            if record_id in result:
                continue
            target = registry[path]
            distances = self.distances(target)
            candidates = sorted(self.canonical, key=lambda c: (
                _hierarchy_distance(path, c),
                min((distances.get(i, float('inf')) for i in _entries(self.canonical[c])), default=float('inf')),
                c,
            ))
            for slot in candidates:
                if check_partner(path, slot, distances):
                    continue
                trial = (fixed - _entries(self.canonical[slot])) | _entries(target)
                signature = self.signature(trial)
                if any(after > before for after, before in zip(signature, reference)):
                    continue
                result[record_id] = slot
                used.add(slot)
                fixed, reference = trial, signature
                break
            else:
                raise ValueError(f'{path} ({record_id}): cannot assign replacement: '
                                 'no structurally admissible input with matching index domains')
        return result


def _validate_slots(model, specification, information):
    """Require explicit pairs and validate the complete exchange assignment."""
    canonical = canonical_inputs(model)
    targets = {i: information.get(i).variable_path for i in specification.specifications}
    for record_id, path in targets.items():
        if path not in canonical and record_id not in specification.replacements:
            raise ValueError(f'{path} ({record_id}): noncanonical fixation requires an explicit replacement input')
    # Direct-only partial documents need no graph construction.
    if not specification.replacements:
        occupied = getattr(model, '_model_language_specification_slots', {})
        for path in targets.values():
            if path in occupied:
                raise ValueError(f'Canonical input {path!r} is already specified')
        return {path: {'variable_path': path, 'record_id': i} for i, path in targets.items()}
    pairs = _ReplacementGraph(model).assign(targets, requested=specification.replacements)
    return {pairs.get(i, path): {'variable_path': path, 'record_id': i} for i, path in targets.items()}


def pair_specification(model, specification, information):
    """Return a document with automatically inferred, editable replacement pairs.

    Selected information is unchanged. Existing explicit pairs are respected;
    infer missing pairs using structural exchanges, hierarchy distance, equation
    distance, and path tie-breaking. No model or information values are changed.
    """
    from .specification import _document, _prepare
    specification = _document(specification)
    _prepare(model, specification, information)  # Paths, units, bounds, fixity.
    audit_fixations(model)
    targets = {i: information.get(i).variable_path for i in specification.specifications}
    if not any(path not in canonical_inputs(model) for path in targets.values()):
        _validate_slots(model, specification, information)
        return specification
    pairs = _ReplacementGraph(model).assign(targets, requested=specification.replacements)
    return specification.model_copy(update={'replacements': pairs})


def specification_slots(model):
    """Describe applied operating slots using paths, fixed targets and record IDs."""
    return [dict(canonical_input=slot, **entry)
            for slot, entry in sorted(getattr(model, '_model_language_specification_slots', {}).items())]


def audit_fixations(model):
    """Reject unexplained public output/supplied-input fixes at solve entry.

    Raw fixes of canonical inputs are permitted. Native-provider configuration
    and explicit first-slice initial conditions have their separate scopes.
    """
    registry = getattr(model, '_model_language_variables', None)
    if registry is None:
        raise ValueError('Model must be constructed by model_language.build_model')
    canonical = canonical_inputs(model)
    slots = getattr(model, '_model_language_specification_slots', {})
    known = {entry['variable_path'] for entry in slots.values()}
    initial = getattr(model, '_model_language_initial_fixations', set())
    for path, family in registry.items():
        if path in canonical or path in known:
            continue
        for index, variable in family.items():
            if variable.fixed and (path, index) not in initial:
                raise ValueError(f'{path}: fixed noncanonical variable requires an explicit replacement input')
    for slot, entry in slots.items():
        target = registry[entry['variable_path']]
        if not all(v.fixed for v in target.values()):
            raise ValueError(f'{slot}: specification target is no longer fixed')
        if slot != entry['variable_path'] and any(v.fixed for v in canonical[slot].values()):
            raise ValueError(f'{slot}: replaced canonical input must remain free')

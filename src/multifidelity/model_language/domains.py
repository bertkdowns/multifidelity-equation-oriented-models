"""Construct occurrence-owned ordered sets from numerical build configuration."""

import math

from pyomo.environ import Block, Set


def domain_members(values, *, time=False):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("Domain members must be a nonempty list or tuple")
    for value in values:
        if type(value) not in (int, float, str) or (
            isinstance(value, float) and not math.isfinite(value)
        ):
            raise ValueError("Domain members must be finite numbers or strings")
        if time and type(value) not in (int, float):
            raise ValueError("Time points must be finite numbers")
    if len(set(values)) != len(values):
        raise ValueError("Domain members must be distinct")
    if time and list(values) != sorted(values):
        raise ValueError("Time points must be strictly increasing")
    return list(values)


class BuildDomains:
    """Bind children to existing sets; never infer sharing from equal members."""

    def __init__(self, root, values):
        self.values = dict(values or {})
        self.used = set()
        time_names = [n for n, d in root.definition.domains.items() if d.kind == "time"]
        if len(time_names) > 1:
            raise ValueError("The root may declare only one time domain")
        self.time_name = time_names[0] if time_names else None
        self.time_points = [0.0]
        if self.time_name is not None and self.time_name in self.values:
            self.time_points = self.members(self.time_name, time=True)

    def members(self, key, *, time=False):
        if key not in self.values:
            raise ValueError(f"Missing domain_values for {key!r}")
        self.used.add(key)
        try:
            return domain_members(self.values[key], time=time)
        except ValueError as error:
            raise ValueError(f"{key}: {error}") from error

    def populate(self, block, resolved, parent, flowsheet_time):
        block.domains = Block()
        domains = {}
        for name, declaration in resolved.definition.domains.items():
            if name in resolved.domain_bindings:
                domains[name] = parent[resolved.domain_bindings[name]]
            elif declaration.kind == "time":
                domains[name] = flowsheet_time
            else:
                key = f"{resolved.path}.{name}" if parent is not None else name
                component = Set(initialize=self.members(key), ordered=True)
                block.domains.add_component(name, component)
                domains[name] = component
        return domains

    def check_unused(self):
        unused = self.values.keys() - self.used
        if unused:
            raise ValueError(f"Unused domain_values: {sorted(unused)}")

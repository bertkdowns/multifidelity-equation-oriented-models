"""Indexed algebraic construction, hierarchy binding, and family determination."""

from copy import deepcopy
import json

import pytest
from pydantic import ValidationError
from pyomo.environ import value
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import Library, build_model, required_inputs
from multifidelity.model_language.definitions import ModelDocument


def pipe_definition():
    return {
        "id": "indexed_pipe",
        "domains": {"time": {"kind": "time"}},
        "structs": {
            "inlet": {"direction": "input", "variables": {
                "flow": {"unit": "kg/s", "dimensions": ["time"]},
            }},
            "outlet": {"direction": "output", "variables": {
                "flow": {"unit": "kg/s", "dimensions": ["time"]},
            }},
        },
        "relationships": {"pass_through": {"constraints": {
            "flow": {
                "for_each": {"t": "time"},
                "lhs": "outlet.flow[t]", "rhs": "inlet.flow[t]",
                "determines": "outlet.flow[t]",
            },
        }}},
    }


def library_for(tmp_path, *definitions):
    for definition in definitions:
        (tmp_path / f"{definition['id']}.json").write_text(json.dumps(definition))
    return Library(tmp_path)


def build_pipe(tmp_path, definition=None, **kwargs):
    definition = definition or pipe_definition()
    return build_model(
        definition["id"], {"relationship": "pass_through"},
        library=library_for(tmp_path, definition), **kwargs,
    )


def test_time_indexed_pipe_and_required_input_family(tmp_path):
    definition = pipe_definition()
    library = library_for(tmp_path, definition)
    selection = {"relationship": "pass_through"}
    m = build_model("indexed_pipe", selection, library=library,
                    domain_values={"time": [0, 10, 30]})
    b = m.fs.root
    assert b.structs.inlet.flow.index_set() is m.fs.time
    assert list(b.structs.outlet.flow) == [0, 10, 30]
    assert list(b.relationship.constraints.flow) == [0, 10, 30]
    for t in m.fs.time:
        b.structs.inlet.flow[t].set_value(2 + t)
        b.structs.outlet.flow[t].set_value(2 + t)
        assert value(b.relationship.constraints.flow[t].body) == 0
        assert not b.structs.inlet.flow[t].fixed
    assert_units_consistent(m)
    assert required_inputs("indexed_pipe", selection, library=library)[
        "inlet.flow"
    ].dimensions == ["time"]
    assert list(build_pipe(tmp_path).fs.time) == [0]
    parsed = ModelDocument.model_validate(definition)
    assert ModelDocument.model_validate_json(parsed.model_dump_json(by_alias=True)) == parsed


def test_two_dimensions_with_scalar_parameter_and_named_members(tmp_path):
    definition = pipe_definition()
    definition["domains"]["components"] = {"kind": "discrete"}
    for struct in definition["structs"].values():
        struct["variables"]["flow"]["dimensions"].append("components")
    definition["structs"]["settings"] = {
        "direction": "input", "variables": {"factor": {}}
    }
    equation = definition["relationships"]["pass_through"]["constraints"]["flow"]
    equation.update(for_each={"j": "components", "t": "time"},
                    lhs="outlet.flow[t, j]", rhs="settings.factor * inlet.flow[t, j]",
                    determines="outlet.flow[t, j]")
    m = build_pipe(tmp_path, definition, domain_values={
        "time": [0, 1], "components": ["water", "salt"],
    })
    b = m.fs.root
    assert len(b.structs.outlet.flow) == 4
    b.structs.settings.factor.set_value(2)
    b.structs.inlet.flow[1, "water"].set_value(3)
    b.structs.outlet.flow[1, "water"].set_value(6)
    assert value(b.relationship.constraints.flow["water", 1].body) == 0
    # No broadcasting on declarations; the scalar input is explicitly used.
    assert not b.structs.settings.factor.is_indexed()


def hierarchy():
    child = pipe_definition()
    parent = deepcopy(child)
    parent["id"] = "network"
    parent["relationships"] = {"network": {
        "models": {"pipe": {"model": "indexed_pipe", "domain_bindings": {"time": "time"}}},
        "connections": {
            "inlet": {"from": "inlet", "to": "pipe.inlet"},
            "outlet": {"from": "pipe.outlet", "to": "outlet"},
        },
    }}
    selection = {"relationship": "network", "submodels": {
        "pipe": {"relationship": "pass_through"},
    }}
    return parent, child, selection


def test_shared_time_domain_and_indexed_connections(tmp_path):
    parent, child, selection = hierarchy()
    library = library_for(tmp_path, parent, child)
    m = build_model("network", selection, library=library, domain_values={"time": [0, 1, 2]})
    b = m.fs.root
    pipe = b.relationship.models.pipe
    assert pipe.structs.inlet.flow.index_set() is b.structs.inlet.flow.index_set()
    assert len(b.relationship.connections.inlet.flow) == 3
    assert set(required_inputs("network", selection, library=library)) == {"inlet.flow"}
    for t in m.fs.time:
        b.structs.inlet.flow[t].set_value(2)
        pipe.structs.inlet.flow[t].set_value(2)
        assert value(b.relationship.connections.inlet.flow[t].body) == 0


def test_child_domain_alias_and_equation_determining_child_input(tmp_path):
    parent, child, selection = hierarchy()
    child["domains"] = {"clock": {"kind": "time"}}
    for struct in child["structs"].values():
        struct["variables"]["flow"]["dimensions"] = ["clock"]
    child["relationships"]["pass_through"]["constraints"]["flow"]["for_each"] = {"t": "clock"}
    rel = parent["relationships"]["network"]
    rel["models"]["pipe"]["domain_bindings"] = {"clock": "time"}
    del rel["connections"]["inlet"]
    rel["constraints"] = {"feed": {
        "for_each": {"t": "time"}, "lhs": "pipe.inlet.flow[t]",
        "rhs": "inlet.flow[t]", "determines": "pipe.inlet.flow[t]",
    }}
    library = library_for(tmp_path, parent, child)
    m = build_model("network", selection, library=library, domain_values={"time": [0, 1]})
    assert len(m.fs.root.relationship.constraints.feed) == 2


@pytest.mark.parametrize("change, message", [
    ("unindexed", "requires explicit indices"),
    ("unknown_index", "bound for_each"),
    ("call", "Unsupported expression syntax"),
    ("attribute_after_index", "Unsupported expression syntax"),
    ("literal_target", "Determination indices"),
    ("extra_axis", "cover exactly"),
    ("duplicate", "duplicate determination"),
    ("missing", "missing output determinations"),
    ("unknown_domain", "unknown for_each domains"),
])
def test_indexed_equation_errors(tmp_path, change, message):
    definition = pipe_definition()
    equations = definition["relationships"]["pass_through"]["constraints"]
    eq = equations["flow"]
    if change == "unindexed":
        eq["rhs"] = "inlet.flow"
    elif change == "unknown_index":
        eq["rhs"] = "inlet.flow[u]"
    elif change == "call":
        eq["rhs"] = "inlet.flow[t]()"
    elif change == "attribute_after_index":
        eq["rhs"] = "inlet.flow[t].value"
    elif change == "literal_target":
        eq["determines"] = "outlet.flow[0]"
    elif change == "extra_axis":
        eq["for_each"]["u"] = "time"
    elif change == "duplicate":
        equations["again"] = deepcopy(eq)
    elif change == "missing":
        equations.clear()
    elif change == "unknown_domain":
        eq["for_each"]["t"] = "missing"
    with pytest.raises(ValueError, match=message):
        build_pipe(tmp_path, definition)


def test_index_domains_checked_even_with_identical_members(tmp_path):
    definition = pipe_definition()
    definition["domains"]["cells"] = {"kind": "discrete"}
    definition["structs"]["inlet"]["variables"]["flow"]["dimensions"] = ["cells"]
    with pytest.raises(ValueError, match="index domains do not match"):
        build_pipe(tmp_path, definition, domain_values={"cells": [0]})


@pytest.mark.parametrize("binding, message", [
    ({}, "requires an explicit binding"),
    ({"time": "missing"}, "invalid domain binding"),
    ({"missing": "time"}, "invalid domain binding"),
])
def test_bad_domain_bindings(tmp_path, binding, message):
    parent, child, selection = hierarchy()
    parent["relationships"]["network"]["models"]["pipe"]["domain_bindings"] = binding
    with pytest.raises(ValueError, match=message):
        build_model("network", selection, library=library_for(tmp_path, parent, child))


@pytest.mark.parametrize("points", [[], [1, 0], [0, 0], [True], [float("nan")], ["now"]])
def test_invalid_time_members(tmp_path, points):
    with pytest.raises(ValueError):
        build_pipe(tmp_path, domain_values={"time": points})


def test_unknown_domains_and_unused_run_configuration(tmp_path):
    with pytest.raises(ValueError, match="Unused domain_values"):
        build_pipe(tmp_path, domain_values={"typo": [1]})
    definition = pipe_definition()
    definition["structs"]["inlet"]["variables"]["flow"]["dimensions"] = ["missing"]
    with pytest.raises(ValueError, match="unknown variable domains"):
        build_pipe(tmp_path, definition)


def test_duplicate_dimensions_rejected():
    definition = pipe_definition()
    definition["structs"]["inlet"]["variables"]["flow"]["dimensions"] = ["time", "time"]
    with pytest.raises(ValidationError, match="distinct"):
        ModelDocument.model_validate(definition)


def test_local_discrete_domains_are_owned_by_each_occurrence(tmp_path):
    child = {
        "id": "local", "domains": {"cells": {"kind": "discrete"}},
        "structs": {"data": {"direction": "input", "variables": {
            "x": {"dimensions": ["cells"]},
        }}}, "relationships": {"empty": {}},
    }
    parent = {"id": "parent", "structs": {}, "relationships": {"pair": {
        "models": {"a": {"model": "local"}, "b": {"model": "local"}},
    }}}
    selection = {"relationship": "pair", "submodels": {
        "a": {"relationship": "empty"}, "b": {"relationship": "empty"},
    }}
    library = library_for(tmp_path, parent, child)
    with pytest.raises(ValueError, match="Missing domain_values"):
        build_model("parent", selection, library=library)
    m = build_model("parent", selection, library=library, domain_values={
        "parent.a.cells": [0, 1], "parent.b.cells": [0, 1],
    })
    a, b = m.fs.root.relationship.models.a, m.fs.root.relationship.models.b
    assert a.structs.data.x.index_set() is a.domains.cells
    assert b.structs.data.x.index_set() is b.domains.cells
    assert a.domains.cells is not b.domains.cells


def test_indexed_connections_convert_units(tmp_path):
    parent, child, selection = hierarchy()
    for struct in child["structs"].values():
        struct["variables"]["flow"]["unit"] = "g/s"
    m = build_model("network", selection, library=library_for(tmp_path, parent, child),
                    domain_values={"time": [0, 1]})
    b = m.fs.root
    b.structs.inlet.flow[1].set_value(2)
    b.relationship.models.pipe.structs.inlet.flow[1].set_value(2000)
    assert value(b.relationship.connections.inlet.flow[1].body) == pytest.approx(0)


def test_connections_reject_equal_members_on_different_domains(tmp_path):
    parent, child, selection = hierarchy()
    parent["domains"]["other"] = {"kind": "discrete"}
    parent["structs"]["inlet"]["variables"]["flow"]["dimensions"] = ["other"]
    with pytest.raises(ValueError, match="connection dimensions differ"):
        build_model("network", selection, library=library_for(tmp_path, parent, child),
                    domain_values={"other": [0]})


def test_indexed_target_can_be_implicit(tmp_path):
    definition = pipe_definition()
    eq = definition["relationships"]["pass_through"]["constraints"]["flow"]
    eq["lhs"] = "inlet.flow[t]"
    eq["rhs"] = "2 * inlet.flow[t]"
    model = build_pipe(tmp_path, definition)
    assert_units_consistent(model)


def test_generic_child_keeps_occurrence_domain_bindings(tmp_path):
    root, child, selection = hierarchy()
    wrapper = deepcopy(root)
    wrapper["id"] = "wrapper"
    wrapper["model_parameters"] = {"Pipe": {"requires": child["structs"]}}
    wrapper["relationships"]["network"]["models"]["pipe"] = {
        "model_parameter": "Pipe", "domain_bindings": {"time": "time"},
    }
    root["relationships"]["network"]["models"]["pipe"] = {
        "model": "wrapper", "model_arguments": {"Pipe": {"model": "indexed_pipe"}},
        "domain_bindings": {"time": "time"},
    }
    selection["submodels"]["pipe"] = {
        "relationship": "network", "submodels": {"pipe": {"relationship": "pass_through"}},
    }
    m = build_model("network", selection, library=library_for(tmp_path, root, wrapper, child),
                    domain_values={"time": [0, 1]})
    nested = m.fs.root.relationship.models.pipe.relationship.models.pipe
    assert nested.structs.inlet.flow.index_set() is m.fs.time


def test_bound_discrete_domains_share_set_identity(tmp_path):
    parent, child, selection = hierarchy()
    # Keep loop binder t, but change the domain to a discrete cell set.
    parent, child = [json.loads(json.dumps(d).replace('"time"', '"cells"'))
                     for d in (parent, child)]
    for definition in (parent, child):
        definition["domains"]["cells"]["kind"] = "discrete"
    m = build_model("network", selection, library=library_for(tmp_path, parent, child),
                    domain_values={"cells": [0, 1]})
    root = m.fs.root
    assert root.relationship.models.pipe.structs.inlet.flow.index_set() is root.domains.cells
    assert len(root.relationship.connections.inlet.flow) == 2

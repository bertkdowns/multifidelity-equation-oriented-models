"""The acquisition seam: bulk reads, typed config, validation, and portability."""
import json

import pytest
from pydantic import BaseModel, ValidationError

from multifidelity.model_language import (
    FeedRegistry, ResourceCatalog, FeedCatalog, WorkspaceCatalog,
    build_model, export_workspace,
)


class Config(BaseModel):
    columns: dict[str, str] = {"flow": "FT101", "pressure": "PT101"}


class Feed:
    def __init__(self, values, *, tags=None):
        self.tags = list(values) if tags is None else tags
        self.tag_calls = 0
        self.config = Config()
        self.values = values
        self.calls = []

    def get_config(self) -> Config:
        return self.config

    def get_tags(self):
        self.tag_calls += 1
        return self.tags

    def read(self, tags):
        self.calls.append(tags)
        return {tag: self.values[tag] for tag in tags}


def resources():
    return ResourceCatalog([
        dict(tag="flow", resource_type="sensor_reading", variable_path="inlet.flow",
             unit="kg/s", value=1, trust_rank=8, standard_deviation=0.1),
        dict(tag="pressure", resource_type="sensor_reading", variable_path="inlet.pressure",
             unit="kPa", value=100, trust_rank=9),
        dict(tag="fallback", resource_type="assumption", variable_path="inlet.pressure",
             unit="kPa", value=90, trust_rank=1),
    ])


def test_bulk_read_keeps_metadata_order_and_original_resources():
    table = resources()
    registry = FeedRegistry()
    feed = Feed({"flow": 2, "pressure": 200}, tags=["pressure", "flow"])
    registry.register_feed("plant", feed)
    refreshed = registry.read(table)
    assert feed.calls == [("pressure", "flow")]
    assert [r.tag for r in refreshed.root] == ["flow", "pressure", "fallback"]
    assert [r.value for r in refreshed.root] == [2, 200, 90]
    assert [r.value for r in table.root] == [1, 100, 90]
    assert refreshed.get("flow").model_dump(exclude={"value"}) == table.get("flow").model_dump(exclude={"value"})
    assert FeedRegistry().read(table) == table
    feed.values["flow"] = 3
    assert registry.read(table).get("flow").value == 3
    assert refreshed.get("flow").value == 2


def test_registration_conflicts_are_atomic_and_static_records_are_unclaimed():
    registry = FeedRegistry()
    feed = Feed({"flow": 2})
    registry.register_feed("plant", feed)
    before = registry.describe()
    for name, tags in [("plant", ["pressure"]), ("other", ["flow"]), ("other", ["pressure", "pressure"]), ("", ["pressure"]), ("other", [""])]:
        with pytest.raises(ValueError):
            registry.register_feed(name, Feed({}, tags=tags))
        assert registry.describe() == before
    with pytest.raises(TypeError, match="not a string"):
        registry.register_feed("other", Feed({}, tags="pressure"))
    registry.register_feed("other", Feed({"pressure": 250}, tags=["pressure"]))
    assert registry.read(resources()).get("fallback").value == 90


def test_unknown_tags_are_checked_before_any_read_and_empty_feeds_are_skipped():
    registry = FeedRegistry()
    feed = Feed({"flow": 2})
    registry.register_feed("plant", feed)
    registry.register_feed("unknown", Feed({}, tags=["absent"]))
    with pytest.raises(ValueError, match="Unknown resource record tags"):
        registry.read(resources())
    assert feed.calls == []
    registry = FeedRegistry()
    registry.register_feed("unused", Feed({}, tags=[]))
    assert registry.read(resources()) == resources()
    assert feed.calls == []


@pytest.mark.parametrize("response", [None, {}, {"pressure": 3}, {"flow": 2, "extra": 3}, {"flow": True}, {"flow": float("nan")}, {"flow": [1, 2]}])
def test_invalid_responses_do_not_mutate_resources_or_use_saved_values(response):
    class Bad(Feed):
        def read(self, tags):
            return response
    table = resources()
    before = table.model_dump_json()
    registry = FeedRegistry()
    registry.register_feed("good", Feed({"pressure": 200}, tags=["pressure"]))
    registry.register_feed("bad", Bad({}, tags=["flow"]))
    with pytest.raises(ValueError, match="Feed 'bad'"):
        registry.read(table)
    assert table.model_dump_json() == before


def test_feed_error_retains_context_and_cause():
    class Broken(Feed):
        def read(self, tags):
            raise TimeoutError("historian unavailable")
    registry = FeedRegistry()
    registry.register_feed("plant", Broken({}, tags=["flow"]))
    with pytest.raises(ValueError, match="plant.*historian unavailable") as error:
        registry.read(resources())
    assert isinstance(error.value.__cause__, TimeoutError)


def test_series_shape_is_preserved_and_returned_arrays_are_copied():
    values = [2, 3]
    table = ResourceCatalog([dict(tag="profile", resource_type="sensor_reading",
        variable_path="inlet.flow", unit="kg/s", type="series", value=[1, 1], trust_rank=8)])
    registry = FeedRegistry()
    feed = Feed({"profile": values})
    registry.register_feed("plant", feed)
    result = registry.read(table)
    values[0] = 999
    assert result.get("profile").value == (2, 3)
    feed.values["profile"] = [2, 3, 4]
    with pytest.raises(ValueError, match="shape"):
        registry.read(table)


def test_typed_config_catalogue_is_detached_and_roundtrips_without_reading(tmp_path):
    feed = Feed({}, tags=["flow"])
    registry = FeedRegistry()
    registry.register_feed("plant", feed)
    catalog = registry.describe()
    assert feed.calls == []
    assert catalog.root[0].provider_type.endswith(".Feed")
    assert catalog.root[0].config == feed.config.model_dump(mode="json")
    catalog.root[0].config["columns"]["flow"] = "changed"
    assert registry.describe().root[0].config["columns"]["flow"] == "FT101"
    path = tmp_path / "feeds.json"
    registry.describe().write_json(path)
    restored = FeedCatalog.load_json(path)
    assert restored == registry.describe()
    config = Config.model_validate(restored.root[0].config)
    assert isinstance(config, Config)
    assert feed.calls == []


def test_invalid_configuration_or_protocol_is_rejected_before_registration():
    class Untyped(Feed):
        def get_config(self):
            return {}
    class Nonfinite(Feed):
        def get_config(self):
            class BadConfig(BaseModel):
                value: float = float("inf")
            return BadConfig()
    class MissingTags:
        def get_config(self):
            return Config()

        def read(self, tags):
            return {}

    registry = FeedRegistry()
    for feed in [object(), MissingTags(), Untyped({}), Nonfinite({})]:
        with pytest.raises((TypeError, ValueError)):
            registry.register_feed("bad", feed)
    assert registry.describe().root == ()
    for data in [[dict(name="p", provider_type="module.Class", tags=["flow"], config=[])],
                 [dict(name="p", provider_type="module.Class", tags=["flow"], config={}, code="exec")]]:
        with pytest.raises(ValidationError):
            FeedCatalog.model_validate(data)


def test_workspace_catalogue_is_optional_portable_and_detached(tmp_path):
    registry = FeedRegistry()
    registry.register_feed("plant", Feed({}, tags=["flow", "pressure"]))
    model = build_model("valve", {"formulation": "isenthalpic"})
    legacy = export_workspace(model, resources())
    assert set(legacy.model_dump()) == {"model_catalog", "resources", "results"}
    workspace = WorkspaceCatalog.from_results(legacy.results, resources(), feeds=registry.describe())
    path = tmp_path / "workspace.json"
    workspace.write_json(path)
    assert WorkspaceCatalog.load_json(path) == workspace
    assert isinstance(json.loads(path.read_text())["feeds"], list)
    assert workspace.results.run_id == legacy.results.run_id
    assert export_workspace(model, resources(), feeds=registry.describe()).feeds == registry.describe()


def test_dynamic_tags_are_refreshed_and_snapshotted_once_per_read():
    feed = Feed({"flow": 2})
    registry = FeedRegistry()
    registry.register_feed("plant", feed)
    assert registry.describe().root[0].tags == ("flow",)
    feed.tags.append("pressure")
    feed.values["pressure"] = 210
    assert registry.describe().root[0].tags == ("flow", "pressure")
    feed.tag_calls = 0
    fresh = registry.read(resources())
    assert feed.tag_calls == 1
    assert feed.calls == [("flow", "pressure")]
    assert fresh.get("pressure").value == 210
    feed.tags.remove("flow")
    fresh = registry.read(resources())
    assert fresh.get("flow").value == resources().get("flow").value
    assert feed.calls[-1] == ("pressure",)


def test_dynamic_conflicts_and_unknown_tags_fail_before_any_value_reads():
    first = Feed({"flow": 2})
    second = Feed({"pressure": 210})
    registry = FeedRegistry()
    registry.register_feed("first", first)
    registry.register_feed("second", second)
    for bad_tags in [["flow"], ["absent"], ["pressure", "pressure"], "pressure"]:
        second.tags = bad_tags
        with pytest.raises((TypeError, ValueError)):
            registry.read(resources())
        assert first.calls == second.calls == []
    second.tags = ["pressure"]
    assert registry.read(resources()).get("pressure").value == 210

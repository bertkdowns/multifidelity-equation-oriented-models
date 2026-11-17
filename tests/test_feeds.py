"""Plugin registration, document loading and runtime acquisition boundaries."""
import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from multifidelity.model_language import (
    FeedRegistry, FeedDocument, ResourceDocument, WorkspaceDocument,
    build_model, export_workspace,
)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, float | list[float]]


class TestFeed:
    __test__ = False

    def __init__(self, config: Config):
        self.config = config
        self.tags = list(config.values)
        self.tag_calls = 0
        self.calls = []

    def get_config(self) -> Config:
        return self.config

    def get_tags(self):
        self.tag_calls += 1
        return self.tags

    def read(self, tags):
        self.calls.append(tags)
        return {tag: self.config.values[tag] for tag in tags}


def document(*entries):
    return FeedDocument(feeds=[dict(name=name, provider_type=plugin, config=config)
                               for name, plugin, config in entries])


def resources():
    return ResourceDocument([
        dict(tag="flow", resource_type="sensor_reading", variable_path="inlet.flow",
             unit="kg/s", value=1, trust_rank=8, standard_deviation=0.1),
        dict(tag="pressure", resource_type="sensor_reading", variable_path="inlet.pressure",
             unit="kPa", value=100, trust_rank=9),
        dict(tag="fallback", resource_type="assumption", variable_path="inlet.pressure",
             unit="kPa", value=90, trust_rank=1),
    ])


def setup_feeds(*values):
    registry = FeedRegistry()
    instances = []
    def factory(config):
        feed = TestFeed(config)
        instances.append(feed)
        return feed
    registry.register("test", factory, config_type=Config)
    feeds = registry.create_feeds(document(*[(str(i), "test", {"values": v}) for i, v in enumerate(values)]))
    return registry, feeds, instances


def test_registry_describes_available_plugins_without_constructing_or_discovering():
    class Offline(TestFeed):
        def __init__(self, config):
            raise AssertionError("Registration must not construct feeds")
    registry = FeedRegistry()
    registry.register("csv", Offline)
    assert registry.describe() == {"csv": Config.model_json_schema()}
    assert registry.create_feeds(FeedDocument()).read(resources()) == resources()
    with pytest.raises(ValueError, match="Duplicate feed plugin"):
        registry.register("csv", TestFeed)
    for name, factory in [("", TestFeed), ("bad", object()), ("missing", type("Missing", (), {}))]:
        with pytest.raises((TypeError, ValueError)):
            registry.register(name, factory)
    assert list(registry.describe()) == ["csv"]


def test_document_is_configuration_not_plugin_availability_or_tag_snapshot(tmp_path):
    registry, feeds, instances = setup_feeds({"flow": 2})
    saved = feeds.get_document()
    assert saved.model_dump() == {"feeds": ({"name": "0", "provider_type": "test", "config": {"values": {"flow": 2.0}}},)}
    assert instances[0].tag_calls == 0
    path = tmp_path / "feeds.json"
    saved.write_json(path)
    assert FeedDocument.load_json(path) == saved
    restored = registry.create_feeds(path)
    assert restored.read(resources()).get("flow").value == 2
    saved.feeds[0].config["values"]["flow"] = 999
    assert feeds.get_document().feeds[0].config["values"]["flow"] == 2
    assert list(registry.describe()) == ["test"]


def test_all_configs_and_plugin_names_are_validated_before_construction():
    constructed = []
    registry = FeedRegistry()
    registry.register("test", lambda config: constructed.append(config), config_type=Config)
    for bad in [("unknown", {"values": {}}), ("test", {"values": {"flow": "bad"}}), ("test", {"values": {}, "extra": 1})]:
        doc = document(("valid", "test", {"values": {}}), ("invalid", *bad))
        with pytest.raises(ValueError, match="invalid"):
            registry.create_feeds(doc)
        assert constructed == []


@pytest.mark.parametrize("value", [[], {"feeds": [{"name": "p", "provider_type": "test", "config": {}, "tags": []}]},
    {"feeds": [{"name": "p", "provider_type": "test", "config": []}]},
    {"feeds": [{"name": "p", "provider_type": "test", "config": {"x": float('inf')}}]}])
def test_invalid_documents_rejected(value):
    with pytest.raises((ValidationError, ValueError)):
        FeedDocument.model_validate(value)


def test_duplicate_instance_names_rejected_but_plugin_can_be_used_twice():
    with pytest.raises(ValueError, match="Duplicate feed name"):
        document(("same", "test", {}), ("same", "test", {}))
    _, feeds, _ = setup_feeds({"flow": 2}, {"pressure": 200})
    assert feeds.read(resources()).get("pressure").value == 200


def test_bulk_read_preserves_metadata_static_values_and_original_table():
    _, feeds, instances = setup_feeds({"pressure": 200, "flow": 2})
    table = resources()
    refreshed = feeds.read(table)
    assert instances[0].calls == [("pressure", "flow")]
    assert [r.value for r in refreshed.root] == [2, 200, 90]
    assert [r.value for r in table.root] == [1, 100, 90]
    assert refreshed.get("flow").model_dump(exclude={"value"}) == table.get("flow").model_dump(exclude={"value"})


def test_dynamic_claims_snapshotted_once_and_conflicts_checked_before_read():
    _, feeds, instances = setup_feeds({"flow": 2}, {"pressure": 200})
    first, second = instances
    for tags in [["flow"], ["absent"], ["pressure", "pressure"], "pressure", [""]]:
        second.tags = tags
        with pytest.raises((TypeError, ValueError)):
            feeds.read(resources())
        assert first.calls == second.calls == []
    second.tags = ["pressure"]
    first.tag_calls = second.tag_calls = 0
    assert feeds.read(resources()).get("pressure").value == 200
    assert first.tag_calls == second.tag_calls == 1
    first.tags = []
    assert feeds.read(resources()).get("flow").value == 1


@pytest.mark.parametrize("response", [None, {}, {"pressure": 3}, {"flow": 2, "extra": 3}, {"flow": True}, {"flow": float("nan")}, {"flow": [1, 2]}])
def test_bad_responses_never_mutate_or_fall_back(response):
    _, feeds, instances = setup_feeds({"flow": 2})
    instances[0].read = lambda tags: response
    table = resources()
    before = table.model_dump_json()
    with pytest.raises(ValueError, match="Feed '0'"):
        feeds.read(table)
    assert table.model_dump_json() == before


def test_read_errors_retain_context_and_cause():
    _, feeds, instances = setup_feeds({"flow": 2})
    def broken(tags):
        raise TimeoutError("offline")
    instances[0].read = broken
    with pytest.raises(ValueError, match="Feed '0'.*offline") as error:
        feeds.read(resources())
    assert isinstance(error.value.__cause__, TimeoutError)


def test_series_shape_and_detachment():
    _, feeds, instances = setup_feeds({"profile": [2, 3]})
    table = ResourceDocument([dict(tag="profile", resource_type="sensor_reading", variable_path="inlet.flow",
        unit="kg/s", type="series", value=[1, 1], trust_rank=8)])
    result = feeds.read(table)
    instances[0].config.values["profile"][0] = 999
    assert result.get("profile").value == (2, 3)
    instances[0].config.values["profile"] = [2, 3, 4]
    with pytest.raises(ValueError, match="shape"):
        feeds.read(table)


def test_invalid_factory_products_fail_with_instance_context():
    registry = FeedRegistry()
    registry.register("bad", lambda config: object(), config_type=Config)
    with pytest.raises(ValueError, match="plant.*get_config"):
        registry.create_feeds(document(("plant", "bad", {"values": {}})))


def test_workspace_embeds_document_without_live_plugins(tmp_path):
    registry, feeds, _ = setup_feeds({"flow": 2})
    model = build_model("valve", {"formulation": "isenthalpic"})
    plain = export_workspace(model, resources())
    assert "feeds" not in plain.model_dump()
    workspace = WorkspaceDocument.from_results(plain.results, resources(), feeds=feeds.get_document())
    path = tmp_path / "workspace.json"
    workspace.write_json(path)
    loaded = WorkspaceDocument.load_json(path)
    assert loaded == workspace
    assert registry.create_feeds(loaded.feeds).read(resources()).get("flow").value == 2

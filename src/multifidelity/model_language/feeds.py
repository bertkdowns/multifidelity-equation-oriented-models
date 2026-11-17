"""Bulk input acquisition, separate from symbolic formulation providers."""

from collections.abc import Callable, Iterable, Mapping
import json
from pathlib import Path
from typing import Annotated, Protocol, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .definitions import Definition
from .resources import ResourceDocument, Resource, ResourceValue

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]


class Feed[C: BaseModel](Protocol):
    """Return values in the resource records' units and final grid order.

    Configuration is a JSON-serializable Pydantic model. Clients, credentials,
    and other runtime dependencies belong to the live feed, not config.
    """

    def get_config(self) -> C: ...

    def get_tags(self) -> Iterable[str]: ...

    def read(self, tags: tuple[str, ...]) -> Mapping[str, ResourceValue]: ...


class FeedDescription(Definition):
    """One configured use of an explicitly registered plugin."""

    name: Text
    provider_type: Text
    config: dict[str, JsonValue]

    @model_validator(mode="after")
    def finite_config(self):
        json.dumps(self.config, allow_nan=False)
        return self


class FeedDocument(Definition):
    """Portable feed instances and settings; contains no code or discovered tags."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    feeds: tuple[FeedDescription, ...] = ()

    @model_validator(mode="after")
    def unique_names(self):
        names = [feed.name for feed in self.feeds]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate feed name")
        return self

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")


class FeedRegistry:
    """Available trusted plugins, independent of any workspace configuration."""

    def __init__(self):
        self._plugins = {}

    def register[C: BaseModel](
        self, provider_type: str, factory: Callable[[C], Feed[C]], *,
        config_type: type[C] | None = None,
    ) -> None:
        """Register a class taking typed config, or a factory with config_type.

        Classes infer their config model from get_config()'s return annotation.
        A factory can close over runtime clients without exporting credentials.
        Registration neither constructs feeds nor discovers tags.
        """
        if not isinstance(provider_type, str) or not provider_type.strip():
            raise ValueError("Plugin name must be a nonempty string")
        if provider_type in self._plugins:
            raise ValueError(f"Duplicate feed plugin: {provider_type}")
        if not callable(factory):
            raise TypeError("Feed plugin must be callable")
        if config_type is None:
            for method in ("get_config", "get_tags", "read"):
                if not callable(getattr(factory, method, None)):
                    raise TypeError(f"Feed plugin requires {method}() or an explicit factory config_type")
            config_type = get_type_hints(factory.get_config).get("return")
        if not isinstance(config_type, type) or not issubclass(config_type, BaseModel):
            raise TypeError("Feed plugin config_type must be a Pydantic model")
        self._plugins[provider_type] = (factory, config_type)

    def describe(self) -> dict[str, dict]:
        """Available plugin names and JSON config schemas for frontend inspection."""
        return {name: config_type.model_json_schema()
                for name, (_, config_type) in self._plugins.items()}

    def create_feeds(self, document: FeedDocument | dict | str | Path) -> "FeedCollection":
        """Validate every declaration before constructing any configured feeds."""
        if isinstance(document, (str, Path)):
            document = FeedDocument.load_json(document)
        else:
            document = FeedDocument.model_validate(document)
        prepared = []
        for declaration in document.feeds:
            if declaration.provider_type not in self._plugins:
                raise ValueError(f"Feed {declaration.name!r}: unknown plugin {declaration.provider_type!r}")
            factory, config_type = self._plugins[declaration.provider_type]
            try:
                config = config_type.model_validate(declaration.config)
                json.dumps(config.model_dump(mode="json"), allow_nan=False)
            except Exception as error:
                raise ValueError(f"Feed {declaration.name!r}: invalid config: {error}") from error
            prepared.append((declaration, factory, config, config_type))
        feeds, declarations = {}, []
        for declaration, factory, config, config_type in prepared:
            try:
                feed = factory(config)
                for method in ("get_config", "get_tags", "read"):
                    if not callable(getattr(feed, method, None)):
                        raise TypeError(f"{method}() is required")
                actual = feed.get_config()
                if not isinstance(actual, config_type):
                    raise TypeError("get_config() must return the registered config type")
                declarations.append(FeedDescription(name=declaration.name,
                    provider_type=declaration.provider_type, config=actual.model_dump(mode="json")))
                feeds[declaration.name] = feed
            except Exception as error:
                raise ValueError(f"Feed {declaration.name!r}: {error}") from error
        return FeedCollection(feeds, FeedDocument(feeds=tuple(declarations)))


class FeedCollection:
    """Configured runtime feeds: discover current tags and route bulk reads."""

    def __init__(self, feeds: Mapping[str, Feed], document: FeedDocument):
        self._feeds = dict(feeds)
        self._document = document.model_copy(deep=True)

    def get_document(self) -> FeedDocument:
        """Export current typed settings without discovering tags or reading data."""
        return FeedDocument(feeds=tuple(FeedDescription(name=d.name,
            provider_type=d.provider_type,
            config=self._feeds[d.name].get_config().model_dump(mode="json"))
            for d in self._document.feeds))

    def get_tags(self) -> dict[str, tuple[str, ...]]:
        """Discover tags once per feed and reject duplicate claims before reads."""
        claims, seen = {}, set()
        for name, feed in self._feeds.items():
            tags = feed.get_tags()
            if isinstance(tags, (str, bytes)):
                raise TypeError(f"Feed {name!r}: get_tags() must return an iterable, not a string")
            tags = tuple(tags)
            for tag in tags:
                if not isinstance(tag, str) or not tag.strip():
                    raise ValueError(f"Feed {name!r}: tags must be nonempty strings")
                if tag in seen:
                    raise ValueError(f"Record tag claimed more than once: {tag}")
                seen.add(tag)
            claims[name] = tags
        return claims

    def read(self, resources: ResourceDocument) -> ResourceDocument:
        """Read each feed once and return a new validated resource table.

        Tags are snapshotted once per feed for this read. All claims must be
        unique and exist before any feed read() is called. Responses must
        contain exactly the requested tags. Values retain record metadata and
        series shape. Missing/invalid data raises without modifying the original
        table; no saved-value fallback is performed. Grid applicability is still
        checked when the resulting resources are applied to a built model.
        """
        records = {record.tag: record for record in resources.root}
        claims = self.get_tags()
        unknown = {tag for tags in claims.values() for tag in tags} - records.keys()
        if unknown:
            raise ValueError(f"Unknown resource record tags: {sorted(unknown)}")
        replacements = {}
        for name, tags in claims.items():
            feed = self._feeds[name]
            if not tags:
                continue
            try:
                values = feed.read(tags)
                if not isinstance(values, Mapping) or set(values) != set(tags):
                    raise ValueError("read() must return exactly the requested record tags")
                for tag in tags:
                    record = Resource.model_validate({
                        **records[tag].model_dump(), "value": values[tag],
                    })
                    record.validate_shape(records[tag].shape)
                    replacements[tag] = record
            except Exception as error:
                raise ValueError(f"Feed {name!r}: {error}") from error
        return ResourceDocument(tuple(replacements.get(r.tag, r) for r in resources.root))

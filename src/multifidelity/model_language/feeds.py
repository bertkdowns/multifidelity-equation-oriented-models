"""Bulk input acquisition, separate from symbolic formulation providers."""

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, model_validator

from .definitions import Definition
from .resources import ResourceCatalog, Resource, ResourceValue

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
    """Portable declaration; loading it never imports or executes a connector."""

    name: Text
    provider_type: Text
    tags: tuple[Text, ...]
    config: dict[str, JsonValue]

    @model_validator(mode="after")
    def valid_declaration(self):
        if len(set(self.tags)) != len(self.tags):
            raise ValueError(f"Feed {self.name!r}: duplicate record tag")
        # JsonValue permits nonfinite floats, but portable JSON does not.
        json.dumps(self.config, allow_nan=False)
        return self


class FeedCatalog(RootModel[tuple[FeedDescription, ...]]):
    """JSON array of feed declarations, usable without connector code."""

    model_config = ConfigDict(frozen=True)
    root: tuple[FeedDescription, ...] = ()

    @model_validator(mode="after")
    def unique_claims(self):
        names, tags = set(), set()
        for feed in self.root:
            if feed.name in names:
                raise ValueError(f"Duplicate feed name: {feed.name}")
            overlap = tags.intersection(feed.tags)
            if overlap:
                raise ValueError(f"Record tags claimed by multiple feeds: {sorted(overlap)}")
            names.add(feed.name)
            tags.update(feed.tags)
        return self

    @classmethod
    def load_json(cls, path: str | Path) -> "FeedCatalog":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")


class FeedRegistry:
    """Register case inputs, inspect configuration, and read fresh resources.

    Registration is explicit and local to this registry. Tags are discovered
    through get_tags() on each operation; loading a catalogue never imports code.
    """

    def __init__(self):
        self._feeds: dict[str, Feed] = {}

    @staticmethod
    def _describe(name, feed):
        tags = feed.get_tags()
        if isinstance(tags, (str, bytes)):
            raise TypeError(f"Feed {name!r}: get_tags() must return an iterable of tags, not a string")
        tags = tuple(tags)
        config = feed.get_config()
        if not isinstance(config, BaseModel):
            raise TypeError(f"Feed {name!r}: get_config() must return a Pydantic model")
        return FeedDescription(
            name=name,
            provider_type=f"{type(feed).__module__}.{type(feed).__qualname__}",
            tags=tags,
            config=config.model_dump(mode="json"),
        )

    def register_feed[C: BaseModel](
        self, name: str, feed: Feed[C],
    ) -> None:
        """Register a feed; validate its current declarations before storing it."""
        if name in self._feeds:
            raise ValueError(f"Duplicate feed name: {name}")
        for method in ("read", "get_config", "get_tags"):
            if not callable(getattr(feed, method, None)):
                raise TypeError(f"Feed {name!r}: {method}() is required")
        declaration = self._describe(name, feed)
        FeedCatalog((*self.describe().root, declaration))
        self._feeds[name] = feed

    def describe(self) -> FeedCatalog:
        """Snapshot current config and get_tags() results without calling read()."""
        return FeedCatalog(tuple(
            self._describe(name, feed)
            for name, feed in tuple(self._feeds.items())
        ))

    def read(self, resources: ResourceCatalog) -> ResourceCatalog:
        """Read each feed once and return a new validated resource table.

        Tags are snapshotted once per feed for this read. All claims must be
        unique and exist before any feed read() is called. Responses must
        contain exactly the requested tags. Values retain record metadata and
        series shape. Missing/invalid data raises without modifying the original
        table; no saved-value fallback is performed. Grid applicability is still
        checked when the resulting resources is applied to a built model.
        """
        records = {record.tag: record for record in resources.root}
        catalog = self.describe()
        unknown = {tag for feed in catalog.root for tag in feed.tags} - records.keys()
        if unknown:
            raise ValueError(f"Unknown resource record tags: {sorted(unknown)}")
        replacements = {}
        for declaration in catalog.root:
            name, tags = declaration.name, declaration.tags
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
        return ResourceCatalog(tuple(replacements.get(r.tag, r) for r in resources.root))

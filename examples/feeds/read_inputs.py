"""Read CSV evidence through an explicitly registered feed plugin.

Overall flow: register the CSV plugin, load its instance configuration from a
FeedDocument, construct runtime feeds, then refresh an existing ResourceDocument.
The registry describes available code; the document describes which instances a
case uses. Neither registration nor document loading opens the CSV file.

The example exports an UNSOLVED workspace. Acquiring values, choosing parameters,
applying them and solving are separate operations. No numerical solver is needed.

Run from the repository root:
    .venv/bin/python examples/feeds/read_inputs.py [output-folder]

The default output folder is /tmp/multifidelity-feed-example. Open workspace.json
in the viewer to inspect the configured plugin and refreshed resource values.
"""
import csv
from pathlib import Path
import sys

from pydantic import BaseModel

from multifidelity.model_language import (
    FeedRegistry, ResourceDocument, FeedDocument, build_model,
    export_workspace, select_parameters,
)

HERE = Path(__file__).parent


# 1. Describe the feed's settings, independently of its execution code.
# BaseModel is Pydantic's typed model: it validates loaded settings and provides
# JSON serialization. Each feed can define whichever configuration it needs.
class CSVConfig(BaseModel):
    """Which file to read and which columns identify records and their values.

    The defaults match inputs.csv, whose header is `tag,value`. A different CSV
    layout can use the same feed with different configuration. Runtime
    resources such as open files or database clients would stay outside config.
    """

    path: str
    tag_column: str = "tag"
    value_column: str = "value"


# 2. Implement three methods, without inheriting a framework base class:
# get_config() exposes settings, get_tags() discovers available records, and
# read(tags) supplies their values in bulk.
class CSVFeed:
    """Adapt a CSV file to the feed tag-to-value interface."""

    def __init__(self, config: CSVConfig):
        self.config = config

    def get_config(self) -> CSVConfig:
        # The runtime collection serializes this model for the document and viewer.
        # Asking for configuration does not open the CSV or acquire any data.
        return self.config

    def get_tags(self):
        # Discover the available tags from the file rather than duplicating a
        # fixed list at registration. This runs again for each collection read,
        # so additions/removals in the CSV are reflected in the next request.
        with Path(self.config.path).open(newline="", encoding="utf-8") as file:
            return tuple(row[self.config.tag_column] for row in csv.DictReader(file))

    def read(self, tags):
        # Read the file once for the whole batch, rather than reopening it for
        # each measurement. A SQL/API feed could make a bulk query here.
        with Path(self.config.path).open(newline="", encoding="utf-8") as file:
            rows = {row[self.config.tag_column]: float(row[self.config.value_column])
                    for row in csv.DictReader(file)}

        # Return exactly the requested record tags. These are the same tags used
        # in the resource document; no additional identifier or binding is needed.
        # Missing rows raise an error; we never silently reuse a saved value.
        # The CSV values must already be in their resource records' units.
        return {tag: rows[tag] for tag in tags}


def main(output: Path):
    output.mkdir(parents=True, exist_ok=True)

    # 3. Make a trusted plugin available. The registry stores the class, not a
    # configured CSVFeed. It infers CSVConfig from get_config()'s return type.
    # A second workspace can reuse this plugin with entirely different settings.
    registry = FeedRegistry()
    registry.register("csv", CSVFeed)

    # 4. Declare one configured instance. provider_type selects a registered
    # plugin name; config is ordinary JSON validated as CSVConfig during loading.
    # Tags are not repeated here: the configured CSVFeed discovers them itself.
    document = FeedDocument(feeds=[{
        "name": "plant_csv", "provider_type": "csv",
        "config": CSVConfig(path=str(HERE / "inputs.csv")).model_dump(mode="json"),
    }])
    document.write_json(output / "feeds.json")
    saved = FeedDocument.load_json(output / "feeds.json")

    # create_feeds() checks every plugin name and config before constructing any
    # feed. It returns a FeedCollection, which owns the runtime instances and
    # performs discovery and bulk reads. Loading the document alone runs no code.
    feeds = registry.create_feeds(saved)

    # 5. Acquire fresh evidence while preserving the resources layer.
    # ResourceDocument holds the record metadata and saved values. Its `tag`
    # identifies evidence; `variable_path` says which model variable it describes.
    # We reuse the valve example's resources, which includes static parameters
    # and alternative observations as well as the two connected measurements.
    resources = ResourceDocument.load_json(HERE.parent / "parameters/resources.json")

    # read() discovers current tags, then calls the feed once with both tags,
    # validates its response, and returns a new catalog. The original table and its saved values are intact.
    # Only values change: units, paths, uncertainty and trust stay with records.
    fresh = feeds.read(resources)

    # 6. Use the refreshed resources with the existing model workflow.
    # build_model chooses the valve's isenthalpic equation formulation.
    # select_parameters decides which evidence can specify that formulation;
    # acquiring a measurement does not automatically fix a model variable.
    model = build_model("valve", {"formulation": "isenthalpic"})
    selection = select_parameters(model, fresh)

    # 7. Bundle the case so its data and connections can be inspected together.
    # A workspace contains selected formulation choices, resources and a numerical
    # snapshot, with the feed document included here as optional metadata.
    # We save the selection for inspection but do NOT apply it or solve. A real
    # solve would check selection.complete, apply selection.parameters using
    # apply_parameters(), and then call the numerical solver before exporting
    # results with the actual solve status. The default here is "not_solved".
    export_workspace(model, fresh, feeds=feeds.get_document(),
                     parameters=selection.parameters).write_json(output / "workspace.json")

    print(f"Read {fresh.get('inlet_flow').value} kg/s and {fresh.get('pressure_measurement').value} kPa")
    print(f"Feed document and unsolved workspace: {output}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/multifidelity-feed-example"))

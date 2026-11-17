"""Get external values into a model without coupling the model to a CSV file.

Overall flow
------------
An resources catalog already describes the evidence available to a model:
record tags, model variable paths, units, uncertainty, trust, and saved values.
A feed supplies fresh values for some of those existing record tags. The
registry routes the requests and returns a new resources catalog, keeping
all of its metadata and any static records intact.

This example uses a CSV feed to refresh inlet flow and pressure for a valve:

    inputs.csv -> CSVFeed.read(tags) -> fresh ResourceCatalog
                                                |
                                     parameters selection
                                                |
                                       workspace.json

The feed has a typed configuration that can also be saved as ordinary JSON.
We export it, reload it, and explicitly reconstruct the feed to show how
settings edited in the viewer can be used by a Python application. Loading JSON
alone never imports or runs connector code.

Finally, we select parameters and export an UNSOLVED workspace. Acquisition
provides evidence; selecting that evidence, applying it, and solving the model
are separate operations. No numerical solver or external service is needed here.

Run from the repository root:
    .venv/bin/python examples/feeds/read_inputs.py

The example prints the refreshed values and writes feeds.json and
workspace.json to /tmp/multifidelity-feed-example. To choose another folder:
    .venv/bin/python examples/feeds/read_inputs.py /tmp/my-feed-example

Open workspace.json in the model viewer, then choose Feeds to inspect the
configuration and supplied records. Resource shows the refreshed values;
Results correctly reports that the model has not been solved.
"""
import csv
from pathlib import Path
import sys

from pydantic import BaseModel

from multifidelity.model_language import (
    FeedRegistry, ResourceCatalog, FeedCatalog, build_model,
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
    """Adapt a CSV file to the registry's record-tag-to-value interface."""

    def __init__(self, config: CSVConfig):
        self.config = config

    def get_config(self) -> CSVConfig:
        # The registry serializes this model for the catalogue and the viewer.
        # Asking for configuration does not open the CSV or acquire any data.
        return self.config

    def get_tags(self):
        # Discover the available tags from the file rather than duplicating a
        # fixed list at registration. This runs again for each registry read,
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
        # in the resources catalog; no additional identifier or binding is needed.
        # Missing rows raise an error; we never silently reuse a saved value.
        # The CSV values must already be in their resource records' units.
        return {tag: rows[tag] for tag in tags}


def main(output: Path):
    output.mkdir(parents=True, exist_ok=True)

    # 3. Register the feed. It owns its available tags through get_tags().
    # FeedRegistry is the router between resources tags and Python feeds.
    # "plant_csv" names the feed for inspection; it is not a measurement tag.
    # Each record tag can belong to only one feed. Records not registered
    # with a feed keep their static resources values.
    config = CSVConfig(path=str(HERE / "inputs.csv"))
    feed = CSVFeed(config)
    data = FeedRegistry()
    data.register_feed("plant_csv", feed)

    # 4. Export and reload the connection settings, without fetching values.
    # describe() returns a FeedCatalog: portable declarations containing
    # feed names, provider types, supplied tags and JSON configuration.
    # The viewer can display/edit this catalogue without running Python.
    data.describe().write_json(output / "feeds.json")
    saved = FeedCatalog.load_json(output / "feeds.json").root[0]

    # This round trip is optional in a normal run; data is already ready to use.
    # We include it to show the application boundary: the application chooses a
    # trusted feed class and validates the saved JSON with its config model.
    # The catalogue's provider_type is descriptive, not an import command.
    restored_config = CSVConfig.model_validate(saved.config)
    restored = FeedRegistry()
    # Saved tags describe the previous discovery; the feed discovers its
    # current tags again instead of using that list as a fixed assignment.
    restored.register_feed(saved.name, CSVFeed(restored_config))

    # 5. Acquire fresh evidence while preserving the resources layer.
    # ResourceCatalog holds the record metadata and saved values. Its `tag`
    # identifies evidence; `variable_path` says which model variable it describes.
    # We reuse the valve example's resources, which includes static parameters
    # and alternative observations as well as the two connected measurements.
    resources = ResourceCatalog.load_json(HERE.parent / "parameters/resources.json")

    # read() discovers current tags, then calls the feed once with both tags,
    # validates its response, and
    # returns a NEW catalog. The original table and its saved values are intact.
    # Only values change: units, paths, uncertainty and trust stay with records.
    fresh = restored.read(resources)

    # 6. Use the refreshed resources with the existing model workflow.
    # build_model chooses the valve's isenthalpic equation formulation.
    # select_parameters decides which evidence can specify that formulation;
    # acquiring a measurement does not automatically fix a model variable.
    model = build_model("valve", {"formulation": "isenthalpic"})
    selection = select_parameters(model, fresh)

    # 7. Bundle the case so its data and connections can be inspected together.
    # A workspace contains selected formulation choices, resources and a numerical
    # snapshot, with the feed catalogue included here as optional metadata.
    # We save the selection for inspection but do NOT apply it or solve. A real
    # solve would check selection.complete, apply selection.parameters using
    # apply_parameters(), and then call the numerical solver before exporting
    # results with the actual solve status. The default here is "not_solved".
    export_workspace(model, fresh, feeds=restored.describe(),
                     parameters=selection.parameters).write_json(output / "workspace.json")

    print(f"Read {fresh.get('inlet_flow').value} kg/s and {fresh.get('pressure_measurement').value} kPa")
    print(f"Catalogue and unsolved workspace: {output}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/multifidelity-feed-example"))

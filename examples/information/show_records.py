"""Map alternative information records to a final grid without fixing values."""

from pathlib import Path

from pyomo.environ import TransformationFactory

from multifidelity.model_language import InformationDocument, build_model

HERE = Path(__file__).parent
model = build_model(
    "tank", {"model": "tank", "relationship": "mixed"},
    mode="dynamic", domain_values={"time": [0, 60]},
)
TransformationFactory("dae.finite_difference").apply_to(
    model, wrt=model.fs.time, nfe=2, scheme="BACKWARD",
)
table = InformationDocument.load_json(HERE / "records.json")
for record in table.candidates("inlet.temperature"):
    values = record.values_for(model.fs.root.structs.inlet.temperature)
    print(f"{record.id} ({record.type}): {values} [{record.unit}]")

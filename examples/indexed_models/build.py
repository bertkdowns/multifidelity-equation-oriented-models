"""Build indexed algebraic equations; no initialization or solver required."""

from pathlib import Path

from multifidelity.model_language import Library, build_model, required_inputs

HERE = Path(__file__).parent
library = Library(HERE / "models")
implementation = HERE / "implementation.json"
model = build_model(
    "pipe", implementation, library=library,
    domain_values={"time": [0, 10, 30]},
)
model.fs.root.pprint()
for path, variable in required_inputs("pipe", implementation, library=library).items():
    print(f"{path}: {variable.dimensions} [{variable.unit}]")

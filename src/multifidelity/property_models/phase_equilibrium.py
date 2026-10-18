"""Phase-capable PH packages for the SGHP refrigerant and steam circuits.

IDAES uses one process-wide Helmholtz data directory. Merge its installed data
with the bundled n-butane EOS in a temporary directory, leaving installations
unchanged and preserving the other registered fluids.
"""

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from idaes.models.properties.general_helmholtz import (
    AmountBasis,
    HelmholtzParameterBlock,
    PhaseType,
    StateVars,
)
from idaes.models.properties.general_helmholtz.components.parameters import (
    get_parameter_path,
    set_parameter_path,
)

_parameter_directory = None


def phase_parameters(component: str):
    global _parameter_directory
    if _parameter_directory is None:
        original = Path(get_parameter_path())
        _parameter_directory = TemporaryDirectory(prefix="multifidelity-eos-")
        merged = Path(_parameter_directory.name)
        for source in original.iterdir():
            if source.is_file():
                shutil.copy2(source, merged / source.name)
        for source in (Path(__file__).parent / "data").iterdir():
            if source.suffix in {".json", ".nl"}:
                shutil.copy2(source, merged / source.name)
        set_parameter_path(str(merged))
    return HelmholtzParameterBlock(
        pure_component=component,
        phase_presentation=PhaseType.MIX,
        state_vars=StateVars.PH,
        amount_basis=AmountBasis.MASS,
    )

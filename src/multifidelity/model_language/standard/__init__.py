"""Optional symbolic symbolic providers; registration never constructs native blocks."""

from ..resolution import BlockRegistry
from .compressor_map import build_compressor_map
from .humid_air import build_humid_air
from .thermo import build_helmholtz_ph, scale_helmholtz_ph
from .lmtd import build_lmtd
from .phase_mixture import build_phase_mixture


def register_standard_providers(registry: BlockRegistry) -> None:
    """Register the bundled symbolic providers on an existing registry.

    Optional modelling dependencies and artifacts load only when a selected
    formulation calls a provider. Duplicate names follow BlockRegistry's usual error.
    """
    registry.register_provider("standard.helmholtz_ph", build_helmholtz_ph,
                              scaler=scale_helmholtz_ph)
    registry.register_provider("standard.lmtd", build_lmtd)
    registry.register_provider("standard.phase_mixture", build_phase_mixture)
    registry.register_provider("standard.humid_air", build_humid_air)
    registry.register_provider("standard.en12900_map", build_compressor_map)

"""Optional symbolic providers; registration never constructs native models."""

from ..resolution import Library
from .compressor_map import build_compressor_map
from .humid_air import build_humid_air
from .thermo import build_helmholtz_ph


def register_standard_providers(library: Library) -> None:
    """Register the bundled providers on an existing library.

    Optional modelling dependencies and artifacts load only when a selected
    relationship calls a provider. Duplicate names follow Library's usual error.
    """
    library.register_provider("standard.helmholtz_ph", build_helmholtz_ph)
    library.register_provider("standard.humid_air", build_humid_air)
    library.register_provider("standard.en12900_map", build_compressor_map)

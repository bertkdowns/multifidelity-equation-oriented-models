"""Ahuora's milk thermodynamics with pressure–enthalpy public state variables."""

from copy import deepcopy

from ahuora_property_packages.milk.milk_modular import milk_configuration
from ahuora_property_packages.modular.modular_extended import (
    GenericExtendedParameterBlock,
)
from idaes.models.properties.modular_properties.state_definitions import FPhx
from pyomo.environ import units as u


def milk_parameters():
    """Keep the published milk equations, replacing only FTPx with FPhx."""
    config = deepcopy(milk_configuration)
    config["state_definition"] = FPhx
    config["state_bounds"]["enth_mol"] = (0, 15000, 100000, u.J / u.mol)
    return GenericExtendedParameterBlock(**config)

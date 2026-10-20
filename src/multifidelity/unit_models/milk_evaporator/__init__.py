"""Milk evaporation with aggregate and explicit MVR representations."""

from .aggregate import AggregateMilkEvaporator
from .detailed import DetailedMilkEvaporator
from .model import MilkEvaporator

__all__ = ["MilkEvaporator", "AggregateMilkEvaporator", "DetailedMilkEvaporator"]

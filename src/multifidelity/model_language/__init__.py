"""Load declarative model definitions and build explicitly selected IDAES structures."""

from .builder import Library, build_model

__all__ = ["Library", "build_model"]

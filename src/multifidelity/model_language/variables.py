"""Root-relative public lookup for variables in a model-language instance."""


def get_variable(model, variable_path: str):
    """Return a live scalar or indexed Pyomo variable family by occurrence path.

    For indexed families, select entries on the returned object, e.g. [t].
    The registry follows model cloning and the current discretized grid.
    """
    registry = getattr(model, "_model_language_variables", None)
    if registry is None:
        raise ValueError("Model must be constructed by model_language.build_model")
    try:
        return registry[variable_path]
    except KeyError:
        raise ValueError(f"Unknown model variable {variable_path!r}") from None

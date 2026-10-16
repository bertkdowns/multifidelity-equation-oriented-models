import pytest

from idaes.core.solvers import get_solver


@pytest.fixture
def solver():
    solver = get_solver("ipopt", options={"tol": 1e-8, "max_iter": 500})
    if not solver.available(False):
        pytest.skip("IPOPT is required for numerical integration tests")
    return solver

"""
.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de>
"""

import numpy as np
import pytest

from pde import PDE, DiffusionPDE, grids
from pde.fields import ScalarField, VectorField
from pde.pdes.base import PDEBase
from pde.tools import mpi
from pde.tools.numba import jit


@pytest.mark.multiprocessing
@pytest.mark.parametrize("dim", [1, 2, 3])
@pytest.mark.parametrize("backend", ["numpy", "numba"])
def test_pde_complex_bcs_mpi(dim, backend, rng):
    """Test PDE with complex BCs using multiprocessing."""
    eq = DiffusionPDE()
    grid = grids.UnitGrid([8] * dim)
    field = ScalarField.random_normal(grid, rng=rng).smooth(1)

    args = {
        "state": field,
        "t_range": 1,
        "dt": 0.01,
        "tracker": None,
    }
    res = eq.solve(backend=backend, solver="explicit_mpi", **args)

    if mpi.is_main:
        res_exp = eq.solve(backend="numpy", solver="explicit", **args)
        res_exp.assert_field_compatible(res)
        np.testing.assert_allclose(res_exp.data, res.data)
    else:
        assert res is None


@pytest.mark.multiprocessing
def test_pde_vector_mpi(rng):
    """Test PDE with a single vector field using multiprocessing."""
    eq = PDE({"u": "vector_laplace(u) + exp(-t)"})
    assert eq.explicit_time_dependence
    assert not eq.complex_valued
    grid = grids.UnitGrid([8, 8])
    field = VectorField.random_normal(grid, rng=rng).smooth(1)

    args = {
        "state": field,
        "t_range": 1,
        "dt": 0.01,
        "tracker": None,
    }
    res_a = eq.solve(backend="numpy", solver="explicit_mpi", **args)
    res_b = eq.solve(backend="numba", solver="explicit_mpi", **args)

    if mpi.is_main:
        res_a.assert_field_compatible(res_b)
        np.testing.assert_allclose(res_a.data, res_b.data)


@pytest.mark.multiprocessing
def test_pde_complex_mpi(rng):
    """Test complex valued PDE."""
    eq = PDE({"p": "I * laplace(p)"})
    assert not eq.explicit_time_dependence
    assert eq.complex_valued

    field = ScalarField.random_uniform(grids.UnitGrid([4]), rng=rng)
    assert not field.is_complex

    args = {
        "state": field,
        "t_range": 1.01,
        "dt": 0.1,
        "tracker": None,
        "ret_info": True,
    }
    res1, info1 = eq.solve(backend="numpy", solver="explicit_mpi", **args)
    res2, info2 = eq.solve(backend="numba", solver="explicit_mpi", **args)

    if mpi.is_main:
        # check results in the main process
        expect, _ = eq.solve(backend="numpy", solver="explicit", **args)

        assert res1.is_complex
        np.testing.assert_allclose(res1.data, expect.data)
        assert info1["solver"]["steps"] == 11

        assert res2.is_complex
        np.testing.assert_allclose(res2.data, expect.data)
        assert info2["solver"]["steps"] == 11
    else:
        assert res1 is None
        assert res2 is None


@pytest.mark.multiprocessing
@pytest.mark.parametrize("backend", ["numpy", "numba"])
def test_pde_const_mpi(backend):
    """Test PDE with a field constant using multiprocessing."""
    grid = grids.UnitGrid([8])
    eq = PDE({"u": "k"}, consts={"k": ScalarField.from_expression(grid, "x")})

    args = {"state": ScalarField(grid), "t_range": 1, "dt": 0.01, "tracker": None}
    res_a = eq.solve(backend="numpy", solver="explicit", **args)
    res_b = eq.solve(backend=backend, solver="explicit_mpi", **args)

    if mpi.is_main:
        res_a.assert_field_compatible(res_b)
        np.testing.assert_allclose(res_a.data, res_b.data)
    else:
        assert res_b is None


@pytest.mark.multiprocessing
@pytest.mark.parametrize("backend", ["numpy", "numba"])
def test_pde_const_mpi_class(backend):
    """Test PDE with a field constant using multiprocessing."""
    grid = grids.UnitGrid([8])

    class ExplicitFieldPDE(PDEBase):
        def evolution_rate(self, state, t):
            return ScalarField(state.grid, state.grid.axes_coords[0])

        def _make_pde_rhs_numba(self, state):
            x = state.grid.axes_coords[0]

            @jit
            def pde_rhs(state_data, t):
                return x

            return pde_rhs

    eq = ExplicitFieldPDE()

    args = {"state": ScalarField(grid), "t_range": 1, "dt": 0.01, "tracker": None}
    res_a = eq.solve(backend="numpy", solver="explicit", **args)
    res_b = eq.solve(backend=backend, solver="explicit_mpi", **args)

    if mpi.is_main:
        res_a.assert_field_compatible(res_b)
        np.testing.assert_allclose(res_a.data, res_b.data)
    else:
        assert res_b is None

"""
.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de>
"""

import itertools
from copy import copy, deepcopy

import numpy as np
import pytest

from pde import grids
from pde.grids.base import (
    GridBase,
    OperatorInfo,
    discretize_interval,
    registered_operators,
)
from pde.tools.misc import module_available


def iter_grids():
    """Generator providing some test grids."""
    for periodic in [True, False]:
        yield grids.UnitGrid([3], periodic=periodic)
        yield grids.UnitGrid([3, 3, 3], periodic=periodic)
        yield grids.CartesianGrid([[-1, 2], [0, 3]], [5, 7], periodic=periodic)
        yield grids.CylindricalSymGrid(3, [-1, 2], [7, 8], periodic_z=periodic)
    yield grids.PolarSymGrid(3, 4)
    yield grids.SphericalSymGrid(3, 4)


@pytest.mark.parametrize("grid", iter_grids())
def test_basic_grid_properties(grid):
    """Test basic grid properties."""
    with pytest.raises(AttributeError):
        grid.periodic = True
    with pytest.raises(AttributeError):
        grid.shape = 12


def test_discretize(rng):
    """Test the discretize function."""
    x_min = rng.uniform(0, 1)
    x_max = rng.uniform(2, 3)
    num = rng.integers(5, 8)
    x, dx = discretize_interval(x_min, x_max, num)
    assert dx == pytest.approx((x_max - x_min) / num)
    x_expect = np.linspace(x_min + dx / 2, x_max - dx / 2, num)
    np.testing.assert_allclose(x, x_expect)


@pytest.mark.parametrize("grid", iter_grids())
def test_serialization(grid):
    """Test whether grid can be serialized and copied."""
    g = GridBase.from_state(grid.state_serialized)
    assert grid == g
    assert grid._cache_hash() == g._cache_hash()

    for g in (grid.copy(), copy(grid), deepcopy(grid)):
        assert grid == g
        assert grid is not g


def test_iter_mirror_points():
    """Test iterating mirror points in grids."""
    grid_cart = grids.UnitGrid([2, 2], periodic=[True, False])
    grid_cyl = grids.CylindricalSymGrid(2, (0, 2), (2, 2), periodic_z=False)
    grid_sph = grids.SphericalSymGrid(2, 2)
    assert grid_cart._cache_hash() != grid_cyl._cache_hash() != grid_sph._cache_hash()

    for with_, only_periodic in itertools.product([False, True], repeat=2):
        num_expect = 2 if only_periodic else 8
        num_expect += 1 if with_ else 0
        ps = grid_cart.iter_mirror_points([1, 1], with_, only_periodic)
        assert len(list(ps)) == num_expect

        num_expect = 0 if only_periodic else 2
        num_expect += 1 if with_ else 0
        ps = grid_cyl.iter_mirror_points([0, 0, 1], with_, only_periodic)
        assert len(list(ps)) == num_expect

        num_expect = 1 if with_ else 0
        ps = grid_sph.iter_mirror_points([0, 0, 0], with_, only_periodic)
        assert len(list(ps)) == num_expect


@pytest.mark.parametrize("grid", iter_grids())
def test_coordinate_conversion(grid, rng):
    """Test the conversion between cells and points."""
    p_empty = np.zeros((0, grid.dim))
    c_empty = np.zeros((0, grid.num_axes))

    p = grid.get_random_point(coords="grid", rng=rng)
    for coords in ["cartesian", "cell", "grid"]:
        # test empty conversion
        assert grid.transform(p_empty, "cartesian", coords).size == 0
        assert grid.transform(c_empty, "grid", coords).size == 0
        assert grid.transform(c_empty, "cell", coords).size == 0

        # test full conversion
        p1 = grid.transform(p, "grid", coords)
        for target in ["cartesian", "grid"]:
            p2 = grid.transform(p1, coords, target)
            p3 = grid.transform(p2, target, coords)
            np.testing.assert_allclose(p1, p3, err_msg=f"{coords} -> {target}")


@pytest.mark.parametrize("grid", iter_grids())
def test_integration_serial(grid, rng):
    """Test integration of fields."""
    arr = rng.normal(size=grid.shape)
    res = grid.make_integrator()(arr)
    assert np.isscalar(res)
    assert res == pytest.approx(grid.integrate(arr))
    if grid.num_axes == 1:
        assert res == pytest.approx(grid.integrate(arr, axes=0))
    else:
        assert res == pytest.approx(grid.integrate(arr, axes=range(grid.num_axes)))


def test_grid_plotting():
    """Test plotting of grids."""
    grids.UnitGrid([4]).plot()
    grids.UnitGrid([4, 4]).plot()

    with pytest.raises(NotImplementedError):
        grids.UnitGrid([4, 4, 4]).plot()

    grids.PolarSymGrid(4, 8).plot()
    grids.PolarSymGrid((2, 4), 8).plot()


@pytest.mark.parametrize("grid", iter_grids())
def test_operators(grid):
    """Test operator mechanism."""

    def make_op(state):
        return lambda state: state

    assert "laplace" in grid.operators
    with pytest.raises(ValueError):
        grid.make_operator("not_existent", "auto_periodic_neumann")
    grid.register_operator("noop", make_op)
    assert "noop" in grid.operators
    del grid._operators["noop"]  # reset original state

    # test all instance operators
    for op in grid.operators:
        assert isinstance(grid._get_operator_info(op), OperatorInfo)


def test_cartesian_operator_infos():
    """Test special case of cartesian operators."""
    assert "d_dx" not in grids.UnitGrid.operators
    assert "d_dx" in grids.UnitGrid([2]).operators
    assert "d_dy" not in grids.UnitGrid([2]).operators


def test_registered_operators():
    """Test the registered_operators function."""
    for grid_name, ops in registered_operators().items():
        grid_class_ops = getattr(grids, grid_name).operators
        assert all(op in grid_class_ops for op in ops)


@pytest.mark.parametrize("grid", iter_grids())
def test_cell_volumes(grid):
    """Test calculation of cell volumes."""
    d2 = grid.discretization / 2
    x_low = grid._coords_full(grid.cell_coords - d2, value="min")
    x_high = grid._coords_full(grid.cell_coords + d2, value="max")
    cell_vols = grid.c.cell_volume(x_low, x_high)
    np.testing.assert_allclose(cell_vols, grid.cell_volumes)


@pytest.mark.skipif(
    not module_available("modelrunner"), reason="requires `py-modelrunner`"
)
@pytest.mark.parametrize("grid", iter_grids())
def test_grid_modelrunner_storage(grid, tmp_path):
    """Test storing grids in modelrunner storages."""
    from modelrunner import open_storage

    path = tmp_path / "grid.json"

    with open_storage(path, mode="truncate") as storage:
        storage["grid"] = grid

    with open_storage(path, mode="read") as storage:
        assert storage["grid"] == grid


@pytest.mark.parametrize("grid", iter_grids())
def test_vector_to_cartesian(grid, rng):
    """Test vector_to_cartesian function of grids."""
    point = grid.get_random_point(coords="grid", rng=rng)
    point = grid._coords_full(point)

    if grid.dim == 1:
        return

    elif grid.dim == 2:
        vec1 = grid._vector_to_cartesian(point, [1, 0])
        vec2 = grid._vector_to_cartesian(point, [0, 1])
        u = [vec1, vec2]

        for i in range(2):
            for j in range(2):
                ui_uj = np.einsum("i...,i...->...", u[i], u[j])
                assert ui_uj == pytest.approx(float(i == j))

    elif grid.dim == 3:
        vec1 = grid._vector_to_cartesian(point, [1, 0, 0])
        vec2 = grid._vector_to_cartesian(point, [0, 1, 0])
        vec3 = grid._vector_to_cartesian(point, [0, 0, 1])
        u = [vec1, vec2, vec3]

        for i in range(3):
            for j in range(3):
                ui_uj = np.einsum("i...,i...->...", u[i], u[j])
                assert ui_uj == pytest.approx(float(i == j))

    else:
        raise NotImplementedError

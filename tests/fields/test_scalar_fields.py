"""
.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de>
"""

import gc

import numpy as np
import pytest

from fixtures.fields import get_cartesian_grid, iter_grids
from pde.fields.base import FieldBase
from pde.fields.scalar import ScalarField
from pde.grids import CartesianGrid, PolarSymGrid, UnitGrid, boundaries
from pde.grids._mesh import GridMesh
from pde.tools import mpi
from pde.tools.misc import module_available


def test_interpolation_singular():
    """Test interpolation on singular dimensions."""
    grid = UnitGrid([1])
    field = ScalarField(grid, data=3)

    # test constant boundary conditions
    x = np.linspace(0, 1, 7).reshape((7, 1))
    y = field.interpolate(x)
    np.testing.assert_allclose(y, 3)

    # # test boundary interpolation
    for upper in [True, False]:
        val = field.get_boundary_values(axis=0, upper=upper, bc={"x": {"value": 1}})
        assert val == pytest.approx(1)

        b_field = field.get_boundary_field((0, upper), bc={"x": {"value": 1}})
        assert b_field.data == pytest.approx(1)


def test_interpolation_edge():
    """Test interpolation close to the boundary."""
    grid = UnitGrid([2])
    field = ScalarField(grid, data=[1, 2])

    # test constant boundary conditions
    ps = np.array([0.0, 1.0, 2.0])
    y = field.interpolate(ps.reshape(3, 1))
    np.testing.assert_allclose(y, [1.0, 1.5, 2.0])


@pytest.mark.parametrize("grid", iter_grids())
def test_simple_shapes(grid, rng):
    """Test simple scalar fields."""
    pf = ScalarField.random_uniform(grid, rng=rng)
    np.testing.assert_equal(pf.data.shape, grid.shape)
    pf_lap = pf.laplace("auto_periodic_neumann")
    np.testing.assert_equal(pf_lap.data.shape, grid.shape)
    assert isinstance(pf.integral, float)

    pf_c = pf.copy()
    np.testing.assert_allclose(pf.data, pf_c.data)
    assert pf.grid == pf_c.grid
    assert pf.data is not pf_c.data

    if grid.num_axes == 1:
        ref = pf.plot(ylabel="My plot", ylim=(0, 1))
    else:
        ref = pf.plot(transpose=True, vmin=0, vmax=1)
    pf._update_plot(ref)


def test_scalars(rng):
    """Test some scalar fields."""
    grid = CartesianGrid([[0.1, 0.3], [-2, 3]], [3, 4])
    s1 = ScalarField(grid, np.full(grid.shape, 1))
    s2 = ScalarField(grid, np.full(grid.shape, 2))
    assert s1.average == pytest.approx(1)
    assert s1.magnitude == pytest.approx(1)

    s3 = s1 + s2
    assert s3.grid == grid
    np.testing.assert_allclose(s3.data, 3)
    s1 += s2
    np.testing.assert_allclose(s1.data, 3)

    s2 = FieldBase.from_state(s1.attributes, data=s1.data)
    assert s1 == s2
    assert s1.grid is s2.grid

    attrs = ScalarField.unserialize_attributes(s1.attributes_serialized)
    s2 = FieldBase.from_state(attrs, data=s1.data)
    assert s1 == s2
    assert s1.grid is not s2.grid

    # test options for plotting images
    s1.plot(transpose=True, colorbar=True)

    s3 = ScalarField(grid, s1)
    assert s1 is not s3
    assert s1 == s3
    assert s1.grid is s3.grid

    # multiplication with numpy arrays
    arr = rng.normal(size=grid.shape)
    np.testing.assert_allclose((arr * s1).data, (s1 * arr).data)


def test_laplacian(rng):
    """Test the gradient operator."""
    grid = CartesianGrid([[0, 2 * np.pi], [0, 2 * np.pi]], [16, 16], periodic=True)
    s = ScalarField.random_harmonic(grid, axis_combination=np.add, modes=1, rng=rng)

    s_lap = s.laplace("auto_periodic_neumann")
    assert s_lap.data.shape == (16, 16)
    np.testing.assert_allclose(s_lap.data, -s.data, rtol=0.1, atol=0.1)

    s.laplace("auto_periodic_neumann", out=s_lap)
    assert s_lap.data.shape == (16, 16)
    np.testing.assert_allclose(s_lap.data, -s.data, rtol=0.1, atol=0.1)


def test_gradient():
    """Test the gradient operator."""
    grid = CartesianGrid([[0, 2 * np.pi], [0, 2 * np.pi]], [16, 16], periodic=True)
    x, y = grid.cell_coords[..., 0], grid.cell_coords[..., 1]
    data = np.cos(x) + np.sin(y)

    s = ScalarField(grid, data)
    v = s.gradient("auto_periodic_neumann")
    assert v.data.shape == (2, 16, 16)
    np.testing.assert_allclose(v.data[0], -np.sin(x), rtol=0.1, atol=0.1)
    np.testing.assert_allclose(v.data[1], np.cos(y), rtol=0.1, atol=0.1)

    s.gradient("auto_periodic_neumann", out=v)
    assert v.data.shape == (2, 16, 16)
    np.testing.assert_allclose(v.data[0], -np.sin(x), rtol=0.1, atol=0.1)
    np.testing.assert_allclose(v.data[1], np.cos(y), rtol=0.1, atol=0.1)


@pytest.mark.parametrize("grid", iter_grids())
def test_interpolation_to_grid(grid, rng):
    """Test whether data is interpolated correctly for different grids."""
    sf = ScalarField.random_uniform(grid, rng=rng)
    sf2 = sf.interpolate_to_grid(grid)
    np.testing.assert_allclose(sf.data, sf2.data, rtol=1e-6)


def test_interpolation_bcs():
    """Test interpolation of data involving boundary conditions."""
    grid = UnitGrid([3])
    f = ScalarField(grid, [1, 2, 3])
    res = f.interpolate(np.c_[-1:5], bc="extrapolate", fill=42)
    np.testing.assert_allclose(res, np.array([42.0, 0.5, 1.5, 2.5, 3.5, 42.0]))


@pytest.mark.parametrize("grid", iter_grids())
@pytest.mark.parametrize("compiled", [True, False])
def test_insert_scalar(grid, compiled, rng):
    """Test the `insert` method."""
    f = ScalarField(grid)
    a = rng.random()

    c = grid.get_random_point(coords="cell", rng=rng).astype(int)  # pick a random cell
    p = grid.transform(c + 0.5, "cell", "grid")  # point at cell center
    if compiled:
        insert = grid.make_inserter_compiled()
        insert(f.data, p, a)  # add material to cell center
    else:
        f.insert(p, a)  # add material to cell center
    assert f.data[tuple(c)] == pytest.approx(a / grid.cell_volumes[tuple(c)])

    f.insert(grid.get_random_point(coords="grid", rng=rng), a)
    assert f.integral == pytest.approx(2 * a)


def test_insert_1d(rng):
    """Test the `insert` method for 1d systems."""
    grid = UnitGrid([2], periodic=True)
    f = ScalarField(grid)
    g = f.copy()
    a = rng.random()
    for r in np.linspace(0, 3, 8).reshape(8, 1):
        f.data = g.data = 0
        f.insert(r, a)
        assert f.integral == pytest.approx(a)
        grid.make_inserter_compiled()(g.data, r, a)
        np.testing.assert_array_almost_equal(f.data, g.data)


def test_insert_polar(rng):
    """Test the `insert` method for polar systems."""
    grid = PolarSymGrid(3, 5)
    f = ScalarField(grid)
    g = f.copy()
    a = rng.random()
    for r in np.linspace(0, 3, 8).reshape(8, 1):
        f.data = g.data = 0
        f.insert(r, a)
        assert f.integral == pytest.approx(a)
        grid.make_inserter_compiled()(g.data, r, a)
        np.testing.assert_array_almost_equal(f.data, g.data)


def test_random_harmonic(rng):
    """Test whether random harmonic fields behave correctly."""
    grid = get_cartesian_grid(2)  # get random Cartesian grid
    x = ScalarField.random_harmonic(grid, modes=1, rng=rng)
    scaling = sum((2 * np.pi / L) ** 2 for L in grid.cuboid.size)
    y = -x.laplace("auto_periodic_neumann") / scaling
    np.testing.assert_allclose(x.data, y.data, rtol=1e-2, atol=1e-2)


def test_get_line_data(rng):
    """Test different extraction methods for line data."""
    grid = UnitGrid([16, 32])
    c = ScalarField.random_harmonic(grid, rng=rng)

    np.testing.assert_equal(
        c.get_line_data(extract="cut_0"), c.get_line_data(extract="cut_x")
    )
    np.testing.assert_equal(
        c.get_line_data(extract="cut_1"), c.get_line_data(extract="cut_y")
    )

    for extract in ["project_0", "project_1", "project_x", "project_y"]:
        data = c.get_line_data(extract=extract)["data_y"]
        np.testing.assert_allclose(data, 0, atol=1e-14)


def test_from_expression():
    """Test creating scalar field from expression."""
    grid = UnitGrid([1, 2])
    sf = ScalarField.from_expression(grid, "x * y", label="abc")
    assert sf.label == "abc"
    np.testing.assert_allclose(sf.data, [[0.25, 0.75]])

    def f(x, y):
        return x * y

    sf = ScalarField.from_expression(grid, "f(x, y)", user_funcs={"f": f})
    np.testing.assert_allclose(sf.data, [[0.25, 0.75]])

    sf = ScalarField.from_expression(grid, "c", consts={"c": [0.25, 0.75]})
    np.testing.assert_allclose(sf.data, [[0.25, 0.75]])

    sf = ScalarField.from_expression(grid, "cartesian[0] * cartesian[1]")
    np.testing.assert_allclose(sf.data, [[0.25, 0.75]])


def test_from_image(tmp_path, rng):
    from matplotlib.pyplot import imsave

    img_data = rng.uniform(size=(9, 8, 3))
    img_data_gray = img_data @ np.array([0.299, 0.587, 0.114])
    path = tmp_path / "test_from_image.png"
    imsave(path, img_data, vmin=0, vmax=1)
    sf = ScalarField.from_image(path)
    np.testing.assert_allclose(sf.data, img_data_gray.T[:, ::-1], atol=0.05)


def test_to_scalar(rng):
    """Test conversion to scalar field."""
    sf = ScalarField.random_uniform(UnitGrid([3, 3]), rng=rng)
    np.testing.assert_allclose(sf.to_scalar().data, sf.data)
    np.testing.assert_allclose(sf.to_scalar("norm_squared").data, sf.data**2)
    np.testing.assert_allclose(sf.to_scalar(lambda x: 2 * x).data, 2 * sf.data)

    sf = ScalarField.random_uniform(UnitGrid([3, 3]), 0, 1 + 1j, rng=rng)
    np.testing.assert_allclose(sf.to_scalar().data, np.abs(sf.data))
    np.testing.assert_allclose(sf.to_scalar("abs").data, sf.to_scalar("norm").data)
    np.testing.assert_allclose(sf.to_scalar("norm_squared").data, np.abs(sf.data) ** 2)
    np.testing.assert_allclose(sf.to_scalar(np.angle).data, np.angle(sf.data))

    with pytest.raises(ValueError):
        sf.to_scalar("nonsense")


@pytest.mark.parametrize("grid", (grid for grid in iter_grids() if grid.num_axes > 1))
@pytest.mark.parametrize("method", ["integral", "average"])
def test_projection(grid, method, rng):
    """Test scalar projection."""
    sf = ScalarField.random_uniform(grid, rng=rng)
    for ax in grid.axes:
        sp = sf.project(ax, method=method)
        assert sp.grid.dim < grid.dim
        assert sp.grid.num_axes == grid.num_axes - 1
        if method == "integral":
            assert sp.integral == pytest.approx(sf.integral)
        elif method == "average":
            assert sp.average == pytest.approx(sf.average)

    with pytest.raises(ValueError):
        sf.project(grid.axes[0], method="nonsense")


@pytest.mark.parametrize("grid", (grid for grid in iter_grids() if grid.num_axes > 1))
def test_slice(grid, rng):
    """Test scalar slicing."""
    sf = ScalarField(grid, 0.5)
    p = grid.get_random_point(coords="grid", rng=rng)
    for i in range(grid.num_axes):
        sf_slc = sf.slice({grid.axes[i]: p[i]})
        np.testing.assert_allclose(sf_slc.data, 0.5)
        assert sf_slc.grid.dim < grid.dim
        assert sf_slc.grid.num_axes == grid.num_axes - 1

    with pytest.raises(boundaries.DomainError):
        sf.slice({grid.axes[0]: -10})
    with pytest.raises(ValueError):
        sf.slice({"q": 0})


def test_slice_positions():
    """Test scalar slicing at standard positions."""
    grid = UnitGrid([3, 1])
    sf = ScalarField(grid, np.arange(3).reshape(3, 1))
    assert sf.slice({"x": "min"}).data == 0
    assert sf.slice({"x": "mid"}).data == 1
    assert sf.slice({"x": "max"}).data == 2

    with pytest.raises(ValueError):
        sf.slice({"x": "foo"})
    with pytest.raises(ValueError):
        sf.slice({"x": 0}, method="nonsense")


def test_interpolation_mutable():
    """Test interpolation on mutable fields."""
    grid = UnitGrid([2], periodic=True)
    field = ScalarField(grid)

    field.data = 1
    np.testing.assert_allclose(field.interpolate([0.5]), 1)
    field.data = 2
    np.testing.assert_allclose(field.interpolate([0.5]), 2)

    # test overwriting field values
    data = np.full_like(field._data_full, 3)
    intp = field.make_interpolator()
    np.testing.assert_allclose(intp(np.array([0.5]), data), 3)

    # test overwriting field values
    data = np.full_like(field.data, 4)
    intp = field.make_interpolator()
    np.testing.assert_allclose(intp(np.array([0.5]), data), 4)


def test_boundary_interpolation_1d():
    """Test boundary interpolation for 1d fields."""
    grid = UnitGrid([5])
    field = ScalarField(grid, np.arange(grid.shape[0]))

    # test boundary interpolation
    bndry_val = 0.25
    for bndry in grid._iter_boundaries():
        val = field.get_boundary_values(*bndry, bc={"value": bndry_val})
        np.testing.assert_allclose(val, bndry_val)

        b_field = field.get_boundary_field(bndry, bc={"value": bndry_val})
        np.testing.assert_allclose(b_field.data, bndry_val)

    b_field = field.get_boundary_field("right", bc={"value": bndry_val})
    np.testing.assert_allclose(b_field.data, bndry_val)


def test_boundary_interpolation_2d(rng):
    """Test boundary interpolation for 2d fields."""
    grid = CartesianGrid([[0.1, 0.3], [-2, 3]], [3, 3])
    field = ScalarField.random_normal(grid, rng=rng)

    # test boundary interpolation
    bndry_val = rng.normal(size=3)
    for bndry in grid._iter_boundaries():
        val = field.get_boundary_values(*bndry, bc={"value": bndry_val})
        np.testing.assert_allclose(val, bndry_val)

        b_field = field.get_boundary_field(bndry, bc={"value": bndry_val})
        np.testing.assert_allclose(b_field.data, bndry_val)

    b_field = field.get_boundary_field("left", bc={"value": bndry_val})
    np.testing.assert_allclose(b_field.data, bndry_val)


def test_numpy_ufuncs(rng):
    """Test numpy ufuncs."""
    grid = UnitGrid([2, 2])
    f1 = ScalarField.random_uniform(grid, 0.1, 0.9, rng=rng)

    f2 = np.sin(f1)
    np.testing.assert_allclose(f2.data, np.sin(f1.data))
    f2.data = 0
    np.sin(f1, out=f2)
    np.testing.assert_allclose(f2.data, np.sin(f1.data))

    np.testing.assert_allclose(np.add(f1, 2).data, f1.data + 2)

    with pytest.raises(TypeError):
        np.sum(f1, 1)


def test_plotting_1d(rng):
    """Test plotting of 1d scalar fields."""
    grid = UnitGrid([3])
    field = ScalarField.random_uniform(grid, 0.1, 0.9, rng=rng)

    ref = field.plot()
    field._update_plot(ref)


def test_plotting_2d(rng):
    """Test plotting of 2d scalar fields."""
    grid = UnitGrid([3, 3])
    field = ScalarField.random_uniform(grid, 0.1, 0.9, rng=rng)

    ref = field.plot()
    field._update_plot(ref)


@pytest.mark.skipif(not module_available("napari"), reason="requires `napari` module")
@pytest.mark.interactive
def test_interactive_plotting(rng):
    """Test the interactive plotting."""
    grid = UnitGrid([3, 3])
    field = ScalarField.random_uniform(grid, 0.1, 0.9, rng=rng)
    field.plot_interactive(viewer_args={"show": False, "close": True})

    grid = UnitGrid([3, 3, 3])
    field = ScalarField.random_uniform(grid, 0.1, 0.9, rng=rng)
    field.plot_interactive(viewer_args={"show": False, "close": True})


def test_complex_dtype():
    """Test the support of a complex data type."""
    grid = UnitGrid([2])
    f = ScalarField(grid, 1j)
    assert f.is_complex
    np.testing.assert_allclose(f.data, np.array([1j, 1j]))

    f = ScalarField(grid, 1)
    assert not f.is_complex
    with pytest.raises(TypeError):
        f += 1j

    f = f + 1j
    assert f.is_complex
    np.testing.assert_allclose(f.data, np.full((2,), 1 + 1j))
    assert f.integral == pytest.approx(2 + 2j)
    assert f.average == pytest.approx(1 + 1j)
    np.testing.assert_allclose(f.to_scalar("abs").data, np.full((2,), np.sqrt(2)))
    assert f.magnitude == pytest.approx(np.sqrt(2))


def test_complex_plotting():
    """Test plotting of complex fields."""
    for dim in (1, 2):
        f = ScalarField(UnitGrid([3] * dim), 1j)
        f.plot()


def test_complex_methods():
    """Test special methods for complex data type."""
    grid = UnitGrid([2, 2])
    f = ScalarField(grid, 1j)
    val = f.interpolate([1, 1])
    np.testing.assert_allclose(val, np.array([1j, 1j]))

    f = ScalarField(grid, 1 + 2j)
    np.testing.assert_allclose(f.project("x").data, np.full((2,), 2 + 4j))
    np.testing.assert_allclose(f.slice({"x": 1}).data, np.full((2,), 1 + 2j))


def test_complex_operators():
    """Test differential operators for complex data type."""
    f = ScalarField(UnitGrid([2, 2]), 1j)
    assert f.laplace("auto_periodic_neumann").magnitude == pytest.approx(0)


def test_interpolation_after_free(rng):
    """Test whether interpolation is possible when the original field is removed."""
    f = ScalarField.from_expression(UnitGrid([5]), "x")
    intp = f.make_interpolator()

    # delete original field
    del f
    gc.collect()

    # hope that this overwrites the memory
    ScalarField.random_uniform(UnitGrid([5]), rng=rng)

    assert intp(np.array([2.3])) == pytest.approx(2.3)


def test_corner_interpolation():
    """Test whether the field can also be interpolated up to the corner of the grid."""
    grid = UnitGrid([1, 1], periodic=False)
    field = ScalarField(grid)
    field.set_ghost_cells({"value": 1})

    assert field.interpolate(np.array([0.5, 0.5])) == pytest.approx(0.0)
    assert field.interpolate(np.array([0.0, 0.5])) == pytest.approx(0.0)
    assert field.interpolate(np.array([0.5, 0.0])) == pytest.approx(0.0)
    assert field.interpolate(np.array([0.0, 0.0])) == pytest.approx(0.0)


@pytest.mark.parametrize("grid", iter_grids())
def test_generic_derivatives(grid, rng):
    """Test generic derivatives operators."""
    sf = ScalarField.random_uniform(grid, rng=rng)
    sf_grad = sf.gradient("auto_periodic_neumann")
    sf_lap = ScalarField(grid)

    # iterate over all grid axes
    for axis_id, axis in enumerate(grid.axes):
        # test first derivatives
        sf_deriv = sf.apply_operator(f"d_d{axis}", bc="auto_periodic_neumann")
        assert isinstance(sf_deriv, ScalarField)
        np.testing.assert_allclose(sf_deriv.data, sf_grad.data[axis_id])

        # accumulate second derivatives for Laplacian
        sf_lap += sf.apply_operator(f"d2_d{axis}2", bc="auto_periodic_neumann")

    sf_laplace = sf.laplace("auto_periodic_neumann")
    if isinstance(grid, CartesianGrid):
        # Laplacian is the sum of second derivatives in Cartesian coordinates
        np.testing.assert_allclose(sf_lap.data, sf_laplace.data)
    else:
        # the two deviate in curvilinear coordinates
        assert not np.allclose(sf_lap.data, sf_laplace.data)


def test_piecewise_expressions():
    """Test special expressions for creating fields."""
    grid = CartesianGrid([[0, 4]], 32)
    field = ScalarField.from_expression(grid, "Piecewise((x**2, x>2), (1+x, x<=2))")
    x = grid.axes_coords[0]
    field_data = np.piecewise(x, [x > 2, x <= 2], [lambda x: x**2, lambda x: 1 + x])
    np.testing.assert_allclose(field.data, field_data)


def test_boundary_expressions_with_t():
    """Test special case of imposing time-dependent boundary conditions."""
    field = ScalarField(UnitGrid([3]), 0)
    res = field.laplace({"value_expression": "t"}, args={"t": 0})
    np.testing.assert_allclose(res.data, [0, 0, 0])
    res = field.laplace({"value_expression": "t"}, args={"t": 1})
    np.testing.assert_allclose(res.data, [2, 0, 2])


@pytest.mark.multiprocessing
@pytest.mark.parametrize("decomp", ["auto", (-1, 1), (1, -1)])
def test_field_split(decomp, rng):
    """Test the field splitting function in an MPI context."""
    grid = UnitGrid([4, 4])
    field = ScalarField.random_uniform(grid, rng=rng)

    # basic split
    subfield = field.split_mpi(decomposition=decomp)

    # recombination
    mesh = GridMesh.from_grid(grid, decomposition=decomp)
    field_data = mesh.combine_field_data_mpi(subfield.data)
    if mpi.is_main:
        np.testing.assert_allclose(field.data, field_data)
    else:
        assert field_data is None


def test_field_corner_interpolation_2d():
    """Test corner interpolation for a 2d field."""
    f = ScalarField(UnitGrid([1, 1]), 0)
    bc = {
        "x-": {"value": -1},
        "x+": {"value": 2},
        "y-": {"value": -2},
        "y+": {"value": 1},
    }
    f.set_ghost_cells(bc=bc, set_corners=True)
    expect = np.array([[-1.5, -2, 0], [-1, 0, 2], [0, 1, 1.5]]).T
    np.testing.assert_allclose(f._data_full, 2 * expect)


def test_field_corner_interpolation_3d():
    """Test corner interpolation for a 3d field."""
    f = ScalarField(UnitGrid([1, 1, 1]), 0)
    bcs = {}
    for ax in f.grid.axes:
        bcs[ax + "-"] = {"value": -3}
        bcs[ax + "+"] = {"value": 3}
    f.set_ghost_cells(bc=bcs, set_corners=True)
    expect = np.array(
        [
            [[-6, -6, -2], [-6, -6, 0], [-2, 0, 2]],
            [[-6, -6, 0], [-6, 0, 6], [0, 6, 6]],
            [[-2, 0, 2], [0, 6, 6], [2, 6, 6]],
        ]
    )
    np.testing.assert_allclose(f._data_full, expect)

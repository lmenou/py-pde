"""
.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de>
"""

import numpy as np
import pytest

from ...grids import CartesianGrid, UnitGrid
from ..base import FieldBase
from ..tensorial import Tensor2Field
from .test_generic import iter_grids


def test_tensors():
    """ test some tensor calculations """
    grid = CartesianGrid([[0.1, 0.3], [-2, 3]], [3, 4])

    t1 = Tensor2Field(grid, np.full((2, 2) + grid.shape, 1))
    t2 = Tensor2Field(grid, np.full((2, 2) + grid.shape, 2))
    np.testing.assert_allclose(t2.average, [[2, 2], [2, 2]])
    assert t1.magnitude == pytest.approx(2)

    t3 = t1 + t2
    assert t3.grid == grid
    np.testing.assert_allclose(t3.data, 3)
    t1 += t2
    np.testing.assert_allclose(t1.data, 3)

    field = Tensor2Field.random_uniform(grid)
    trace = field.trace()
    from ..scalar import ScalarField

    assert isinstance(trace, ScalarField)
    np.testing.assert_allclose(trace.data, field.data.trace())

    t1 = Tensor2Field(grid)
    t1.data[0, 0, :] = 1
    t1.data[0, 1, :] = 2
    t1.data[1, 0, :] = 3
    t1.data[1, 1, :] = 4
    for method, value in [
        ("min", 1),
        ("max", 4),
        ("norm", np.linalg.norm([[1, 2], [3, 4]])),
        ("squared_sum", 30),
        ("trace", 5),
        ("invariant1", 5),
        ("invariant2", -1),
    ]:
        p1 = t1.to_scalar(method)
        assert p1.data.shape == grid.shape
        np.testing.assert_allclose(p1.data, value)

    t2 = FieldBase.from_state(t1.attributes, data=t1.data)
    assert t1 == t2
    assert t1.grid is t2.grid

    attrs = Tensor2Field.unserialize_attributes(t1.attributes_serialized)
    t2 = FieldBase.from_state(attrs, data=t1.data)
    assert t1 == t2
    assert t1.grid is not t2.grid


def test_tensor_symmetrize():
    """ test advanced tensor calculations """
    grid = CartesianGrid([[0.1, 0.3], [-2, 3]], [2, 2])
    t1 = Tensor2Field(grid)
    t1.data[0, 0, :] = 1
    t1.data[0, 1, :] = 2
    t1.data[1, 0, :] = 3
    t1.data[1, 1, :] = 4

    # traceless = False
    t2 = t1.copy()
    t1.symmetrize(make_traceless=False, inplace=True)
    tr = t1.trace()
    assert np.all(tr.data == 5)
    t1_trans = np.swapaxes(t1.data, 0, 1)
    np.testing.assert_allclose(t1.data, t1_trans.data)

    ts = t1.copy()
    ts.symmetrize(make_traceless=False, inplace=True)
    np.testing.assert_allclose(t1.data, ts.data)

    # traceless = True
    t2.symmetrize(make_traceless=True, inplace=True)
    tr = t2.trace()
    assert np.all(tr.data == 0)
    t2_trans = np.swapaxes(t2.data, 0, 1)
    np.testing.assert_allclose(t2.data, t2_trans.data)

    ts = t2.copy()
    ts.symmetrize(make_traceless=True, inplace=True)
    np.testing.assert_allclose(t2.data, ts.data)


@pytest.mark.parametrize("grid", iter_grids())
def test_add_interpolated_tensor(grid):
    """ test the `add_interpolated` method """
    f = Tensor2Field(grid)
    a = np.random.random(f.data_shape)

    c = tuple(grid.point_to_cell(grid.get_random_point()))
    c_data = (Ellipsis,) + c
    p = grid.cell_to_point(c, cartesian=False)
    f.add_interpolated(p, a)
    np.testing.assert_almost_equal(f.data[c_data], a / grid.cell_volumes[c])

    f.add_interpolated(grid.get_random_point(cartesian=False), a)
    np.testing.assert_almost_equal(f.integral, 2 * a)

    f.data = 0  # reset
    add_interpolated = grid.make_add_interpolated_compiled()
    c = tuple(grid.point_to_cell(grid.get_random_point()))
    c_data = (Ellipsis,) + c
    p = grid.cell_to_point(c, cartesian=False)
    add_interpolated(f.data, p, a)
    np.testing.assert_almost_equal(f.data[c_data], a / grid.cell_volumes[c])

    add_interpolated(f.data, grid.get_random_point(cartesian=False), a)
    np.testing.assert_almost_equal(f.integral, 2 * a)


def test_tensor_invariants():
    """ test the invariants """
    # dim == 1
    f = Tensor2Field.random_uniform(UnitGrid([3]))
    np.testing.assert_allclose(
        f.to_scalar("invariant1").data, f.to_scalar("invariant3").data
    )
    np.testing.assert_allclose(f.to_scalar("invariant2").data, 0)

    # dim == 2
    f = Tensor2Field.random_uniform(UnitGrid([3, 3]))
    invs = [f.to_scalar(f"invariant{i}").data for i in range(1, 4)]
    np.testing.assert_allclose(2 * invs[1], invs[2])

    a = np.random.uniform(0, 2 * np.pi)  # pick random rotation angle
    rot = Tensor2Field(f.grid)
    rot.data[0, 0, ...] = np.cos(a)
    rot.data[0, 1, ...] = np.sin(a)
    rot.data[1, 0, ...] = -np.sin(a)
    rot.data[1, 1, ...] = np.cos(a)
    f_rot = rot @ f @ rot.transpose()  # apply the transpose

    for i, inv in enumerate(invs, 1):
        np.testing.assert_allclose(
            inv,
            f_rot.to_scalar(f"invariant{i}").data,
            err_msg=f"Mismatch in invariant {i}",
        )

    # dim == 3
    from scipy.spatial.transform import Rotation

    f = Tensor2Field.random_uniform(UnitGrid([1, 1, 1]))
    rot = Tensor2Field(f.grid)
    rot_mat = Rotation.from_rotvec(np.random.randn(3)).as_matrix()
    rot.data = rot_mat.reshape(3, 3, 1, 1, 1)
    f_rot = rot @ f @ rot.transpose()  # apply the transpose
    for i in range(1, 4):
        np.testing.assert_allclose(
            f.to_scalar(f"invariant{i}").data,
            f_rot.to_scalar(f"invariant{i}").data,
            err_msg=f"Mismatch in invariant {i}",
        )

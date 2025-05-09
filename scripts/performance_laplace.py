#!/usr/bin/env python3
"""This script tests the performance of the implementation of the laplace operator as a
primary example for the differential operators supplied by `py-pde`."""

import sys
from pathlib import Path

PACKAGE_PATH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_PATH))

import numba as nb
import numpy as np

from pde import CylindricalSymGrid, ScalarField, SphericalSymGrid, UnitGrid, config
from pde.grids.boundaries import BoundariesList
from pde.grids.operators.cartesian import _make_laplace_numba_2d
from pde.tools.misc import estimate_computation_speed
from pde.tools.numba import jit

config["numba.multithreading"] = "never"  # disable multithreading for better comparison


def custom_laplace_2d_periodic(shape, dx=1):
    """Make laplace operator with periodic boundary conditions."""
    dx_2 = 1 / dx**2
    dim_x, dim_y = shape
    parallel = dim_x * dim_y >= config["numba.multithreading_threshold"]

    @jit(parallel=parallel)
    def laplace(arr, out=None):
        """Apply laplace operator to array `arr`"""
        if out is None:
            out = np.empty((dim_x, dim_y))

        for i in nb.prange(dim_x):
            im = dim_x - 1 if i == 0 else i - 1
            ip = 0 if i == dim_x - 1 else i + 1

            j = 0
            jm = dim_y - 1
            jp = j + 1
            term = arr[i, jm] + arr[i, jp] + arr[im, j] + arr[ip, j] - 4 * arr[i, j]
            out[i, j] = term * dx_2

            for j in range(1, dim_y - 1):
                jm = j - 1
                jp = j + 1
                term = arr[i, jm] + arr[i, jp] + arr[im, j] + arr[ip, j] - 4 * arr[i, j]
                out[i, j] = term * dx_2

            j = dim_y - 1
            jm = j - 1
            jp = 0
            term = arr[i, jm] + arr[i, jp] + arr[im, j] + arr[ip, j] - 4 * arr[i, j]
            out[i, j] = term * dx_2
        return out

    return laplace


def custom_laplace_2d_neumann(shape, dx=1):
    """Make laplace operator with Neumann boundary conditions."""
    dx_2 = 1 / dx**2
    dim_x, dim_y = shape
    parallel = dim_x * dim_y >= config["numba.multithreading_threshold"]

    @jit(parallel=parallel)
    def laplace(arr, out=None):
        """Apply laplace operator to array `arr`"""
        if out is None:
            out = np.empty((dim_x, dim_y))

        for i in nb.prange(dim_x):
            im = 0 if i == 0 else i - 1
            ip = dim_x - 1 if i == dim_x - 1 else i + 1

            for j in range(dim_y):
                jm = 0 if j == 0 else j - 1
                jp = dim_y - 1 if j == dim_y - 1 else j + 1

                term = arr[i, jm] + arr[i, jp] + arr[im, j] + arr[ip, j] - 4 * arr[i, j]
                out[i, j] = term * dx_2
        return out

    return laplace


def custom_laplace_2d(shape, periodic, dx=1):
    """Make laplace operator with Neumann or periodic boundary conditions."""
    if periodic:
        return custom_laplace_2d_periodic(shape, dx=dx)
    else:
        return custom_laplace_2d_neumann(shape, dx=dx)


def optimized_laplace_2d(bcs):
    """Make an optimized laplace operator.

    The main optimization is that we expect the input to be a full array containing
    virtual boundary points. This avoids memory allocation and a copy of the data.
    """
    set_ghost_cells = bcs.make_ghost_cell_setter()
    apply_laplace = bcs.grid.make_operator_no_bc("laplace")
    shape = bcs.grid.shape

    @jit
    def laplace(arr):
        """Apply laplace operator to array `arr`"""
        set_ghost_cells(arr)
        out = np.empty(shape)
        apply_laplace(arr, out)
        return out

    return laplace


def custom_laplace_cyl_neumann(shape, dr=1, dz=1):
    """Make laplace operator with Neumann boundary conditions."""
    dim_r, dim_z = shape
    dr_2 = 1 / dr**2
    dz_2 = 1 / dz**2

    @jit
    def laplace(arr, out=None):
        """Apply laplace operator to array `arr`"""
        if out is None:
            out = np.empty((dim_r, dim_z))

        for j in range(dim_z):  # iterate axial points
            jm = 0 if j == 0 else j - 1
            jp = dim_z - 1 if j == dim_z - 1 else j + 1

            # inner radial boundary condition
            i = 0
            out[i, j] = (
                2 * (arr[i + 1, j] - arr[i, j]) * dr_2
                + (arr[i, jm] + arr[i, jp] - 2 * arr[i, j]) * dz_2
            )

            for i in range(1, dim_r - 1):  # iterate radial points
                out[i, j] = (
                    (arr[i + 1, j] - 2 * arr[i, j] + arr[i - 1, j]) * dr_2
                    + (arr[i + 1, j] - arr[i - 1, j]) / (2 * i + 1) * dr_2
                    + (arr[i, jm] + arr[i, jp] - 2 * arr[i, j]) * dz_2
                )

            # outer radial boundary condition
            i = dim_r - 1
            out[i, j] = (
                (arr[i - 1, j] - arr[i, j]) * dr_2
                + (arr[i, j] - arr[i - 1, j]) / (2 * i + 1) * dr_2
                + (arr[i, jm] + arr[i, jp] - 2 * arr[i, j]) * dz_2
            )
        return out

    return laplace


def test_cartesian(shape: tuple[int, int], periodic: bool) -> None:
    """Test Laplacian on Cartesian grids.

    Args:
        shape (tuple):
            Dimensions of the 2d grid
        periodic (bool):
            Periodicity of the grid
    """
    grid = UnitGrid(shape, periodic=periodic)
    print(grid)
    field = ScalarField.random_normal(grid)
    bcs = grid.get_boundary_conditions("auto_periodic_neumann", rank=0)
    expected = field.laplace("auto_periodic_neumann")

    for method in ["CUSTOM", "OPTIMIZED", "9POINT", "numba", "scipy"]:
        if method == "CUSTOM":
            laplace = custom_laplace_2d(shape, periodic=periodic)
        elif method == "OPTIMIZED":
            laplace = optimized_laplace_2d(bcs)
        elif method == "9POINT":
            laplace = grid.make_operator("laplace", bc=bcs, corner_weight=1 / 3)
        elif method in {"numba", "scipy"}:
            laplace = grid.make_operator("laplace", bc=bcs, backend=method)
        else:
            raise ValueError(f"Unknown method `{method}`")

        # call once to pre-compile and test result
        if method == "OPTIMIZED":
            result = laplace(field._data_full)
            np.testing.assert_allclose(result, expected.data)
            speed = estimate_computation_speed(laplace, field._data_full)
        else:
            if method != "9POINT":
                np.testing.assert_allclose(laplace(field.data), expected.data)
            speed = estimate_computation_speed(laplace, field.data)
        print(f"{method:>9s}: {int(speed):>9d}")
    print()


def test_cylindrical(shape: tuple[int, int]) -> None:
    """Test Laplacian on cylindrical grids.

    Args:
        shape (tuple):
            Dimensions of the cylindrical grid
    """
    grid = CylindricalSymGrid(shape[0], [0, shape[1]], shape)
    print(f"Cylindrical grid, shape={shape}")
    field = ScalarField.random_normal(grid)
    bcs = BoundariesList.from_data("derivative", grid=grid)
    expected = field.laplace(bcs)

    for method in ["CUSTOM", "numba"]:
        if method == "CUSTOM":
            laplace = custom_laplace_cyl_neumann(shape)
        elif method == "numba":
            laplace = grid.make_operator("laplace", bc=bcs)
        else:
            raise ValueError(f"Unknown method `{method}`")
        # call once to pre-compile and test result
        np.testing.assert_allclose(laplace(field.data), expected.data)
        speed = estimate_computation_speed(laplace, field.data)
        print(f"{method:>8s}: {int(speed):>9d}")
    print()


def test_spherical(shape: int) -> None:
    """Test Laplacian on spherical grids.

    Args:
        shape (int):
            Number of support points along the radial direction
    """
    grid = SphericalSymGrid(shape, shape)
    print(grid)
    field = ScalarField.random_normal(grid)
    bcs = BoundariesList.from_data("derivative", grid=grid)

    for conservative in [True, False]:
        laplace = grid.make_operator("laplace", bcs, conservative=conservative)
        laplace(field.data)  # call once to pre-compile
        speed = estimate_computation_speed(laplace, field.data)
        print(f" numba (conservative={str(conservative):<5}): {int(speed):>9d}")
    print()


def main():
    """Main routine testing the performance."""
    print("Reports calls-per-second (larger is better)")
    print("  The `CUSTOM` method implemented by hand is the baseline case.")
    print("  The `OPTIMIZED` uses some infrastructure form the py-pde package.")
    print("  The other methods use the functions supplied by the package.\n")

    for shape in [(32, 32), (512, 512)]:
        for periodic in [True, False]:
            test_cartesian(shape, periodic)

    for shape in [(32, 64), (512, 512)]:
        test_cylindrical(shape)

    for shape in [32, 512]:
        test_spherical(shape)


if __name__ == "__main__":
    main()

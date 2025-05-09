"""Cartesian grids of arbitrary dimension.

.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de>
"""

from __future__ import annotations

import itertools
from collections.abc import Generator, Sequence
from typing import Any

import numpy as np

from ..tools.cuboid import Cuboid
from ..tools.plotting import plot_on_axes
from .base import (
    CoordsType,
    DimensionError,
    GridBase,
    _check_shape,
    discretize_interval,
)
from .coordinates import CartesianCoordinates


class CartesianGrid(GridBase):
    r"""D-dimensional Cartesian grid with uniform discretization for each axis.

    The grids can be thought of as a collection of n-dimensional boxes, called cells, of
    equal length in each dimension. The bounds then defined the total volume covered by
    these cells, while the cell coordinates give the location of the box centers. We
    index the boxes starting from 0 along each dimension. Consequently, the cell
    :math:`i-\frac12` corresponds to the left edge of the  covered interval and the
    index :math:`i+\frac12` corresponds to the right edge, when the dimension is covered
    by d boxes.

    In particular, the discretization along dimension :math:`k` is defined as

    .. math::
            x^{(k)}_i &= x^{(k)}_\mathrm{min} + \left(i + \frac12\right)
                \Delta x^{(k)}
            \quad \text{for} \quad i = 0, \ldots, N^{(k)} - 1
        \\
            \Delta x^{(k)} &= \frac{x^{(k)}_\mathrm{max} -
                                    x^{(k)}_\mathrm{min}}{N^{(k)}}

    where :math:`N^{(k)}` is the number of cells along this dimension. Consequently,
    cells have dimension :math:`\Delta x^{(k)}` and cover the interval
    :math:`[x^{(k)}_\mathrm{min}, x^{(k)}_\mathrm{max}]`.
    """

    cuboid: Cuboid

    def __init__(
        self,
        bounds: Sequence[tuple[float, float]],
        shape: int | Sequence[int],
        periodic: bool | Sequence[bool] = False,
    ):
        """
        Args:
            bounds (list of tuple):
                Give the coordinate range for each axis. This should be a tuple of two
                number (lower and upper bound) for each axis. The length of `bounds`
                thus determines the grid dimension.
            shape (list):
                The number of support points for each axis. The length of `shape` needs
                to match the grid dimension.
            periodic (bool or list):
                Specifies which axes possess periodic boundary conditions. This is
                either a list of booleans defining periodicity for each individual axis
                or a single boolean value specifying the same periodicity for all axes.
        """
        bounds_arr: np.ndarray = np.array(bounds, ndmin=1, dtype=np.double)
        if bounds_arr.shape == (2,):
            raise ValueError(
                "`bounds with shape (2,) are ambiguous. Either use shape (1, 2) to set "
                "up a 1d system with two bounds or shape (2, 1) for a 2d system with "
                "only the upper bounds specified"
            )

        if bounds_arr.ndim == 1 or bounds_arr.shape[1] == 1:
            # only set the upper bounds
            bounds_arr = np.atleast_1d(np.squeeze(bounds_arr))
            self.cuboid = Cuboid(np.zeros_like(bounds_arr), bounds_arr, mutable=False)

        elif bounds_arr.ndim == 2 and bounds_arr.shape[1] == 2:
            # upper and lower bounds of the grid are given
            self.cuboid = Cuboid.from_bounds(bounds_arr, mutable=False)

        else:
            raise ValueError(
                f"Do not know how to interpret shape {bounds_arr.shape} for bounds"
            )

        # handle the shape array
        shape = _check_shape(shape)
        if len(shape) == 1 and self.cuboid.dim > 1:
            shape = (int(shape[0]),) * self.cuboid.dim
        if self.cuboid.dim != len(shape):
            raise DimensionError("Dimension of `bounds` and `shape` are not compatible")
        self._shape = _check_shape(shape)
        self.c = CartesianCoordinates(dim=len(self.shape))

        # initialize the base class
        super().__init__()

        if isinstance(periodic, (bool, np.bool_)):
            self._periodic = [bool(periodic)] * self.dim
        elif len(periodic) != self.dim:
            raise DimensionError(
                "Number of axes with specified periodicity does not match grid "
                f"dimension ({len(periodic)} != {self.dim})"
            )
        else:
            self._periodic = list(periodic)

        # determine the coordinates
        p1, p2 = self.cuboid.corners
        axes_coords, discretization = [], []
        for d in range(self.dim):
            c, dc = discretize_interval(p1[d], p2[d], self.shape[d])  # type: ignore
            axes_coords.append(c)
            discretization.append(dc)
        self._discretization = np.array(discretization)
        self._axes_coords = tuple(axes_coords)
        self._axes_bounds = tuple(self.cuboid.bounds)

        # name all the boundaries
        self.boundary_names = {"left": (0, False), "right": (0, True)}
        if self.num_axes > 1:
            self.boundary_names.update({"bottom": (1, False), "top": (1, True)})
        if self.num_axes > 2:
            self.boundary_names.update({"back": (2, False), "front": (2, True)})

    @property
    def state(self) -> dict[str, Any]:
        """dict: the state of the grid"""
        return {
            "bounds": self.axes_bounds,
            "shape": self.shape,
            "periodic": self.periodic,
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> CartesianGrid:  # type: ignore
        """Create a field from a stored `state`.

        Args:
            state (dict):
                The state from which the grid is reconstructed.

        Returns:
            :class:`CartesianGrid`: the grid re-created from the state data
        """
        state_copy = state.copy()
        obj = cls(
            bounds=state_copy.pop("bounds"),
            shape=state_copy.pop("shape"),
            periodic=state_copy.pop("periodic"),
        )
        if state_copy:
            raise ValueError(f"State items {state_copy.keys()} were not used")
        return obj

    @classmethod
    def from_bounds(
        cls,
        bounds: Sequence[tuple[float, float]],
        shape: Sequence[int],
        periodic: Sequence[bool],
    ) -> CartesianGrid:
        """
        Args:
            bounds (tuple):
                Give the coordinate range for each axis. This should be a tuple of two
                number (lower and upper bound) for each axis. The length of `bounds`
                thus determines the grid dimension.
            shape (tuple):
                The number of support points for each axis. The length of `shape` needs
                to match the grid dimension.
            periodic (bool or list):
                Specifies which axes possess periodic boundary conditions. This is
                either a list of booleans defining periodicity for each individual axis
                or a single boolean value specifying the same periodicity for all axes.

        Returns:
            :class:`CartesianGrid`: representing the region chosen by bounds
        """
        return CartesianGrid(bounds, shape, periodic)

    @property
    def volume(self) -> float:
        """float: total volume of the grid"""
        return float(self.cuboid.volume)

    @property
    def cell_volume_data(self):
        """Size associated with each cell."""
        return tuple(self.discretization)

    def iter_mirror_points(
        self, point: np.ndarray, with_self: bool = False, only_periodic: bool = True
    ) -> Generator:
        """Generates all mirror points corresponding to `point`

        Args:
            point (:class:`~numpy.ndarray`):
                The point within the grid
            with_self (bool):
                Whether to include the point itself
            only_periodic (bool):
                Whether to only mirror along periodic axes

        Returns:
            A generator yielding the coordinates that correspond to mirrors
        """
        point = np.asanyarray(point, dtype=np.double)

        # find all offsets of the individual axes
        offsets = []
        for i in range(self.dim):
            if only_periodic and not self.periodic[i]:
                offsets.append([0])
            else:
                s = self.cuboid.size[i]
                offsets.append([-s, 0, s])  # type: ignore

        # produce the respective mirrored points
        for offset in itertools.product(*offsets):
            if with_self or np.linalg.norm(offset) != 0:
                yield point + offset

    def get_random_point(
        self,
        *,
        boundary_distance: float = 0,
        coords: CoordsType = "cartesian",
        rng: np.random.Generator | None = None,
    ) -> np.ndarray:
        """Return a random point within the grid.

        Args:
            boundary_distance (float):
                The minimal distance this point needs to have from all boundaries.
            coords (str):
                Determines the coordinate system in which the point is specified. Valid
                values are `cartesian`, `cell`, and `grid`;
                see :meth:`~pde.grids.base.GridBase.transform`.
            rng (:class:`~numpy.random.Generator`):
                Random number generator (default: :func:`~numpy.random.default_rng()`)

        Returns:
            :class:`~numpy.ndarray`: The coordinates of the point
        """
        rng = np.random.default_rng(rng)

        # handle the boundary distance
        cuboid = self.cuboid
        if boundary_distance != 0:
            if any(cuboid.size <= 2 * boundary_distance):
                raise RuntimeError("Random points would be too close to boundary")
            cuboid = cuboid.buffer(-boundary_distance)

        # create random point
        point = cuboid.pos + rng.random(self.dim) * cuboid.size

        if coords == "cartesian" or coords == "grid":
            return point  # type: ignore
        elif coords == "cell":
            return self.transform(point, "grid", "cell")
        else:
            raise ValueError(f"Unknown coordinate system `{coords}`")

    def difference_vector(
        self, p1: np.ndarray, p2: np.ndarray, *, coords: CoordsType = "grid"
    ) -> np.ndarray:
        return self._difference_vector(
            p1, p2, coords=coords, periodic=self.periodic, axes_bounds=self.axes_bounds
        )

    def get_line_data(self, data: np.ndarray, extract: str = "auto") -> dict[str, Any]:
        """Return a line cut through the given data.

        Args:
            data (:class:`~numpy.ndarray`):
                The values at the grid points
            extract (str):
                Determines which cut is done through the grid. Possible choices
                are (default is `cut_0`):

                * `cut_#`: return values along the axis specified by # and use
                  the mid point along all other axes.
                * `project_#`: average values for all axes, except axis #.

                Here, # can either be a zero-based index (from 0 to dim-1) or
                a letter denoting the axis.

        Returns:
            dict: A dictionary with information about the line cut, which is convenient
            for plotting.
        """
        if data.shape[-self.dim :] != self.shape:
            raise ValueError(
                f"Shape {data.shape} of the data array is not compatible with grid "
                f"shape {self.shape}"
            )

        def _get_axis(axis):
            """Determine the axis from a given specifier."""
            try:
                axis = int(axis)
            except ValueError:
                try:
                    axis = self.axes.index(axis)
                except ValueError:
                    raise ValueError(f"Axis `{axis}` not defined") from None
            return axis

        if extract == "auto":
            extract = "cut_0"  # use a cut along first axis

        if extract.startswith("cut_"):
            # consider a cut along a given axis
            axis = _get_axis(extract[4:])
            data_y = data
            rank = data.ndim - self.dim  # rank of data
            for ax in reversed(range(self.dim)):
                if ax != axis:
                    mid_point = self.shape[ax] // 2
                    data_y = np.take(data_y, mid_point, axis=ax + rank)
            label_y = f"Cut along {self.axes[axis]}"

        elif extract.startswith("project_"):
            # consider a projection along a given axis
            axis = _get_axis(extract[8:])
            avg_axes = [ax - self.dim for ax in range(self.dim) if ax != axis]
            data_y = data.mean(axis=tuple(avg_axes))
            label_y = f"Projection onto {self.axes[axis]}"

        else:
            raise ValueError(f"Unknown extraction method `{extract}`")

        if self.dim == 1:
            label_y = ""

        # return the data with the respective labels
        return {
            "data_x": self.axes_coords[axis],
            "data_y": data_y,
            "extent_x": self.axes_bounds[axis],
            "label_x": self.axes[axis],
            "label_y": label_y,
        }

    def get_image_data(self, data: np.ndarray) -> dict[str, Any]:
        if data.shape[-self.dim :] != self.shape:
            raise ValueError(
                f"Shape {data.shape} of the data array is not compatible with grid "
                f"shape {self.shape}"
            )

        if self.dim == 2:
            image_data = data
        elif self.dim == 3:
            image_data = data[:, :, self.shape[-1] // 2]
        else:
            raise NotImplementedError(
                "Creating images is only implemented for 2d and 3d grids"
            )

        extent: list[float] = []
        for c in self.axes_bounds[:2]:
            extent.extend(c)

        return {
            "data": image_data,
            "x": self.axes_coords[0],
            "y": self.axes_coords[1],
            "extent": extent,
            "label_x": self.axes[0],
            "label_y": self.axes[1],
        }

    def get_vector_data(self, data: np.ndarray, **kwargs) -> dict[str, Any]:
        if self.dim != 2:
            raise DimensionError("Vector data only available for dim==2")
        if data.shape != (2,) + self.shape:
            raise ValueError(
                f"Shape {data.shape} of the data array is not compatible with grid "
                f"shape {self.shape}"
            )

        return {
            "data_x": data[0],
            "data_y": data[1],
            "x": self.axes_coords[0],
            "y": self.axes_coords[1],
            "extent": np.ravel(self.axes_bounds).tolist(),
            "label_x": self.axes[0],
            "label_y": self.axes[1],
        }

    @plot_on_axes()
    def plot(self, ax, **kwargs):
        r"""Visualize the grid.

        Args:
            {PLOT_ARGS}
            \**kwargs: Extra arguments are passed on the to the matplotlib
                plotting routines, e.g., to set the color of the lines
        """
        if self.dim not in {1, 2}:
            raise NotImplementedError(
                f"Plotting is not implemented for grids of dimension {self.dim}"
            )

        kwargs.setdefault("color", "k")
        xb = self.axes_bounds[0]
        for x in np.linspace(*xb, self.shape[0] + 1):
            ax.axvline(x, **kwargs)
        ax.set_xlim(*xb)
        ax.set_xlabel(self.axes[0])

        if self.dim == 2:
            yb = self.axes_bounds[1]
            for y in np.linspace(*yb, self.shape[1] + 1):
                ax.axhline(y, **kwargs)
            ax.set_ylim(*yb)
            ax.set_ylabel(self.axes[1])

            ax.set_aspect(1)

    def slice(self, indices: Sequence[int]) -> CartesianGrid:
        """Return a subgrid of only the specified axes.

        Args:
            indices (list):
                Indices indicating the axes that are retained in the subgrid

        Returns:
            :class:`CartesianGrid`: The subgrid
        """
        subgrid = self.__class__(
            bounds=[self.axes_bounds[i] for i in indices],
            shape=tuple(self.shape[i] for i in indices),
            periodic=[self.periodic[i] for i in indices],
        )
        subgrid.axes = [self.axes[i] for i in indices]
        return subgrid


class UnitGrid(CartesianGrid):
    r"""D-dimensional Cartesian grid with unit discretization in all directions.

    The grids can be thought of as a collection of d-dimensional cells of unit length.
    The `shape` parameter determines how many boxes there are in each direction. The
    cells are enumerated starting with 0, so the last cell has index :math:`n-1` if
    there are :math:`n` cells along a dimension. A given cell :math:`i` extends from
    coordinates :math:`i` to :math:`i + 1`, so the midpoint is at :math:`i + \frac12`,
    which is the cell coordinate. Taken together, the cells covers the interval
    :math:`[0, n]` along this dimension.
    """

    def __init__(
        self, shape: int | Sequence[int], periodic: bool | Sequence[bool] = False
    ):
        """
        Args:
            shape (list):
                The number of support points for each axis. The dimension of the grid is
                given by `len(shape)`.
            periodic (bool or list):
                Specifies which axes possess periodic boundary conditions. This is
                either a list of booleans defining periodicity for each individual axis
                or a single boolean value specifying the same periodicity for all axes.
        """
        if isinstance(shape, int):
            shape = [shape]
        super().__init__([(0, s) for s in shape], shape, periodic)
        self.cuboid = Cuboid(np.zeros(self.dim), self.shape)
        self._discretization = np.ones(self.dim)

        # determine the cell center coordinates
        self._axes_coords = tuple(np.arange(n) + 0.5 for n in self.shape)
        self._axes_bounds = tuple(self.cuboid.bounds)

    @property
    def state(self) -> dict[str, Any]:
        """dict: the state of the grid"""
        return {"shape": self.shape, "periodic": self.periodic}

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> UnitGrid:  # type: ignore
        """Create a field from a stored `state`.

        Args:
            state (dict):
                The state from which the grid is reconstructed.
        """
        state_copy = state.copy()
        obj = cls(shape=state_copy.pop("shape"), periodic=state_copy.pop("periodic"))
        if state_copy:
            raise ValueError(f"State items {state_copy.keys()} were not used")
        return obj

    def to_cartesian(self) -> CartesianGrid:
        """Convert unit grid to :class:`CartesianGrid`

        Returns:
            :class:`CartesianGrid`: The equivalent cartesian grid
        """
        return CartesianGrid(
            self.cuboid.bounds, shape=self.shape, periodic=self.periodic
        )

    def slice(self, indices: Sequence[int]) -> UnitGrid:
        """Return a subgrid of only the specified axes.

        Args:
            indices (list):
                Indices indicating the axes that are retained in the subgrid

        Returns:
            :class:`UnitGrid`: The subgrid
        """
        subgrid = self.__class__(
            shape=[self.shape[i] for i in indices],
            periodic=[self.periodic[i] for i in indices],
        )
        subgrid.axes = [self.axes[i] for i in indices]
        return subgrid

"""Defines a tensorial field of rank 2 over a grid.

.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de>
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Callable

import numpy as np
from numpy.typing import DTypeLike

from ..grids.base import DimensionError, GridBase
from ..tools.docstrings import fill_in_docstring
from ..tools.misc import get_common_dtype
from ..tools.plotting import PlotReference, plot_on_figure
from ..tools.typing import NumberOrArray
from .datafield_base import DataFieldBase
from .scalar import ScalarField
from .vectorial import VectorField

if TYPE_CHECKING:
    from ..grids.boundaries.axes import BoundariesData


class Tensor2Field(DataFieldBase):
    """Tensor field of rank 2 discretized on a grid.

    Warning:
        Components of the tensor field are given in the local basis. While the local
        basis is identical to the global basis in Cartesian coordinates, the local basis
        depends on position in curvilinear coordinate systems. Moreover, the field
        always contains all components, even if the underlying grid assumes symmetries.
    """

    rank = 2

    @classmethod
    @fill_in_docstring
    def from_expression(
        cls,
        grid: GridBase,
        expressions: Sequence[Sequence[str]],
        *,
        user_funcs: dict[str, Callable] | None = None,
        consts: dict[str, NumberOrArray] | None = None,
        label: str | None = None,
        dtype: DTypeLike | None = None,
    ) -> Tensor2Field:
        """Create a tensor field on a grid from given expressions.

        Warning:
            {WARNING_EXEC}

        Args:
            grid (:class:`~pde.grids.base.GridBase`):
                Grid defining the space on which this field is defined
            expressions (list of str):
                A 2d list of mathematical expression, one for each component of the
                tensor field. The expressions determine the values as a function of the
                position on the grid. The expressions may contain standard mathematical
                functions and they may depend on the axes labels of the grid.
                More information can be found in the
                :ref:`expression documentation <documentation-expressions>`.
            user_funcs (dict, optional):
                A dictionary with user defined functions that can be used in the
                expression
            consts (dict, optional):
                A dictionary with user defined constants that can be used in the
                expression. The values of these constants should either be numbers or
                :class:`~numpy.ndarray`.
            label (str, optional):
                Name of the field
            dtype (numpy dtype):
                The data type of the field. If omitted, it will be determined from
                `data` automatically.
        """
        from ..tools.expressions import ScalarExpression

        if (
            isinstance(expressions, str)
            or len(expressions) != grid.dim
            or any(len(expr) != grid.dim for expr in expressions)
        ):
            axes_names = grid.axes + grid.axes_symmetric
            raise DimensionError(
                f"Expected a nested list of {grid.dim}x{grid.dim} expressions for the "
                f"tensor components of the coordinates {axes_names}."
            )

        if any("cartesian" in str(expression) for expression in expressions):
            # support Cartesian coordinates via a special constant
            if consts is None:
                consts = {}
            if "cartesian" not in consts:
                coords_cart = grid.point_to_cartesian(grid.cell_coords)
                consts["cartesian"] = np.moveaxis(coords_cart, -1, 0)
            assert "cartesian" in consts

        # obtain the coordinates of the grid points
        points = [grid.cell_coords[..., i] for i in range(grid.num_axes)]

        # evaluate all vector components at all points
        data: list[list[np.ndarray]] = [[None] * grid.dim for _ in range(grid.dim)]  # type: ignore
        for i in range(grid.dim):
            for j in range(grid.dim):
                expr = ScalarExpression(
                    expressions[i][j],
                    signature=grid.axes,
                    user_funcs=user_funcs,
                    consts=consts,
                    repl=grid.c._axes_alt_repl,
                    allow_indexed=True,
                )
                values = np.broadcast_to(expr(*points), grid.shape)
                data[i][j] = values

        # create vector field from the data
        return cls(grid=grid, data=data, label=label, dtype=dtype)

    def _get_axes_index(self, key: tuple[int | str, int | str]) -> tuple[int, int]:
        """Turns a general index of two axis into a tuple of two numeric indices."""
        try:
            if len(key) != 2:
                raise IndexError("Index must be given as two integers")
        except TypeError as err:
            raise IndexError("Index must be given as two values") from err
        return tuple(self.grid.get_axis_index(k) for k in key)  # type: ignore

    def __getitem__(self, key: tuple[int | str, int | str]) -> ScalarField:
        """Extract a single component of the tensor field as a scalar field."""
        return ScalarField(
            self.grid,
            data=self._data_full[self._get_axes_index(key)],
            with_ghost_cells=True,
        )

    def __setitem__(
        self,
        key: tuple[int | str, int | str],
        value: NumberOrArray | ScalarField,
    ):
        """Set a single component of the tensor field."""
        idx = self._get_axes_index(key)
        if isinstance(value, ScalarField):
            self.grid.assert_grid_compatible(value.grid)
            self.data[idx] = value.data
        else:
            self.data[idx] = value

    @DataFieldBase._data_flat.setter  # type: ignore
    def _data_flat(self, value):
        """Set the data from a value from a collection."""
        # create a view and reshape it to disallow copying
        data_full = value.view()
        dim = self.grid.dim
        full_grid_shape = tuple(s + 2 for s in self.grid.shape)
        data_full.shape = (dim, dim, *full_grid_shape)

        # set the result as the full data array
        self._data_full = data_full

        # ensure that no copying happend
        if not np.may_share_memory(self.data, value):
            raise RuntimeError("Spurious copy detected!")

    def dot(
        self,
        other: VectorField | Tensor2Field,
        out: VectorField | Tensor2Field | None = None,
        *,
        conjugate: bool = True,
        label: str = "dot product",
    ) -> VectorField | Tensor2Field:
        """Calculate the dot product involving a tensor field.

        This supports the dot product between two tensor fields as well as the
        product between a tensor and a vector. The resulting fields will be a
        tensor or vector, respectively.

        Args:
            other (VectorField or Tensor2Field):
                the second field
            out (VectorField or Tensor2Field, optional):
                Optional field to which the  result is written.
            conjugate (bool):
                Whether to use the complex conjugate for the second operand
            label (str, optional):
                Name of the returned field

        Returns:
            :class:`~pde.fields.vectorial.VectorField` or
            :class:`~pde.fields.tensorial.Tensor2Field`: result of applying the dot operator
        """
        # check input
        self.grid.assert_grid_compatible(other.grid)
        if not isinstance(other, (VectorField, Tensor2Field)):
            raise TypeError("Second term must be a vector or tensor field")

        # create and check the output instance
        if out is None:
            out = other.__class__(self.grid, dtype=get_common_dtype(self, other))
        else:
            if not isinstance(out, other.__class__):
                raise TypeError(f"`out` must be of type `{other.__class__}`")
            self.grid.assert_grid_compatible(out.grid)

        # calculate the result
        other_data = other.data.conjugate() if conjugate else other.data
        np.einsum("ij...,j...->i...", self.data, other_data, out=out.data)
        if label is not None:
            out.label = label

        return out

    __matmul__ = dot  # support python @-syntax for matrix multiplication

    @fill_in_docstring
    def divergence(
        self, bc: BoundariesData | None, out: VectorField | None = None, **kwargs
    ) -> VectorField:
        r"""Apply tensor divergence and return result as a field.

        The tensor divergence is a vector field :math:`v_\alpha` resulting from a
        contracting of the derivative of the tensor field :math:`t_{\alpha\beta}`:

        .. math::
            v_\alpha = \sum_\beta \frac{\partial t_{\alpha\beta}}{\partial x_\beta}

        Args:
            bc:
                The boundary conditions applied to the field.
                {ARG_BOUNDARIES_OPTIONAL}
            out (VectorField, optional):
                Optional scalar field to which the  result is written.
            label (str, optional):
                Name of the returned field
            **kwargs:
                Additional arguments affecting how the operator behaves.

        Returns:
            :class:`~pde.fields.vectorial.VectorField`: result of applying the operator
        """
        return self.apply_operator("tensor_divergence", bc=bc, out=out, **kwargs)  # type: ignore

    @property
    def integral(self) -> np.ndarray:
        """:class:`~numpy.ndarray`: integral of each component over space."""
        return self.grid.integrate(self.data)  # type: ignore

    def transpose(self, label: str = "transpose") -> Tensor2Field:
        """Return the transpose of the tensor field.

        Args:
            label (str, optional): Name of the returned field

        Returns:
            :class:`~pde.fields.tensorial.Tensor2Field`: transpose of the tensor field
        """
        axes = (1, 0) + tuple(range(2, 2 + self.grid.num_axes))
        return Tensor2Field(self.grid, self.data.transpose(axes), label=label)

    def symmetrize(
        self, make_traceless: bool = False, inplace: bool = False
    ) -> Tensor2Field:
        """Symmetrize the tensor field in place.

        Args:
            make_traceless (bool):
                Determines whether the result is also traceless
            inplace (bool):
                Flag determining whether to symmetrize the current field or
                return a new one

        Returns:
            :class:`~pde.fields.tensorial.Tensor2Field`: result of the operation
        """
        if inplace:
            out = self
        else:
            out = self.copy()

        out += self.transpose()
        out *= 0.5

        if make_traceless:
            dim = self.grid.dim
            value = self.trace() / dim
            for i in range(dim):
                out.data[i, i] -= value.data
        return out

    def to_scalar(
        self, scalar: str = "auto", *, label: str | None = "scalar `{scalar}`"
    ) -> ScalarField:
        r"""Return scalar variant of the field.

        The invariants of the tensor field :math:`\boldsymbol{A}` are

        .. math::
            I_1 &= \mathrm{tr}(\boldsymbol{A}) \\
            I_2 &= \frac12 \left[
                (\mathrm{tr}(\boldsymbol{A})^2 -
                \mathrm{tr}(\boldsymbol{A}^2)
            \right] \\
            I_3 &= \det(A)

        where `tr` denotes the trace and `det` denotes the determinant. Note that the
        three invariants can only be distinct and non-zero in three dimensions. In two
        dimensional spaces, we have the identity :math:`2 I_2 = I_3` and in
        one-dimensional spaces, we have :math:`I_1 = I_3` as well as
        :math:`I_2 = 0`.

        Args:
            scalar (str):
                The method to calculate the scalar. Possible choices include `norm` (the
                default chosen when the value is `auto`), `min`, `max`, `squared_sum`,
                `norm_squared`, `trace` (or `invariant1`), `invariant2`, and
                `determinant` (or `invariant3`)
            label (str, optional):
                Name of the returned field

        Returns:
            :class:`~pde.fields.scalar.ScalarField`: the scalar field after
            applying the operation
        """
        if scalar == "auto":
            scalar = "norm"

        if scalar == "norm":
            data = np.linalg.norm(self.data, axis=(0, 1))

        elif scalar == "min":
            data = np.min(self.data, axis=(0, 1))

        elif scalar == "max":
            data = np.max(self.data, axis=(0, 1))

        elif scalar == "squared_sum":
            data = np.sum(self.data**2, axis=(0, 1))

        elif scalar == "norm_squared":
            data = np.sum(self.data * self.data.conjugate(), axis=(0, 1))

        elif scalar == "trace" or scalar == "invariant1":
            data = self.data.trace(axis1=0, axis2=1)

        elif scalar == "invariant2":
            data = np.zeros(self.grid.shape)
            for i in range(self.grid.dim):
                for j in range(i):
                    data += (
                        self.data[i, i] * self.data[j, j]
                        - self.data[i, j] * self.data[j, i]
                    )
            data *= 0.5

        elif scalar in {"det", "determinant", "invariant3"}:
            if self.grid.dim == 1:
                data = self.data[0, 0]
            else:
                data = np.zeros(self.grid.shape)
                # this iterates over all of space and might thus be slow, but
                # the interface of np.linalg.det is not very flexible. We could
                # in principle use the definition of np.linalg.det without the
                # multiple checks to gain some speed
                for idx in np.ndindex(*self.grid.shape):
                    data[idx] = np.linalg.det(self.data[(...,) + idx])

        else:
            raise ValueError(
                f"Unknown method `{scalar}` for `to_scalar`. Valid methods are `norm`, "
                "`min`, `max`, squared_sum`, `norm_squared`, `trace`, `determinant`, "
                "and `invariant#`, where # is 1, 2, or 3"
            )

        # determine label of the result
        if self.label is None:
            if label is not None:
                label = label.format(scalar=scalar)
        else:
            label = f"{scalar} of {self.label}"

        return ScalarField(self.grid, data, label=label)

    def trace(self, label: str | None = "trace") -> ScalarField:
        """Return the trace of the tensor field as a scalar field.

        Args:
            label (str, optional): Name of the returned field

        Returns:
            :class:`~pde.fields.scalar.ScalarField`: scalar field of traces
        """
        return self.to_scalar(scalar="trace", label=label)

    def _update_plot_components(self, reference: list[list[PlotReference]]) -> None:
        """Update a plot collection with the current field values.

        Args:
            reference (list of :class:`PlotReference`):
                All references of the plot to update
        """
        for i in range(self.grid.dim):
            for j in range(self.grid.dim):
                self[i, j]._update_plot(reference[i][j])

    @plot_on_figure(update_method="_update_plot_components")
    def plot_components(
        self,
        kind: str = "auto",
        fig=None,
        **kwargs,
    ) -> list[list[PlotReference]]:
        r"""Visualize all the components of this tensor field.

        Args:
            kind (str or list of str):
                Determines the kind of the visualizations. Supported values are `image`
                or `line`. Alternatively, `auto` determines the best visualization based
                on the grid.
            {PLOT_ARGS}
            \**kwargs:
                All additional keyword arguments are forwarded to the actual plotting
                function of all subplots.

        Returns:
            2d list of :class:`PlotReference`: Instances that contain information
            to update all the plots with new data later.
        """
        # create all the subpanels
        dim = self.grid.dim
        axs = fig.subplots(nrows=dim, ncols=dim, squeeze=False)

        # plot all the elements onto the respective axes
        kwargs.setdefault("action", "none")
        kwargs["kind"] = kind
        comps = self.grid.axes + self.grid.axes_symmetric
        references = [
            [
                self[i, j].plot(
                    ax=axs[i][j],
                    title=f"{comps[i]}{comps[j]} Component",
                    **kwargs,
                )
                for j in range(dim)
            ]
            for i in range(dim)
        ]
        # return the references for all subplots
        return references

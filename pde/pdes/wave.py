"""A simple wave equation.

.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de>
"""

from __future__ import annotations

from typing import Callable

import numba as nb
import numpy as np

from ..fields import FieldCollection, ScalarField
from ..grids.boundaries import set_default_bc
from ..grids.boundaries.axes import BoundariesData
from ..tools.docstrings import fill_in_docstring
from ..tools.numba import jit
from .base import PDEBase, expr_prod


class WavePDE(PDEBase):
    r"""A simple wave equation.

    The mathematical definition, :math:`\partial_t^2 u = c^2 \nabla^2 u`, is implemented
    as two first-order equations,

    .. math::
        \partial_t u &= v \\
        \partial_t v &= c^2 \nabla^2 u

    where :math:`c` sets the wave speed and :math:`v` is an auxiallary field. Note that
    the class expects an initial condition specifying both fields, which can be created
    using the :meth:`WavePDE.get_initial_condition` method. The result will also return
    two fields.
    """

    explicit_time_dependence = False
    default_bc = "auto_periodic_neumann"
    """Default boundary condition used when no specific conditions are chosen."""

    @fill_in_docstring
    def __init__(self, speed: float = 1, *, bc: BoundariesData | None = None):
        """
        Args:
            speed (float):
                The speed :math:`c` of the wave
            bc:
                The boundary conditions applied to the field :math:`u`.
                {ARG_BOUNDARIES}
        """
        super().__init__()

        self.speed = speed
        self.bc = set_default_bc(bc, self.default_bc)

    def get_initial_condition(self, u: ScalarField, v: ScalarField | None = None):
        """Create a suitable initial condition.

        Args:
            u (:class:`~pde.fields.ScalarField`):
                The initial density on the grid
            v (:class:`~pde.fields.ScalarField`, optional):
                The initial rate of change. This is assumed to be zero if the
                value is omitted.

        Returns:
            :class:`~pde.fields.FieldCollection`:
                The combined fields u and v, suitable for the simulation
        """
        if v is None:
            v = ScalarField(u.grid)
        return FieldCollection([u, v], labels=["u", "v"])

    @property
    def expressions(self) -> dict[str, str]:
        """dict: the expressions of the right hand side of this PDE"""
        return {"u": "v", "v": expr_prod(self.speed**2, "∇²u")}

    def evolution_rate(  # type: ignore
        self,
        state: FieldCollection,
        t: float = 0,
    ) -> FieldCollection:
        """Evaluate the right hand side of the PDE.

        Args:
            state (:class:`~pde.fields.FieldCollection`):
                The fields :math:`u` and :math:`v`
            t (float):
                The current time point

        Returns:
            :class:`~pde.fields.FieldCollection`:
            Fields describing the evolution rates of the PDE
        """
        if not isinstance(state, FieldCollection):
            raise ValueError("`state` must be FieldCollection")
        if len(state) != 2:
            raise ValueError("`state` must contain two fields")
        u, v = state
        u_t = v.copy()
        v_t = self.speed**2 * u.laplace(self.bc, args={"t": t})  # type: ignore
        return FieldCollection([u_t, v_t])

    def _make_pde_rhs_numba(  # type: ignore
        self, state: FieldCollection
    ) -> Callable[[np.ndarray, float], np.ndarray]:
        """Create a compiled function evaluating the right hand side of the PDE.

        Args:
            state (:class:`~pde.fields.FieldCollection`):
                An example for the state defining the grid and data types

        Returns:
            A function with signature `(state_data, t)`, which can be called with an
            instance of :class:`~numpy.ndarray` of the state data and the time to
            obtained an instance of :class:`~numpy.ndarray` giving the evolution rate.
        """
        arr_type = nb.typeof(state.data)
        signature = arr_type(arr_type, nb.double)

        speed2 = self.speed**2
        laplace = state.grid.make_operator("laplace", bc=self.bc)

        @jit(signature)
        def pde_rhs(state_data: np.ndarray, t: float):
            """Compiled helper function evaluating right hand side."""
            rate = np.empty_like(state_data)
            rate[0] = state_data[1]
            rate[1][:] = laplace(state_data[0], args={"t": t})
            rate[1] *= speed2
            return rate

        return pde_rhs  # type: ignore

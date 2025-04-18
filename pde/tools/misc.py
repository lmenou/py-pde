"""Miscellaneous python functions.

.. autosummary::
   :nosignatures:

   module_available
   ensure_directory_exists
   preserve_scalars
   decorator_arguments
   import_class
   classproperty
   hybridmethod
   estimate_computation_speed
   hdf_write_attributes
   number
   get_common_dtype
   number_array

.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de>
"""

from __future__ import annotations

import errno
import functools
import importlib
import json
import os
import warnings
from pathlib import Path
from typing import Any, Callable, TypeVar

import numpy as np
from numpy.typing import DTypeLike

from .typing import ArrayLike, Number

TFunc = TypeVar("TFunc", bound=Callable[..., Any])


def module_available(module_name: str) -> bool:
    """Check whether a python module is available.

    Args:
        module_name (str): The name of the module

    Returns:
        `True` if the module can be imported and `False` otherwise
    """
    try:
        importlib.import_module(module_name)
    except ImportError:
        return False
    else:
        return True


def ensure_directory_exists(folder: str | Path):
    """Creates a folder if it not already exists.

    Args:
        folder (str): path of the new folder
    """
    try:
        Path(folder).mkdir(parents=True)
    except OSError as err:
        if err.errno != errno.EEXIST:
            raise


def preserve_scalars(method: TFunc) -> TFunc:
    """Decorator that makes vectorized methods work with scalars.

    This decorator allows to call functions that are written to work on numpy
    arrays to also accept python scalars, like `int` and `float`. Essentially,
    this wrapper turns them into an array and unboxes the result.

    Args:
        method: The method being decorated

    Returns:
        The decorated method
    """
    # deprecated on 2024-08-21
    warnings.warn("Method `preserve_scalars` is deprecated", DeprecationWarning)

    @functools.wraps(method)
    def wrapper(self, *args):
        args = [number_array(arg, copy=None) for arg in args]
        if args[0].ndim == 0:
            args = [arg[None] for arg in args]
            return method(self, *args)[0]
        else:
            return method(self, *args)

    return wrapper  # type: ignore


def decorator_arguments(decorator: Callable) -> Callable:
    r"""make a decorator usable with and without arguments:

    The resulting decorator can be used like `@decorator`
    or `@decorator(\*args, \**kwargs)`

    Inspired by https://stackoverflow.com/a/14412901/932593

    Args:
        decorator: the decorator that needs to be modified

    Returns:
        the decorated function
    """

    @functools.wraps(decorator)
    def new_decorator(*args, **kwargs):
        if len(args) == 1 and len(kwargs) == 0 and callable(args[0]):
            # actual decorated function
            return decorator(args[0])
        else:
            # decorator arguments
            return lambda realf: decorator(realf, *args, **kwargs)

    return new_decorator


def import_class(identifier: str):
    """Import a class or module given an identifier.

    Args:
        identifier (str):
            The identifier can be a module or a class. For instance, calling the
            function with the string `identifier == 'numpy.linalg.norm'` is
            roughly equivalent to running `from numpy.linalg import norm` and
            would return a reference to `norm`.
    """
    module_path, _, class_name = identifier.rpartition(".")
    if module_path:
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    else:
        # this happens when identifier does not contain a dot
        return importlib.import_module(class_name)


class classproperty(property):
    """Decorator that can be used to define read-only properties for classes.

    This is inspired by the implementation of :mod:`astropy`, see
    `astropy.org <http://astropy.org/>`_.

    Example:
        The decorator can be used much like the `property` decorator::

            class Test:
                item: str = "World"

                @classproperty
                def message(cls):
                    return "Hello " + cls.item


            print(Test.message)
    """

    def __new__(cls, fget=None, doc=None):
        if fget is None:
            # use wrapper to support decorator without arguments
            def wrapper(func):
                return cls(func)

            return wrapper

        return super().__new__(cls)

    def __init__(self, fget, doc=None):
        fget = self._wrap_fget(fget)

        super().__init__(fget=fget, doc=doc)

        if doc is not None:
            self.__doc__ = doc

    def __get__(self, obj, objtype):
        # The base property.__get__ will just return self here;
        # instead we pass objtype through to the original wrapped
        # function (which takes the class as its sole argument)
        return self.fget.__wrapped__(objtype)

    def getter(self, fget):
        return super().getter(self._wrap_fget(fget))

    def setter(self, fset):
        raise NotImplementedError("classproperty is read-only")

    def deleter(self, fdel):
        raise NotImplementedError("classproperty is read-only")

    @staticmethod
    def _wrap_fget(orig_fget):
        if isinstance(orig_fget, classmethod):
            orig_fget = orig_fget.__func__

        @functools.wraps(orig_fget)
        def fget(obj):
            return orig_fget(obj.__class__)

        return fget


class hybridmethod:
    """Descriptor that can be used as a decorator to allow calling a method both as a
    classmethod and an instance method.

    Adapted from https://stackoverflow.com/a/28238047
    """

    def __init__(self, fclass, finstance=None, doc=None):
        self.fclass = fclass
        self.finstance = finstance
        self.__doc__ = doc or fclass.__doc__
        # support use on abstract base classes
        self.__isabstractmethod__ = bool(getattr(fclass, "__isabstractmethod__", False))
        # # support extracting information about the function for sphinx
        if finstance:
            self.__func__ = finstance

    def classmethod(self, fclass):
        return type(self)(fclass, self.finstance, None)

    def instancemethod(self, finstance):
        return type(self)(self.fclass, finstance, self.__doc__)

    def __get__(self, instance, cls):
        if instance is None or self.finstance is None:
            # either bound to the class, or no instance method available
            return self.fclass.__get__(cls, None)
        return self.finstance.__get__(instance, cls)


def estimate_computation_speed(func: Callable, *args, **kwargs) -> float:
    """Estimates the computation speed of a function.

    Args:
        func (callable): The function to call

    Returns:
        float: the number of times the function can be calculated in one second.
        The inverse is thus the runtime in seconds per function call
    """
    import timeit

    test_duration = kwargs.pop("test_duration", 1)

    # prepare the function
    if args or kwargs:
        test_func = functools.partial(func, *args, **kwargs)
    else:
        test_func = func  # type: ignore

    # call function once to allow caches be filled
    test_func()

    # call the function until the total time is achieved
    number, duration = 1, 0
    while duration < 0.1 * test_duration:
        number *= 10
        duration = timeit.timeit(test_func, number=number)  # type: ignore
    return number / duration


def hdf_write_attributes(
    hdf_path,
    attributes: dict[str, Any] | None = None,
    raise_serialization_error: bool = False,
) -> None:
    """Write (JSON-serialized) attributes to a hdf file.

    Args:
        hdf_path:
            Path to a group or dataset in an open HDF file
        attributes (dict):
            Dictionary with values written as attributes
        raise_serialization_error (bool):
            Flag indicating whether serialization errors are raised or silently
            ignored
    """
    if attributes is None:
        return

    for key, value in attributes.items():
        try:
            value_serialized = json.dumps(value)
        except TypeError:
            if raise_serialization_error:
                raise
        else:
            hdf_path.attrs[key] = value_serialized


def number(value: Number | str) -> Number:
    """Convert a value into a float or complex number.

    Args:
        value (Number or str):
            The value which needs to be converted

    Result:
        Number: A complex number or a float if the imaginary part vanishes
    """
    result = complex(value)
    return result.real if result.imag == 0 else result


def get_common_dtype(*args):
    r"""Returns a dtype in which all arguments can be represented.

    Args:
        *args: All items (arrays, scalars, etc) to be checked

    Returns: numpy.cdouble if any entry is complex, otherwise np.double
    """
    for arg in args:
        if np.iscomplexobj(arg):
            return np.cdouble
    return np.double


def number_array(
    data: ArrayLike, dtype: DTypeLike = None, copy: bool | None = None
) -> np.ndarray:
    """Convert data into an array, assuming float numbers if no dtype is given.

    Args:
        data (:class:`~numpy.ndarray`):
            The data that needs to be converted to a number array. This can also be any
            iterable of numbers.
        dtype (numpy dtype):
            The data type of the field. All the numpy dtypes are supported. If omitted,
            it will be :class:`~numpy.double` unless `data` contains complex numbers in
            which case it will be :class:`~numpy.cdouble`.
        copy (bool):
            Whether the data must be copied (in which case the original array is left
            untouched). The default `None` implies that data is only copied if
            necessary, e.g., when changing the dtype.

    Returns:
        :class:`~numpy.ndarray`: An array with the correct dtype
    """
    if np.__version__.startswith("1") and copy is None:
        copy = False  # fall-back for numpy 1

    if dtype is None:
        # dtype needs to be determined automatically
        try:
            # convert the result to a numpy array with the given dtype
            result = np.array(data, dtype=get_common_dtype(data), copy=copy)
        except TypeError:
            # Conversion can fail when `data` contains a complex sympy number, i.e.,
            # sympy.I. In this case, we simply try to convert the expression using a
            # complex dtype
            result = np.array(data, dtype=np.cdouble, copy=copy)

    else:
        # a specific dtype is requested
        result = np.array(data, dtype=np.dtype(dtype), copy=copy)

    return result  # type: ignore

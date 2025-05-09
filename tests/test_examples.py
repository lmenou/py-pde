"""
.. codeauthor:: David Zwicker <david.zwicker@ds.mpg.de>
"""

import os
import subprocess as sp
import sys
from pathlib import Path

import pytest

from pde.tools.misc import module_available
from pde.visualization.movies import Movie

PACKAGE_PATH = Path(__file__).resolve().parents[1]
EXAMPLES = (PACKAGE_PATH / "examples").glob("*/*.py")
NOTEBOOKS = (PACKAGE_PATH / "examples").glob("*/*.ipynb")

SKIP_EXAMPLES: list[str] = []
if not Movie.is_available():
    SKIP_EXAMPLES.extend(["make_movie_live.py", "make_movie_storage.py", "storages.py"])
if not module_available("mpi4py"):
    SKIP_EXAMPLES.extend(["mpi_parallel_run"])
if not module_available("napari"):
    SKIP_EXAMPLES.extend(["tracker_interactive", "show_3d_field_interactively"])
if not module_available("h5py"):
    SKIP_EXAMPLES.extend(["trajectory_io"])
if not all(module_available(m) for m in ["modelrunner", "h5py"]):
    SKIP_EXAMPLES.extend(["py_modelrunner"])
if not module_available("utilitiez"):
    SKIP_EXAMPLES.extend(["logarithmic_kymograph"])


@pytest.mark.slow
@pytest.mark.no_cover
@pytest.mark.skipif(sys.platform == "win32", reason="Assumes unix setup")
@pytest.mark.parametrize("path", EXAMPLES)
def test_example_scripts(path):
    """Runs an example script given by path."""
    # check whether this test needs to be run
    if path.name.startswith("_"):
        pytest.skip("skip examples starting with an underscore")
    if any(name in str(path) for name in SKIP_EXAMPLES):
        pytest.skip(f"Skip test {path}")

    # run the actual test in a separate python process
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_PATH) + ":" + env.get("PYTHONPATH", "")
    proc = sp.Popen([sys.executable, path], env=env, stdout=sp.PIPE, stderr=sp.PIPE)
    try:
        outs, errs = proc.communicate(timeout=30)
    except sp.TimeoutExpired:
        proc.kill()
        outs, errs = proc.communicate()

    # delete files that might be created by the test
    try:
        (PACKAGE_PATH / "diffusion.mov").unlink()
        (PACKAGE_PATH / "allen_cahn.avi").unlink()
        (PACKAGE_PATH / "allen_cahn.hdf").unlink()
    except OSError:
        pass

    # prepare output
    msg = f"Script `{path}` failed with following output:"
    if outs:
        msg = f"{msg}\nSTDOUT:\n{outs}"
    if errs:
        msg = f"{msg}\nSTDERR:\n{errs}"
    assert proc.returncode <= 0, msg


@pytest.mark.slow
@pytest.mark.no_cover
@pytest.mark.skipif(not module_available("h5py"), reason="requires `h5py`")
@pytest.mark.skipif(not module_available("jupyter"), reason="requires `jupyter`")
@pytest.mark.skipif(not module_available("notebook"), reason="requires `notebook`")
@pytest.mark.parametrize("path", NOTEBOOKS)
def test_jupyter_notebooks(path, tmp_path):
    """Run the jupyter notebooks."""
    import notebook as jupyter_notebook

    if int(jupyter_notebook.__version__.split(".")[0]) < 7:
        raise RuntimeError("Jupyter notebooks must be at least version 7")

    if path.name.startswith("_"):
        pytest.skip("Skip examples starting with an underscore")

    # adjust python environment
    my_env = os.environ.copy()
    my_env["PYTHONPATH"] = str(PACKAGE_PATH) + ":" + my_env.get("PYTHONPATH", "")

    # run the notebook
    sp.check_call([sys.executable, "-m", "jupyter", "execute", path], env=my_env)

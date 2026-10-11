"""The project has to install on Windows, which is a measurement machine.

`uv run` is how every launcher reaches Python, so a dependency that cannot
install on Windows does not fail one lane. It fails `make lint`'s privacy step,
the whole suite, and serve-llamacpp.sh's call to `harness.context`, which is
what sizes a GGUF. The last of those is silent: the launcher has a WARN path,
so the store's slot plan simply stops arriving and the server runs at a
default slot count instead. #758.

A grep over pyproject.toml rather than an install, for the reason
test_services_windows gives: the alternative is resolving the project on a
Windows runner inside this test, and the failure being guarded against is
visible in the text.
"""
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "pyproject.toml"
OCR = REPO / "harness" / "checks" / "ocr.py"

#: The last CPython winsdk publishes a wheel for, and the first it does not.
#: Everything from the latter up resolves to the sdist, which scikit-build
#: cannot configure without Visual Studio.
WINSDK_LAST_WHEEL = "3.12"
WINSDK_FIRST_WHEELLESS = "3.13"


def _dependencies():
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]


def _requirement(name):
    for line in _dependencies():
        if line.split(";")[0].strip().lower().startswith(name):
            return line
    return None


def test_winsdk_is_bound_to_the_pythons_it_has_wheels_for():
    """THE FAILURE THIS FILE EXISTS FOR.

    winsdk ships wheels for cp38 through cp312. requires-python allows 3.13,
    so uv resolves 3.13 where nothing is pinned, finds no wheel, and tries to
    build from source:

        scikit-build could not get a working generator for your system
        Building windows wheels requires Microsoft Visual Studio

    and the entire project becomes uninstallable on Windows over an optional
    OCR binding.
    """
    line = _requirement("winsdk")
    assert line, "winsdk is no longer a dependency; drop this test with it"
    assert f"python_version < '{WINSDK_FIRST_WHEELLESS}'" in line, (
        "bound winsdk to the Pythons it publishes wheels for, or Windows "
        f"resolves above {WINSDK_LAST_WHEEL} and builds from source: {line}")


def test_the_windows_ocr_binding_stays_optional_in_code():
    """The marker above is only safe because nothing imports winsdk at module
    scope. If that changes, bounding the marker turns an uninstallable project
    into one that fails at import instead, which is not an improvement."""
    text = OCR.read_text(encoding="utf-8")
    top_level = [line for line in text.splitlines()
                 if line.startswith(("import winsdk", "from winsdk"))]
    assert not top_level, (
        "winsdk is imported at module scope, so it is no longer optional: "
        + "; ".join(top_level))
    assert "ImportError" in text, (
        "the optional-binding probe should still swallow a missing binding")


def test_requires_python_still_admits_a_version_winsdk_has_wheels_for():
    """Bounding the marker means Windows above 3.12 loses the OCR backend. That
    is only acceptable while a contributor who wants it can still choose a
    Python that has it."""
    spec = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["requires-python"]
    assert ">=3.11" in spec, (
        f"nothing winsdk has a wheel for is allowed any more: {spec}")


@pytest.mark.skipif(sys.platform != "win32", reason="the install this guards is Windows only")
def test_the_context_planner_imports_without_the_windows_binding():
    """What the node actually needs. harness.context sizes a GGUF and must not
    depend on an OCR binding to do it."""
    import importlib

    importlib.import_module("harness.context")

"""`soh gauntlet audit|review`: closed defects with no class, and the review questions a diff raises. #492."""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

from harness.commands.common import emit, err

#: The checkout this harness runs from; the gauntlet registry lives in its tests/.
CHECKOUT = Path(__file__).resolve().parents[2]
REGISTRY = "tests.gauntlet.registry:REGISTRY"


def _gauntlet():
    if str(CHECKOUT) not in sys.path:
        sys.path.insert(0, str(CHECKOUT))
    from gauntlet import cli
    return cli


def cmd_gauntlet(a) -> int:
    """Run the pinned gauntlet package's `<action>` over this checkout's registry, as text or as one --json object."""
    if not (CHECKOUT / "tests" / "gauntlet" / "registry.py").is_file():
        return err(f"soh gauntlet needs a SoHoT checkout; {CHECKOUT} has no tests/gauntlet/registry.py")
    try:
        gauntlet = _gauntlet()
    except ImportError:
        return err("soh gauntlet needs the gauntlet package: `uv sync` installs it with the dev group")
    argv = [a.action, "--registry", REGISTRY]
    if a.action == "audit":
        if a.range:
            return err("audit takes no range; name its history with --ref")
        argv += (["--offline"] if a.offline else []) + (["--ref", a.ref] if a.ref else [])
    elif a.offline or a.ref:
        return err("--offline and --ref are for audit; review takes a git range")
    elif a.range:
        argv.append(a.range)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = gauntlet.main(argv)
    if a.json:
        emit(rc == 0, action=a.action, report=out.getvalue().rstrip("\n"))
    else:
        print(out.getvalue(), end="")
    return rc

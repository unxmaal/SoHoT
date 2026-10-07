"""`soh gauntlet audit|review`: closed defects with no class, and the review questions a diff raises. #492."""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

from harness.commands.common import emit, err

#: The checkout this harness runs from; the gauntlet registry lives in its tests/.
CHECKOUT = Path(__file__).resolve().parents[2]


def _gauntlet():
    if not (CHECKOUT / "tests" / "gauntlet").is_dir():
        return None
    if str(CHECKOUT) not in sys.path:
        sys.path.insert(0, str(CHECKOUT))
    from tests.gauntlet import __main__ as gauntlet
    return gauntlet


def cmd_gauntlet(a) -> int:
    """Run `python -m tests.gauntlet <action>` from this checkout, as text or as one --json object."""
    gauntlet = _gauntlet()
    if gauntlet is None:
        return err(f"soh gauntlet needs a SoHoT checkout; {CHECKOUT} has no tests/gauntlet")
    argv = [a.action]
    if a.action == "audit":
        argv += (["--offline"] if a.offline else []) + (["--ref", a.range] if a.range else [])
    elif a.offline:
        return err("--offline is for audit; review reads only git")
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

"""One place for everything this project produces.

THERE WERE FOUR, and one of them was relative:

    out/                  the CLI, relative to whatever directory you ran it in
    ~/localharness-out/   the MCP server
    .logs/                eval runs, mixed in with the service logs
    /tmp/                 whatever anyone was doing at the time

The relative one is the worst. `lh` installs onto PATH and runs from anywhere,
so `out/` scattered artifacts into every directory anyone happened to be
standing in, and a generation you cannot find is a generation you did not make.

    $LOCALHARNESS_HOME              default ~/localharness
      out/                          artifacts: images, audio, svg, pages
      out/mcp/                      artifacts asked for over MCP
      runs/<stamp>-<modality>/      one eval run: its artifacts and results.json
      logs/                         service stdout and stderr

`out` and `logs` are kept apart because a generated artifact and a server's
stderr are different things and only one of them is worth keeping.
"""
from __future__ import annotations

import itertools
import os
import subprocess
import sys
import time
from pathlib import Path

#: Process-local tiebreak. The stamp has millisecond resolution, but a caller
#: can ask for two names inside one millisecond and NEITHER file exists yet, so
#: an existence check alone hands back the same name twice.
_SEQ = itertools.count()

ENV_VAR = "LOCALHARNESS_HOME"
DEFAULT_HOME = Path.home() / "localharness"


def home() -> Path:
    """The single root. Absolute, always: see the module docstring."""
    raw = os.environ.get(ENV_VAR)
    return (Path(raw).expanduser().resolve() if raw else DEFAULT_HOME)


#: The checkout this code was imported from.
REPO = Path(__file__).resolve().parents[1]
#: Set to 1 to let a non-deploy checkout migrate the live store anyway. #455.
ALLOW_MIGRATE_ENV = "LH_ALLOW_MIGRATE"


def is_live(path: Path) -> bool:
    """Is this the store the deployed services use: discovery.db under the default home."""
    return Path(path).resolve() == (DEFAULT_HOME / "discovery.db").resolve()


def deploy_checkout() -> Path | None:
    """Where the services run from, as scripts/launchd.sh defines it; None without launchd."""
    if sys.platform == "win32":
        return None
    try:
        out = subprocess.run(["bash", str(REPO / "scripts" / "launchd.sh"), "deploy-path"],
                             capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    got = out.stdout.strip()
    return Path(got).resolve() if got else None


def runs_elsewhere() -> Path | None:
    """The deploy checkout, when this machine has one and this code is not it."""
    deploy = deploy_checkout()
    if deploy is None or deploy == REPO or not (deploy / ".git").exists():
        return None
    return deploy


def _sub(name: str) -> Path:
    d = home() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def outputs() -> Path:
    """Artifacts a person or an agent asked for and will want again."""
    return _sub("out")


def runs() -> Path:
    """Eval runs, one directory each."""
    return _sub("runs")


def logs() -> Path:
    """Service stdout and stderr. Not outputs; deletable at any time."""
    return _sub("logs")


def stamp() -> str:
    """Sortable, and unique to the millisecond.

    Milliseconds because two `lh image` calls a second apart must not overwrite
    each other, and losing a generation to a name collision is the kind of thing
    noticed much later, if at all.
    """
    return time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"


def artifact(kind: str, suffix: str, where: Path | None = None) -> Path:
    """`<out>/image-20260907-142233-041.png`."""
    base = where if where is not None else outputs()
    base.mkdir(parents=True, exist_ok=True)
    while True:
        out = base / f"{kind}-{stamp()}-{next(_SEQ):04d}{suffix}"
        # The counter settles same-process collisions; the existence check
        # settles two processes writing into one directory.
        if not out.exists():
            return out


def new_run(modality: str) -> Path:
    """A directory for one eval run, named so `ls` reads chronologically."""
    while True:
        d = runs() / f"{stamp()}-{next(_SEQ):04d}-{modality}"
        if not d.exists():
            d.mkdir(parents=True)
            return d

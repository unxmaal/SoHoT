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
import tempfile
from threading import local
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


_asking = local()


def deploy_checkout() -> Path | None:
    """Where the services run from, as scripts/launchd.sh defines it; None without launchd."""
    if sys.platform == "win32" or getattr(_asking, "now", False):
        return None  # the cut a timed-out lookup records asks again; it must not wait another timeout
    from harness import cuts
    _asking.now = True
    try:
        with cuts.timeout("harness/paths.py:deploy_checkout->subprocess.run(timeout)", "the deploy path lookup"):
            out = subprocess.run(["bash", str(REPO / "scripts" / "launchd.sh"), "deploy-path"],
                                 capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        _asking.now = False
    got = out.stdout.strip()
    return Path(got).resolve() if got else None


def runs_elsewhere() -> Path | None:
    """The deploy checkout, when this machine has one and this code is not it."""
    deploy = deploy_checkout()
    if deploy is None or deploy == REPO or not (deploy / ".git").exists():
        return None
    return deploy


def live_from_elsewhere(path: Path) -> bool:
    """Is `path` the live store while this code is not the deploy checkout: rows written here would pass for its work."""
    return is_live(path) and runs_elsewhere() is not None


class LiveHomeRefused(RuntimeError):
    """An eval or probe was pointed at the live home without saying it means to write it. #1346"""


#: Set by an eval or probe that must read this home: it then records no cut or usage rows. #1346
EVAL_ENV = "LH_EVAL_RUN"


def evaluating() -> bool:
    return os.environ.get(EVAL_ENV) == "1"


def eval_home(scratch: Path | None = None, *, live: bool = False, reads_live: bool = False) -> Path:
    """The home an eval or probe runs in: a scratch one unless a non-live home was named, `live`, or `reads_live`. #1346"""
    from harness import purpose
    purpose.set_process(purpose.EVAL)
    if live:
        return home()
    if reads_live:
        os.environ[EVAL_ENV] = "1"
        return home()
    if os.environ.get(ENV_VAR):
        if is_live(home() / "discovery.db"):
            raise LiveHomeRefused(f"{ENV_VAR} names the live home {home()}; an eval or probe writes only a "
                                  f"scratch home unless told to write the live one (--live-home)")
        return home()
    where = Path(scratch).expanduser() if scratch else Path(tempfile.mkdtemp(prefix="soh-eval-"))
    where = where.resolve()
    if is_live(where / "discovery.db"):
        raise LiveHomeRefused(f"{where} is the live home, not a scratch one")
    where.mkdir(parents=True, exist_ok=True)
    os.environ[ENV_VAR] = str(where)
    return where


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


def unused_run(stamp: str, suffix: str = "") -> Path:
    """A run directory under runs() that no other run holds, created here: stamp, then stamp.2, stamp.3, ... #1443."""
    n = 1
    while True:
        got = runs() / f"{stamp}{f'.{n}' if n > 1 else ''}{suffix}"
        try:
            got.mkdir(parents=True)
            return got
        except FileExistsError:
            n += 1


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

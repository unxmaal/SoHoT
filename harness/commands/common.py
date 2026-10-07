"""What every verb shares: err, say, note and emit, and the --json contract they keep. #329."""
from __future__ import annotations

from pathlib import Path
import json
import sys

from harness import paths


#: Set by main() from --json. A module global because every verb reports
#: through err()/say(), and threading a flag through nine functions to reach
#: two print statements is worse than this.
_JSON = False
_VERB = ""


def err(msg: str) -> int:
    """Report a failure. Under --json it is DATA on stdout, not a stderr line.

    An agent that has to read stderr to discover something went wrong will not
    read stderr. The exit code stays 1 either way.
    """
    if _JSON:
        print(json.dumps({"ok": False, "verb": _VERB, "error": msg}))
    else:
        print(msg, file=sys.stderr)
    return 1


def say(*, path=None, body=None, seconds=None, peak_kb=None, size=None,
        human: str = "", method: dict | None = None) -> int:
    """Report a success, in whichever shape the caller asked for; `method` is a served method's cost."""
    if _JSON:
        out = {"ok": True, "verb": _VERB}
        if path is not None:
            out["path"] = str(path)
        if body is not None:
            out["body"] = body
        if seconds is not None:
            out["seconds"] = round(seconds, 3)
        if peak_kb:
            out["peak_gib"] = round(peak_kb / 1024 / 1024, 2)
        if size is not None:
            out["size"] = size
        if method:
            out["method"] = method
        print(json.dumps(out))
    else:
        print(human)
        if method:
            print(method_note(method), file=sys.stderr)
    return 0


def method_note(method: dict) -> str:
    """One line on what a served method cost, for stderr."""
    extra = (f", kept sample {method['chosen']} of {method['samples']}"
             if method.get("samples") else "")
    return f"[{method['method']} over {method['base']}: {method['calls']} calls{extra}]"


def note(*args, **kw) -> None:
    """Human text. Under --json it goes to stderr so stdout stays one object."""
    print(*args, file=sys.stderr if _JSON else sys.stdout, **kw)


def emit(ok: bool = True, **data) -> None:
    """Under --json, the verb's result as one object on stdout. #329."""
    if _JSON:
        print(json.dumps({"ok": ok, "verb": _VERB, **data}, default=str))


def default_output(kind: str, suffix: str) -> Path:
    """Where an artifact goes when the caller did not say.

    Under $LOCALHARNESS_HOME/out, which is ABSOLUTE. It used to be a relative
    `out/`, and since `lh` installs onto PATH and runs from anywhere, that
    scattered artifacts into whatever directory the caller happened to be
    standing in.
    """
    return paths.artifact(kind, suffix)

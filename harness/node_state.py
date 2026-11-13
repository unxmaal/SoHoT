"""A node's own lock, memory and interactive load, reported over the ssh its deploys use; the queue admits its batch work by it. #1689, #713."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from harness.atomic_file import replace
from harness import paths

GIB = 1024 ** 3
#: How long the Studio trusts a node's report before it asks the node again.
FRESH_S = 30.0
#: How long the ssh that reads a node's report may take.
READ_TIMEOUT_S = 30.0


def _busy(get, stems) -> int | None:
    """Slots processing a request on the node's own server, over its pinned stems; None when it will not say."""
    total = 0
    for stem in stems:
        try:
            slots = get(f"/slots?model={stem}")
        except Exception:  # noqa: BLE001 - a server that will not say has an unknown load
            return None
        total += sum(1 for s in slots or [] if isinstance(s, dict) and s.get("is_processing"))
    return total


def served_file(path) -> dict:
    """{size, mtime_ns, sha256} of a pinned GGUF now; sha256 only when this node already hashed these bytes. #1775."""
    from harness import identity
    if not path:
        return {}
    try:
        _, size, mtime = identity.file_stat(path)
        return {"size": size, "mtime_ns": mtime, "sha256": identity.cached_digest(path)}
    except OSError as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def report(get=None, sample=None) -> dict:
    """What this node says about itself: pressure, budget, pinned set, its lock and the interactive requests in flight."""
    from harness import exclusive, interactive, memory, pressure, router, serving
    plan = interactive.read()
    lanes = plan.get("lanes") or {}
    base = serving.bare(str(plan.get("url") or interactive.url()))
    ask = interactive._ask(base, get) or (lambda path: router._get(path, base))
    held = router.statuses(ask, base=base) or {}
    p = (sample or pressure.sample)()
    ceiling = memory.ceiling_gb()
    reserve = memory.reserve_for(memory.detect())
    pinned = float(plan.get("bytes") or 0) / GIB
    lock = exclusive.holder() if exclusive._taken(exclusive.lock_path()) else {}
    models = {e["stem"]: {"lane": lane, "ctx": int(e.get("ctx") or 0) or None, "slots": int(e.get("slots") or 0) or None,
                          "resident": held.get(e["stem"]) in router.RESIDENT, "file": served_file(e.get("path"))}
              for lane, e in lanes.items()}
    return {"at": time.time(), "level": p.level, "alarming": p.alarming, "available_gb": round(memory.available_gb(), 2),
            "ceiling_gb": round(ceiling, 2), "reserve_gb": reserve, "pinned_gb": round(pinned, 2),
            "room_gb": round(ceiling - reserve - pinned, 2), "lock": lock, "models": models,
            "interactive": _busy(ask, sorted(models))}


def _path(name: str) -> Path:
    return paths.home() / "nodes" / f"{name}.state.json"


def cached(name: str) -> dict:
    """The last report read from the node, {} for none."""
    try:
        got = json.loads(_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def read(node, runner=None, now=None, fresh_s: float = FRESH_S) -> dict:
    """The node's report, asked over its deploy ssh when the cached one is older than fresh_s; {"error"} when it cannot."""
    from harness import node_deploy
    now = time.time() if now is None else now
    got = cached(node.name)
    if got.get("read_at") and now - float(got["read_at"]) < fresh_s:
        return got
    if not node.ssh:
        return {"error": f"node {node.name} has no deploy: ssh in nodes.yaml, so it cannot report its state"}
    rc, said = (runner or node_deploy._ssh)(node_deploy.ssh_argv(node, "state", node.deploy_dir), node_deploy.SCRIPT,
                                             READ_TIMEOUT_S)
    line = next((ln for ln in reversed((said or "").splitlines()) if ln.startswith("{")), "")
    try:
        got = json.loads(line) if rc == 0 else None
    except ValueError:
        got = None
    if not isinstance(got, dict):
        return {"error": f"node {node.name} did not report its state (ssh rc {rc}): {node_deploy._tail(said)}"}
    got["read_at"] = now
    _path(node.name).parent.mkdir(parents=True, exist_ok=True)
    tmp = _path(node.name).with_suffix(".tmp")
    tmp.write_text(json.dumps(got, sort_keys=True), encoding="utf-8")
    replace(tmp, _path(node.name))
    return got


def served_by(spec: str, config=None) -> tuple[str, str]:
    """(node, the id the node is sent) a gateway candidate's served entry goes to first; ("", "") when this machine serves it."""
    from harness import context, gateway, nodes
    entry = context._entry_for((spec or "").partition(",")[0].strip(), config) or {}
    if not entry.get(nodes.NODE_KEY):
        return "", ""
    return str(entry[nodes.NODE_KEY]), gateway.strip_provider(str((entry.get("litellm_params") or {}).get("model") or ""))


def placed(specs, config=None) -> tuple[str, list[str]]:
    """(node, its model ids) when every candidate is served by one node first, so the batch loads nothing here; else ("", [])."""
    got = [served_by(s, config) for s in specs]
    names = {n for n, _ in got}
    if not got or len(names) != 1 or "" in names:
        return "", []
    return names.pop(), [m for _, m in got]


def node(name: str, load=None):
    """The unparked node of that name in nodes.yaml, else None."""
    from harness import nodes
    try:
        return next((n for n in (load or nodes.load)() if n.name == name), None)
    except ValueError:
        return None


def admits(name: str, models=(), load=None, read_fn=None, held_fn=None) -> tuple[bool, str]:
    """(admitted, why) for batch work on a node: its report reads, pressure normal, no lock or interactive load, models held."""
    from harness import serve_lease
    found = node(name, load)
    if found is None:
        return False, f"node {name} is not an unparked node in nodes.yaml"
    who = (held_fn or serve_lease.held)(node=name)
    if who:
        return False, f"node {name} is serving {who}; interactive work comes first"
    got = (read_fn or read)(found)
    if got.get("error"):
        return False, got["error"]
    if got.get("alarming"):
        return False, f"node {name} memory pressure level {got.get('level')}, not normal"
    if got.get("lock"):
        return False, f"node {name}'s own lock is held by {got['lock'].get('kind') or 'a process'} pid {got['lock'].get('pid')}"
    if got.get("interactive") is None:
        return False, f"node {name} did not say what its interactive server is doing"
    if got["interactive"]:
        return False, f"node {name} is answering {got['interactive']} interactive request(s); they come first"
    held = {stem for stem, m in (got.get("models") or {}).items() if m.get("resident")}
    missing = [m for m in models if m not in held]
    if missing:
        return False, (f"node {name} does not hold {', '.join(missing)} and loads nothing beside its pinned set "
                       f"({got.get('room_gb')} GiB of room); a harness limit, never the model's")
    return True, f"node {name} free: pressure level {got.get('level')}, {got.get('room_gb')} GiB of room"


def cap(name: str, model: str) -> int | None:
    """The slots a node last reported serving a model with, by the id it is sent; None when it has not said. #754."""
    return ((cached(name).get("models") or {}).get(model) or {}).get("slots") or None


if __name__ == "__main__":
    json.dump(report(), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")

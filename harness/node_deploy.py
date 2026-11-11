"""After this machine deploys a sha, each unparked node with a `deploy:` in nodes.yaml is brought to it over ssh. #1692."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from harness import cuts, deploy, deploy_switch, paths
from harness import nodes as nodes_mod
from harness import workqueue as wq

DEPLOYED, CURRENT, ROLLED_BACK, FAILED = "deployed", "current", "rolled_back", "failed"
DOWN, UNCONFIGURED, INSTALLING, REFUSED = "down", "unconfigured", "installing", "refused"
#: Outcomes the next deploy poll tries again; the others wait for the next deploy of this machine.
RETRY = frozenset({DOWN, UNCONFIGURED})
#: ssh's exit status when it could not reach or log in to the node.
SSH_DOWN = 255
CONNECT_TIMEOUT_S = 10
#: How long reading the node's checkout head, role file or loaded units may take.
HEAD_TIMEOUT_S = 60.0
#: How long the node's checkout, `uv sync --frozen` and `launchd.sh reinstall` may take.
INSTALL_TIMEOUT_S = 1800.0
#: How long a reinstalled node may take to answer /models before its smoke.
WARM_S = 300.0
WARM_POLL_S = 5.0
LOG = "deploy-nodes.log"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SAID = re.compile(r"^(role|want|loaded|disabled)(?: (\S*))?$")

#: Sent on stdin to `bash -s -- head|units|state DIR` or `install DIR SHA ROLE`, DIR "" for the node's own; a non-login PATH lacks uv.
SCRIPT = r"""set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
home="${LOCALHARNESS_HOME:-$HOME/localharness}"
dir="${2:-$home/deploy}"
case "$dir" in "~") dir="$HOME" ;; "~/"*) dir="$HOME/${dir#\~/}" ;; esac
role() { printf 'role %s\n' "$(if [ -f "$home/role" ]; then tr -d '[:space:]' < "$home/role"; fi)"; }
cd "$dir"
if [ "$1" = head ]; then git rev-parse HEAD; role; exit 0; fi
if [ "$1" = units ]; then
  role; LH_ROLE= bash scripts/launchd.sh units 2>&1 || true
  printf 'machine %s\n' "$({ uv run --no-sync python -m harness.nodes fingerprint 2>/dev/null || true; } | tail -n 1)"
  exit 0
fi
if [ "$1" = state ]; then exec uv run --no-sync python -m harness.node_state; fi
git cat-file -e "$3^{commit}" 2>/dev/null || git fetch -q origin main
git checkout -q --detach "$3"
test "$(git rev-parse HEAD)" = "$3"
uv sync --frozen
LH_ROLE="$4" LH_DEPLOY="$dir" bash scripts/launchd.sh reinstall
"""


def ssh_argv(node: nodes_mod.Node, *args: str) -> list[str]:
    argv = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={CONNECT_TIMEOUT_S}",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=4"]
    if node.ssh_key:
        argv += ["-i", str(Path(node.ssh_key).expanduser()), "-o", "IdentitiesOnly=yes"]
    return [*argv, node.ssh, "bash -s -- " + shlex.join(args)]


def _ssh(argv: list[str], script: str, timeout: float) -> tuple[int | None, str]:
    """(rc, stdout and stderr), or (None, why) when ssh could not run or ran out of time."""
    try:
        got = subprocess.run(argv, input=script, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout:.0f} s"
    except OSError as exc:
        return None, f"could not run ssh: {exc}"
    return got.returncode, (got.stdout or "") + (got.stderr or "")


def _smoke(node: nodes_mod.Node) -> list[tuple[bool, str]]:
    from harness import completion, gateway_key
    return nodes_mod.smoke(completion.gateway_url(), gateway_key.key(), [node])


class StudioSide(str):
    """Why verify passed a node that answers itself but not through this machine's gateway: no rollback. #1791."""


def _direct(node: nodes_mod.Node, ask) -> list[str]:
    out = []
    for model in node.models:
        try:
            r = ask(node, model)
        except Exception as exc:  # noqa: BLE001 - any failure to answer is the node's
            out.append(f"node {node.name} {model}: did not answer when asked directly ({exc})")
            continue
        if r.status_code >= 400:
            out.append(f"node {node.name} {model}: HTTP {r.status_code} when asked directly")
    return out


def verify(node: nodes_mod.Node, *, get=None, smoke=None, ask=None, sleep=time.sleep, clock=time.monotonic) -> str:
    """'' when the node passes `nodes check`, answers /models within WARM_S and passes `nodes smoke`; else why. #1791."""
    why = nodes_mod.unidentified(node)
    if why:
        return f"nodes check: {why}"
    end = clock() + WARM_S
    while not nodes_mod._probe(node, get or nodes_mod._get_models)[0]:
        if clock() >= end:
            cuts.cut("harness/node_deploy.py:WARM_S", f"node {node.name} not answering after its install", dropped=1)
            return f"node {node.name} did not answer {node.api_base}/models within {WARM_S:.0f} s of its install"
        sleep(WARM_POLL_S)
    smoke = smoke or _smoke
    bad = [line for ok, line in smoke(node) if not ok]
    if bad and all(isinstance(b, nodes_mod.ViaGateway) for b in bad):
        # The gateway holds a node it saw go down during the install out of routing for its cooldown.
        sleep(node.cooldown + WARM_POLL_S)
        bad = [line for ok, line in smoke(node) if not ok]
    if not bad:
        return ""
    if any(not isinstance(b, nodes_mod.ViaGateway) for b in bad):
        return "nodes smoke: " + "; ".join(bad)
    failed = _direct(node, ask or nodes_mod.ask_node)
    if failed:
        return "nodes smoke: " + "; ".join(bad + failed)
    return StudioSide(f"node {node.name} answers {', '.join(node.models)} itself, but this machine's gateway does not "
                      f"serve them from it: " + "; ".join(bad))


def _tail(said: str, n: int = 300) -> str:
    lines = [ln.strip() for ln in (said or "").splitlines() if ln.strip()]
    return (" | ".join(lines[-3:]) or "no output")[-n:]


def target(conn=None) -> dict | None:
    """This machine's newest deploy that ended deployed, None while a deploy runs or before the first: what nodes follow."""
    with wq._store(conn) as c:
        where, args = wq._here(c)
        rows = c.execute(f"SELECT id, sha, outcome FROM deploys WHERE {where} ORDER BY id DESC", args).fetchall()
    if not rows or not rows[0]["outcome"]:
        return None
    hit = next((r for r in rows if r["outcome"] == deploy.DEPLOYED), None)
    return {"id": int(hit["id"]), "sha": hit["sha"]} if hit else None


def _due(prior: dict, retry: bool) -> bool:
    got = prior.get("outcome")
    if not prior or got in RETRY:
        return True
    if got == INSTALLING:
        return not wq.alive(int(prior.get("pid") or 0))
    return retry and got in (ROLLED_BACK, FAILED, REFUSED)


def _said(said: str) -> dict[str, list[str]]:
    got: dict[str, list[str]] = {}
    for ln in (said or "").splitlines():
        m = _SAID.match(ln.strip())
        if m:
            got.setdefault(m[1], []).append(m[2] or "")
    return got


def choose_role(node: nodes_mod.Node, persisted: str) -> tuple[str, str]:
    """(LH_ROLE, "") from deploy.role, else the node's own role file; ("", why) when neither says or they disagree. #1707."""
    if node.role:
        return node.role, ""
    fix = f"set deploy: role: for it in {nodes_mod.path()}"
    if not persisted:
        return "", f"node {node.name} has no role file and no deploy role, so nothing says which units it runs; {fix}"
    if persisted not in nodes_mod.ROLES:
        return "", f"node {node.name}'s role file says {persisted!r}, not one of {', '.join(nodes_mod.ROLES)}; {fix}"
    if node.lanes and persisted != "interactive":
        return "", f"node {node.name} has lanes:, so it is interactive, but its role file says {persisted}; {fix}"
    return persisted, ""


def units_match(node: nodes_mod.Node, role: str, runner, log, *, strict: bool = True) -> tuple[int | None, str]:
    """(ssh rc, "") when the node's role file says ROLE and its loaded SoHoT units are exactly ROLE's set; else why. #1707."""
    rc, said = runner(ssh_argv(node, "units", node.deploy_dir), SCRIPT, HEAD_TIMEOUT_S)
    log.write(f"--- node {node.name} units rc {rc}\n{said}\n")
    if rc != 0:
        return rc, f"could not list its units (ssh rc {rc}): {_tail(said)}"
    got = _said(said)
    have = (got.get("role") or [""])[-1]
    if have != role:
        return rc, f"its role file says {have or 'nothing'}, not {role}"
    want = set(got.get("want") or [])
    if not want:
        return rc, f"its launchd.sh lists no units for {role}: {_tail(said)}" if strict else ""
    loaded = set(got.get("loaded") or [])
    extra, missing = sorted(loaded - want), sorted(want - loaded - set(got.get("disabled") or []))
    parts = ([f"extra {', '.join(extra)}"] if extra else []) + ([f"missing {', '.join(missing)}"] if missing else [])
    if parts:
        return rc, f"its loaded units are not the {role} set: {'; '.join(parts)}"
    return rc, same_machine(node, said, strict=strict)


def same_machine(node: nodes_mod.Node, said: str, *, strict: bool = True) -> str:
    """'' when the fingerprint the node reports for itself is the one nodes.yaml names; else why, naming both. #1791."""
    from harness import machine
    if not node.fingerprint:
        return ""
    have = next((ln.strip()[len("machine"):].strip() for ln in reversed((said or "").splitlines())
                 if ln.strip() == "machine" or ln.strip().startswith("machine ")), "")
    if not have:
        return "it did not report its machine fingerprint (`python -m harness.nodes fingerprint`)" if strict else ""
    got = machine.parse_fingerprint(have)
    real = machine.fingerprint(got["hw_model"], got["os"], got["arch"], got["host"]) if got else have
    if real == node.fingerprint:
        return ""
    return (f"machine fingerprint mismatch: {node.ssh} reports {real}, but {nodes_mod.path().name} names node "
            f"{node.name} {node.fingerprint}; its replies would be filed under the wrong machine")


def _one(node: nodes_mod.Node, sha: str, prior: dict, *, runner, check, alert, log, mark, now) -> dict:
    base = {"sha": sha, "at": now(), "tries": int(prior.get("tries") or 0) + 1}
    if not node.ssh:
        return {**base, "outcome": UNCONFIGURED, "detail": f"no deploy: ssh in {nodes_mod.path()}, so no deploy reaches it"}
    rc, said = runner(ssh_argv(node, "head", node.deploy_dir), SCRIPT, HEAD_TIMEOUT_S)
    log.write(f"--- node {node.name} head rc {rc}\n{said}\n")
    if rc in (SSH_DOWN, None):
        return {**base, "outcome": DOWN, "previous_sha": prior.get("previous_sha", ""), "started": prior.get("started", False),
                "previous_role": prior.get("previous_role", ""),
                "detail": f"ssh {node.ssh}: {_tail(said)}; tried again at the next deploy poll"}
    head = next((ln.strip() for ln in reversed(said.splitlines()) if _SHA.match(ln.strip())), "")
    if rc != 0 or not head:
        return {**base, "outcome": FAILED, "detail": f"no git checkout at {node.deploy_dir or 'its deploy dir'} on {node.ssh}: {_tail(said)}"}
    # An install cut off part way may have checked the sha out and written the role already, so neither proves anything. #1692.
    started = bool(prior.get("started"))
    persisted = (_said(said).get("role") or [""])[-1]
    previous = (prior.get("previous_sha") or head) if started else head
    was = (prior.get("previous_role") or persisted) if started else persisted
    role, why = choose_role(node, was)
    if why:
        out = {**base, "outcome": REFUSED, "previous_sha": previous, "detail": f"not installed: {why}"}
        alert(f"node {node.name} deploy of {sha[:12]} refused: {why}")
        return out
    if head == sha and role == persisted and not started:
        return {**base, "outcome": CURRENT, "previous_sha": head, "role": role, "detail": f"already at {sha[:12]} as {role}"}
    # Rollback puts back the role file the node had; a node that had none keeps the role it was given. #1707.
    back_role = was or role
    mark({**base, "outcome": INSTALLING, "pid": os.getpid(), "previous_sha": previous, "previous_role": was, "role": role,
          "started": True})
    rc, said = runner(ssh_argv(node, "install", node.deploy_dir, sha, role), SCRIPT, INSTALL_TIMEOUT_S)
    log.write(f"--- node {node.name} install {sha[:12]} as {role} rc {rc}\n{said}\n")
    if rc is None and said.startswith("timed out"):
        cuts.cut("harness/node_deploy.py:INSTALL_TIMEOUT_S", f"node {node.name} install of {sha[:12]}", dropped=1)
    if rc == 0:
        rc, why = units_match(node, role, runner, log)
        if rc != SSH_DOWN:
            why = why or check(node)
    elif rc != SSH_DOWN:
        why = f"install of {sha[:12]} " + (f"exited rc {rc}" if rc is not None else "") + f": {_tail(said)}"
    if rc == SSH_DOWN:
        return {**base, "outcome": DOWN, "previous_sha": previous, "previous_role": was, "started": True,
                "detail": f"ssh {node.ssh} dropped during the install: {_tail(said)}; tried again at the next deploy poll"}
    if not why or isinstance(why, StudioSide):
        if why:
            alert(f"node {node.name} deployed {sha[:12]}, but {why}")
        return {**base, "outcome": DEPLOYED, "previous_sha": previous, "previous_role": was, "role": role,
                "detail": f"serving {sha[:12]} as {role}" + (f"; {why}" if why else "")}
    rc, said = runner(ssh_argv(node, "install", node.deploy_dir, previous, back_role), SCRIPT, INSTALL_TIMEOUT_S)
    log.write(f"--- node {node.name} rollback to {previous[:12]} as {back_role} rc {rc}\n{said}\n")
    if rc != 0:
        back = f"rollback install exited rc {rc}: {_tail(said)}"
    else:
        back = units_match(node, back_role, runner, log, strict=False)[1] or check(node)
        back = "" if isinstance(back, StudioSide) else back
    out = {**base, "outcome": FAILED if back else ROLLED_BACK, "previous_sha": previous, "role": back_role,
           "detail": f"{why}; rolled back to {previous[:12]} as {back_role}" + (f", which fails too: {back}" if back else "")}
    alert(f"node {node.name} deploy of {sha[:12]} {out['outcome']}: {out['detail']}")
    return out


def follow(conn=None, *, retry: bool = False, runner=_ssh, check=verify, alert=None, load=None,
           now=time.time) -> dict:
    """Each unparked node due a deploy of the sha this machine last deployed; the record's `nodes` holds every outcome."""
    why = deploy.blocked()
    t = None if why else target(conn)
    if t is None:
        return {"deploy": None, "sha": "", "why": why or "no finished deploy of this machine to follow", "nodes": {}}
    try:
        have = (load or nodes_mod.load)()
    except ValueError as exc:
        return {"deploy": t["id"], "sha": t["sha"], "why": str(exc), "nodes": {}}
    path = deploy.record_path(t["id"])
    try:
        rec = deploy_switch.load(path)
    except (OSError, ValueError):
        rec = {"id": t["id"], "sha": t["sha"]}
    done, acted = rec.setdefault("nodes", {}), {}
    alert = alert or (lambda m: deploy._alert_script(m, "node deploy"))
    paths.logs().mkdir(parents=True, exist_ok=True)
    with open(paths.logs() / LOG, "a", encoding="utf-8") as log:
        for node in have:
            if not _due(done.get(node.name) or {}, retry):
                continue

            def mark(entry: dict, name: str = node.name) -> None:
                done[name] = entry
                deploy_switch.save(path, rec)

            got = _one(node, t["sha"], done.get(node.name) or {}, runner=runner, check=check, alert=alert, log=log,
                       mark=mark, now=now)
            mark(got)
            acted[node.name] = got
    return {"deploy": t["id"], "sha": t["sha"], "why": "", "nodes": acted}


def status(conn=None) -> dict:
    """Each node's outcome in this machine's newest deployed record."""
    t = target(conn)
    if t is None:
        return {}
    try:
        return deploy_switch.load(deploy.record_path(t["id"])).get("nodes") or {}
    except (OSError, ValueError):
        return {}


def line(name: str, r: dict) -> str:
    head = {DEPLOYED: "PASS", CURRENT: "PASS", DOWN: "WARN", UNCONFIGURED: "SKIP", INSTALLING: "RUN "}.get(
        r.get("outcome"), "FAIL")
    return f"{head}  node {name} {r.get('outcome')} at {str(r.get('sha', ''))[:12]}: {r.get('detail', '')}"

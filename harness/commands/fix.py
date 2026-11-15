"""`soh fix`: one issue planned in the cloud, made to pass locally and gated by the runner; replay over closed issues (#2035)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("fix", help="an issue planned by one capped claude -p call that writes a failing test, made "
                       "to pass by the local agent alias, refused unless the runner's gate holds; nothing merges. "
                       "`soh fix replay` scores closed issues; --report reads the stored rows")
    p.add_argument("target", nargs="?", default="", help="an issue number, or `replay`")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--plan-only", action="store_true", help="plan and check the test fails at base; no local step")
    mode.add_argument("--execute", action="store_true", help="plan, run the local step and the gate")
    mode.add_argument("--report", action="store_true", help="per class: resolved locally, local and cloud tokens")
    p.add_argument("--n", type=int, default=20, help="replay: in-class issues to try (default 20)")
    p.add_argument("--issues", default="", help="replay: these closed issues (comma-separated) instead of a search")
    p.add_argument("--limit", type=int, default=200, help="replay: closed issues searched for candidates")
    p.add_argument("--base", default="origin/main", help="--execute: the commit the workspace starts at")
    p.add_argument("--alias", default="", help="the gateway alias of the local step (default sohot-agent)")
    p.add_argument("--model", default="", help="the planning model (default claude-opus-5-5)")
    p.add_argument("--gateway", default="", help="gateway URL (default SOHOT_GATEWAY_URL or local)")
    p.add_argument("--attempts", type=int, default=0, help="local attempts per issue (default 2)")
    p.add_argument("--out", default="", help="workspaces and escalation handoffs (default $LOCALHARNESS_HOME/out/fix)")
    p.add_argument("--since-days", type=float, default=30.0, help="--report: rows this many days back")
    p.set_defaults(func=cmd_fix)


def _gh(*args) -> object:
    from harness import fix, paths
    rc, out = fix.run_cmd(("gh", *args), paths.REPO, timeout=60)
    if rc != 0:
        raise OSError(f"gh {' '.join(args[:3])}: {fix.tail(out, 3)}")
    return json.loads(out or "null")


def _issue(n: int) -> tuple[str, str]:
    got = _gh("issue", "view", str(n), "--json", "title,body")
    return str(got.get("title") or ""), str(got.get("body") or "")


def _workspace(out: Path, name: str, base: str) -> Path:
    from harness import fix, paths
    ws = out / name
    if ws.exists():
        fix.run_cmd(("git", "worktree", "remove", "--force", str(ws)), paths.REPO)
    rc, text = fix.run_cmd(("git", "worktree", "add", "--detach", str(ws), base), paths.REPO)
    if rc != 0:
        raise OSError(f"git worktree add {base}: {fix.tail(text, 3)}")
    return ws


def _drop(ws: Path) -> None:
    from harness import fix, paths
    fix.run_cmd(("git", "worktree", "remove", "--force", str(ws)), paths.REPO)


def _executor(a):
    from harness import completion, fix, gateway_key
    key = gateway_key.key()
    if not key:
        raise OSError(f"no gateway key: {gateway_key.HINT}")
    return fix.headless_executor(a.alias or fix.AGENT_ALIAS, a.gateway or completion.gateway_url(), key,
                                 "eval" if a.target == "replay" else "work")


def _out(a) -> Path:
    from harness import paths
    out = Path(a.out).expanduser() if a.out else paths.home() / "out" / "fix"
    out.mkdir(parents=True, exist_ok=True)
    return out.resolve()


def _keep(a, out: Path, rec, replay: bool) -> None:
    from dataclasses import asdict

    from harness import delegations, fix
    try:
        with delegations.ledger() as conn:
            if conn is not None and not isinstance(conn, delegations.Spool):
                fix.store(conn, rec, a.alias or fix.AGENT_ALIAS, replay=replay)
            else:
                note("fix: the store is not writable here; the record is only in the handoff file")
    except Exception as exc:  # noqa: BLE001 - a store failure never loses the run: the handoff below keeps it
        note(f"fix: not recorded in the store ({exc})")
    if not rec.resolved:
        (out / f"escalate-{rec.issue}.json").write_text(json.dumps(asdict(rec), indent=1), encoding="utf-8")


def _one(a, out: Path, issue: int, title: str, body: str, base: str, replay: bool, held=(), ref: str = ""):
    from harness import fix
    model = a.model or fix.PLAN_MODEL
    ws = _workspace(out, f"ws-{issue}", base)
    try:
        return fix.run_issue(issue, title, body, ws, plan_fn=lambda prompt, w: fix.ask_plan(prompt, w, model),
                             execute=None if a.plan_only else _executor(a), plan_only=a.plan_only,
                             attempts=a.attempts or fix.ATTEMPTS, held_out=held, held_out_ref=ref)
    finally:
        _drop(ws)


def _show(rec) -> None:
    note(f"#{rec.issue:<6} {rec.klass or '-':<22} {'LOCAL' if rec.resolved else 'ESCALATE':<8} {rec.stage}: "
         f"{rec.why[:120]} (attempts {len(rec.attempts)}, plan {rec.plan_tokens.get('input', 0) + rec.plan_tokens.get('output', 0) + rec.plan_tokens.get('cache_write', 0):,} cloud)",
         flush=True)


def _candidates(a) -> list:
    from harness import fix
    if a.issues:
        wanted = [int(x) for x in a.issues.split(",") if x.strip()]
    else:
        listed = _gh("issue", "list", "--state", "closed", "--limit", str(a.limit), "--json",
                     "number,closedByPullRequestsReferences")
        wanted = [int(i["number"]) for i in listed if i.get("closedByPullRequestsReferences")]
    out = []
    for n in wanted:
        refs = _gh("issue", "view", str(n), "--json", "closedByPullRequestsReferences")
        for pr in refs.get("closedByPullRequestsReferences") or []:
            got = _gh("pr", "view", str(pr["number"]), "--json", "state,mergeCommit,files")
            if got.get("state") != "MERGED" or not got.get("mergeCommit"):
                continue
            c = fix.candidate([f["path"] for f in got.get("files") or []], got["mergeCommit"]["oid"], n, pr["number"])
            if c:
                out.append(c)
                break
    return out


def _replay(a, out: Path) -> int:
    from harness import delegate, fix
    try:
        cands = _candidates(a)
    except (OSError, ValueError) as exc:
        return err(f"fix replay: {exc}")
    note(f"{len(cands)} candidate closed issues; trying until {a.n} are in class")
    recs = []
    for c in cands:
        if sum(1 for r in recs if r.klass in fix.CLASSES) >= a.n:
            break
        held = delegate.busy()
        if held and not a.plan_only:
            note(f"stopped: the machine is held by {held}; rerun when it is free")
            break
        title, body = _issue(c.issue)
        rec = _one(a, out, c.issue, title, body, c.base, True, c.held_out, c.merge)
        _keep(a, out, rec, True)
        _show(rec)
        recs.append(rec)
    rows = [{"issue": r.issue, "class": r.klass or "unplanned", "resolved": r.resolved, "why": r.why,
             "local": sum(int(r.local_tokens.get(k) or 0) for k in ("input", "output", "cache_write")),
             "cloud": fix.counted(r.plan_tokens)} for r in recs]
    summary = fix.summarize(rows)
    for line in fix.lines(summary):
        note(line)
    emit(True, summary=summary, rows=rows)
    return 0


def _report(a) -> int:
    from harness import fix
    from harness.commands.common import lent_store
    since = time.time() - a.since_days * 86400
    with lent_store() as conn:
        rows = fix.stored(conn, since) + fix.stored(conn, since, replay=True)
    summary = fix.summarize(rows)
    for line in fix.lines(summary):
        note(line)
    emit(True, summary=summary, rows=rows)
    return 0


def cmd_fix(a) -> int:
    from harness import delegate
    if a.report:
        return _report(a)
    if a.target != "replay" and (not a.target.isdigit() or not (a.plan_only or a.execute)):
        return err("soh fix <issue> --plan-only|--execute, soh fix replay [--n N], or soh fix --report")
    out = _out(a)
    if a.target == "replay":
        return _replay(a, out)
    held = delegate.busy()
    if held and a.execute:
        return err(f"fix refused: the machine is held by {held}; rerun when it is free")
    issue = int(a.target)
    try:
        title, body = _issue(issue)
        rec = _one(a, out, issue, title, body, a.base, False)
    except OSError as exc:
        return err(f"fix: {exc}")
    if not a.plan_only:
        _keep(a, out, rec, False)
    _show(rec)
    if rec.stage == "planned":
        note(json.dumps(rec.plan, indent=1))
    emit(rec.resolved or rec.stage == "planned", record=rec.__dict__)
    return 0 if rec.resolved or rec.stage == "planned" else 1

"""`soh headless`: `claude -p` on a local model through the gateway, and the recorded jobs it is graded on. #830."""
from __future__ import annotations

import json
import os
import shutil

from harness.commands.common import default_output, emit, err, note, say


def _gateway(a) -> str:
    from harness import completion
    return a.gateway or completion.gateway_url()


def cmd_headless(a) -> int:
    from harness import gateway_key, headless
    if a.action == "env":
        text = headless.shell(a.model, _gateway(a))
        return say(body=text, human=text.rstrip("\n"))
    key = gateway_key.key()
    if a.action == "exec":
        if not key:
            return err(f"no gateway key: {gateway_key.HINT}")
        binary = shutil.which("claude")
        if binary is None:
            return err("claude is not on PATH")
        args = a.rest[1:] if a.rest[:1] == ["--"] else a.rest
        os.execve(binary, [binary, *args], headless.child_env(a.model, _gateway(a), key))
    return _run(a, key)


def _run(a, key: str) -> int:
    from evals import headless as tasks_mod
    from harness import gateway_key, headless
    from harness import memory_store as ms
    local = not a.model.startswith(tasks_mod.CONTROL_PREFIX)
    if local and not key:
        return err(f"no gateway key: {gateway_key.HINT}")
    try:
        tasks = tasks_mod.load(a.task or None)
    except ValueError as exc:
        return err(str(exc))
    env = headless.child_env(a.model, _gateway(a), key) if local else headless.control_env()
    out = default_output("headless", ".jsonl") if not a.out else a.out
    note(f"{len(tasks)} tasks on {a.model} ({'gateway' if local else 'Claude control'})")
    rows = []
    for t in tasks:
        row = tasks_mod.run_task(t, a.model, env, local)
        rows.append(row)
        note(f"  {t.name:<16} {'PASS' if row['passed'] else 'FAIL'} turns {row['turns']} "
             f"calls {row['tool_calls']} invalid {row['invalid_calls']} {row['wall_s']:.1f}s "
             f"{row['limit']} {'; '.join(row['why'])}")
    leak = tasks_mod.attach_leaks(rows, ms.db_path(), a.model) if local else None
    total = tasks_mod.summary(rows)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        f.write(json.dumps({"summary": total, "leak": leak}) + "\n")
    note(f"{total['passed']}/{total['tasks']} passed, {total['turns']} turns, valid-call rate "
         f"{total['valid_rate']}, {total['wall_s']}s; written to {out}")
    if leak is not None:
        note(f"leak check: {'OK' if leak['ok'] else 'FAILED'}: {leak['requests']} gateway requests "
             f"for {leak['api_calls']} API calls, served {leak['served']} {'; '.join(leak['problems'])}")
    emit(leak is None or leak["ok"], summary=total, leak=leak, rows=rows, path=str(out))
    return 0 if leak is None or leak["ok"] else 1


def add_parser(sub) -> None:
    hp = sub.add_parser("headless", help="claude -p against a local model through the gateway: "
                        "env prints the profile, exec runs claude under it, run grades the recorded jobs")
    hp.add_argument("action", choices=("env", "exec", "run"))
    hp.add_argument("--model", required=True,
                    help="gateway alias (sohot-agent), or claude:<model> for the control")
    hp.add_argument("--gateway", default="", help="gateway URL (default SOHOT_GATEWAY_URL or local)")
    hp.add_argument("--task", action="append", help="run only this task (repeatable)")
    hp.add_argument("--out", default="", help="results JSONL (default under $LOCALHARNESS_HOME/out)")
    hp.add_argument("rest", nargs="*", help="exec: arguments for claude, after --")
    hp.set_defaults(func=cmd_headless)

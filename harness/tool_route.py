"""Oversized Bash and Read results handed to the local lanes by a PostToolUse hook, raw kept under tmp/ (#2032)."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

#: A Bash result or whole-file Read shorter than this many characters (about 2k tokens) reaches the session as is.
CHARS = 8000
#: Raw outputs older than this many days are removed from tmp/tool-route when the hook next writes one.
KEEP_DAYS = 7
#: Seconds Claude Code gives the hook before it shows the result whole.
TIMEOUT_S = 120
#: "off" or "0" in the session's environment turns routing off for that session.
OFF_ENV = "SOH_ROUTE"
#: A Bash command carrying this gets its output whole.
RAW_MARK = "SOH_RAW=1"
TOOLS = ("Bash", "Read")
SCRIPT = "tool-route-hook.py"
DIR = ("tmp", "tool-route")
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def disabled(env=None) -> bool:
    return str((os.environ if env is None else env).get(OFF_ENV, "")).strip().lower() in ("off", "0", "no", "false")


def _bash_text(resp) -> str | None:
    if not isinstance(resp, dict) or not isinstance(resp.get("stdout"), str) or resp.get("isImage"):
        return None
    err = resp.get("stderr") if isinstance(resp.get("stderr"), str) else ""
    return resp["stdout"] + (("\n" if resp["stdout"] else "") + err if err else "")


def _read_file(event: dict) -> dict | None:
    """The Read result's file block when the call read a whole text file, else None."""
    ti, resp = event.get("tool_input") or {}, event.get("tool_response")
    if any(ti.get(k) for k in ("offset", "limit", "pages")) or not isinstance(resp, dict) or resp.get("type") != "text":
        return None
    f = resp.get("file")
    if not isinstance(f, dict) or not isinstance(f.get("content"), str) or not f.get("filePath"):
        return None
    if (f.get("startLine") or 1) != 1 or (f.get("totalLines") and f.get("numLines") != f.get("totalLines")):
        return None
    if DIR[1] in Path(str(f["filePath"])).parts:
        return None
    return f


def wanted(event: dict, chars: int = CHARS, env=None) -> bool:
    """Whether the event is a result this hook would route: cheap, stdlib only, so the hook script can ask first."""
    if disabled(env) or event.get("hook_event_name", "PostToolUse") != "PostToolUse":
        return False
    tool = event.get("tool_name")
    if tool == "Bash":
        if RAW_MARK in str((event.get("tool_input") or {}).get("command") or ""):
            return False
        text = _bash_text(event.get("tool_response"))
        return text is not None and len(text) >= chars
    if tool == "Read":
        f = _read_file(event)
        return f is not None and len(f["content"]) >= chars
    return False


def raw_dir(cwd) -> Path:
    from harness import ask
    return ask.worktree(Path(cwd or os.getcwd())).joinpath(*DIR)


def _prune(where: Path, now: float) -> None:
    from harness import cuts
    kept = dropped = 0
    for p in where.glob("*.log"):
        try:
            if now - p.stat().st_mtime > KEEP_DAYS * 86400:
                p.unlink()
                dropped += 1
            else:
                kept += 1
        except OSError:
            continue
    if dropped:
        cuts.cut("tool_route_keep_days", "raw tool outputs removed from tmp/tool-route", value=KEEP_DAYS, kept=kept,
                 dropped=dropped)


def keep_raw(event: dict, text: str, now: float | None = None) -> Path:
    """Write the whole output under the worktree's tmp/tool-route and return its path."""
    now = time.time() if now is None else now
    where = raw_dir(event.get("cwd"))
    where.mkdir(parents=True, exist_ok=True)
    _prune(where, now)
    name = _SAFE.sub("-", str(event.get("tool_use_id") or "call"))[:80]
    path = where / f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}-{name}.log"
    path.write_text(text, encoding="utf-8")
    return path


def _question(ti: dict) -> str:
    cmd = " ".join(str(ti.get("command") or "").split())[:300]
    what = str(ti.get("description") or "").strip()
    return (f"This is the output of the shell command `{cmd}`" + (f" ({what})" if what else "") + ". What in it "
            "does the engineer who ran it need? Keep every error, failing test, count and exit status, and each "
            "path, id, number or name a next step would use. Answer \"none\" when it holds nothing of that.")


def _need(transcript: str) -> str:
    """The session's last text before this call, the reason for the Read; "" when there is none."""
    from harness import context_class as cc
    from harness import unverified as uv
    path = Path(transcript or "")
    if not transcript or not path.is_file():
        return ""
    for rec in reversed(uv._records(path, uv.TRANSCRIPT_BYTES)[0]):
        if rec.get("type") == "user" and isinstance((rec.get("message") or {}).get("content"), str):
            return str(rec["message"]["content"])
        if rec.get("type") == "assistant":
            texts = [b.get("text") for b in cc._blocks(rec) if b.get("type") == "text" and b.get("text")]
            if texts:
                return str(texts[-1])
    return ""


def _replace(out, chars: int, raw: int, shown: int) -> dict:
    from harness import cuts
    cuts.cut("tool_route_chars", "a tool result shown as its local digest", value=chars, kept=shown, dropped=raw - shown)
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": out}}


def bash(event: dict, digest_run=None, chars: int = CHARS) -> dict | None:
    from harness import ask, digest
    resp, text = event["tool_response"], _bash_text(event["tool_response"])
    path = keep_raw(event, text)
    try:
        got = (digest_run or digest.run)([str(path)], _question(event.get("tool_input") or {}),
                                          roots=[ask.Root(path.parent)], cwd=path.parent)
    except Exception:  # noqa: BLE001 - the output goes through whole
        got = None
    if not got or got.get("unmodelled") or not got.get("call_id") or len(got["text"]) >= len(text):
        path.unlink(missing_ok=True)
        return None
    head = (f"[soh tool-route: {len(text):,} characters digested by the local {got.get('lane') or 'extract'} lane, "
            f"call_id {got['call_id']}; the whole output is {path}; rerun with {RAW_MARK} for it here]")
    body = head + "\n" + got["text"]
    return _replace({**resp, "stdout": body, "stderr": ""}, chars, len(text), len(body))


def read(event: dict, ask_file=None, chars: int = CHARS) -> dict | None:
    from harness import ask, spans
    resp, f = event["tool_response"], _read_file(event)
    need = _need(str(event.get("transcript_path") or ""))
    if not need.strip():
        return None
    target = Path(str(f["filePath"]))
    try:
        got = (ask_file or spans.ask_file)([str(target)], need, roots=[ask.Root(target.parent)],
                                           cwd=Path(str(event.get("cwd") or target.parent)), delegated=True)
    except Exception:  # noqa: BLE001 - the file goes through whole
        got = None
    if not got or got.get("mode") != spans.SPANS or not got.get("call_id") or len(got["text"]) >= len(f["content"]):
        return None
    head = (f"[soh tool-route: lines of {target} picked by the local {got.get('lane') or 'code'} lane, "
            f"call_id {got['call_id']}; each row is numbered twice, the second number is the file's own line; "
            "Read with offset/limit for exact text before an Edit]")
    body = head + "\n" + got["text"]
    return _replace({**resp, "file": {**f, "content": body, "numLines": body.count("\n") + 1}}, chars,
                    len(f["content"]), len(body))


def hook(event: dict, chars: int = CHARS, env=None, digest_run=None, ask_file=None) -> dict | None:
    """The PostToolUse output replacing an oversized result with its local digest; None leaves the result whole."""
    if not wanted(event, chars, env):
        return None
    if event.get("tool_name") == "Bash":
        return bash(event, digest_run, chars)
    return read(event, ask_file, chars)


def settings(command: str, timeout: int) -> dict:
    """The settings.json block that runs the hook on every Bash and Read result."""
    return {"hooks": {"PostToolUse": [{"matcher": "|".join(TOOLS),
                                       "hooks": [{"type": "command", "command": command, "timeout": timeout}]}]}}


def install(settings_path: Path, block: dict) -> str:
    """Merge the block into a settings file under a lock: "added", "replaced" (an older tool-route entry), or "present"."""
    import hashlib
    import json

    from harness import atomic_file, exclusive
    p = Path(settings_path).expanduser()
    lock = "tool-route-" + hashlib.sha256(str(p.resolve()).encode("utf-8")).hexdigest()[:16] + ".lock"
    with exclusive.alone(lock, 0) as took:
        if not took:
            raise RuntimeError(f"another soh tool-route --install is writing {p}")
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        data = json.loads(text) if text.strip() else {}
        new = block["hooks"]["PostToolUse"][0]
        have = data.setdefault("hooks", {}).setdefault("PostToolUse", [])
        ours = [h for e in have for h in e.get("hooks") or [] if SCRIPT in str(h.get("command") or "")]
        if new in have and len(ours) == 1:
            return "present"
        kept = []
        for e in have:
            rest = [h for h in e.get("hooks") or [] if h not in ours]
            if rest or not e.get("hooks"):
                kept.append({**e, "hooks": rest} if rest != e.get("hooks") else e)
        data["hooks"]["PostToolUse"] = kept + [new]
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tool-route.tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        atomic_file.replace(tmp, p)
    return "replaced" if ours else "added"

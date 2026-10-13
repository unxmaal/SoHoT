"""Headless `claude -p` against the gateway: the env profile and the leak check. #830."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

#: Every variable that names a model Claude Code may call: main loop, tiers, background, subagents.
MODEL_VARS = ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
              "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
              "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
              "CLAUDE_CODE_SUBAGENT_MODEL")
#: The gateway key goes in both: Authorization: Bearer, and X-Api-Key (the only one --bare reads).
KEY_VARS = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
QUIET = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1",
    "CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION": "false",
    "CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL": "1",
    "CLAUDE_CODE_DISABLE_ARTIFACT": "1",
}
#: Removed from the child's environment: another credential or provider would route around the gateway.
UNSET = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
         "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_BEDROCK_BASE_URL",
         "ANTHROPIC_VERTEX_BASE_URL", "ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_AWS_BASE_URL",
         "ANTHROPIC_PROFILE", "ANTHROPIC_BETAS")
#: What `soh headless env` prints in place of the key, so the key never lands in a file or a log.
KEY_REF = '"$(soh gateway key)"'
CLIENT_PREFIX = "claude-cli"


def profile(model: str, base: str, key: str) -> dict[str, str]:
    """The variables that send every call of `claude -p` to `model` on the gateway at `base`."""
    if not model or not base:
        raise ValueError("a headless profile needs a model alias and a gateway URL")
    env = {"ANTHROPIC_BASE_URL": base.rstrip("/")}
    env.update({v: key for v in KEY_VARS})
    env.update({v: model for v in MODEL_VARS})
    env.update(QUIET)
    return env


def child_env(model: str, base: str, key: str, environ=None) -> dict[str, str]:
    """The parent's environment with the profile laid over it and the bypass routes removed."""
    env = {k: v for k, v in (os.environ if environ is None else environ).items() if k not in UNSET}
    env.update(profile(model, base, key))
    return env


def control_env(environ=None) -> dict[str, str]:
    """The control's environment: no profile, so `claude -p` uses its own login and Anthropic."""
    names = {"ANTHROPIC_BASE_URL", *KEY_VARS, *MODEL_VARS}
    env = {k: v for k, v in (os.environ if environ is None else environ).items() if k not in names}
    env.update(QUIET)
    return env


def shell(model: str, base: str) -> str:
    """The profile as `export` lines; the key is a command substitution, never its value."""
    lines = []
    for name, value in profile(model, base, "KEY").items():
        lines.append(f"export {name}={KEY_REF}" if name in KEY_VARS else f"export {name}={value}")
    lines += [f"unset {name}" for name in UNSET]
    return "\n".join(lines) + "\n"


def requests_between(path: Path, start: float, end: float) -> list[dict]:
    """claude-cli rows of gateway_requests in [start, end], read with SQLite's mode=ro."""
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT at, alias, served, client, call_type, stream, prompt_tokens, completion_tokens, "
            "tool_calls, tool_calls_valid, finish_reason, error_class FROM gateway_requests "
            "WHERE at >= ? AND at <= ? AND client LIKE ? ORDER BY at",
            (start, end, CLIENT_PREFIX + "%")).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def leak_check(rows: list[dict], alias: str, model_usage: list[str], api_calls: int) -> dict:
    """Did every call of a run reach the gateway's local alias, and none go anywhere else?

    `model_usage` is the result's modelUsage keys (every model Claude Code called, background
    included); `api_calls` is the distinct assistant message ids it streamed, one per main-loop
    request, each of which must be a streamed row. Unstreamed rows are background calls (the
    haiku tier), which must reach the alias too.
    """
    problems = []
    cloud = [r for r in rows if str(r.get("served") or "").startswith("anthropic/")]
    if cloud:
        problems.append(f"{len(cloud)} gateway requests served by {sorted({r['served'] for r in cloud})}")
    other = sorted({r.get("alias") or "" for r in rows} - {alias})
    if other:
        problems.append(f"claude-cli requests to other aliases {other}")
    called = sorted(set(model_usage) - {alias})
    if called:
        problems.append(f"Claude Code called models other than {alias}: {called}")
    streamed = sum(1 for r in rows if r.get("stream"))
    if streamed < api_calls:
        problems.append(f"{api_calls} API calls streamed but only {streamed} reached the gateway")
    if api_calls == 0:
        problems.append("no API call was made, so nothing is proven")
    return {"ok": not problems, "problems": problems, "requests": len(rows), "api_calls": api_calls,
            "streamed": streamed, "background": len(rows) - streamed,
            "served": sorted({r.get("served") or "" for r in rows}),
            "tool_calls": sum(int(r.get("tool_calls") or 0) for r in rows),
            "tool_calls_valid": sum(int(r.get("tool_calls_valid") or 0) for r in rows),
            "errors": sum(1 for r in rows if r.get("error_class")),
            "max_prompt_tokens": max((int(r.get("prompt_tokens") or 0) for r in rows), default=0)}

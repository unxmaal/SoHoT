"""local_complete and local_decide, shared by the MCP tools and `soh local` so neither needs the other. #1687."""
from __future__ import annotations

from pathlib import Path

from harness import ask, cuts, delegate, spans


def complete(prompt: str = "", lane: str = "", system: str | None = None, max_tokens: int | None = None,
             temperature: float | None = None, thinking: bool | None = None, paths: list[str] | None = None,
             question: str = "", mode: str = "", here=None, cwd: Path | None = None) -> dict:
    """One delegation as local_complete runs it; `here` vets a caller passing paths, `cwd` resolves relative ones."""
    if mode not in ("", "spans"):
        raise ValueError(f"mode is \"spans\" or left out, not {mode!r}")
    if mode == "spans":
        if not paths:
            raise ValueError("mode \"spans\" reads one file: pass it in `paths`")
        if here:
            here()
        return spans.ask_file(paths, question or prompt, lane=lane or "code", cwd=cwd,
                              max_tokens=max_tokens, delegated=True)
    if paths:
        if here:
            here()
        return ask.ask(paths, question or prompt, lane=lane or "extract", cwd=cwd,
                       max_tokens=max_tokens or ask.REPLY_TOKENS, system=system, thinking=thinking, delegated=True)
    if question and not prompt:
        raise ValueError("`question` asks about `paths`; pass the files, or put the task in `prompt`")
    given = {} if max_tokens is None else {"max_tokens": max_tokens}
    return _prompted(prompt, lane or "code", system, temperature=temperature, thinking=thinking, **given)


def _prompted(prompt: str, lane: str, system: str | None, max_tokens: int = 2048, **kw) -> dict:
    got = delegate.complete(lane, prompt, system=system, max_tokens=max_tokens, delegated=True, **kw)
    if (got.get("completion_tokens") or 0) >= max_tokens:
        cuts.cut("harness/local_tools.py:_prompted(max_tokens)", f"a {lane} delegation reply at its token budget",
                 value=max_tokens, kept=0, dropped=1)
    return got


def decide(question: str, schema: dict, context: str = "") -> dict:
    return delegate.decide(question, schema, context=context, delegated=True)

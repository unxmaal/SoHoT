"""Which server produced the tokens.

The gateway exists so a new inference method costs a config line plus an eval
run rather than a redesign. That claim has never been tested: mlx_lm.server is
the only engine this project has served, so nothing ever needed to say which
one a receipt came from.

It matters the moment a second one appears. `evals.core.comparable()` decides
whether two runs may share a table, and with no record of the engine two runs
across DIFFERENT servers look like the same exam -- the same failure as the
same card under two operating systems producing one accelerator string while
the instruments differed. Issue #190.

The HOST is deliberately not part of this: comparable() already argues that the
same aliases served from another machine answer the same questions. What
changes the exam is the implementation, not the address.
"""
from __future__ import annotations

import os
from typing import NamedTuple

#: Set this when serving the text lane through something else. A config line,
#: which is the whole claim under test.
ENV_VAR = "TEXT_ENGINE"

#: What scripts/serve-mlx.sh starts. Kept here rather than only in the shell so
#: the receipt and the launcher cannot disagree; a test asserts they match.
DEFAULT = "mlx_lm.server"


#: llama-server for structured output and GGUF candidates (scripts/serve-eval.sh).
LLAMACPP_URL = "http://127.0.0.1:8082"
LLAMACPP = "llama-server"
LLAMACPP_PREFIX = "llamacpp:"


def llamacpp_build(binary: str = "") -> str:
    """The installed llama-server's build number, or "" if it cannot say."""
    import re
    import subprocess
    try:
        out = subprocess.run([binary or os.environ.get("LLAMACPP_BIN")
                              or LLAMACPP, "--version"], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"build (\d+)", out.stdout + out.stderr)
    return m.group(1) if m else ""


def engine_for(candidate: str, environ=None, config=None) -> str:
    """The server that answers this candidate, read from where it routes."""
    name = (candidate or "").partition(",")[0].strip()
    if name.startswith(LLAMACPP_PREFIX):
        return LLAMACPP
    from harness import gateway
    for entry in gateway.load(config).get("model_list") or []:
        if str(entry.get("model_name", "")).lower() == name.lower():
            base = str((entry.get("litellm_params") or {}).get("api_base", ""))
            if base.rstrip("/").removesuffix("/v1") == LLAMACPP_URL:
                return LLAMACPP
    return text_engine(environ)


def text_engine(environ=None) -> str:
    """The name of the server behind the text lane."""
    environ = os.environ if environ is None else environ
    return (environ.get(ENV_VAR) or "").strip() or DEFAULT


#: Sampling keys a spec may carry after a comma, e.g. `q3-4b,temperature=0`. #90.
SAMPLING_KEYS = ("temperature", "top_p", "repetition_penalty")


class Route(NamedTuple):
    """Where a text spec is answered: the server's base URL and the model name it takes."""
    base: str
    model: str
    sampling: dict


def text_spec(spec: str) -> bool:
    """True when a text server can answer this spec: an alias, a repo id or a llamacpp: stem."""
    name = (spec or "").partition(",")[0].strip()
    return bool(name) and (":" not in name or name.startswith(LLAMACPP_PREFIX))


def _sampling(optstr: str, spec: str) -> dict:
    out = {}
    for part in (p.strip() for p in optstr.split(",") if p.strip()):
        key, eq, value = part.partition("=")
        key = key.strip()
        if not eq or key not in SAMPLING_KEYS:
            raise ValueError(f"{spec}: unknown option(s) {key}")
        try:
            out[key] = float(value)
        except ValueError:
            raise ValueError(f"{spec}: {key} must be a number") from None
    return out


def route(spec: str, gateway: str = "", config=None) -> Route:
    """The server that serves a text spec, shared by lane commands and evals.run. #297.

    `llamacpp:<stem>` goes to llama-server's router as <stem>. With an explicit
    `gateway` everything else goes there verbatim. Otherwise a gateway alias stays
    on the gateway, a fetched GGUF repo goes to the router by its stem, and an
    mlx repo id goes to the upstream that hot-swaps to it (screen.routed_gateway).
    """
    name, _, optstr = (spec or "").partition(",")
    name = name.strip()
    sampling = _sampling(optstr, spec)
    if not text_spec(name):
        raise ValueError(f"{spec!r} is not served by a text server")
    if name.startswith(LLAMACPP_PREFIX):
        from harness import router
        return Route(router.url(), name[len(LLAMACPP_PREFIX):].strip(), sampling)
    if gateway:
        return Route(gateway.rstrip("/"), name, sampling)
    from harness.completion import DEFAULT_GATEWAY
    if "/" not in name:
        return Route(DEFAULT_GATEWAY, name, sampling)
    from harness import screen
    names, _ = screen.gateway_routes(config)
    if name.lower() in names:
        return Route(DEFAULT_GATEWAY, name, sampling)
    from harness import gguf, router
    try:
        stem = gguf.fetched(name)
    except Exception:  # noqa: BLE001
        stem = None
    if stem:
        return Route(router.url(), stem, sampling)
    return Route(screen.routed_gateway(name, config) or DEFAULT_GATEWAY, name, sampling)

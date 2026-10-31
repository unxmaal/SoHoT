"""Start a vLLM server on this Mac for one measurement and stop it after. #310."""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import NamedTuple

from harness import paths
from harness.serving import VLLM_ENGINES as ENGINES

#: The venv of the engine VLLM_ENGINE names; otherwise <home>/venvs/<engine>.
VENV_VAR = "VLLM_VENV"

#: vllm-metal sizes its KV pool to 0.92 of the machine and the model's trained length unless told.
METAL_MEMORY_FRACTION = 0.2
METAL_MAX_MODEL_LEN = 16384


def venv_for(engine: str) -> Path:
    from harness import serving
    override = (os.environ.get(VENV_VAR) or "").strip()
    try:
        selected = serving.vllm_engine()
    except ValueError:
        selected = ""
    if override and engine == selected:
        return Path(override)
    return paths.home() / "venvs" / engine


def binary(engine: str, venv=None) -> Path:
    """The executable argv starts for `engine`."""
    return Path(venv or venv_for(engine)) / "bin" / ("vllm-mlx" if engine == "vllm-mlx" else "vllm")


def installed() -> tuple[str, ...]:
    """The engines whose venv holds the executable argv would start."""
    return tuple(e for e in ENGINES if binary(e).is_file() and os.access(binary(e), os.X_OK))


def available() -> str:
    """The engine a `vllm:` spec is served by here, or "" when its executable is absent: the one answer to "has vLLM". #960."""
    from harness import serving
    try:
        engine = serving.vllm_engine()
    except ValueError:
        return ""
    return engine if engine in installed() else ""


def argv(engine: str, model: str, port: int, venv=None, extra=()) -> list[str]:
    """The command that serves `model` on `port`, with batching on and memory capped."""
    if engine not in ENGINES:
        raise ValueError(f"{engine} is not one of {', '.join(ENGINES)}")
    common = ["serve", model, "--host", "127.0.0.1", "--port", str(port)]
    if engine == "vllm-mlx":
        return [str(binary(engine, venv)), *common, "--continuous-batching", *extra]
    return [str(binary(engine, venv)), *common,
            "--gpu-memory-utilization", str(METAL_MEMORY_FRACTION),
            "--max-model-len", str(METAL_MAX_MODEL_LEN), *extra]


class Served(NamedTuple):
    base: str
    proc: subprocess.Popen


#: The server is on loopback: no proxy from the environment or the system settings applies.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _probe(base: str, listed: list | None = None) -> str:
    """"" when the server answers /v1/models with 200, else why not; the ids it lists go in `listed`."""
    try:
        with _DIRECT.open(base + "/v1/models", timeout=2) as r:
            if r.status == 200 and listed is not None:
                listed += [str(m.get("id")) for m in json.load(r).get("data") or []]
            return "" if r.status == 200 else f"HTTP {r.status}"
    except Exception as exc:  # noqa: BLE001 - not up yet
        return f"{type(exc).__name__}: {exc}"


def _tail(log: Path, n: int = 2000) -> str:
    try:
        return Path(log).read_text(encoding="utf-8", errors="replace")[-n:]
    except OSError:
        return ""


def _signal(proc: subprocess.Popen, hard: bool) -> None:
    """The child's whole session where the OS has process groups, the child alone where it does not."""
    with contextlib.suppress(ProcessLookupError):
        if hasattr(os, "killpg") and hasattr(signal, "SIGKILL"):
            os.killpg(proc.pid, signal.SIGKILL if hard else signal.SIGTERM)
        elif hard:
            proc.kill()
        else:
            proc.terminate()


def _stop(proc: subprocess.Popen, grace: float) -> None:
    if proc.poll() is not None:
        return
    _signal(proc, hard=False)
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        _signal(proc, hard=True)
        proc.wait()


@contextlib.contextmanager
def served(cmd: list[str], port: int, log, env=None, timeout: float = 600.0,
           grace: float = 30.0, poll: float = 0.5, timeout_knob: str = "harness/vllm.py:served(timeout)"):
    """Run `cmd` until it answers /v1/models on `port`, yield it, then stop its process group."""
    base = f"http://127.0.0.1:{port}"
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ if env is None else env)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    with open(log, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, env=env,
                                start_new_session=True)
    try:
        deadline = time.monotonic() + timeout
        while why := _probe(base):
            if proc.poll() is not None:
                raise RuntimeError(f"{cmd[0]} exited {proc.returncode} before serving:\n"
                                   f"{_tail(log)}")
            if time.monotonic() > deadline:
                from harness import cuts
                cuts.cut(timeout_knob, f"{cmd[0]} did not serve in time", value=timeout,
                         kept=0, dropped=1)
                raise RuntimeError(f"{cmd[0]} did not serve within {timeout:.0f}s "
                                   f"(last probe: {why}):\n{_tail(log)}")
            time.sleep(poll)
        yield Served(base, proc)
    finally:
        _stop(proc, grace)


class Unservable(RuntimeError):
    """No vLLM server here can answer the spec: the harness's gap, never the candidate's."""


@contextlib.contextmanager
def serving(spec: str):
    """A server answering `vllm:<repo>`: the one already up when it lists the repo, else one started for it. #960."""
    from harness import serving as routes
    where = routes.route(spec)
    listed: list[str] = []
    if not _probe(where.base, listed):
        if where.model not in listed:
            raise Unservable(f"{where.base} serves {', '.join(listed) or 'nothing'}, not {where.model}")
        yield None
        return
    engine = available()
    if not engine:
        raise Unservable(f"no vLLM engine here: {absent()}")
    port = int(where.base.rsplit(":", 1)[1])
    with contextlib.ExitStack() as stack:
        try:
            srv = stack.enter_context(served(argv(engine, where.model, port), port,
                                             log=paths.home() / "logs" / f"{engine}-{port}.log"))
        except RuntimeError as exc:
            raise Unservable(str(exc)) from exc
        yield srv


def absent() -> str:
    """Why `available()` is "", for a refusal to name."""
    from harness import serving as routes
    try:
        engine = routes.vllm_engine()
    except ValueError as exc:
        return str(exc)
    return f"{binary(engine)} is not an executable"

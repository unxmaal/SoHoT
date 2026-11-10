"""Untrusted, non-GPU work in a locked-down Docker container, and the Docker VM's memory for the budget. #1510."""
from __future__ import annotations

import os
import shutil
import subprocess
import time

#: How long `docker info` may take before Docker counts as down for this call.
INFO_TIMEOUT_S = 10.0
#: How long a Docker VM size read is reused before docker is asked again.
VM_TTL_S = 300.0
#: Every container this module starts carries this label, so a stray one can be found and removed.
LABEL = "com.unxmaal.sohot.untrusted"

_vm: dict = {}


def docker() -> str:
    """The docker CLI on PATH, read at call time; "" when there is none."""
    return shutil.which("docker") or ""


def _info(run=None) -> dict | None:
    exe = docker()
    if not exe:
        return None
    from harness import cuts
    try:
        with cuts.timeout("harness/containers.py:INFO_TIMEOUT_S", "docker info"):
            got = (run or subprocess.run)([exe, "info", "--format", "{{.MemTotal}} {{.NCPU}}"], capture_output=True,
                                          text=True, timeout=INFO_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    parts = (got.stdout or "").split()
    if got.returncode != 0 or len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return {"mem_bytes": int(parts[0]), "cpus": int(parts[1])}


def available(run=None) -> bool:
    """Whether a docker engine answers here now."""
    return _info(run) is not None


def vm_gb(run=None, now: float | None = None) -> float:
    """GiB the Docker VM is given (all of it is counted: it can hold that much); 0 when Docker is absent or down."""
    now = time.monotonic() if now is None else float(now)
    if run is None and _vm and now - _vm["at"] < VM_TTL_S:
        return _vm["gb"]
    got = _info(run)
    gb = got["mem_bytes"] / 1024 ** 3 if got else 0.0
    if run is None:
        _vm.update(at=now, gb=gb)
    return gb


def cli_env(base: dict | None = None) -> dict:
    """The environment the docker CLI itself needs (its config and context live under HOME); nothing reaches the container."""
    return dict(os.environ if base is None else base)


def run_argv(image: str, command: list, *, name: str, mounts: list, memory_gb: float, cpus: float,
             network: bool, env: dict | None = None, pids: int = 256, tmp_mb: int = 512) -> list:
    """`docker run` for one untrusted step: nobody, read-only root, no capabilities, capped, only `mounts` shared."""
    argv = [docker() or "docker", "run", "--rm", "--name", name, "--label", LABEL, "--pull", "missing",
            "--network", "bridge" if network else "none", "--memory", f"{int(memory_gb * 1024)}m",
            "--memory-swap", f"{int(memory_gb * 1024)}m", "--cpus", f"{cpus:g}", "--pids-limit", str(pids),
            "--read-only", "--tmpfs", f"/tmp:rw,size={tmp_mb}m", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "65534:65534", "-e", "HOME=/tmp"]
    for k, v in sorted((env or {}).items()):
        argv += ["-e", f"{k}={v}"]
    for host, inside, mode in mounts:
        argv += ["-v", f"{os.fspath(host)}:{inside}:{mode}"]
    return [*argv, image, *command]


def remove(name: str, run=None) -> bool:
    """Remove a container by name, whatever state it is in; False when docker could not be asked."""
    exe = docker()
    if not exe:
        return False
    try:
        (run or subprocess.run)([exe, "rm", "-f", name], capture_output=True, text=True, timeout=INFO_TIMEOUT_S,
                                stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return True

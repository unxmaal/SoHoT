"""What this machine can RUN, which is a different question from which OS it is.

Discovery has one question to answer about a candidate: can this machine run
it. That question is about RUNTIMES. mlx, cuda, rocm and the cpu are the things
a repo depends on; the operating system is only how you find out which of them
are present.

Writing it the other way round is what this module exists to undo. `decide()`
used to read "CUDA is absolute on this machine", which was true of the Mac it
was written on and made every CUDA candidate a rejection on a box bought to run
them, while an MLX repo that cannot start there passed the same gate.

A LINUX BOX WITH AN NVIDIA CARD IS THE SAME MACHINE AS A WINDOWS ONE here, and
that is the property to keep. Nothing downstream should branch on the platform,
so adding Linux, or a ROCm card, or whatever comes after, is a row in
_RUNTIME_PROBES rather than another branch in every caller.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from dataclasses import dataclass
from functools import lru_cache

from harness import memory
from harness.memory import Accelerator

#: The cpu is always there, so it is never a reason to refuse anything.
ALWAYS = "cpu"


def _has_mlx() -> bool:
    """Apple's array framework. Present means Apple Silicon in practice: the
    package imports on other platforms and then fails to load its library."""
    if sys.platform != "darwin":
        return False
    try:
        import mlx.core  # noqa: F401
    except Exception:  # noqa: BLE001 - an unusable mlx is an absent one
        return False
    return True


def _has_cuda() -> bool:
    """nvidia-smi ships with the driver, so this answers before any toolkit or
    Python binding is installed."""
    return memory._discrete() is not None and shutil.which("nvidia-smi") is not None


def _has_rocm() -> bool:
    """AMD's stack. Untested here, and listed so that adding the machine is a
    row rather than a branch: nothing downstream asks which of these is true,
    only whether the runtime a candidate needs is in the set."""
    return shutil.which("rocm-smi") is not None or shutil.which("rocminfo") is not None


def _has_vllm() -> bool:
    """A vLLM server, which some cards name as what serves them.

    Probed rather than assumed absent: without this, `machine.refuses("vllm")`
    would answer "needs-vllm" on the box that HAS one, which is the mirror of
    the mistake #228 made about GGUF.
    """
    if shutil.which("vllm"):
        return True
    try:
        import importlib.util
        return importlib.util.find_spec("vllm") is not None
    except Exception:  # noqa: BLE001
        return False


def _has_llamacpp() -> bool:
    """What loads a GGUF. Nothing else here does.

    30 proposals in the store name GGUF, and until this probe existed the
    ladder had no way to say so: a GGUF fetched, screened against a server
    that cannot load it, and was recorded `broken` -- our gap, written down as
    the candidate's. Issue #228.

    $LLAMACPP_BIN is what the Linux runbook sets; the bare name covers a
    package install.
    """
    import os
    named = os.environ.get("LLAMACPP_BIN", "").strip()
    if named and Path(named).exists():
        return True
    return any(shutil.which(n) for n in ("llama-server", "llama-cli"))


def _has_ds4() -> bool:
    """antirez/ds4's ds4-server, built by scripts/ds4-build.sh. #611."""
    from harness import ds4
    return ds4.available()


#: runtime -> how to tell whether this machine has it. Order is not meaningful;
#: a machine may have several.
_RUNTIME_PROBES = {
    "mlx": _has_mlx,
    "vllm": _has_vllm,
    "llamacpp": _has_llamacpp,
    "ds4": _has_ds4,
    "cuda": _has_cuda,
    "rocm": _has_rocm,
}


@dataclass(frozen=True)
class Machine:
    """The runtimes this machine has, and what it loads weights into."""
    runtimes: frozenset[str]
    accelerator: Accelerator

    def refuses(self, runtime: str) -> str | None:
        """The verdict for a candidate needing `runtime`, or None if it runs.

        The verdict names the RUNTIME rather than the platform, so the same
        sentence reads correctly from either direction: needs-cuda on a Mac and
        needs-mlx on a card are one rule, not two.
        """
        if runtime == ALWAYS or runtime in self.runtimes:
            return None
        return f"needs-{runtime}"

    def describe(self) -> str:
        """One line for a result sheet. Two machines with the same card and the
        same runtimes are comparable; two without are not, and the row should
        say so rather than leaving a reader to infer it from a hostname."""
        return (f"{self.accelerator.name} "
                f"({self.accelerator.kind}, {self.accelerator.total_gb:.0f} GB) "
                f"[{', '.join(sorted(self.runtimes))}]")


#: WHERE A LANE'S WORK EXECUTES, which is three answers rather than the GPU
#: boolean the chart started with. Issue #170.
#:
#:   in-pod    the container itself: sweep, inspect, the judge's caller
#:   gpu-node  a node carrying a card the scheduler can see
#:   host      a machine outside the cluster entirely, which is every Metal
#:             lane -- Metal is a macOS userspace API, the Linux VM behind
#:             Docker Desktop has no /dev/dri and no nvidia device, and there
#:             is no passthrough to add. A pod can hold such a lane's identity
#:             and ask `lh` on the host to do the work, which is the pattern
#:             the judge tier already uses.
IN_POD, GPU_NODE, HOST = "in-pod", "gpu-node", "host"
WHERE = (IN_POD, GPU_NODE, HOST)
WHERE_ENV = "LOCALHARNESS_WHERE"


def where(environ=None, machine=None) -> str:
    """Where this process's work runs. Declared if the environment says so.

    A POD THAT DISPATCHES TO A HOST IS A DIFFERENT EXAM FROM A POD THAT RUNS
    THE WORK, so the declaration has to win: nothing about the container can
    tell you that the Metal work happened on somebody's desk. Inference only
    covers the case where nobody said.
    """
    import os
    e = os.environ if environ is None else environ
    declared = (e.get(WHERE_ENV) or "").strip().lower()
    if declared:
        if declared not in WHERE:
            raise ValueError(
                f"{WHERE_ENV}={declared!r} is not one of {', '.join(WHERE)}. "
                f"A receipt that names a place nothing recognises is worse "
                f"than one that names none.")
        return declared
    # No service account, no scheduler: this is somebody's machine.
    if not e.get("KUBERNETES_SERVICE_HOST"):
        return HOST
    acc = (machine if machine is not None else detect()).accelerator
    return GPU_NODE if acc.kind == "discrete" else IN_POD


@lru_cache(maxsize=1)
def detect() -> Machine:
    """This machine. Cached: the probes shell out, and the answer does not
    change while the process runs."""
    found = {name for name, probe in _RUNTIME_PROBES.items() if probe()}
    found.add(ALWAYS)
    return Machine(runtimes=frozenset(found), accelerator=memory.detect())


#: The os family per platform.platform() prefix; older Pythons say Darwin.
_OS_FAMILY = {"darwin": "macOS", "macos": "macOS", "linux": "Linux",
              "windows": "Windows"}


def os_family(os_string: str) -> str:
    """`macOS-27.0.1-arm64-arm-64bit-Mach-O` -> `macOS`. #415."""
    head = (os_string or "").strip().split("-", 1)[0]
    return _OS_FAMILY.get(head.lower(), head)


def fingerprint(hw_model: str, os_string: str, arch: str, host: str = "") -> str:
    """A machine's identity: hardware, OS family, arch and host, never the interpreter.

    platform.platform() differs between Python builds on one machine, which
    split one machine into several rows. #415. Two boxes of one model are two
    machines, so the host id is the last part. #697.
    """
    parts = (hw_model or "", os_family(os_string), arch or "", host or "")
    return "/".join(x for x in parts if x) or "unknown"


def parse_fingerprint(fp: str) -> dict:
    """The receipt environment a hw/os/arch/host fingerprint names; {} when it is not one. #697."""
    # A board name may hold a slash; OS family, arch and host never do. #781.
    parts = (fp or "").rsplit("/", 3)
    if len(parts) != 4 or not all(p.strip() for p in parts):
        return {}
    return dict(zip(("hw_model", "os", "arch", "host"), parts))


HOST_FILE = "host-id"

#: Hostnames that mean this host, for the gateway and the client alike. #697.
LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def is_loopback(url: str) -> bool:
    from urllib.parse import urlsplit
    return (urlsplit(url or "").hostname or "") in LOOPBACK


#: The platform uuid once a probe has answered; a failed probe is asked again. #747.
_UUID: str | None = None
#: When the uuid probe last failed, so a failing probe is not re-run on every call. #747.
_UUID_FAILED_AT: float | None = None
#: Seconds before a failed identity probe is asked again. #747.
RETRY_S = 60.0


def _now() -> float:
    import time
    return time.monotonic()


def uuid_failed() -> bool:
    """True while the last platform uuid probe failed rather than answered. #747."""
    return _UUID is None and _UUID_FAILED_AT is not None


def _platform_uuid() -> str:
    """IOPlatformUUID on a Mac, machine-id on Linux, "" when neither answers."""
    global _UUID, _UUID_FAILED_AT
    if _UUID:
        return _UUID
    if _UUID_FAILED_AT is not None and _now() - _UUID_FAILED_AT < RETRY_S:
        return ""
    import re
    import subprocess
    got, failed = "", False
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                 capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out or "")
        got = m.group(1) if m else ""
        # Every Mac has one, so no answer is a failed probe, not a machine without one.
        failed = not got
    else:
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                got = Path(p).read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if got:
                break
    _UUID = got or None
    _UUID_FAILED_AT = _now() if failed else None
    return got


def host_id(probe=None, home=None) -> str:
    """The platform uuid hashed, else the id persisted in LH_HOME; "" while the probe fails with none kept. #697, #747."""
    import hashlib
    import uuid
    raw = (probe or _platform_uuid)()
    from harness import paths
    f = Path(home or paths.home()) / HOST_FILE
    try:
        got = f.read_text(encoding="utf-8").strip()
    except OSError:
        got = ""
    if raw:
        real = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        if got != real:
            # Kept so a later failed probe reads back this host, not a random one. #747.
            _persist(f, real)
        return real
    if got or (probe is None and uuid_failed()):
        return got
    got = uuid.uuid4().hex[:12]
    return got if _persist(f, got) else ""


def _persist(f: Path, host: str) -> bool:
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(host + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


#: Packages whose installed version a verdict or receipt may need. #389, #415.
WATCHED = ("mlx", "mlx-lm", "mlx-vlm", "mlx-audio", "mflux", "diffusers",
           "torch", "transformers", "litellm", "ace-step",
           "vllm-mlx", "vllm-metal", "vllm")

#: Services `uv run --with` the exact pin at every launch, so the pin is installed.
UV_WITH = ("mlx-audio", "litellm")


def _site_versions(venv) -> dict[str, str]:
    """dist-info versions inside one virtualenv; {} when it is absent."""
    from harness import stages
    root = Path(venv)
    found: dict[str, str] = {}
    for site in [*sorted(root.glob("lib/python*/site-packages")),
                 root / "Lib" / "site-packages"]:
        if site.is_dir():
            for k, v in stages.dist_versions(site).items():
                found.setdefault(k, v)
    return found


def _imported_versions() -> dict[str, str]:
    from importlib import metadata
    found = {}
    for pkg in WATCHED:
        try:
            found[pkg] = metadata.version(pkg)
        except Exception:  # noqa: BLE001 - absent is not an error
            pass
    return found


def _other_venvs() -> list[Path]:
    """The venvs a lane runs through rather than imports: diffusers, ACE-Step."""
    import os
    from harness import engines, paths
    out = [Path(os.environ.get("DIFFUSERS_VENV")
                or paths.home() / "venvs" / "diffusers-cuda")]
    root = engines.acestep_root()
    if root:
        out.append(Path(root) / ".venv")
    return out


#: A vLLM venv carries its own mlx stack; only its vLLM packages describe it.
VLLM_PACKAGES = ("vllm-mlx", "vllm-metal", "vllm")


def _vllm_venvs() -> list[Path]:
    from harness import vllm
    return [vllm.venv_for(e) for e in vllm.ENGINES]


def _uv_with_pins(path: Path | None = None) -> dict[str, str]:
    import re
    path = path or Path(__file__).resolve().parent.parent / "scripts" / "versions.sh"
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    got = {m.group(1).lower(): m.group(2) for m in re.finditer(
        r'^[A-Z_]+_PIN="([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==([^"]+)"', text, re.M)}
    return {k: v for k, v in got.items() if k in UV_WITH}


def _mflux_cli() -> str:
    import subprocess
    try:
        out = subprocess.run(["mflux-generate", "--version"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    parts = out.split()
    return parts[-1] if parts else ""


@lru_cache(maxsize=1)
def versions() -> dict[str, str]:
    """Installed runtime versions on this machine: the one probe. #415.

    remember_machine records it in machines.versions; until_met and the
    receipt's environment read that rather than probing again.
    """
    import platform
    from harness import serving, stages
    got: dict[str, str] = {"python": platform.python_version()}
    tool = stages.tool_versions()
    for pkg in WATCHED:
        if pkg in tool:
            got[pkg] = tool[pkg]
    for k, v in _imported_versions().items():
        got.setdefault(k, v)
    for venv in _other_venvs():
        for k, v in _site_versions(venv).items():
            if k in WATCHED:
                got.setdefault(k, v)
    for venv in _vllm_venvs():
        for k, v in _site_versions(venv).items():
            if k in VLLM_PACKAGES:
                got.setdefault(k, v)
    for k, v in _uv_with_pins().items():
        got.setdefault(k, v)
    if "mflux" not in got:
        cli = _mflux_cli()
        if cli:
            got["mflux"] = cli
    build = serving.llamacpp_build()
    if build:
        got["llama.cpp"] = build
    from harness import ds4
    built = ds4.version()
    if built:
        got["ds4"] = built
    from harness import needle
    runtime = needle.installed_version()
    if runtime:
        got["needle"] = runtime
    return got

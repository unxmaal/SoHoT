"""Refusing to load a model that will take the machine down.

WRITTEN AFTER TAKING THE MACHINE DOWN. An eval sweeping seven candidates
reached Qwen3-30B-A3B-4bit -- 16 GB of weights -- while Qwen3-14B was still
resident and a Docker VM held 7.2 GB, on a 32 GB Mac. The eval log ends
mid-line at the candidate header. There was no panic report and no jetsam
entry; the machine simply stopped.

Nothing in this repo checked a model's size against available memory, on a
machine whose entire design constraint is 32 GB of unified memory. The eval
measured peak memory AFTER the fact and printed it in a column, which is a
postmortem, not a guard.

Two numbers matter and they are different:

  * TOTAL RAM is not the budget. Apple's Metal driver reports a recommended
    working set well below it (25.0 GiB of 32 on this machine, per tools/h3probe),
    and exceeding that is where things go wrong rather than at the RAM figure.
  * WHAT IS FREE RIGHT NOW is not the budget either. mlx_lm.server hot-swaps
    models per request and the outgoing weights are not guaranteed to be freed
    before the incoming ones are read, so a swap can hold both at once.

So the check is deliberately pessimistic: it budgets for the resident model
staying put, and reserves headroom for everything that is not us.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Fraction of physical RAM Metal will hand out as a working set. Apple does
#: not document the formula and it is version-dependent; 0.75 matches what
#: h3probe reported here (25.0 of 32 GiB) and is conservative on larger
#: machines, where the real fraction is higher.
GPU_FRACTION = 0.75

#: For WindowServer, the browser, a Docker VM, the audio server, the MCP
#: server -- everything that is not the model. Measured against a real crash:
#: Docker alone held 7.2 GB.
DEFAULT_RESERVE_GB = 6.0

#: The same reserve, for a DISCRETE card. Nothing else lives in VRAM: no
#: WindowServer, no Docker VM, no browser heap -- those sit in system RAM,
#: which the model never touches. Measured 1.2 GiB in use on this idle 4070
#: desktop, so 2 GB covers the compositor plus a browser's own GPU surfaces.
#: Carrying the 6 GB unified figure across would reserve half of a 12 GB card
#: and refuse models that fit with room to spare.
DISCRETE_RESERVE_GB = 2.0


@dataclass(frozen=True)
class Accelerator:
    """What the weights actually load into.

    The distinction is not cosmetic. On unified memory the budget is a
    FRACTION of system RAM, because the GPU is handed a working set out of the
    same pool as everything else. A discrete card is a hard wall: the 61.6 GB
    of system RAM behind a 12 GB 4070 is irrelevant to what the GPU can hold,
    and computing a budget from it produces 46 GB of imaginary headroom.
    """
    kind: str                #: "unified" (Apple Silicon) or "discrete" (NVIDIA)
    total_gb: float
    available_gb: float
    name: str = ""
    #: The Metal working set sysctl iogpu.wired_limit_mb sets, 0 when unset. #699.
    wired_gb: float = 0.0


def ceiling_for(acc: Accelerator) -> float:
    """The working set to budget against, given what we are loading into."""
    if acc.kind == "discrete":
        # The card is the wall; there is no fraction to take. What the desktop
        # is already holding comes off via available_gb, not off the ceiling.
        return acc.total_gb
    return acc.wired_gb or acc.total_gb * GPU_FRACTION


def reserve_for(acc: Accelerator) -> float:
    """Headroom for everything that is not the model. See the constants."""
    return DISCRETE_RESERVE_GB if acc.kind == "discrete" else DEFAULT_RESERVE_GB


def _unified_total_gb() -> float:
    """Physical RAM, on a machine where that is what the GPU draws from."""
    try:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        return int(out) / 1024 ** 3
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _wired_limit_gb() -> float:
    """The GPU working set a serving Mac raised with sysctl iogpu.wired_limit_mb, 0 when unset. #699."""
    try:
        out = subprocess.run(["sysctl", "-n", "iogpu.wired_limit_mb"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        return max(int(out), 0) / 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _metal_info() -> dict:
    """mlx's Metal device info, {} where mlx is not installed."""
    try:
        import mlx.core as mx
        return dict((getattr(mx, "device_info", None) or mx.metal.device_info)())
    except Exception:  # noqa: BLE001 - no mlx, or no Metal device
        return {}


def _working_set_gb() -> float:
    """sysctl iogpu.wired_limit_mb, else Metal's recommendedMaxWorkingSetSize; 0 when neither answers. #699."""
    wired = _wired_limit_gb()
    if wired:
        return wired
    try:
        return max(float(_metal_info().get("max_recommended_working_set_size") or 0), 0.0) / 1024 ** 3
    except (TypeError, ValueError):
        return 0.0


def system_memory_gb() -> float:
    """Physical RAM where there is no sysctl to ask. Standard library only:
    this runs before anything optional is installed."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        try:
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(
                    ctypes.byref(status)):
                return 0.0
        except (AttributeError, OSError):
            return 0.0
        return status.ullTotalPhys / 1024**3
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024**2
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def commit_headroom_gb() -> float | None:
    """What a new allocation may actually take: the commit limit less what is
    already committed. None where the platform has no such limit to read.

    THE WALL A PARTLY OFFLOADED MODEL HITS, and not the one anybody looks at.
    Serving an 18.48 GiB model on a 12 GiB card put the 4070 node 0.58 GiB from
    its commit limit, with 20.23 GiB of committed PRIVATE memory in one process
    and 0.34 GiB of standby cache, so almost nothing reclaimable. Past the
    limit, allocations fail across the whole machine and not only in the server.
    Free physical RAM says nothing useful about that: it was 0.54 GiB at the
    time and would have been 0.54 GiB with a 200 GiB pagefile, which would have
    been survivable. #779.

    Windows keeps the figure directly: GlobalMemoryStatusEx's ullAvailPageFile
    IS commit limit minus committed, so it already accounts for the pagefile.
    Linux exposes CommitLimit and Committed_AS, which mean the same thing only
    when overcommit is off, so it is read but treated as advisory. macOS has no
    commit limit: it grows swap until the disk is gone, so there is no number
    here to return and the caller should say nothing rather than guess.
    """
    if sys.platform == "win32":
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        try:
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(
                    ctypes.byref(status)):
                return None
        except (AttributeError, OSError):
            return None
        return status.ullAvailPageFile / 1024**3
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo", encoding="utf-8") as fh:
                have = {}
                for line in fh:
                    name = line.split(":", 1)[0]
                    if name in ("CommitLimit", "Committed_AS"):
                        have[name] = int(line.split()[1]) / 1024**2
            if len(have) == 2:
                return max(have["CommitLimit"] - have["Committed_AS"], 0.0)
        except (OSError, ValueError, IndexError, KeyError):
            # Unreadable meminfo is not zero headroom, it is no answer. Saying
            # so explicitly rather than falling through a bare `pass`, which
            # would have been a new entry in an inventory that may only shrink.
            return None
    return None


def _visible(cards: list[tuple], visible: str, order: str) -> list[tuple]:
    """The cards CUDA_VISIBLE_DEVICES names, by index or UUID prefix, up to the first it cannot match. #699."""
    by_index = order.strip().upper() == "PCI_BUS_ID" or len({(c[2], c[3]) for c in cards}) <= 1
    # FASTEST_FIRST numbering is not nvidia-smi's, so an index on mixed cards budgets the smallest. #699.
    ranked = cards if by_index else sorted(cards, key=lambda c: c[3])
    kept = []
    for x in (x.strip() for x in visible.split(",")):
        if x.isdigit():
            got = ranked[int(x) if by_index else len(kept)] if int(x) < len(ranked) else None
        else:
            got = next((c for c in cards if x and c[1].lower().startswith(x.lower())), None)
        if got is None:
            break
        if got not in kept:
            kept.append(got)
    return kept


def _discrete() -> Accelerator | None:
    """Every NVIDIA card CUDA_VISIBLE_DEVICES leaves visible, summed as llama-server splits across them; None if none. #699."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    cards = []
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            total_mib, free_mib = float(parts[3]), float(parts[4])
        except ValueError:
            continue
        if total_mib > 0:
            cards.append((parts[0], parts[1], parts[2], total_mib, free_mib))
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is not None:
        cards = _visible(cards, visible, os.environ.get("CUDA_DEVICE_ORDER") or "")
    if not cards:
        return None
    return Accelerator("discrete", sum(c[3] for c in cards) / 1024,
                       sum(c[4] for c in cards) / 1024, " + ".join(c[2] for c in cards))


def detect() -> Accelerator:
    """What this machine loads weights into. Unified is checked first, so a
    Mac answers without ever shelling out to a tool it does not have.

    A machine with neither answers with its system RAM. That is a PC with no
    discrete card, where an integrated GPU draws from the same pool the CPU
    does, and where anything that runs at all runs against system memory. The
    alternative was a zero, and a zero ceiling refuses every candidate on a
    machine that has not been asked yet.
    """
    total = _unified_total_gb()
    if total > 0:
        return Accelerator("unified", total, available_gb() or total,
                           platform.machine(), _working_set_gb())
    found = _discrete()
    if found:
        return found
    ram = system_memory_gb()
    return Accelerator("unified", ram, ram, platform.machine())


def total_gb() -> float:
    total = _unified_total_gb()
    if total > 0:
        return total
    found = _discrete()
    if found:
        return found.total_gb
    return system_memory_gb()


def ceiling_gb() -> float:
    """The working set to budget against, not the RAM figure on the box."""
    total = _unified_total_gb()
    if total > 0:
        return _working_set_gb() or total * GPU_FRACTION
    found = _discrete()
    if found:
        return found.total_gb
    return system_memory_gb() * GPU_FRACTION


def available_gb() -> float:
    """Free plus inactive, which is what the system can actually hand over."""
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        # No vm_stat means this is not a Mac. A discrete card reports its own
        # free memory directly, which is a better answer than total_gb().
        found = _discrete()
        if found:
            return found.available_gb
        # NOT total_gb(). On a Linux box with no card that answered "every byte
        # is free", and this module exists because a budget computed from a
        # number nobody checked took the machine down. MemAvailable is the
        # kernel's own estimate of what can be handed out without swapping,
        # which is the same question free+inactive answers on macOS.
        return _meminfo_available_gb() or total_gb()
    page = 16384
    counts = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip().rstrip(".")
        if value.isdigit():
            counts[key.strip()] = int(value)
        if "page size of" in line:
            digits = [w for w in line.split() if w.isdigit()]
            if digits:
                page = int(digits[0])
    # Free plus everything macOS will hand back without paging anything out.
    # Free + inactive ALONE understates badly right after reading a large model
    # off disk: most of what shows as active is file cache. On an idle machine
    # that `memory_pressure` called 92% free, free+inactive read 12.8 GB.
    free = sum(counts.get(k, 0) for k in
               ("Pages free", "Pages inactive", "Pages speculative",
                "Pages purgeable"))
    if not free:
        return total_gb()
    return free * page / 1024 ** 3


def _meminfo_available_gb(path: str = "/proc/meminfo") -> float:
    """MemAvailable, in GB. 0.0 where there is no /proc/meminfo."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024**2
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


#: A measured margin below this is more likely noise than a safe reserve.
MIN_RESERVE_GB = 1.0


def measured_reserve_gb(conn=None) -> float:
    """The largest margin `lh memory ramp` stored for this machine, else the
    default FOR THE ACCELERATOR IT IS BUDGETING FOR. #299, #415, #788.

    The fallback used to be DEFAULT_RESERVE_GB whatever the hardware was. That
    is the unified figure, right where the GPU draws from system RAM and 6 GiB
    belongs to the OS. On a discrete card it reserved half a 12 GiB card: the
    planner budgeted 5.99 GiB, refused a 14B whose weights and KV fit the card
    with room, and cost a 7B its eighth slot, which is the measured knee in KB
    #367. reserve_for() already made this distinction; nothing asked it.
    """
    from harness import memory_store as ms
    from harness import ramp, runs
    default = reserve_for(detect())
    try:
        with runs.store(conn) as c:
            margins = [r.get("margin_gb") for r in
                       ramp.runs(c, ms.machine_row(c))]
    except Exception:  # noqa: BLE001 - the guard must not fail on its own record
        return default
    margins = [m for m in margins if isinstance(m, (int, float))]
    return max(max(margins), MIN_RESERVE_GB) if margins else default


def measured_peak_gb(spec: str, conn=None) -> float | None:
    """The largest peak a stored run on THIS machine measured for `spec`. #322.

    0 means the work happened in a server process, so it is None.
    """
    from harness import candidates, runs
    with runs.store(conn) as c:
        key = candidates.key_for(c, spec)
        best = runs.peak_kb(c, key, runs.here(c)) if key else 0
    return best / 1024 ** 2 if best else None


def budget_gb(available_gb: float, ceiling_gb: float, resident_gb: float,
              reserve_gb: float) -> float:
    return min(available_gb, ceiling_gb) - reserve_gb - resident_gb


def fits(need_gb: float, available_gb: float, ceiling_gb: float,
         resident_gb: float = 0.0,
         reserve_gb: float = DEFAULT_RESERVE_GB) -> tuple[bool, str]:
    """Can `need_gb` of weights be loaded without taking the machine down?

    `resident_gb` is what a hot-swapping server may still be holding. Budgeting
    as if only one model is resident is exactly how this went wrong.
    """
    budget = budget_gb(available_gb, ceiling_gb, resident_gb, reserve_gb)
    if need_gb > budget:
        return False, (
            f"needs {need_gb:.1f} GB but only {budget:.1f} GB is safely "
            f"available ({available_gb:.1f} GB free, {ceiling_gb:.1f} GB GPU "
            f"ceiling, {reserve_gb:.1f} GB reserved for the system"
            + (f", {resident_gb:.1f} GB still resident" if resident_gb else "")
            + ")")
    return True, f"{need_gb:.1f} GB into {budget:.1f} GB"


def cache_path(repo: str) -> str | None:
    """Where this repo's recorded download is, or None if none is. #411."""
    from harness import downloads
    found = downloads.path_of(repo)
    return str(found) if found else None


def size_gb(path: str) -> float | None:
    """Weight size on disk: the best estimate of load cost, and free to get.

    None when unknown. NOT zero -- zero reads as "fits easily", which is the
    dangerous default for a number nobody could determine.
    """
    root = Path(path)
    if not root.exists():
        return None
    if root.is_file():
        return root.stat().st_size / 1024 ** 3 or None
    # Deduplicate by inode. The HuggingFace cache keeps the real weights in
    # blobs/ and symlinks them into snapshots/, so walking naively counts
    # every file TWICE -- which reported a 4.3 GB model as 8.6 GB and had the
    # guard refusing models that fit with room to spare.
    total = 0
    seen: set[tuple[int, int]] = set()
    for f in root.rglob("*"):
        try:
            st = f.stat()          # follows symlinks, which is what we want
            if not f.is_file():
                continue
            key = (st.st_dev, st.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += st.st_size
        except OSError:
            continue
    return total / 1024 ** 3 if total else None


def mlx_kv_bytes_per_token(repo: str) -> int:
    """f16 K and V bytes one token of context costs this repo, from its config.json; 0 when unknown. #699."""
    import json
    path = cache_path(repo)
    if not path:
        return 0
    root = Path(path)
    found = [root / "config.json"] if (root / "config.json").is_file() else sorted(root.rglob("config.json"))
    try:
        cfg = json.loads(found[0].read_text(encoding="utf-8")) if found else {}
    except (OSError, ValueError):
        return 0
    cfg = cfg.get("text_config") if isinstance(cfg.get("text_config"), dict) else cfg
    try:
        layers = int(cfg.get("num_hidden_layers") or 0)
        heads = int(cfg.get("num_attention_heads") or 0)
        kv = int(cfg.get("num_key_value_heads") or heads)
        dim = int(cfg.get("head_dim") or (int(cfg.get("hidden_size") or 0) // heads if heads else 0))
    except (TypeError, ValueError):
        return 0
    return 2 * layers * kv * dim * 2


#: Bits per weight in an unquantised checkpoint. Used to scale the on-disk
#: size when a caller will quantise on load.
_BASE_BITS = 16


def check_model(repo: str, resident_gb: float = 0.0,
                reserve_gb: float | None = None,
                quantize: int | None = None,
                spec: str = "", parallel: int = 0) -> tuple[bool, str]:
    """One call: will loading `repo` be safe on this machine right now?

    `quantize` is the bit width the CALLER will load at. Without it this used
    the on-disk size, which is right for a pre-quantised MLX repo and badly
    wrong for a bf16 checkpoint loaded with `--quantize 4`: it refused
    FLUX.1-dev at "needs 31.4 GB" while a stage using exactly that model ran
    successfully on the same machine. A guard that blocks working work gets
    switched off, which is worse than no guard at all.
    """
    need = need_gb(repo, quantize, spec, parallel)
    if need is None:
        # Allowed, but said out loud. Refusing everything uncached would make
        # the guard the thing that breaks the workflow.
        return True, f"size of {repo} is unknown (not cached); proceeding unchecked"
    if isinstance(need, str):
        return True, need
    if reserve_gb is None:
        reserve_gb = measured_reserve_gb()
    return fits(need, available_gb(), ceiling_gb(), resident_gb, reserve_gb)


def need_gb(repo: str, quantize: int | None = None, spec: str = "",
            parallel: int = 0) -> float | str | None:
    """What loading `repo` costs in GB, None when unknown, or why it cannot be priced."""
    path = cache_path(repo)
    need = size_gb(path) if path else None
    if need is not None and quantize:
        need = need * quantize / _BASE_BITS
    from harness import ds4
    if need is not None and spec.startswith(ds4.PREFIX):
        # ds4 reads its n-gram and Engram tables from disk; streaming holds only the expert cache. #611.
        resident = ds4.resident_bytes(spec, int(need * 1024 ** 3))
        if resident is None:
            return (f"{spec}: ds4 sizes its expert cache to the memory it finds; "
                    f"proceeding unchecked")
        need = resident / 1024 ** 3
    # A measured peak beats the weights-on-disk proxy. #322.
    peak = measured_peak_gb(spec) if spec else None
    if peak is not None and (need is None or peak > need):
        need = peak
    if need is None:
        return None
    if parallel:
        from harness import serving
        # Each request in flight holds its own KV cache beside the weights. #699.
        need += parallel * mlx_kv_bytes_per_token(repo) * serving.MLX_REQUEST_CTX / 1024 ** 3
    return need


def room_gb() -> float:
    """What fits() would budget here now with nothing resident: the quantity `room_gb:>n` reads. #928."""
    return budget_gb(available_gb(), ceiling_gb(), 0.0, measured_reserve_gb())


def wait_for(repo: str, spec: str = "", parallel: int = 0, resident_gb: float = 0.0,
             quantize: int | None = None) -> str:
    """The until a load fits() refused waits on: room for its need, or '' when the need is unknown. #928."""
    need = need_gb(repo, quantize, spec, parallel)
    if isinstance(need, str) or need is None:
        return ""
    return f"room_gb:>{need + resident_gb:.1f}"

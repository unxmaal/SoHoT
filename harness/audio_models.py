"""The models the audio server holds: read them, give a screened one back, and judge the server's footprint (#1671)."""
from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
import urllib.request

#: The launchd unit that runs scripts/serve-tts.sh.
SERVICE = "tts"
#: Seconds one read or DELETE of the audio server may take.
TIMEOUT_S = 10.0
#: GiB of physical footprint past which an idle tts server is restarted.
FOOTPRINT_MAX_GB = 16.0
#: Seconds vmmap may take to sum a large server's regions.
FOOTPRINT_TIMEOUT_S = 60.0
WHAT = "the tts server's footprint is past its limit with no request in flight and no eval using it"
_SERVER = re.compile(r"(?:-m\s+(?:mlx_audio\.server|harness\.tts_server)\b)")
_PHYS = re.compile(r"Physical footprint:\s+([\d.]+)([KMGT])")
_UNIT = {"K": 1 / 2**20, "M": 1 / 2**10, "G": 1.0, "T": 2.0**10}


def base_url() -> str:
    from harness import audio
    return audio.DEFAULT_BASE_URL.rstrip("/")


def port(base: str = "") -> int:
    return urllib.parse.urlsplit(base or base_url()).port or 80


def loaded(base: str = "", timeout: float | None = None, opener=urllib.request.urlopen) -> list[str] | None:
    """The model ids the server holds (its GET /v1/models is its load cache), or None when it cannot be asked."""
    try:
        with opener(f"{base or base_url()}/models", timeout=TIMEOUT_S if timeout is None else timeout) as r:
            got = json.loads(r.read())
    except (OSError, ValueError):
        return None
    return [str(m["id"]) for m in got.get("data") or [] if isinstance(m, dict) and m.get("id")]


def served() -> set[str]:
    """What the unit serves its own clients: the tts and stt lane defaults."""
    from harness import adopt, audio
    return {adopt.serving_default("tts", audio.DEFAULT_TTS_MODEL),
            adopt.serving_default("stt", audio.DEFAULT_STT_MODEL)}


def model_of(spec: str) -> str:
    """"tts:<repo>,voice=x" -> "<repo>"; "" for a spec no audio lane sends the server."""
    from harness import reasons
    lane, _, rest = str(spec or "").partition(":")
    return rest.partition(",")[0].strip() if lane in reasons._AUDIO_HEADS else ""


def release(model: str, why: str, *, base: str = "", keep=None, timeout: float | None = None,
            opener=urllib.request.urlopen, say=print) -> bool:
    """DELETE `model` from the server when it holds it and nothing serves it or waits on it; True when it let go."""
    timeout = TIMEOUT_S if timeout is None else timeout
    if not model or model not in (loaded(base, timeout, opener) or []):
        return False
    try:
        if keep is None:
            from harness import router
            keep = served() | router.kept()
    except Exception as exc:  # noqa: BLE001 - unknown protection means nothing is free to unload
        say(f"  audio: kept {model}: the lane defaults could not be read ({exc})")
        return False
    if model in keep:
        return False
    req = urllib.request.Request(f"{base or base_url()}/models?model_name={urllib.parse.quote(model, safe='')}",
                                 method="DELETE")
    try:
        with opener(req, timeout=timeout) as r:
            ok = r.status in (200, 204)
    except (OSError, ValueError) as exc:
        say(f"  audio: could not unload {model}: {exc}")
        return False
    if ok:
        say(f"  audio: unloaded {model} ({why})")
    return ok


def release_spec(spec: str, why: str, **kw) -> bool:
    """release() for the model an audio lane's candidate spec loads into the server."""
    model = model_of(spec)
    return bool(model) and release(model, why, **kw)


def footprint_gib(pid: int, run=subprocess.run) -> float | None:
    """`vmmap --summary`'s physical footprint of `pid` in GiB; None when it cannot be read."""
    try:
        got = run(["vmmap", "--summary", str(pid)], capture_output=True, text=True, timeout=FOOTPRINT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    m = _PHYS.search(got.stdout or "")
    return round(float(m.group(1)) * _UNIT[m.group(2)], 2) if m else None


def server_pid(unit_pid: int | None, procs) -> int | None:
    """The deepest process under the unit naming the server: `uv run`'s own argv names it too, its python child holds the models."""
    if unit_pid is None:
        return None
    by_pid = {p.pid: p for p in procs}
    by_parent: dict = {}
    for p in procs:
        by_parent.setdefault(p.ppid, []).append(p.pid)
    level, seen, found = [unit_pid], set(), None
    while level:
        seen.update(level)
        found = next((pid for pid in level if pid in by_pid and _SERVER.search(by_pid[pid].command)), found)
        level = [c for pid in level for c in by_parent.get(pid, []) if c not in seen]
    return found


def in_flight(lsof: str | None, pid: int) -> bool | None:
    """Whether the server holds an established connection (`lsof -Fpn` text); None when lsof could not be asked."""
    if lsof is None:
        return None
    owner = None
    for line in lsof.splitlines():
        if line.startswith("p"):
            owner = line[1:].strip()
        elif line.startswith("n") and owner == str(pid):
            return True
    return False


def watch(probes, procs) -> dict:
    """The tts server's pid, footprint, held models and whether a request is in flight; {} with no tts unit here."""
    pid = server_pid(probes.launchd_pid(SERVICE), procs)
    if pid is None:
        return {}
    return {"pid": pid, "footprint_gib": probes.footprint(pid), "limit_gib": FOOTPRINT_MAX_GB,
            "in_flight": in_flight(probes.mcp_connections(port()), pid), "loaded": loaded()}


def morning() -> dict:
    """watch() of this machine's tts server for soh morning, read only."""
    from harness import watchdog
    probes = watchdog.Probes()
    return watch(probes, probes.processes() or [])


def line(t: dict) -> str:
    """One morning line: the tts server's footprint against its limit and what it holds."""
    gib = t.get("footprint_gib")
    held = ", ".join(t.get("loaded") or []) or "nothing it can name"
    size = "footprint unreadable" if gib is None else f"{gib:.1f} GiB footprint (limit {t.get('limit_gib'):g})"
    return f"{size}; holds {held}"


def over(t: dict) -> str:
    """The morning needs-line when the footprint is past its limit, else ""."""
    gib = t.get("footprint_gib")
    if gib is None or gib <= (t.get("limit_gib") or FOOTPRINT_MAX_GB):
        return ""
    return (f"the tts server holds {gib:.1f} GiB, past tts_footprint_gb {t.get('limit_gib'):g}: the watchdog "
            "restarts it once idle, or run `scripts/launchd.sh restart tts`")


def _evals_use_audio(w) -> bool:
    """True when a running eval names an audio lane spec, or one wrote no progress file to say."""
    from harness.watchdog import _in_use
    used = _in_use(w)
    return used is None or any(model_of(u) for u in used)


def finding(w) -> list:
    """tts_footprint: past FOOTPRINT_MAX_GB, nothing in flight, no eval using the server; restart it."""
    from harness.watchdog import Finding, Subject
    got = w.tts or {}
    gib = got.get("footprint_gib")
    if gib is None or gib <= FOOTPRINT_MAX_GB or got.get("in_flight") is not False or _evals_use_audio(w):
        return []
    from harness import cuts
    cuts.cut("tts_footprint_gb", "tts server restarted past its footprint limit", dropped=1)
    return [Finding("tts_footprint", Subject("server", SERVICE, "the launchd tts unit's mlx_audio server",
                                             pid=got["pid"], detail={"service": SERVICE}),
                    {k: got.get(k) for k in ("footprint_gib", "limit_gib", "loaded")})]

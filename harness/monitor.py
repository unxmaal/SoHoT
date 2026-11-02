"""Machine monitoring through monit (#1485): render its config, install it, act on its alerts, read its state."""
from __future__ import annotations

import json
import math
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from harness import paths

#: Free GiB on the system Data volume below which monit alerts.
DISK_ALERT_GIB = 50
#: Free GiB at which the queue and the running evals pause, then monit alerts.
DISK_PAUSE_GIB = 25
#: Seconds between monit's checks.
CYCLE_S = 300
#: Seconds memory pressure stays at warn or worse before monit alerts.
MEMORY_WARN_S = 600
#: Seconds a service port stays closed before monit alerts; launchd restarts it meanwhile.
SERVICE_DOWN_S = 600
#: Seconds the du of the known growers may take on a disk alert, all of them together.
DU_TIMEOUT_S = 30
#: Seconds the webhook post may take.
POST_TIMEOUT_S = 10
#: Seconds a local command (monit -t, monit summary, launchctl, the notifier) may take.
CLI_TIMEOUT_S = 30
#: Discord refuses a message longer than this.
POST_CHARS = 2000

ENV_FILE = "monitor.env"
WEBHOOK = "SOH_ALERT_WEBHOOK"
LABEL = "com.unxmaal.localharness.monit"
TITLE = "SoHoT monit"
RECOVERED = "recovered"
DISK_KINDS = ("disk", "disk-pause")
KINDS = DISK_KINDS + ("volume", "volume-low", "memory", "service", RECOVERED)
#: (monit name, launchd unit, port variable, the launcher's default port): read as scripts/serve-*.sh read them.
SERVICES = (("gateway", "gateway", "GATEWAY_PORT", 4000), ("mlx", "mlx", "MLX_PORT", 8081),
            ("tts", "tts", "TTS_PORT", 8890))
HEADER = "# Rendered by `soh monitor install` (#1485). Install again rather than editing it."
_UNQUOTABLE = re.compile(r'[\s"]')


def state_dir(home: Path | None = None) -> Path:
    return Path(home or paths.home()) / "monit"


def rc_path(home: Path | None = None) -> Path:
    return state_dir(home) / "monitrc"


def alerts_path(home: Path | None = None) -> Path:
    return state_dir(home) / "alerts.jsonl"


def env_path(home: Path | None = None) -> Path:
    return Path(home or paths.home()) / ENV_FILE


def plist_path() -> Path:
    from harness import volume
    return volume.agents_dir() / f"{LABEL}.plist"


def cycles(seconds: float) -> int:
    return math.ceil(seconds / CYCLE_S) or 1


def read_env(path: Path) -> dict:
    """KEY=VALUE lines of the owner's monitor.env; a missing file is empty."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        out[key.strip()] = value.strip().strip("'\"")
    return out


def mount_point(path: str, run=subprocess.run) -> str:
    """The mount point of the filesystem holding `path` (or its nearest existing parent), as df names it."""
    where = Path(os.path.abspath(path))
    while not where.exists() and where != where.parent:
        where = where.parent
    try:
        got = run(["df", "-P", str(where)], capture_output=True, text=True, timeout=CLI_TIMEOUT_S)
        fields = got.stdout.strip().splitlines()[-1].split(None, 5) if got.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, IndexError):
        fields = []
    if len(fields) == 6 and fields[5].startswith("/"):
        return fields[5]
    from harness import volume
    return volume.volume_of(str(path))


def models_volume(data: str, run=subprocess.run) -> str | None:
    """The weights root's volume when it is not the system Data volume, mounted or not."""
    from harness import env, volume
    vol = volume.volume_of(env.configured())
    if Path(vol) == Path(vol).parent:
        return None
    if Path(vol).exists() and mount_point(vol, run=run) == data:
        return None
    return vol


def job_path(which=shutil.which) -> str:
    """PATH for monit's actions: uv, monit and the notifier wherever they are installed, then the system's."""
    dirs = [str(Path(p).parent) for p in (which("uv"), which("monit"), which("terminal-notifier")) if p]
    dirs += ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    return ":".join(dict.fromkeys(dirs))


def scripts_dir() -> Path:
    """The deploy checkout's scripts when it has this monitor's, else this checkout's."""
    deploy = paths.deploy_checkout()
    if deploy is not None and (deploy / "scripts" / "monit-alert.sh").is_file():
        return deploy / "scripts"
    return paths.REPO / "scripts"


def watched_services(agents: Path | None = None) -> list[tuple[str, int]]:
    """(name, port) of every service whose launchd unit is installed."""
    from harness import volume
    where = agents or volume.agents_dir()
    return [(name, int(os.environ.get(var) or port)) for name, unit, var, port in SERVICES
            if (where / f"{volume.PREFIX}.{unit}.plist").is_file()]


def spec_here(run=subprocess.run) -> dict:
    """What this machine's config is rendered from."""
    from harness import fetching
    home = paths.home()
    data = mount_point(str(home), run=run)
    return {"home": str(home), "scripts": str(scripts_dir()), "path": job_path(), "data": data,
            "models": models_volume(data, run=run), "models_floor_gib": fetching.DISK_FLOOR // (1024 ** 3),
            "services": watched_services()}


def _word(value) -> str:
    text = str(value)
    if not text or _UNQUOTABLE.search(text):
        raise ValueError(f"monit cannot take {text!r} in an exec line: it has a space or a quote")
    return text


def render(s: dict) -> str:
    """The monitrc text for a spec from spec_here(). It holds no secret: the webhook is read when an alert fires."""
    home, st = _word(s["home"]), _word(f"{s['home']}/monit")
    prefix = f"/usr/bin/env PATH={_word(s['path'])} {paths.ENV_VAR}={home}"
    alert = f"{prefix} {_word(s['scripts'])}/monit-alert.sh"

    def then(kind: str, recover: bool = True) -> str:
        back = f' else if succeeded then exec "{alert} {RECOVERED}"' if recover else ""
        return f'then exec "{alert} {kind}"{back}'

    out = [HEADER, f"set daemon {CYCLE_S}", f"set log {home}/logs/monit.log", f"set pidfile {st}/monit.pid",
           f"set idfile {st}/monit.id", f"set statefile {st}/monit.state",
           f"set httpd unixsocket {st}/monit.sock", "    allow localhost", "",
           f"check filesystem system_data with path {_word(s['data'])}",
           f"    if space free < {DISK_ALERT_GIB} GB {then('disk')}",
           f"    if space free < {DISK_PAUSE_GIB} GB {then('disk-pause', recover=False)}", ""]
    if s.get("models"):
        out += [f"check filesystem models_volume with path {_word(s['models'])}",
                f"    if does not exist {then('volume')}",
                f"    if space free < {int(s['models_floor_gib'])} GB {then('volume-low')}", ""]
    out += [f'check program memory_pressure with path "{prefix} {s["scripts"]}/monit-pressure.sh" '
            f"with timeout {CLI_TIMEOUT_S} seconds",
            f"    if status != 0 for {cycles(MEMORY_WARN_S)} cycles {then('memory')}", ""]
    for name, port in s.get("services") or []:
        out += [f"check host service_{_word(name)} with address 127.0.0.1",
                f"    if failed port {int(port)} type tcp for {cycles(SERVICE_DOWN_S)} cycles {then('service')}", ""]
    return "\n".join(out)


def plist(monit: str, home: Path) -> bytes:
    log = str(Path(home) / "logs" / "monit.log")
    return plistlib.dumps({"Label": LABEL, "ProgramArguments": [monit, "-I", "-c", str(rc_path(home))],
                           "RunAtLoad": True, "KeepAlive": True, "StandardOutPath": log, "StandardErrorPath": log,
                           "ProcessType": "Background"})


class InstallError(RuntimeError):
    pass


def write_rc(text: str, home: Path | None = None) -> Path:
    """The config at mode 600: monit refuses a control file others can read."""
    rc = rc_path(home)
    rc.parent.mkdir(parents=True, exist_ok=True)
    (Path(home or paths.home()) / "logs").mkdir(parents=True, exist_ok=True)
    tmp = rc.with_suffix(".new")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(rc)
    return rc


def syntax(monit: str, rc: Path, run=subprocess.run) -> str:
    """'' when `monit -t` accepts the config, else what it said."""
    got = run([monit, "-t", "-c", str(rc)], capture_output=True, text=True, timeout=CLI_TIMEOUT_S)
    return "" if got.returncode == 0 else (got.stdout + got.stderr).strip()[-600:]


def install(run=subprocess.run, which=shutil.which, platform: str | None = None) -> dict:
    """Render this machine's config, check it, and load monit under launchd. The webhook is never written."""
    if (platform or sys.platform) != "darwin":
        raise InstallError("soh monitor install is macOS-only: it loads a launchd agent")
    monit = which("monit")
    if not monit:
        raise InstallError("monit is not installed: brew install monit")
    from harness import volume
    s = spec_here(run=run)
    rc = write_rc(render(s))
    said = syntax(monit, rc, run=run)
    if said:
        raise InstallError(f"monit -t refused {rc}: {said}")
    unit = plist_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_bytes(plist(monit, paths.home()))
    run(["launchctl", "bootout", f"{volume._domain()}/{LABEL}"], capture_output=True, text=True,
        timeout=CLI_TIMEOUT_S)
    got = run(["launchctl", "bootstrap", volume._domain(), str(unit)], capture_output=True, text=True,
              timeout=CLI_TIMEOUT_S)
    if got.returncode != 0:
        raise InstallError(f"launchctl bootstrap {unit} failed: {(got.stderr or got.stdout).strip()[:300]}")
    return {"rc": str(rc), "plist": str(unit), "spec": s, "webhook": webhook_set()}


def webhook_set(home: Path | None = None) -> bool:
    return bool(read_env(env_path(home)).get(WEBHOOK))


def env_mode_problem(home: Path | None = None) -> str:
    p = env_path(home)
    try:
        mode = p.stat().st_mode
    except OSError:
        return ""
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        return f"{p} is mode {stat.S_IMODE(mode):o}; it holds the webhook, make it 600"
    return ""


def summary(monit: str, rc: Path, run=subprocess.run) -> tuple[bool, list[str]]:
    """(running, monit summary lines) from the daemon through its socket."""
    try:
        got = run([monit, "-c", str(rc), "summary"], capture_output=True, text=True, timeout=CLI_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, [f"monit summary failed: {exc}"]
    lines = [ln.rstrip() for ln in (got.stdout or got.stderr).splitlines() if ln.strip()]
    return got.returncode == 0, lines


def status(run=subprocess.run, which=shutil.which, expected: str | None = None) -> dict:
    """Is monit installed, running and on the config install would write now; is the webhook set."""
    monit, rc = which("monit"), rc_path()
    out = {"installed": bool(monit), "rc": str(rc), "current": None, "running": False, "summary": [],
           "webhook": webhook_set(), "problems": []}
    probs = out["problems"]
    if not monit:
        probs.append("monit is not installed (brew install monit, then soh monitor install): nothing watches "
                     "the disk, memory pressure or the models volume")
        return out
    if not rc.is_file():
        probs.append("monit is installed but not configured: run soh monitor install")
    else:
        if expected is None:
            try:
                expected = render(spec_here(run=run))
            except ValueError as exc:
                expected = f"unrenderable: {exc}"
        out["current"] = rc.read_text(encoding="utf-8") == expected
        if not out["current"]:
            probs.append(f"{rc} is not what soh monitor install renders now: run soh monitor install")
        out["running"], out["summary"] = summary(monit, rc, run=run)
        if not out["running"]:
            probs.append("monit is not running: soh monitor install loads it")
    if not out["webhook"]:
        probs.append(f"no {WEBHOOK} in {env_path()}: alerts go to the desktop and the morning brief only")
    mode = env_mode_problem()
    if mode:
        probs.append(mode)
    return out


def desktop(title: str, message: str, run=subprocess.run, which=shutil.which, platform: str | None = None) -> str:
    """terminal-notifier when installed; the watchdog's osascript notice when it is absent or fails."""
    from harness import watchdog
    platform = platform or sys.platform
    tn = which("terminal-notifier") if platform == "darwin" else None
    if not tn:
        return watchdog.desktop(title, message, run=run, platform=platform)
    try:
        got = run([tn, "-title", title, "-message", message[:200], "-group", LABEL], capture_output=True, text=True,
                  timeout=CLI_TIMEOUT_S)
        if got.returncode == 0:
            return "notified"
        first = f"terminal-notifier rc {got.returncode}"
    except (OSError, subprocess.SubprocessError) as exc:
        first = f"terminal-notifier {type(exc).__name__}"
    second = watchdog.desktop(title, message, run=run, platform=platform)
    if second.startswith(watchdog.NOTIFIED):
        return f"notified by osascript after {first}"
    return f"notify failed: {first}; {second.removeprefix('notify failed: ')}"


def post(text: str, url: str, opener=urllib.request.urlopen) -> str:
    """POST {"content": text} to the webhook; the outcome never holds the URL."""
    body = json.dumps({"content": text[:POST_CHARS]}).encode()
    try:
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "SoHoT-monit (#1485)"})
        with opener(req, timeout=POST_TIMEOUT_S) as resp:
            return f"posted: HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return f"post failed: HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - any failure is reported without its message, which may name the URL
        return f"post failed: {type(exc).__name__}"


def growers(home: Path | None = None) -> list[tuple[str, Path]]:
    """What has filled the Data volume before: runs, the repo lane's worktrees and mirrors, the queue, runtime trials."""
    from evals import repo
    from harness import runtime_trials
    home = Path(home or paths.home())
    cache = repo.cache_root()
    return [("runs", home / "runs"), ("repo worktrees", cache / "work"), ("repo cache", cache),
            ("queue", home / "queue"), ("runtime trials", home / runtime_trials.TRIALS_DIR)]


def du(found: list[tuple[str, Path]], timeout: float, popen=subprocess.Popen,
       clock=time.monotonic, sleep=time.sleep) -> list[dict]:
    """KiB under each grower by du -sk, all at once and stopped at `timeout`; a du cut short says so."""
    procs = []
    for name, path in found:
        if not Path(path).is_dir():
            procs.append((name, path, None))
            continue
        procs.append((name, path, popen(["du", "-sk", str(path)], stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True)))
    deadline, out = clock() + timeout, []
    while clock() < deadline and any(p is not None and p.poll() is None for _, _, p in procs):
        sleep(0.05)
    for name, path, proc in procs:
        row = {"name": name, "path": str(path), "kib": None, "why": "absent"}
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()
            row["why"] = f"over {timeout:g}s, not measured"
            from harness import cuts
            cuts.cut("harness/monitor.py:DU_TIMEOUT_S", f"du of {name} on a disk alert", value=timeout)
        elif proc is not None:
            fields = (proc.communicate()[0] or "").split()
            row.update(kib=int(fields[0]), why="") if fields and fields[0].isdigit() else row.update(why="no answer")
        out.append(row)
    return out


def du_line(rows: list[dict]) -> str:
    def one(r):
        return f"{r['name']} {r['kib'] / 1024 ** 2:.1f} GiB" if r["kib"] is not None else f"{r['name']} {r['why']}"
    return "growers: " + ", ".join(one(r) for r in sorted(rows, key=lambda r: -(r["kib"] or 0)))


def pause_all(reason: str) -> dict:
    """Pause the job queue and every running eval through its pause file, the watchdog's request path."""
    from harness import watchdog, workqueue
    workqueue.pause()
    reader = watchdog.ProgressFiles()
    return {"queue": "paused", "runs": [reader.pause(r, reason) for r in reader.runs()]}


def record(entry: dict, home: Path | None = None) -> None:
    p = alerts_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "<webhook>") if secret else text


def alert(kind: str, environ=None, *, notify=desktop, send=post, pause=pause_all, measure=None, clock=time.time,
          home: Path | None = None) -> dict:
    """monit's exec action: pause first on disk-pause, then the alert line, the desktop and the webhook; du on disk."""
    if kind not in KINDS:
        raise ValueError(f"unknown alert kind {kind!r}; one of {', '.join(KINDS)}")
    environ = os.environ if environ is None else environ
    url = read_env(env_path(home)).get(WEBHOOK, "")
    service, event, desc = (_scrub(environ.get(k) or d, url) for k, d in
                            (("MONIT_SERVICE", "manual"), ("MONIT_EVENT", ""), ("MONIT_DESCRIPTION", "")))
    entry = {"at": clock(), "kind": kind, "service": service, "event": event, "description": desc}
    if kind == "disk-pause":
        entry["paused"] = pause(f"monit: {service} {desc}")
    message = f"{kind}: {service}: {desc}".strip()
    if kind == "disk-pause":
        n = len(entry["paused"].get("runs") or [])
        message += f"; paused the job queue and {n} running eval(s); `soh jobs resume` once space is back"
    entry["message"] = message
    entry["desktop"] = notify(TITLE, entry["message"])
    entry["webhook"] = _scrub(send(f"{TITLE}: {entry['message']}", url), url) if url else "no webhook set"
    record(entry, home)
    _bound(kind, f"monit {service}: {desc}")
    if kind in DISK_KINDS:
        rows = (measure or (lambda: du(growers(home), DU_TIMEOUT_S)))()
        line = du_line(rows)
        after = {"at": clock(), "kind": "du", "service": service, "event": "", "description": line, "rows": rows}
        after["webhook"] = _scrub(send(f"{TITLE}: {service}: {line}", url), url) if url else "no webhook set"
        record(after, home)
        entry["du"] = line
    return entry


def _bound(kind: str, what: str) -> None:
    """Record the threshold that fired as a cut, as every other limit is."""
    from harness import cuts
    if kind == "disk":
        cuts.cut("harness/monitor.py:DISK_ALERT_GIB", what)
    elif kind == "disk-pause":
        cuts.cut("harness/monitor.py:DISK_PAUSE_GIB", what)
    elif kind == "memory":
        cuts.cut("harness/monitor.py:MEMORY_WARN_S", what)
    elif kind == "service":
        cuts.cut("harness/monitor.py:SERVICE_DOWN_S", what)


def alerts(since: float, home: Path | None = None) -> list[dict]:
    try:
        lines = alerts_path(home).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            got = json.loads(ln)
        except ValueError:
            continue
        if isinstance(got, dict) and float(got.get("at") or 0) >= since:
            out.append(got)
    return out


def still_open(found: list[dict]) -> list[dict]:
    """The alerts whose service has not recovered since."""
    last = {}
    for a in found:
        if a.get("kind") == "du":
            continue
        last[a.get("service")] = a
    return [a for a in last.values() if a.get("kind") != RECOVERED]


def morning(since: float, run=subprocess.run, which=shutil.which, home: Path | None = None) -> dict:
    """The brief's monitor section: monit's summary and the alerts in the window."""
    monit, rc = which("monit"), rc_path(home)
    out = {"alerts": alerts(since, home), "summary": [], "why": ""}
    if not monit:
        out["why"] = "monit is not installed"
    elif not rc.is_file():
        out["why"] = "monit is not configured: soh monitor install"
    else:
        running, out["summary"] = summary(monit, rc, run=run)
        if not running:
            out["why"] = "monit is not running"
    return out


def line(a: dict) -> str:
    when = time.strftime("%H:%M", time.localtime(float(a.get("at") or 0)))
    return f"{when} {a.get('kind')} {a.get('service')}: {a.get('description')}"

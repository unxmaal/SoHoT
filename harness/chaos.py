"""Fault scenarios run on purpose, on a scratch home, and only when explicitly asked. #492."""
from __future__ import annotations

import contextlib
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, NamedTuple

from harness import fetching, paths, reasons, screen
from harness import memory_store as ms

CONFIRM_FLAG = "--yes-break-things"
CI_VARS = ("CI", "GITHUB_ACTIONS", "BUILDKITE", "JENKINS_URL", "GITLAB_CI",
           "CIRCLECI", "TF_BUILD")
#: Environment variables that name a live path; each points into the scratch home.
SCRATCH_VARS = {paths.ENV_VAR: "", "HF_HOME": "hf", "LLAMACPP_MODELS_DIR": "gguf"}
#: Where scratch homes are made; None means the system temp directory.
SCRATCH_PARENT: Path | None = None
CANDIDATE = "chaos/scratch-model"
MIB = 1024 ** 2


class ChaosRefused(RuntimeError):
    """Chaos would have touched something it must never touch."""


class ChaosError(RuntimeError):
    """A scenario could not set up the fault it exists to cause."""


class Result(NamedTuple):
    name: str
    ok: bool
    detail: str


@dataclass
class Context:
    home: Path
    live: Path
    note: Callable = print


@dataclass
class Scenario:
    name: str
    run: Callable[[Context], tuple]


def environment():
    return os.environ, sys.modules


def machine_lock():
    from harness import exclusive
    return exclusive.try_held("chaos")


def refusal(confirmed: bool, env, modules) -> str:
    """Why chaos must not run here, or "" when it may."""
    if not confirmed:
        return (f"refusing: chaos kills processes and fills disks on purpose; "
                f"pass {CONFIRM_FLAG} to run it")
    if env.get("PYTEST_CURRENT_TEST") or "pytest" in modules:
        return "refusing: running under pytest; chaos never runs from a test"
    hit = [v for v in CI_VARS if env.get(v)]
    if hit:
        return f"refusing: running under CI ({', '.join(hit)} is set)"
    return ""


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


@contextlib.contextmanager
def scratch_home(parent: Path, live: Path):
    """A fresh LOCALHARNESS_HOME (and HF_HOME, models dir) under parent, removed on exit."""
    home = Path(tempfile.mkdtemp(prefix="soh-chaos-", dir=parent)).resolve()
    saved = {k: os.environ.get(k) for k in SCRATCH_VARS}
    try:
        if _inside(home, live):
            raise ChaosRefused(f"scratch home {home} is inside the live home")
        for var, sub in SCRATCH_VARS.items():
            os.environ[var] = str(home / sub) if sub else str(home)
        yield home
    finally:
        for var, was in saved.items():
            if was is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = was
        shutil.rmtree(home, ignore_errors=True)


@contextlib.contextmanager
def _no_service_restarts():
    """Nothing a scenario calls may restart a launchd service or sweep the weights cache."""
    from harness import disk, gateway, gguf
    blocked = [(gguf, "refresh_router"), (gateway, "refresh_gateway"), (disk, "sweep")]
    saved = [(mod, name, getattr(mod, name)) for mod, name in blocked]
    try:
        for mod, name in blocked:
            setattr(mod, name, lambda *a, **k: {})
        yield
    finally:
        for mod, name, fn in saved:
            setattr(mod, name, fn)


def run_all(scenarios, *, live: Path, parent: Path | None = None,
            note: Callable = print) -> list[Result]:
    """Each scenario on its own scratch home; one failing never stops the next."""
    live = Path(live).resolve()
    parent = Path(parent or SCRATCH_PARENT or tempfile.gettempdir()).resolve()
    if _inside(parent, live):
        raise ChaosRefused(f"scratch parent {parent} is inside the live home {live}")
    parent.mkdir(parents=True, exist_ok=True)
    results = []
    with _no_service_restarts():
        for s in scenarios:
            try:
                with scratch_home(parent, live) as home:
                    ok, detail = s.run(Context(home, live, note))
            except ChaosRefused:
                raise
            except Exception as exc:  # noqa: BLE001 - a scenario failing is its result
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            results.append(Result(s.name, bool(ok), str(detail)))
    return results


def seed(conn, name: str, size: int, lane: str = "code") -> None:
    """A scratch candidate, queued by inspect with a measured size."""
    ms.record(conn, ms.Seen(name=name, source="chaos", kind="candidate",
                            registry=ms.HUGGINGFACE, lane=lane, resolved=name))
    ms.set_size(conn, name, int(size))
    ms.decide(conn, name, "queued", tier=ms.INSPECT, detail="fits",
              reason=reasons.CANDIDATE)


def _state(conn, name: str) -> str:
    row = conn.execute("SELECT state FROM proposals WHERE name = ?", (name,)).fetchone()
    return row["state"] if row else ""


def _last_verdict(conn, name: str, tier: str):
    return conn.execute(
        "SELECT v.outcome, v.reason, v.detail FROM verdicts v JOIN proposals p "
        "ON p.id = v.proposal_id WHERE p.name = ? AND v.tier = ? "
        "ORDER BY v.id DESC LIMIT 1", (name, tier)).fetchone()


# --- scenario 1: a model server killed mid-screen ----------------------------

_STUB = r"""
import http.server, sys, time
from pathlib import Path
marker = Path(sys.argv[1])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"data": []}')
    def do_POST(self):
        marker.write_text("request", encoding="utf-8")
        time.sleep(3600)
    def log_message(self, *a):
        pass
s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
print(s.server_address[1], flush=True)
s.serve_forever()
"""


@dataclass
class Server:
    url: str
    proc: subprocess.Popen
    marker: Path | None = None


def start_stub_server(where: Path) -> Server:
    """A scratch OpenAI-shaped server child that hangs on every request until killed."""
    where = Path(where)
    where.mkdir(parents=True, exist_ok=True)
    marker = where / "request-arrived"
    proc = subprocess.Popen([sys.executable, "-c", _STUB, str(marker)],
                            stdout=subprocess.PIPE, text=True)
    port = (proc.stdout.readline() or "").strip()
    if not port.isdigit():
        kill(Server("", proc))
        raise ChaosError("the scratch model server did not start")
    return Server(f"http://127.0.0.1:{port}", proc, marker)


def kill(server: Server) -> None:
    if server.proc.poll() is None:
        server.proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        server.proc.wait(10)
    if server.proc.stdout:
        server.proc.stdout.close()


def answers(server: Server) -> bool:
    try:
        with urllib.request.urlopen(f"{server.url}/v1/models", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def run_screen(ctx: Context, row: dict, server: Server, kill_now) -> screen.Verdict:
    """The real screen against the scratch server, killed once the request is in flight."""
    from harness import candidates
    from harness.commands import measure as measure_cmd
    from harness.commands import screen as screen_cmd
    outdir = paths.runs() / f"chaos-screen-{int(time.time())}"
    argv = screen.argv(row, outdir=outdir) + ["--gateway", server.url]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=paths.REPO)
    try:
        deadline = time.time() + 120
        while time.time() < deadline and proc.poll() is None \
                and not (server.marker and server.marker.exists()):
            time.sleep(0.1)
        reached = bool(server.marker and server.marker.exists())
        kill_now()
        _, stderr = proc.communicate(timeout=600)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(10)
    if not reached:
        raise ChaosError("the screen never reached the scratch server, so nothing "
                         "was killed mid-request")
    stored = measure_cmd._receipt_at(outdir)
    summary = stored.get("summary") if stored else None
    return screen_cmd.verdict_of_run(proc.returncode, stderr, summary, row["candidate"],
                                     key=candidates.key_of(row["candidate"]))


@dataclass
class ServerKill:
    start: Callable = field(default=lambda ctx: start_stub_server(ctx.home / "server"))
    screen: Callable = field(default=run_screen)
    alive: Callable = field(default=answers)
    recover_seconds: float = 10.0


def _server_kill(ctx: Context, m: ServerKill) -> tuple[bool, str]:
    row = {"name": CANDIDATE, "candidate": "chaos-scratch", "modality": "code"}
    conn = ms.connect()
    server = None
    try:
        seed(conn, CANDIDATE, MIB)
        server = m.start(ctx)
        verdict = m.screen(ctx, row, server, lambda: kill(server))
        ms.decide_or_skip(conn, CANDIDATE, verdict.outcome, tier=ms.SCREEN,
                          detail=verdict.detail[:600], reason=verdict.reason,
                          until=verdict.until)
        state = _state(conn, CANDIDATE)
    finally:
        if server is not None:
            kill(server)
        conn.close()
    deadline = time.time() + m.recover_seconds
    back = m.alive(server)
    while not back and time.time() < deadline:
        time.sleep(0.5)
        back = m.alive(server)
    lane = "server came back" if back else (
        f"lane reported down: {server.url} did not answer within "
        f"{m.recover_seconds:g}s")
    fault = verdict.reason != reasons.CANDIDATE and state not in ms.TERMINAL
    said = (f"screen recorded {verdict.outcome} reason={verdict.reason} "
            f"class={verdict.failure_class or '-'}; {lane}")
    if not fault:
        return False, f"a killed server became a candidate verdict: {said}"
    return True, f"harness fault, not a candidate verdict: {said}"


def server_kill(m: ServerKill | None = None) -> Scenario:
    m = m or ServerKill()
    return Scenario("server-kill", lambda ctx: _server_kill(ctx, m))


# --- scenario 2: a scratch disk filled below the floor ------------------------

def fill(where: Path, n: int) -> Path:
    """A real file of n bytes, written rather than sparse, so it takes the space."""
    f = Path(where) / f"chaos-fill-{os.getpid()}-{n}.bin"
    chunk = b"\0" * min(n, MIB)
    left = n
    with open(f, "wb") as out:
        while left > 0:
            out.write(chunk[:left])
            left -= min(left, len(chunk))
        out.flush()
        os.fsync(out.fileno())
    return f


def _refuse_download(repo_id: str):
    raise ChaosError(f"a download of {repo_id} was attempted below the floor")


@dataclass
class DiskFill:
    free: Callable = field(default=lambda p: shutil.disk_usage(p).free)
    fill: Callable = field(default=fill)
    fill_bytes: int = 64 * MIB
    size: int = MIB
    snapshot: Callable = field(default=_refuse_download)
    fetch: Callable = field(default=fetching.run)


def _disk_fill(ctx: Context, m: DiskFill) -> tuple[bool, str]:
    if m.fill_bytes <= 2 * m.size:
        raise ChaosError("the fill must be more than twice the candidate's size")
    scratch = ctx.home / "disk"
    scratch.mkdir(parents=True, exist_ok=True)
    conn = ms.connect()
    filler = None
    try:
        seed(conn, CANDIDATE, m.size)
        floor = m.free(scratch) - m.fill_bytes // 2
        try:
            filler = m.fill(scratch, m.fill_bytes)
            have = m.free(scratch)
            if have - m.size >= floor:
                return False, "the fill did not take the scratch disk below the floor"
            got = m.fetch(conn, free=have, floor=floor, snapshot=m.snapshot, limit=1)
        finally:
            if filler is not None:
                filler.unlink(missing_ok=True)
        v = _last_verdict(conn, CANDIDATE, ms.FETCH)
        downloads = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    finally:
        conn.close()
    first = got[0] if got else {}
    said = (f"fetch said {first.get('why', 'nothing')!r}; "
            f"reason={v['reason'] if v else '-'} outcome={v['outcome'] if v else '-'}; "
            f"downloads={downloads}; filler removed={not filler.exists()}")
    ok = (bool(first) and not first.get("ok") and v is not None
          and v["reason"] not in ("", reasons.CANDIDATE)
          and downloads == 0 and not filler.exists())
    return ok, said


def disk_fill(m: DiskFill | None = None) -> Scenario:
    m = m or DiskFill()
    return Scenario("disk-fill", lambda ctx: _disk_fill(ctx, m))


# --- scenario 3: the HF client loses the network ------------------------------

@contextlib.contextmanager
def resetting_endpoint():
    """A local socket that resets every connection, as an HF_ENDPOINT."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(0.2)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            conn.close()

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.getsockname()[1]}"
    finally:
        stop.set()
        t.join(5)
        srv.close()


def _registry_for(url: str):
    from harness import feeds

    def fetch(u: str) -> str:
        return feeds.fetch(u.replace("https://huggingface.co", url), timeout=5,
                           retries=1, delay=0.0)
    return fetch


def _snapshot_for(url: str):
    def snapshot(repo_id: str):
        from huggingface_hub import constants, snapshot_download
        was = constants.HF_HUB_OFFLINE
        constants.HF_HUB_OFFLINE = False
        try:
            return snapshot_download(repo_id=repo_id, endpoint=url, etag_timeout=5)
        finally:
            constants.HF_HUB_OFFLINE = was
    return snapshot


@dataclass
class NetworkDrop:
    endpoint: Callable = field(default=resetting_endpoint)
    registry_for: Callable = field(default=_registry_for)
    snapshot_for: Callable = field(default=_snapshot_for)


def _network_drop(ctx: Context, m: NetworkDrop) -> tuple[bool, str]:
    from harness import inspect as ins
    conn = ms.connect()
    try:
        seed(conn, CANDIDATE, MIB)
        with m.endpoint() as url:
            try:
                ins.hf_model(CANDIDATE, fetch=m.registry_for(url))
                return False, "inspect got an answer through a dropped network"
            except ins.Gone as exc:
                return False, f"inspect settled it as Gone: {exc}"
            except ins.InspectError as exc:
                inspected = str(exc)
            got = fetching.run(conn, free=1 << 60, snapshot=m.snapshot_for(url),
                               limit=1)
        state = _state(conn, CANDIDATE)
        still = any(r["name"] == CANDIDATE for r in fetching.queued(conn))
        failed = conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE repo = ? AND complete = 0 "
            "AND finished_at IS NOT NULL", (CANDIDATE,)).fetchone()[0]
    finally:
        conn.close()
    first = got[0] if got else {}
    said = (f"inspect raised a harness fault ({inspected[:80]}); "
            f"fetch said {str(first.get('why', 'nothing'))[:80]!r}; state={state}, "
            f"queued for retry={still}, failed download rows={failed}")
    ok = (bool(first) and not first.get("ok") and state == "queued" and still
          and failed >= 1)
    return ok, said


def network_drop(m: NetworkDrop | None = None) -> Scenario:
    m = m or NetworkDrop()
    return Scenario("network-drop", lambda ctx: _network_drop(ctx, m))


def default_scenarios() -> list[Scenario]:
    return [server_kill(), disk_fill(), network_drop()]

"""Suite-wide isolation.

A test that writes to the developer's real LOCALHARNESS_HOME is invisible on
CI, where that directory does not exist, and visible only as junk accumulating
on the one machine nobody re-clones. Issue #188 found two such keys, `s` and
`blocked`, sitting in a real discovery-state.json for ten days.
"""
import socket
from pathlib import Path

import pytest

from harness import paths


@pytest.fixture(autouse=True)
def _home(tmp_path_factory, monkeypatch):
    """Every test gets its own LOCALHARNESS_HOME.

    Autouse and unconditional: an opt-in guard protects the tests that
    remembered, which are never the ones that leak.
    """
    home = tmp_path_factory.mktemp("lh-home")
    monkeypatch.setenv(paths.ENV_VAR, str(home))
    # Nor reads this machine's weights: what is on disk is a downloads row. #411.
    monkeypatch.setenv("HF_HOME", str(tmp_path_factory.mktemp("hf-home")))
    monkeypatch.delenv("LLAMACPP_MODELS_DIR", raising=False)
    # Nor this machine's Claude Code transcripts, which the ledger and the trends read. #827.
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path_factory.mktemp("claude-projects")))
    return home


@pytest.fixture(autouse=True)
def _no_reverse_dns(monkeypatch):
    """A reverse lookup costs ~35 s on check-macos; build servers from harness.loopback. #711."""
    def refuse(name=""):
        raise AssertionError(f"reverse DNS lookup of {name!r}; use harness.loopback")
    monkeypatch.setattr(socket, "getfqdn", refuse)


#: Set by CI on an unlabelled pull request; push to main, nightly and full-ci run everything. #720.
FAST_PATH_ENV = "SOHOT_FAST_PATH"


def pytest_collection_modifyitems(config, items):
    import os
    if os.environ.get(FAST_PATH_ENV) != "1":
        return
    skipped = [i for i in items if i.get_closest_marker("long")]
    if skipped:
        config.hook.pytest_deselected(items=skipped)
        items[:] = [i for i in items if not i.get_closest_marker("long")]
        print(f"\n{FAST_PATH_ENV}=1: deselected {len(skipped)} `long` tests; main and nightly run them")


@pytest.fixture(autouse=True)
def _no_real_metal(monkeypatch):
    """No test budgets against this Mac's Metal working set. #699."""
    from harness import memory
    monkeypatch.setattr(memory, "_metal_info", lambda: {})


@pytest.fixture(autouse=True)
def _cli_output_mode(monkeypatch):
    """cli.main sets common._JSON per call; a --json test must not turn the next test's output into JSON. #720."""
    from harness.commands import common
    monkeypatch.setattr(common, "_JSON", False)
    monkeypatch.setattr(common, "_VERB", "")


@pytest.fixture(autouse=True)
def _no_real_gateway_key(monkeypatch, _home):
    """No test reads or writes the real Keychain, or sends this machine's key. #482."""
    from harness import gateway_key
    monkeypatch.delenv(gateway_key.ENV_VAR, raising=False)
    monkeypatch.setattr(gateway_key, "default_store",
                        lambda: gateway_key.FileStore(_home / gateway_key.FILE_NAME))
    monkeypatch.setattr(gateway_key, "_cache", {})


@pytest.fixture(autouse=True)
def _no_real_services(monkeypatch):
    """No test restarts a launchd service. One did on 2026-10-04: a fetch test
    called the real refresh_router, the temporary home gave it a different
    lock, and it restarted the eval server under a live measurement. #319."""
    from harness import gateway, gguf
    restarts = []
    monkeypatch.setattr(gguf, "refresh_router", lambda *a, **k: restarts.append(k.get("expect", True)))
    monkeypatch.setattr(gateway, "refresh_gateway", lambda: restarts.append("gateway"))
    return restarts


@pytest.fixture(autouse=True)
def _no_real_launchd_units(monkeypatch):
    """No watchdog probe asks the real launchd, or the live mlx unit's /health, what it holds; only a test's own stub /health is asked. #912."""
    from harness import watchdog
    monkeypatch.setattr(watchdog.Probes, "launchd_loaded", lambda self, service: None)
    monkeypatch.setattr(watchdog.Probes, "launchd_pid", lambda self, service: None)
    from harness import mlx_server
    real = mlx_server.generating
    live = {u.rstrip("/") for u in ("http://127.0.0.1:8081", "http://localhost:8081")}
    monkeypatch.setattr(mlx_server, "generating",
                        lambda base, *a, **kw: None if base.rstrip("/") in live else real(base, *a, **kw))
    # No test asks the live mlx unit what it holds, so none swaps it off its model. #1082.
    held = mlx_server.held
    monkeypatch.setattr(mlx_server, "held",
                        lambda base, *a, **kw: None if base.rstrip("/") in live else held(base, *a, **kw))


@pytest.fixture(autouse=True)
def _no_real_strays(monkeypatch):
    """No test lists, and so none reaps, this machine's real stopped downloads or nettops. #1092."""
    from harness import throttle
    monkeypatch.setattr(throttle, "_ps", lambda: "")


@pytest.fixture(autouse=True)
def _no_real_lane_probes(monkeypatch):
    """No watchdog wake sends a real lane a completion; a test that wants the real probe restores Probes.lanes.real. #924."""
    from harness import watchdog

    def none(self, conn, now):
        return None
    none.real = watchdog.Probes.lanes
    monkeypatch.setattr(watchdog.Probes, "lanes", none)


@pytest.fixture(autouse=True)
def _no_real_router(monkeypatch):
    """No test asks or unloads the real llama-server router. #444."""
    from harness import context, router
    posts = []
    monkeypatch.setattr(router, "_get", lambda path: {"data": []})
    monkeypatch.setattr(context, "_get_json", lambda url, key="": {"data": []})
    monkeypatch.setattr(router, "_post",
                        lambda path, body: posts.append((path, body)) or {})
    return posts


@pytest.fixture(autouse=True)
def _free_disk_is_pinned(monkeypatch):
    """No test reads the runner's free disk: the tmp HF_HOME sits on whatever
    drive CI gives it (31 GiB on Windows), under the fetch floor. #411."""
    from harness import fetching
    monkeypatch.setattr(fetching, "free_bytes",
                        lambda path=None: 900 * fetching.GIB)


@pytest.fixture(autouse=True)
def _no_real_registry(monkeypatch):
    """No test reads a benchmark registry; a fixture fetcher is passed instead. #491."""
    from harness import benchmarks

    def refuse(url, params=None):
        raise RuntimeError(f"a test asked a real registry: {url}")
    monkeypatch.setattr(benchmarks, "_get_json", refuse)
    # Nor the papers API: a recorded fixture is passed instead. #576.
    from harness import papers
    monkeypatch.setattr(papers, "_get_json", refuse)
    # Nor the Hub API over httpx, which the fetch listing reads through ratelimit. #675.
    import httpx
    real_get = httpx.get

    def hub_refused(url, *a, **k):
        if str(url).startswith("https://huggingface.co/"):
            refuse(url)
        return real_get(url, *a, **k)
    monkeypatch.setattr(httpx, "get", hub_refused)


@pytest.fixture(autouse=True)
def _no_real_disk_sweep(monkeypatch):
    """No test deletes from the real weights cache. #373."""
    from harness import disk
    calls = []
    monkeypatch.setattr(disk, "sweep", lambda *a, **k: calls.append((a, k)) or {})
    return calls


#: Runtime binaries the suite must never execute on the machine it runs on. #536.
RUNTIME_BINARIES = ("llama-server", "llama-cli", "mlx_lm.server", "needle")
RUNTIME_PREFIXES = ("mflux-generate", "needle-")


def runtime_binary(args) -> str:
    """The runtime binary this argv would execute, or ""."""
    import os
    import shlex
    if isinstance(args, (str, bytes)):
        try:
            args = shlex.split(os.fsdecode(args))
        except ValueError:
            args = os.fsdecode(args).split()
    for word in list(args or [])[:4]:
        name = os.path.basename(os.fsdecode(word))
        if name in RUNTIME_BINARIES or name.startswith(RUNTIME_PREFIXES):
            return name
    return ""


@pytest.fixture(autouse=True)
def _no_real_runtime_probe(monkeypatch):
    """machine.versions is cached per process, so whichever test calls it first ran the real probes. #536."""
    from harness import machine, serving
    monkeypatch.setattr(serving, "llamacpp_build", lambda binary="": "")
    monkeypatch.setattr(machine, "_mflux_cli", lambda: "")


@pytest.fixture(autouse=True)
def _no_real_runtime_bytes(monkeypatch):
    """A run's content identity never reads the machine's real llama-server or its libraries; LLAMACPP_BIN names a fake. #1094."""
    import os

    from harness import identity
    monkeypatch.setattr(identity, "_linked", lambda exe: [])
    monkeypatch.setattr(identity, "llama_server",
                        lambda: Path(os.environ["LLAMACPP_BIN"]) if os.environ.get("LLAMACPP_BIN") else None)


@pytest.fixture(autouse=True)
def _no_real_runtime(request, monkeypatch):
    """No test executes a real runtime binary: it answers as absent and fails the test. #536."""
    import subprocess
    calls = []
    real = subprocess.Popen

    class Guarded(real):
        def __init__(self, args, *a, **k):
            name = runtime_binary(args)
            if name:
                calls.append(list(args) if not isinstance(args, (str, bytes)) else [args])
                raise FileNotFoundError(2, "runtime binary refused under test", name)
            super().__init__(args, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", Guarded)
    yield calls
    if calls and request.node.get_closest_marker("real_runtime") is None:
        pytest.fail(f"executed a real runtime binary: {calls}", pytrace=False)


def _rows_from(summary: dict) -> list[dict]:
    """Result rows whose summary is `summary`: n rows, constant time and metric."""
    rows = []
    for key, s in summary.items():
        n = int(s.get("total") or 10)
        passed = (round(float(s["pass_rate"]) * n) if "pass_rate" in s
                  else int(s.get("passed", n)))
        for i in range(n):
            rows.append({"case_id": f"case-{i}", "candidate": key,
                         "passed": i < passed,
                         "seconds": float(s.get("median_s") or 1.0),
                         "peak_kb": int(s.get("peak_kb") or 0),
                         "detail": "" if i < passed else "failed",
                         "output": None, "artifact_path": None, "warnings": [],
                         "metrics": dict(s.get("metrics") or {})})
    return rows


@pytest.fixture
def store_conn(tmp_path):
    """A fresh store connection for code that requires one, such as rank.rank. #893."""
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "store.db")
    yield conn
    conn.close()


@pytest.fixture
def store_run():
    """Store one run, as evals.run would, from rows or a summary. #410."""
    from harness import memory_store as ms
    from harness import paths, runs

    def make(name, lane, summary=None, *, rows=None, tier="measure",
             specs=None, hw_model=None, generated="2026-10-05T12:00:00",
             cases_digest="", conn=None, receipt=None):
        here = ms.this_machine()
        env = {"hw_model": here["hw_model"] if hw_model is None else hw_model,
               "os": here["os"], "arch": here["arch"]}
        data = {"generated": generated, "environment": env,
                "receipt": {"modality": lane, "tier": tier,
                            "cases_digest": cases_digest, **(receipt or {})},
                "specs": specs or {},
                "rows": rows if rows is not None else _rows_from(summary or {})}
        own = conn is None
        conn = conn or ms.connect()
        try:
            return runs.record(conn, paths.runs() / name, data)
        finally:
            if own:
                conn.close()
    return make


#: proposals, verdicts and machines as schema 13 left them. #442.
SCHEMA_13 = """
    CREATE TABLE proposals (id INTEGER PRIMARY KEY, name TEXT,
        kind TEXT DEFAULT '', lane TEXT DEFAULT '',
        resolved TEXT DEFAULT '', consumes TEXT DEFAULT '',
        produces TEXT DEFAULT '', first_seen REAL DEFAULT 0,
        last_seen REAL DEFAULT 0, registry TEXT DEFAULT '',
        description TEXT DEFAULT ''{proposals});
    CREATE TABLE verdicts (id INTEGER PRIMARY KEY, proposal_id INTEGER,
        outcome TEXT, tier TEXT DEFAULT '', detail TEXT DEFAULT '',
        issue INTEGER, run_path TEXT DEFAULT '', score REAL,
        rubric TEXT DEFAULT '', judge TEXT DEFAULT '', decided_at REAL,
        machine_id INTEGER, until TEXT DEFAULT '',
        size_bytes INTEGER DEFAULT 0{verdicts});
    CREATE TABLE machines (id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE,
        hw_model TEXT DEFAULT '', os TEXT DEFAULT '', arch TEXT DEFAULT '',
        memory_gb REAL DEFAULT 0, accelerator TEXT DEFAULT '',
        runtimes TEXT DEFAULT '', ceiling_gb REAL DEFAULT 0,
        first_seen REAL DEFAULT 0, last_seen REAL DEFAULT 0);
"""


@pytest.fixture
def old_store(tmp_path):
    """make(version, rows): an older store from explicit DDL, not DROP COLUMN. #442."""
    import sqlite3

    def make(version, rows="", *, ddl=None, proposals="", verdicts="",
             name="old.db"):
        path = tmp_path / name
        tables = ddl if ddl is not None else SCHEMA_13.format(
            proposals=proposals, verdicts=verdicts)
        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
                + tables + rows)
            conn.execute("INSERT INTO meta VALUES ('schema', ?)",
                         (str(version),))
            conn.commit()
        finally:
            conn.close()
        return path
    return make


@pytest.fixture
def real_ocr(monkeypatch):
    """A test that runs the real Vision OCR retries its transient a bounded number of times. #600.

    AND SKIPS WHERE THERE IS NO ENGINE AT ALL. A machine can legitimately have
    none: winsdk publishes no wheel above cp312, so Windows on 3.13 has no OS
    binding, and RapidOCR is a linux-only install so it does not stand in.
    Without this the tests still ran, read nothing, and a deliberately wrong
    word scored as correct, which reads as a scoring bug rather than as a
    missing engine. #758.
    """
    from harness.checks import ocr
    from tests.ocr_retry import retrying
    if ocr.available_backend() is None:
        pytest.skip("no OCR backend on this machine")
    monkeypatch.setattr(ocr, "read", retrying(ocr.read))


@pytest.fixture(autouse=True)
def _no_gateway_probe(monkeypatch):
    """No test probes a host to ask whether it is a gateway. #702."""
    from harness import completion
    monkeypatch.setattr(completion, "_answers_as_gateway", lambda base: False)


@pytest.fixture(scope="session")
def _render_cache(tmp_path_factory):
    import os
    base = tmp_path_factory.getbasetemp()
    # Under xdist the parent is shared by every worker of this run.
    root = (base.parent if os.environ.get("PYTEST_XDIST_WORKER") else base) / "render-cache"
    root.mkdir(exist_ok=True)
    return root


@pytest.fixture
def shared_render(monkeypatch, _render_cache):
    """Chrome renders each distinct page once per run, for tests of what a page shows rather than how it is shot. #724."""
    import hashlib
    import os
    import shutil
    from pathlib import Path

    from harness.checks import render
    real = render.rasterize_html

    def cached(html, out, width=800):
        key = hashlib.sha256(f"{width}\0{render.chrome_path()}\0{html}".encode()).hexdigest()
        hit = _render_cache / f"{key}.png"
        if not hit.exists():
            part = _render_cache / f"{key}.{os.getpid()}.png"
            real(html, part, width=width)
            os.replace(part, hit)
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(hit, out)
        return out

    monkeypatch.setattr(render, "rasterize_html", cached)
    return cached


#: This worker's identity, probed once under the suite's own patches. #747.
_IDENTITY: dict = {}


@pytest.fixture(autouse=True)
def _identity_per_test(monkeypatch, _home, _no_real_metal, _no_real_runtime_probe,
                       _no_real_runtime, _no_gateway_probe, _free_disk_is_pinned):
    """Every test starts from the same this_machine, whatever an earlier test on this worker cached. #747."""
    import copy

    from harness import machine
    from harness import memory_store as ms
    monkeypatch.setattr(ms.machines, "_PROVISIONAL", None)
    monkeypatch.setattr(machine, "_UUID_FAILED_AT", None)
    if "facts" not in _IDENTITY:
        monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
        monkeypatch.setattr(machine, "_UUID", None)
        got = ms.this_machine()
        if ms.machines._THIS_MACHINE is not None:
            _IDENTITY.update(facts=got, uuid=machine._UUID)
    monkeypatch.setattr(ms.machines, "_PROVISIONAL", None)
    monkeypatch.setattr(machine, "_UUID_FAILED_AT", None)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", copy.deepcopy(_IDENTITY.get("facts")))
    monkeypatch.setattr(machine, "_UUID", _IDENTITY.get("uuid"))
    # With no platform uuid (Windows) host_id reads LH_HOME, so the gateway's identity must find the pinned host there. #852.
    host = (_IDENTITY.get("facts") or {}).get("host")
    if host and not _IDENTITY.get("uuid"):
        (_home / machine.HOST_FILE).parent.mkdir(parents=True, exist_ok=True)
        (_home / machine.HOST_FILE).write_text(host, encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_inherited_purpose():
    """purpose.set_process writes os.environ; a cli or mcp test must not tag the next test's requests. #825."""
    import os
    from harness import purpose
    saved = os.environ.pop(purpose.ENV, None)
    yield
    os.environ.pop(purpose.ENV, None)
    if saved is not None:
        os.environ[purpose.ENV] = saved


@pytest.fixture
def windows_relative_paths(monkeypatch):
    """Path.relative_to answers a PureWindowsPath, so str() of a relative path has backslashes as on Windows. #1077."""
    import pathlib
    cls = type(pathlib.Path())
    real = cls.relative_to
    monkeypatch.setattr(cls, "relative_to", lambda self, *a, **k: pathlib.PureWindowsPath(real(self, *a, **k).as_posix()))

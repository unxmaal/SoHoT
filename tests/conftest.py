"""Suite-wide isolation.

A test that writes to the developer's real LOCALHARNESS_HOME is invisible on
CI, where that directory does not exist, and visible only as junk accumulating
on the one machine nobody re-clones. Issue #188 found two such keys, `s` and
`blocked`, sitting in a real discovery-state.json for ten days.
"""
import contextlib
import socket
from pathlib import Path

import pytest
from hypothesis import settings as hypothesis_settings

from harness import paths

# Bounded and reproducible in make check; the nightly passes --hypothesis-profile=deep. #1766
hypothesis_settings.register_profile("check", max_examples=60, stateful_step_count=25, derandomize=True,
                                     database=None, deadline=None, print_blob=True)
hypothesis_settings.register_profile("deep", max_examples=200, stateful_step_count=40, database=None,
                                     deadline=None, print_blob=True)
hypothesis_settings.load_profile("check")


def unset(monkeypatch, *keys):
    """Each key absent in the test and as it was after, though the code under test writes os.environ itself. #1868."""
    for k in keys:
        # setenv first: monkeypatch.delenv of an absent key records nothing to put back.
        monkeypatch.setenv(k, "")
        monkeypatch.delenv(k)


@pytest.fixture(autouse=True)
def _home(tmp_path_factory, monkeypatch):
    """Every test gets its own LOCALHARNESS_HOME.

    Autouse and unconditional: an opt-in guard protects the tests that
    remembered, which are never the ones that leak.
    """
    home = tmp_path_factory.mktemp("lh-home")
    monkeypatch.setenv(paths.ENV_VAR, str(home))
    # Nor holds or reads this machine's real gpu lock from an eval's scratch home. #1703.
    monkeypatch.setenv(paths.MACHINE_ENV, str(home))
    unset(monkeypatch, paths.MACHINE_FOR_ENV, paths.MACHINE_STORE_ENV)
    # Nor reads this machine's weights: what is on disk is a downloads row. #411.
    monkeypatch.setenv("HF_HOME", str(tmp_path_factory.mktemp("hf-home")))
    # Offline as env.guard() leaves every cli and eval process, and put back after one ran here. #1868.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.delenv("LLAMACPP_MODELS_DIR", raising=False)
    # Nor this machine's Claude Code transcripts, which the ledger and the trends read. #827.
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path_factory.mktemp("claude-projects")))
    return home


@pytest.fixture(autouse=True)
def _live_store_untouched():
    """A test that reached the live store fails, though the code under test swallowed the refusal. #1826."""
    from harness import store
    del store.REFUSALS[:]
    yield
    if store.REFUSALS:
        got, store.REFUSALS[:] = list(store.REFUSALS), []
        pytest.fail(f"reached the live store: {got}")


def _guard_sqlite():
    """sqlite3.connect refuses the live discovery.db for the whole session; no monkeypatch.undo() reaches it. #1826."""
    import sqlite3
    from harness import store
    if getattr(sqlite3.connect, "real", None) is not None:
        return

    def connect(database, *args, **kwargs):
        store.refuse_live(database)
        return connect.real(database, *args, **kwargs)

    connect.real = sqlite3.connect
    sqlite3.connect = connect


@pytest.fixture(autouse=True)
def _pg_schema(request, monkeypatch):
    """On LOCALHARNESS_STORE=postgres every test gets its own empty schema, as it gets its own home. #1507."""
    import os
    from harness import store
    # Restored after the test: an eval's scratch home pins its process to SQLite. #1579.
    monkeypatch.setenv(store.BACKEND_ENV, os.environ.get(store.BACKEND_ENV) or store.SQLITE)
    if request.node.get_closest_marker("sqlite_store"):
        monkeypatch.setenv(store.BACKEND_ENV, store.SQLITE)
    if store.backend() != store.POSTGRES:
        yield None
        return
    with own_schema(monkeypatch) as name:
        yield name


@contextlib.contextmanager
def own_schema(monkeypatch):
    """A fresh Postgres schema, dropped on the server it was made on whatever PG* the test set meanwhile. #1833."""
    import uuid
    import psycopg
    from harness import store
    store.refuse_live(postgres=True)
    admin_dsn = store.dsn()
    name = f"t_{uuid.uuid4().hex[:16]}"
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {name}")
    monkeypatch.setenv("PGOPTIONS", f"-c search_path={name}")
    try:
        yield name
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            # A connection the test leaked idles in a transaction holding locks the drop would wait on.
            admin.execute("SELECT pg_terminate_backend(l.pid) FROM pg_locks l "
                          "JOIN pg_class c ON c.oid = l.relation "
                          "JOIN pg_namespace n ON n.oid = c.relnamespace "
                          "WHERE n.nspname = %s AND l.pid <> pg_backend_pid()", (name,))
            admin.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")


@pytest.fixture(autouse=True)
def _no_reverse_dns(monkeypatch):
    """A reverse lookup costs ~35 s on check-macos; build servers from harness.loopback. #711."""
    def refuse(name=""):
        raise AssertionError(f"reverse DNS lookup of {name!r}; use harness.loopback")
    monkeypatch.setattr(socket, "getfqdn", refuse)


@pytest.fixture(autouse=True)
def _cold_caches():
    """The run that records the coverage map empties every function cache first, so each test's coverage is its own. #1571."""
    import os
    if os.environ.get("SOHOT_COVERAGE_MAP"):
        from tests.gauntlet import covmap
        covmap.clear_caches()


#: Set by CI on an unlabelled pull request; push to main, nightly and full-ci run everything. #720.
FAST_PATH_ENV = "SOHOT_FAST_PATH"


#: Set by CI on a pull request: a file listing the only test files the change can reach. #1567.
SELECTED_ENV = "SOHOT_SELECTED"
_selected: dict = {}


#: Each test's start and end are appended here as they happen, so a cancelled run says where its time went. #1146.
TEST_LOG_ENV = "SOHOT_TEST_LOG"
_test_log: dict = {}
_catches: dict = {}


def _without_junitxml(addopts: str) -> str:
    import shlex
    out, words = [], iter(shlex.split(addopts))
    for w in words:
        if w == "--junitxml" or w == "--junit-xml":
            next(words, None)
        elif not w.startswith(("--junitxml=", "--junit-xml=")):
            out.append(w)
    return shlex.join(out)


#: Past HANG_DUMP_S a test prints every thread's stack; past HANG_EXIT_S its process exits so xdist names it (#1351).
HANG_DUMP_S, HANG_EXIT_S = 180.0, 450.0
_running: dict = {}


def _stacks() -> str:
    import sys
    import threading
    import traceback
    names = {t.ident: t.name for t in threading.enumerate()}
    return "".join(f"Thread {names.get(ident, ident)}:\n{''.join(traceback.format_stack(frame))}\n"
                   for ident, frame in sys._current_frames().items())


def _hang_check(running: dict, now: float, write, leave) -> None:
    test = running.get("test")
    if test is None:
        return
    spent, dump_s, exit_s = now - test["began"], HANG_DUMP_S, HANG_EXIT_S
    if spent >= exit_s:
        write(f"\n{test['nodeid']} ran {spent:.0f} s, past {exit_s:.0f} s: exiting this test process\n")
        leave(70)
    elif spent >= dump_s and not test["dumped"]:
        # The flag goes up only once the text is out: a test that ends on it would take this daemon thread down. #1423.
        write(f"\n{test['nodeid']} has run {spent:.0f} s; every thread's stack:\n{_stacks()}")
        test["dumped"] = True


def _hang_watch() -> None:
    import os
    import sys
    import threading
    import time
    # Bound now, so a test that patches time.monotonic or os._exit cannot fire or silence this.
    clock, leave, tick, put = time.monotonic, os._exit, threading.Event(), os.write
    # A copy of stderr taken before any test's capture, as pytest's faulthandler plugin does.
    fd = os.dup(sys.__stderr__.fileno())

    def write(text):
        put(fd, text.encode("utf-8", "replace"))

    def loop():
        while not tick.wait(1.0):
            _hang_check(_running, clock(), write, leave)
    threading.Thread(target=loop, name="hang-watch", daemon=True).start()
    _running["clock"] = clock


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    clock = _running.get("clock")
    if clock is not None:
        _running["test"] = {"nodeid": item.nodeid, "began": clock(), "dumped": False}
    try:
        yield
    finally:
        _running.pop("test", None)


#: os.environ keys a test may leave changed: pytest's own, and those a library sets once per process on import. #1868, #1885, #1889.
ENV_SETTLED = frozenset({"PYTEST_CURRENT_TEST", "TRANSFORMERS_NO_ADVISORY_WARNINGS", "KMP_DUPLICATE_LIB_OK",
                         "KMP_INIT_AT_FORK", "TORCHINDUCTOR_CACHE_DIR", "LD_LIBRARY_PATH", "QT_QPA_FONTDIR",
                         "QT_QPA_PLATFORM_PLUGIN_PATH"})
_env: dict = {}


def env_left(before: dict, after) -> list[str]:
    """Each os.environ key a test left different, as `KEY: before -> after`."""
    keys = (set(before) | set(after)) - ENV_SETTLED
    return sorted(f"{k}: {before.get(k)!r} -> {after.get(k)!r}" for k in keys if before.get(k) != after.get(k))


def _env_restore(before: dict) -> list[str]:
    import os
    left = env_left(before, os.environ)
    for k in set(os.environ) - set(before) - ENV_SETTLED:
        del os.environ[k]
    os.environ.update({k: v for k, v in before.items() if k not in ENV_SETTLED and os.environ.get(k) != v})
    return left


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_setup(item):
    import os
    _env["before"] = dict(os.environ)
    return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    """A test that leaves os.environ changed fails, and the next test starts from the environment it found. #1868."""
    before = _env.pop("before", None)
    try:
        result = yield
    except BaseException:
        if before is not None:
            _env_restore(before)
        raise
    left = _env_restore(before) if before is not None else []
    if left:
        pytest.fail(f"left os.environ changed (use monkeypatch.setenv, or pass env= to the child): {left}",
                    pytrace=False)
    return result


def pytest_configure(config):
    import os
    from harness import store
    # The suite never takes its backend from the developer's home store.json; check-postgres sets it. #1614.
    os.environ.setdefault(store.BACKEND_ENV, store.SQLITE)
    # Not a monkeypatch, so no test's monkeypatch.undo() drops it; a pytest a test starts inherits it. #1826.
    os.environ[store.GUARD_ENV] = store.guard_flag(paths.DEFAULT_HOME, os.environ.get(store.GUARD_ENV, ""))
    _guard_sqlite()
    # faulthandler's timed dump of a running thread can spin forever in CPython 3.12 and wedge the worker (#1351).
    if not _running:
        _hang_watch()
    path = os.environ.pop(TEST_LOG_ENV, "")
    # Popped so a pytest a test starts collects its own files; xdist workers get it through workerinput.
    listed = os.environ.pop(SELECTED_ENV, "")
    _selected["file"] = getattr(config, "workerinput", {}).get(SELECTED_ENV, listed)
    # A pytest a test starts inherits PYTEST_ADDOPTS and overwrote CI's JUnit XML with its own 2 tests (#1146).
    if "--junit" in os.environ.get("PYTEST_ADDOPTS", ""):
        os.environ["PYTEST_ADDOPTS"] = _without_junitxml(os.environ["PYTEST_ADDOPTS"])
    if path and not hasattr(config, "workerinput"):
        _test_log["file"] = open(path, "a", encoding="utf-8", buffering=1)
        _test_log["spent"] = {}
    from harness import local_catches
    # Popped so neither xdist workers nor a pytest a test starts record; the real home is read before any fixture. #1261.
    if os.environ.pop(local_catches.ENV, "") == "1" and not os.environ.get("CI") and not hasattr(config, "workerinput"):
        _catches.update(path=local_catches.path(), head=local_catches.head(), seen=set(), failed=set())


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node):
    if _selected.get("file"):
        node.workerinput[SELECTED_ENV] = _selected["file"]


def pytest_ignore_collect(collection_path, config):
    if _selected.get("file"):
        from tests.gauntlet import scope
        return scope.ignored(collection_path, config.rootpath, _selected["file"]) or None
    return None


def pytest_terminal_summary(terminalreporter):
    from harness import store
    terminalreporter.write_line(f"store backend: {store.backend()}")


def pytest_unconfigure(config):
    f = _test_log.pop("file", None)
    _test_log.pop("collected", None)
    if f is not None:
        f.close()


def _log_line(event: str, nodeid: str, seconds: str = "") -> None:
    import time
    f = _test_log.get("file")
    if f is not None:
        f.write(f"{time.time():.3f}\t{event}\t{seconds}\t{nodeid}\n")


def pytest_runtest_logstart(nodeid, location):
    _log_line("start", nodeid)


def pytest_collection_finish(session):
    if session.items:
        _log_line("collected", "", str(len(session.items)))


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_node_collection_finished(node, ids):
    # Every worker collects the whole suite; the first one's count is the run's. #1520.
    if not _test_log.get("collected"):
        _test_log["collected"] = True
        _log_line("collected", "", str(len(ids)))


def pytest_sessionfinish(session, exitstatus):
    if _catches.get("seen"):
        from harness import local_catches
        local_catches.record(_catches["path"], _catches["head"], len(_catches["seen"]), int(exitstatus),
                             _catches["failed"])
    _catches.clear()


def pytest_runtest_logreport(report):
    if "seen" in _catches:
        _catches["seen"].add(report.nodeid)
        if report.failed:
            _catches["failed"].add(report.nodeid)
    spent = _test_log.get("spent")
    if spent is None:
        return
    spent[report.nodeid] = spent.get(report.nodeid, 0.0) + report.duration
    if report.when == "teardown":
        _log_line("end", report.nodeid, f"{spent.pop(report.nodeid):.3f}")


def store_state(path=None):
    """What a store holds, to see a write on either backend: a SQLite file's bytes, or each Postgres table's digest. #1579."""
    import hashlib
    from harness import memory_store as ms, store, store_copy
    if not store.home_postgres(path):
        p = Path(path or ms.db_path())
        files = [f for f in (p, p.with_name(p.name + "-wal")) if f.is_file()]
        return hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest() if files else None
    conn = store.open_ro(path)
    try:
        return {t: store_copy.digest(conn, t, store_copy.columns(conn, t)) for t in store_copy.tables(conn)}
    finally:
        conn.close()


def sqlite_copy(dest):
    """A SQLite copy of this home's store at `dest`, as an owner makes one on either backend. #1579."""
    from harness import memory_store as ms, store, store_copy
    if store.home_postgres(None):
        got = store_copy.to_sqlite_report(Path(dest))
        assert got["ok"], got
        return Path(dest)
    return store_copy.snapshot(ms.db_path(), Path(dest))


#: Tests still red on Postgres, one node id per line; the list's length is pinned and may only shrink. #1507.
POSTGRES_KNOWN = Path(__file__).parent / "gauntlet" / "postgres_known.txt"


def postgres_known() -> set[str]:
    try:
        lines = POSTGRES_KNOWN.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {ln.split("  #")[0].strip() for ln in lines if ln.strip() and not ln.startswith("#")}


def pytest_collection_modifyitems(config, items):
    import os
    from harness import store
    if store.backend() == store.POSTGRES:
        known = postgres_known()
        # A parameter id can carry a machine's local time, so a listed parameter set also matches by test name.
        named = {k.split("[")[0] for k in known if "[" in k}
        for item in items:
            # Not strict: several cut tests pass or fail on Postgres by xdist placement, which would flap CI.
            if item.nodeid in known or item.nodeid.split("[")[0] in named:
                item.add_marker(pytest.mark.xfail(strict=False, reason="known red on Postgres (#1507)"))
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
def _no_real_headroom(monkeypatch):
    """No sweep test stops on this machine's free memory; a test of the gate hands in its own. #1482."""
    from harness.commands import measure
    monkeypatch.setattr(measure, "headroom_gb", lambda: 1e6)


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
    activity = mlx_server.activity
    monkeypatch.setattr(mlx_server, "activity",
                        lambda base, *a, **kw: None if base.rstrip("/") in live else activity(base, *a, **kw))
    # No test reads, and so none DELETEs from, the live audio server. #1671.
    from harness import audio_models
    loaded, ears = audio_models.loaded, {"http://127.0.0.1:8890/v1", "http://localhost:8890/v1"}
    monkeypatch.setattr(audio_models, "loaded", lambda base="", *a, **kw: None
                        if (base or audio_models.base_url()).rstrip("/") in ears else loaded(base, *a, **kw))


@pytest.fixture(autouse=True)
def _no_real_strays(monkeypatch):
    """No test lists, and so none reaps, this machine's real stopped downloads or nettops. #1092."""
    from harness import throttle
    monkeypatch.setattr(throttle, "_ps", lambda: "")


@pytest.fixture(autouse=True)
def _no_real_contention(monkeypatch):
    """No queue test waits on this machine's memory pressure; a test of the gate restores workqueue._contended.real. #1509."""
    from harness import workqueue

    def calm(now, job=None):
        return False
    calm.real = workqueue._contended
    monkeypatch.setattr(workqueue, "_contended", calm)


@pytest.fixture(autouse=True)
def _no_real_admission(monkeypatch):
    """No queue test reads this machine's memory to admit a job; a test of admission restores admission.admit.real. #1558."""
    from harness import admission

    def roomy(n, held, sample=None):
        return True, "admitted by the test's stub"
    roomy.real = admission.admit
    monkeypatch.setattr(admission, "admit", roomy)


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
def _no_gateway_down_wait(monkeypatch):
    """A refused warm-up fails on its second refusal, not after GATEWAY_DOWN_WAIT_S; a test wanting the wait restores run.warm.real (#1146)."""
    from evals import run
    real = run.warm

    def warm(runner, clock=None, sleep=None):
        ticks = iter((0.0,))
        return real(runner, clock=clock or (lambda: next(ticks, float("inf"))), sleep=sleep or (lambda s: None))
    warm.real = real
    monkeypatch.setattr(run, "warm", warm)


@pytest.fixture(autouse=True)
def _no_server_back_wait(monkeypatch):
    """A screen that killed the mlx server looks at /health once, not for SERVER_BACK_WAIT_S (#1544)."""
    from harness.commands import screen
    monkeypatch.setattr(screen, "SERVER_BACK_WAIT_S", 0.0)


@pytest.fixture(autouse=True)
def _free_disk_is_pinned(monkeypatch):
    """No test reads the runner's free disk: the tmp HF_HOME sits on whatever
    drive CI gives it (31 GiB on Windows), under the fetch floor. #411."""
    from harness import fetching
    monkeypatch.setattr(fetching, "free_bytes",
                        lambda path=None: 900 * fetching.GIB)
    # Nor env.sh or harness.env: their 20 GB floor read the boot disk, which a full suite fills. #1423.
    monkeypatch.setenv("HF_MIN_FREE_GB", "0")
    from harness import env
    monkeypatch.setattr(env, "free_gb", lambda path: 900)


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
def _no_real_runtime_channel(monkeypatch):
    """No test reads PyPI or GitHub releases, or installs a runtime; tests pass fakes. #1474."""
    from harness import runtime_trials

    def refuse(*a, **k):
        raise RuntimeError(f"a test asked a real runtime release channel or install: {a}")
    for name in ("_get_json", "_gh", "_get_text", "_run"):
        monkeypatch.setattr(runtime_trials, name, refuse)


@pytest.fixture(autouse=True)
def _no_real_engine_trial(monkeypatch):
    """No test reads GitHub or PyPI, installs an engine, files an issue or asks the model for an engine trial; tests pass fakes. #1475."""
    from harness import engine_trials

    def refuse(*a, **k):
        raise RuntimeError(f"a test reached a real engine-trial channel: {a}")
    for name in ("_gh_json", "_pypi_json", "_run", "gh_run", "ask_model"):
        monkeypatch.setattr(engine_trials, name, refuse)


@pytest.fixture(autouse=True)
def _no_real_docker(monkeypatch):
    """No test asks this machine's Docker engine or removes a container; a test of it restores containers._info.real. #1510."""
    from harness import containers

    def absent(run=None):
        return None if run is None else absent.real(run)
    absent.real = containers._info
    monkeypatch.setattr(containers, "_info", absent)
    monkeypatch.setattr(containers, "remove", lambda name, run=None: None)
    monkeypatch.setattr(containers, "_vm", {})


@pytest.fixture(autouse=True)
def _no_real_hub_download(request, monkeypatch):
    """No test downloads from the Hub: one fetched a whole GGUF every run (#1146)."""
    if request.node.get_closest_marker("network") or request.node.get_closest_marker("slow"):
        return
    import huggingface_hub

    def refuse(*a, **k):
        raise RuntimeError(f"a test asked the real Hugging Face Hub for {a or k}")
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", refuse)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", refuse)


@pytest.fixture(autouse=True)
def _no_real_disk_sweep(monkeypatch):
    """No test deletes from the real weights cache. #373."""
    from harness import disk
    calls = []
    monkeypatch.setattr(disk, "sweep", lambda *a, **k: calls.append((a, k)) or {})
    return calls


#: Runtime binaries the suite must never execute on the machine it runs on. #536.
RUNTIME_BINARIES = ("llama-server", "llama-cli", "mlx_lm.server", "needle", "vectorcraft-cli", "figcraft-cli", "shots.sh")
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


#: Programs that put a notice on the owner's desktop. #1720.
NOTIFIERS = ("osascript", "terminal-notifier")


def real_notifier(args, env, fakes: Path) -> str:
    """The desktop notifier this argv would execute, unless it is a test's own fake under `fakes`; else ""."""
    import os
    import shutil
    if isinstance(args, (str, bytes)) or not args:
        return ""
    first = os.fsdecode(args[0])
    if os.path.basename(first) not in NOTIFIERS:
        return ""
    found = first if os.sep in first else shutil.which(first, path=(env or os.environ).get("PATH"))
    if found and Path(found).resolve().is_relative_to(fakes.resolve()):
        return ""
    return os.path.basename(first)


@pytest.fixture(autouse=True)
def _no_real_runtime(request, monkeypatch, tmp_path_factory):
    """No test executes a real runtime binary or desktop notifier: it answers as absent and fails the test. #536, #1720."""
    import subprocess
    calls, notices = [], []
    real = subprocess.Popen
    fakes = tmp_path_factory.getbasetemp()

    class Guarded(real):
        def __init__(self, args, *a, **k):
            name = runtime_binary(args)
            if name:
                calls.append(list(args) if not isinstance(args, (str, bytes)) else [args])
                raise FileNotFoundError(2, "runtime binary refused under test", name)
            name = real_notifier(args, k.get("env"), fakes)
            if name:
                notices.append(list(args)[:4])
                raise FileNotFoundError(2, "desktop notifier refused under test", name)
            super().__init__(args, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", Guarded)
    yield calls
    if calls and request.node.get_closest_marker("real_runtime") is None:
        pytest.fail(f"executed a real runtime binary: {calls}", pytrace=False)
    if notices:
        pytest.fail(f"reached a real desktop notifier (stub it or use _no_real_notifier): {notices}", pytrace=False)


@pytest.fixture(autouse=True)
def _no_real_notifier(monkeypatch):
    """Desktop notices and webhook posts land in this list; a call bringing its own fake run or opener reaches the real one. #1720."""
    import inspect
    import subprocess
    import urllib.request
    from harness import monitor, watchdog
    sent = []

    def recorder(real, kind, outcome, fake):
        def record(*a, **k):
            if inspect.signature(real).bind(*a, **k).arguments.get(fake) not in (None, subprocess.run,
                                                                                 urllib.request.urlopen):
                return real(*a, **k)
            sent.append((kind, *a[:2]))
            return outcome(*a)
        record.real = real
        return record
    monkeypatch.setattr(monitor, "desktop", recorder(monitor.desktop, "desktop", lambda *a: "notified", "run"))
    shown = lambda t, m, *a: watchdog.Said(f"{watchdog.NOTIFIED}: {m}", notified=True)  # noqa: E731
    monkeypatch.setattr(watchdog, "desktop", recorder(watchdog.desktop, "desktop", shown, "run"))
    monkeypatch.setattr(monitor, "post", recorder(monitor.post, "webhook", lambda *a: "posted: HTTP 204", "opener"))
    return sent


def _typed_keys() -> dict[str, str]:
    from harness import candidates, models, screen, winners
    out = {}
    for lane, name in winners.typed().items():
        spec = screen.candidate_for(lane, name) or name
        out.setdefault(candidates.key_of(spec), spec)
        out.update({old: old for old in models.old_names(spec) if old not in out})
    return out


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
def sat_exam(monkeypatch):
    """Every stored fixture run counts as a whole sitting of its lane's current exam, for tests that rank within one. #1120."""
    from harness import winners
    monkeypatch.setattr(winners, "on_exam", lambda *a, **k: True)


@pytest.fixture
def store_conn(tmp_path):
    """A fresh store connection for code that requires one, such as rank.rank. #893."""
    from harness import memory_store as ms
    conn = ms.connect()
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
        rows = rows if rows is not None else _rows_from(summary or {})
        if specs is None:
            # evals.run maps a typed default's key to its spec, so served() finds its row. #1247.
            typed = _typed_keys()
            specs = {r["candidate"]: typed[r["candidate"]] for r in rows if r.get("candidate") in typed}
        data = {"generated": generated, "environment": env,
                "receipt": {"modality": lane, "tier": tier,
                            "cases_digest": cases_digest, **(receipt or {})},
                "specs": specs,
                "rows": rows}
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
def old_store(tmp_path, monkeypatch):
    """make(version, rows): an older store from explicit DDL, not DROP COLUMN. #442."""
    import sqlite3
    from harness import store
    # An old store is a SQLite file; a Postgres store starts at the head schema by copy (#1507).
    monkeypatch.setenv(store.BACKEND_ENV, store.SQLITE)

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
    monkeypatch.setattr(ms.machines, "_THIS_FINGERPRINT", None)
    monkeypatch.setattr(machine, "_UUID", _IDENTITY.get("uuid"))
    # With no platform uuid (Windows) host_id reads LH_HOME, so the gateway's identity must find the pinned host there. #852.
    host = (_IDENTITY.get("facts") or {}).get("host")
    if host and not _IDENTITY.get("uuid"):
        (_home / machine.HOST_FILE).parent.mkdir(parents=True, exist_ok=True)
        (_home / machine.HOST_FILE).write_text(host, encoding="utf-8")


def name_machine(monkeypatch, env: dict) -> None:
    """Names this machine at the identity seam, environment.identity, so the cheap and full paths both see it. #1435."""
    from evals import environment
    from harness import machine
    from harness import memory_store as ms
    me = {k: env.get(k) or "" for k in ("hw_model", "os", "arch", "host")}
    me["fingerprint"] = machine.fingerprint(me["hw_model"], me["os"], me["arch"], me["host"])
    monkeypatch.setattr(environment, "identity", lambda: dict(me))
    monkeypatch.setattr(environment, "capture", lambda: {**env, **me})
    for name in ("_THIS_MACHINE", "_THIS_FINGERPRINT", "_PROVISIONAL"):
        monkeypatch.setattr(ms.machines, name, None)


def stand_in_machine(monkeypatch, facts: dict) -> dict:
    """this_machine() answers `facts`: identity named at the seam, measured facts held as its resolved answer. #1437."""
    from evals import environment
    from harness import memory_store as ms
    keys = ("hw_model", "os", "arch", "host")
    got = {**({} if any(k in facts for k in keys) else ms.this_machine()), **facts}
    name_machine(monkeypatch, {k: got[k] for k in (*keys, "memory_gb", "versions") if k in got})
    me = environment.identity()
    assert facts.get("fingerprint", me["fingerprint"]) == me["fingerprint"], f"{facts} names another machine than {me}"
    got = {k: v for k, v in {**got, **me}.items() if k != "partial"}
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", got)
    return got


@pytest.fixture
def machine_is(monkeypatch):
    return lambda env: name_machine(monkeypatch, env)


@pytest.fixture
def machine_has(monkeypatch):
    return lambda facts: stand_in_machine(monkeypatch, facts)


@pytest.fixture(autouse=True)
def _no_inherited_purpose(monkeypatch):
    """purpose.set_process writes os.environ; a cli or mcp test must not tag the next test's requests. #825."""
    from harness import purpose
    unset(monkeypatch, purpose.ENV, paths.EVAL_ENV)


@pytest.fixture
def windows_relative_paths(monkeypatch):
    """Path.relative_to answers a PureWindowsPath, so str() of a relative path has backslashes as on Windows. #1077."""
    import pathlib
    cls = type(pathlib.Path())
    real = cls.relative_to
    monkeypatch.setattr(cls, "relative_to", lambda self, *a, **k: pathlib.PureWindowsPath(real(self, *a, **k).as_posix()))


class _FakeChrome:
    """A chrome that never exits, on a clock that moves only when render._shoot sleeps. #1471."""
    pid = 1

    def __init__(self):
        self.now = 0.0
        self.terminated = 0
        self._growing: list[Path] = []

    def argv(self, out, writes=True, grows=False):
        if grows:
            self._growing.append(Path(out))
        return ["chrome", str(out) if writes else ""]

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        for p in self._growing:
            with open(p, "ab") as f:
                f.write(b"x")

    def Popen(self, argv, **kw):
        if argv[1]:
            Path(argv[1]).write_bytes(b"png")
        return self

    def poll(self):
        return None

    def terminate(self):
        self.terminated += 1

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


@pytest.fixture
def fake_chrome(monkeypatch):
    import types
    from harness.checks import render
    chrome = _FakeChrome()
    monkeypatch.setattr(render, "time", types.SimpleNamespace(monotonic=chrome.monotonic, sleep=chrome.sleep))
    monkeypatch.setattr(render.subprocess, "Popen", chrome.Popen)
    # On Windows _kill_tree runs taskkill through subprocess.run, which would get the fake too. #855.
    monkeypatch.setattr(render, "_kill_tree", lambda proc: None)
    return chrome

"""Suite-wide isolation.

A test that writes to the developer's real LOCALHARNESS_HOME is invisible on
CI, where that directory does not exist, and visible only as junk accumulating
on the one machine nobody re-clones. Issue #188 found two such keys, `s` and
`blocked`, sitting in a real discovery-state.json for ten days.
"""
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
    return home


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
    monkeypatch.setattr(gguf, "refresh_router", lambda: restarts.append(True))
    monkeypatch.setattr(gateway, "refresh_gateway", lambda: restarts.append("gateway"))
    return restarts


@pytest.fixture(autouse=True)
def _no_real_router(monkeypatch):
    """No test asks or unloads the real llama-server router. #444."""
    from harness import router
    posts = []
    monkeypatch.setattr(router, "_get", lambda path: {"data": []})
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
def _no_real_disk_sweep(monkeypatch):
    """No test deletes from the real weights cache. #373."""
    from harness import disk
    calls = []
    monkeypatch.setattr(disk, "sweep", lambda *a, **k: calls.append((a, k)) or {})
    return calls


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
def store_run():
    """Store one run, as evals.run would, from rows or a summary. #410."""
    from harness import memory_store as ms
    from harness import paths, runs

    def make(name, lane, summary=None, *, rows=None, tier="measure",
             specs=None, hw_model=None, generated="2026-10-05T12:00:00",
             cases_digest="", conn=None):
        here = ms.this_machine()
        env = {"hw_model": here["hw_model"] if hw_model is None else hw_model,
               "os": here["os"], "arch": here["arch"]}
        data = {"generated": generated, "environment": env,
                "receipt": {"modality": lane, "tier": tier,
                            "cases_digest": cases_digest},
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

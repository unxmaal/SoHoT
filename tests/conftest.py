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
def _no_real_services(monkeypatch):
    """No test restarts a launchd service. One did on 2026-10-04: a fetch test
    called the real refresh_router, the temporary home gave it a different
    lock, and it restarted the eval server under a live measurement. #319."""
    from harness import gguf
    restarts = []
    monkeypatch.setattr(gguf, "refresh_router", lambda: restarts.append(True))
    return restarts


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
                         "artifact": None, "warnings": [],
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

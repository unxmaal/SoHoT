"""A code-lane bare prompt whose measured used-rate is under the floor goes to cloud; checked shapes still run. #2033."""
import contextlib

import pytest

from harness import delegate, delegations
from harness import memory_store as ms

pytestmark = pytest.mark.sqlite_store
SPEC = "llamacpp:Ornith-1.5-35B-Q4_K_M"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = ms.connect(tmp_path / "discovery.db")
    monkeypatch.setattr(delegations, "ledger", lambda: contextlib.nullcontext(c))
    monkeypatch.setattr("harness.cuts.cut", lambda *a, **k: None)
    yield c
    c.close()


def _said(conn, outcomes, shape="prompt", spec=SPEC, lane="code"):
    for i, o in enumerate(outcomes):
        cid = f"local-{shape}-{spec}-{i}"
        delegations.record(conn, cid, lane, spec=spec, at=1000.0 + i, shape=shape)
        conn.execute("UPDATE delegations SET outcome = ? WHERE call_id = ?", (o, cid))
    conn.commit()


def test_a_low_used_rate_refuses_bare_code_prompts_to_that_spec_only(conn):
    _said(conn, ["used", "discarded", "discarded", "edited", "discarded", "used", "discarded", "edited"])
    why = delegations.shape_refusal("code", SPEC)
    assert "used as-is 25% of the last 8" in why and "cloud" in why
    assert delegations.shape_refusal("code", SPEC, "spans") == ""
    assert delegations.shape_refusal("code", "llamacpp:Next-Coder") == ""
    assert delegations.shape_refusal("extract", SPEC) == ""


def test_too_few_outcomes_or_a_rate_at_the_floor_lets_it_run(conn):
    _said(conn, ["discarded"] * (delegations.SHAPE_MIN - 1))
    assert delegations.shape_refusal("code", SPEC) == ""
    _said(conn, ["used"] * 7, spec="s2")
    _said(conn, ["discarded"] * 7, spec="s2", shape="ask")
    assert delegations.shape_refusal("code", "s2") == ""


def test_unshaped_history_counts_toward_the_rate(conn):
    _said(conn, ["discarded"] * 6 + ["used"] * 2, shape="")
    assert delegations.shape_refusal("code", SPEC)


def test_the_refusal_comes_before_any_local_call(conn, monkeypatch):
    _said(conn, ["discarded"] * 8)
    monkeypatch.setattr(delegate, "route", lambda lane, model=None: (SPEC, None))
    monkeypatch.setattr(delegate, "_preflight", lambda *a, **k: None)
    monkeypatch.setattr(delegate, "_serving", lambda *a, **k: pytest.fail("served a refused shape"))
    with pytest.raises(delegate.Refused, match="done in cloud"):
        delegate.complete("code", "write a function", delegated=True)
    with delegations.shaped("spans"), pytest.raises(RuntimeError):
        monkeypatch.setattr(delegate, "_budget", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("went on")))
        delegate.complete("code", "which lines", delegated=True)


def test_the_report_gives_each_shape_its_used_rate(conn):
    _said(conn, ["used", "discarded"])
    _said(conn, ["used", "used", "edited"], shape="spans")
    row = next(r for r in delegations.report(conn, since=1e12, now=2000.0) if r["lane"] == "code")
    assert row["shapes"] == {"prompt": {"count": 2, "recorded": 2, "used_rate": 0.5},
                             "spans": {"count": 3, "recorded": 3, "used_rate": 2 / 3}}


def test_the_shape_column_is_in_a_new_store(conn):
    assert "shape" in {r[1] for r in conn.execute("PRAGMA table_info(delegations)")}
    assert delegations.shape() == "prompt"
    with delegations.shaped("digest"):
        assert delegations.shape() == "digest"
    assert delegations.shape() == "prompt"

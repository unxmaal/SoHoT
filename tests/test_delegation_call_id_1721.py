"""A delegation's every gateway_requests row carries its call_id, so the ledger counts them as delegated. #1721."""
import json

import pytest

from harness import cli, delegate, delegations, digest, gateway_key, ledger, purpose, usage
from harness.ledger import local as tally
from tests.test_live_delegations_1717 import _open, _rows, elsewhere, live_sqlite  # noqa: F401
from tests.test_mcp_delegate import fake  # noqa: F401

pytestmark = pytest.mark.sqlite_store

LOG = "".join(f"line {i}: FAILED tests/test_x.py::test_{i} - AssertionError\n" for i in range(400))


def _counted(path):
    conn = _open(path)
    try:
        return tally(ledger.gateway_rows(conn, 0), delegations=ledger.delegation_rows(conn, 0))
    finally:
        conn.close()


def test_a_digest_from_another_checkout_leaves_its_call_id_on_every_request_row(tmp_path, live_sqlite):
    log = tmp_path / "check.log"
    log.write_text(LOG, encoding="utf-8")
    got = digest.run([str(log)], "what failed", cwd=tmp_path, size=4000)
    reqs = _rows(live_sqlite, "gateway_requests")
    (d,) = _rows(live_sqlite, "delegations")
    assert got["calls"] > 1 and len(reqs) == got["calls"]
    assert {r["call_id"] for r in reqs} == {d["call_id"]} == {got["call_id"]}
    (day,) = _counted(live_sqlite).values()
    assert day["delegated"]["requests"] == got["calls"] and day["unjoined"]["requests"] == 0


def test_a_spans_delegation_leaves_its_call_id_on_its_request_rows(tmp_path, live_sqlite):
    from harness import ask, spans
    from tests.test_spans_1336 import TEXT, model, quote
    (tmp_path / "a.py").write_text(TEXT, encoding="utf-8", newline="\n")
    inner = model(quote(20, 22))

    def complete(lane, prompt, **kw):
        inner(lane, prompt, **kw)
        return delegate.complete(lane, prompt, tag=kw.get("tag"))
    got = spans.ask_file(str(tmp_path / "a.py"), "q", roots=[ask.Root(tmp_path)], delegated=True, complete=complete)
    reqs = _rows(live_sqlite, "gateway_requests")
    assert reqs and {r["call_id"] for r in reqs} == {got["call_id"]}


def test_a_request_on_a_delegation_s_behalf_names_it_to_the_gateway_and_the_gateway_row_keeps_it():
    assert "delegation:" not in gateway_key.headers().get(purpose.HEADER, "")
    with delegations.on_behalf("local-abc"):
        with delegations.on_behalf(""):
            tags = gateway_key.headers()[purpose.HEADER].split(",")
    assert "delegation:local-abc" in tags and not delegations.behalf()
    slo = {"standard_logging_object": {"model_group": "sohot-extract", "litellm_call_id": "litellm-1",
                                       "request_tags": ["purpose:work", *tags]}}
    assert usage.row(slo, None)["call_id"] == "local-abc"
    slo["standard_logging_object"]["request_tags"] = ["purpose:work"]
    assert usage.row(slo, None)["call_id"] == "litellm-1"


def test_soh_delegated_with_only_a_call_id_lists_its_rows(tmp_path, live_sqlite, capsys):
    log = tmp_path / "check.log"
    log.write_text(LOG, encoding="utf-8")
    got = digest.run([str(log)], "what failed", cwd=tmp_path, size=4000)
    capsys.readouterr()
    assert cli.main(["delegated", got["call_id"], "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["delegation"]["call_id"] == got["call_id"] and len(shown["requests"]) == got["calls"]
    assert {r["client"] for r in shown["requests"]} == {usage.DIRECT_CLIENT}
    assert cli.main(["delegated", "local-none"]) == 1
    assert "0 gateway request(s)" in capsys.readouterr().out

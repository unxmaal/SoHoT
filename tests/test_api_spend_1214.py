"""#1214: what a metered gateway alias spends is recorded in dollars, and past api_budget it is refused."""
import json

import pytest

from harness import api_spend, purpose
from harness import memory_store as ms

PRICE = {"input_cost_per_token": 4e-06, "output_cost_per_token": 2e-05,
         "cache_read_input_token_cost": 2e-07, "cache_creation_input_token_cost": 5e-06}
OPUS = {"model_name": "cloud-opus", "litellm_params": {"model": "anthropic/claude-opus-5-5",
                                                         "api_key": "os.environ/ANTHROPIC_API_KEY", **PRICE}}
LOCAL = {"model_name": "sohot-code", "litellm_params": {"model": "openai/up", "api_base": "http://127.0.0.1:1/v1",
                                                          "api_key": "not-needed"}}
UNPRICED = {"model_name": "cloud-sonnet", "litellm_params": {"model": "anthropic/claude-sonnet-5-5"}}


@pytest.fixture
def config(tmp_path):
    import yaml
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"model_list": [OPUS, LOCAL, UNPRICED]}), encoding="utf-8")
    return p


def _kwargs(alias="cloud-opus", cost=0.0123, prompt=1000, completion=100, tags=("purpose:eval", "job:42"),
            cache_read=0, cache_write=0):
    return {"standard_logging_object": {
        "model_group": alias, "model": "claude-opus-5-5", "startTime": 1000.0, "endTime": 1001.0,
        "prompt_tokens": prompt, "completion_tokens": completion, "response_cost": cost,
        "request_tags": [*tags, "User-Agent: curl"], "litellm_call_id": "call-1",
        "metadata": {"usage_object": {"cache_read_input_tokens": cache_read,
                                      "cache_creation_input_tokens": cache_write}}}}


def test_only_an_anthropic_or_priced_entry_is_metered():
    assert api_spend.metered(OPUS) and api_spend.metered(UNPRICED)
    assert not api_spend.metered(LOCAL) and not api_spend.metered(None)
    priced_local = {"model_name": "x", "litellm_params": {"model": "openai/x", "api_base": "http://h/v1",
                                                         "output_cost_per_token": 1e-06}}
    assert api_spend.metered(priced_local)


def test_a_row_carries_litellm_s_cost_tokens_and_caller():
    r = api_spend.row(_kwargs(), None, OPUS)
    assert (r["alias"], r["model"], r["call_id"]) == ("cloud-opus", "claude-opus-5-5", "call-1")
    assert (r["prompt_tokens"], r["completion_tokens"]) == (1000, 100)
    assert r["cost_usd"] == pytest.approx(0.0123) and r["cost_source"] == "litellm"
    assert r["caller"] == "job:42,purpose:eval"


def test_with_no_litellm_cost_the_row_is_priced_from_the_declared_price():
    # LiteLLM's prompt_tokens for Anthropic already includes both kinds of cache token.
    r = api_spend.row(_kwargs(cost=None, prompt=1700, completion=100, cache_read=500, cache_write=200), None, OPUS)
    want = 1000 * 4e-06 + 100 * 2e-05 + 500 * 2e-07 + 200 * 5e-06
    assert r["cost_usd"] == pytest.approx(want) and r["cost_source"] == "tokens"
    assert (r["cache_read_tokens"], r["cache_write_tokens"]) == (500, 200)


def test_spent_counts_rows_since_the_recorded_start_and_remaining_follows_the_budget():
    conn = ms.connect()
    try:
        api_spend.record(conn, {**api_spend.row(_kwargs(cost=3.0), None, OPUS), "at": 100.0})
        api_spend.record(conn, {**api_spend.row(_kwargs(cost=5.0, tags=("purpose:work",)), None, OPUS),
                                "at": 200.0})
        assert api_spend.spent(conn) == pytest.approx(8.0)
        api_spend.set_start(conn, 150.0)
        got = api_spend.status(conn, budget=6.0)
        assert got["spent"] == pytest.approx(5.0) and got["remaining"] == pytest.approx(1.0)
        assert got["start"] == 150.0 and got["callers"][0]["caller"] == "purpose:work"
    finally:
        conn.close()


def test_a_metered_alias_past_the_budget_is_refused_naming_the_knob_and_the_amount(config):
    assert api_spend.gate("cloud-opus", config=config, budget=1.0) == ""
    conn = ms.connect()
    try:
        api_spend.record(conn, api_spend.row(_kwargs(cost=1.25), None, OPUS))
        cuts = conn.execute("SELECT COUNT(*) FROM limit_cuts WHERE knob = 'api_budget'").fetchone()[0]
    finally:
        conn.close()
    why = api_spend.gate("cloud-opus", config=config, budget=1.0)
    assert "api_budget" in why and "$1.25" in why
    conn = ms.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM limit_cuts WHERE knob = 'api_budget'").fetchone()[0] == cuts + 1
    finally:
        conn.close()


def test_an_unpriced_metered_alias_is_refused_and_a_local_one_never_reads_the_store(config, monkeypatch):
    assert "input_cost_per_token" in api_spend.gate("cloud-sonnet", config=config)
    monkeypatch.setattr(api_spend, "_open", lambda: (_ for _ in ()).throw(AssertionError("store read")))
    assert api_spend.gate("sohot-code", config=config) == ""
    assert api_spend.note(_kwargs(alias="sohot-code"), None, config=config) is False


def test_an_unreadable_store_refuses_a_metered_request(config, monkeypatch):
    def broken():
        raise OSError("disk gone")
    monkeypatch.setattr(api_spend, "_open", broken)
    assert "cannot read" in api_spend.gate("cloud-opus", config=config)


def test_note_records_a_metered_success_and_nothing_for_a_local_alias(config):
    assert api_spend.note(_kwargs(cost=0.5), None, config=config) is True
    assert api_spend.note(_kwargs(alias="sohot-code", cost=0.5), None, config=config) is False
    conn = ms.connect()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM api_spend")]
    finally:
        conn.close()
    assert [r["alias"] for r in rows] == ["cloud-opus"]


def test_a_job_s_requests_carry_its_id_as_a_tag(monkeypatch):
    monkeypatch.setenv("LH_JOB_ID", "142")
    monkeypatch.setenv(purpose.ENV, "eval")
    assert purpose.headers() == {purpose.HEADER: "purpose:eval,job:142"}
    monkeypatch.delenv(purpose.ENV)
    assert purpose.headers() == {purpose.HEADER: "job:142"}


def test_the_estimate_is_cases_times_tokens_times_price():
    assert api_spend.estimate(10, (1000, 100), PRICE) == pytest.approx(10 * (1000 * 4e-06 + 100 * 2e-05))
    assert api_spend.estimate(10, None, PRICE) is None


def _results(conn, lane, prompt, completion, n=3):
    cur = conn.execute("INSERT INTO runs (path, lane, generated_at, recorded_at) VALUES (?, ?, ?, ?)",
                       (f"/r/{lane}", lane, 1000.0, 1000.0))
    for i in range(n):
        conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, passed, metrics) VALUES (?,?,?,?,?,?)",
                     (cur.lastrowid, i, "local-x", f"c{i}", 1,
                      json.dumps({"prompt_tokens": prompt, "completion_tokens": completion})))
    conn.commit()


def test_tokens_per_case_come_from_the_lane_s_stored_results():
    conn = ms.connect()
    try:
        assert api_spend.per_case(conn, "code") is None
        _results(conn, "code", 2000, 500)
        assert api_spend.per_case(conn, "code") == (2000.0, 500.0)
        _results(conn, "web", None, 800)
        assert api_spend.per_case(conn, "web") is None
        conn.execute("INSERT INTO gateway_requests (at, alias, lane, prompt_tokens) VALUES (1.0, 'sohot-web', 'web', 300)")
        conn.commit()
        assert api_spend.per_case(conn, "web") == (300.0, 800.0)
    finally:
        conn.close()


def test_a_run_whose_estimate_exceeds_the_remaining_budget_is_refused(config):
    conn = ms.connect()
    try:
        _results(conn, "code", 10000, 1000)
    finally:
        conn.close()
    each = 10000 * 4e-06 + 1000 * 2e-05
    ok = api_spend.check_run({"cloud-opus": {"code": 5}, "sohot-code": {"code": 100}}, config=config, budget=1.0)
    assert ok["refuse"] == "" and ok["estimate"] == pytest.approx(5 * each)
    bad = api_spend.check_run({"cloud-opus": {"code": 50}}, config=config, budget=1.0)
    assert "api_budget" in bad["refuse"] and bad["estimate"] == pytest.approx(50 * each)
    assert api_spend.check_run({"sohot-code": {"code": 10 ** 6}}, config=config, budget=0.0) is None


def test_an_unmeasured_lane_is_admitted_with_an_unknown_estimate(config):
    got = api_spend.check_run({"cloud-opus": {"craft": 20}}, config=config, budget=1.0)
    assert got["estimate"] is None and got["refuse"] == "" and got["unmeasured"] == ["craft"]


def test_a_queued_eval_of_a_metered_alias_is_refused_past_the_budget_and_a_local_one_is_not(monkeypatch):
    import sys

    from harness import workqueue
    conn = ms.connect()
    try:
        _results(conn, "code", 10 ** 6, 10 ** 5)
    finally:
        conn.close()
    argv = [sys.executable, "-m", "evals.run", "--modality", "code", "--candidates", "cloud-opus"]
    with pytest.raises(ValueError, match="api_budget"):
        workqueue.add(argv)
    assert workqueue.jobs() == []
    local = [sys.executable, "-m", "evals.run", "--modality", "code", "--candidates", "sohot-code"]
    assert workqueue.add(local)["state"] == workqueue.PENDING
    monkeypatch.setattr(api_spend, "BUDGET_USD", 10 ** 9)
    assert workqueue.add(argv)["state"] == workqueue.PENDING


def test_an_eval_run_prints_its_estimate_and_refuses_past_the_budget(capsys):
    from evals import run
    conn = ms.connect()
    try:
        _results(conn, "code", 10 ** 6, 10 ** 5)
    finally:
        conn.close()
    args = run.parse_args(["--modality", "code", "--candidates", "cloud-opus"])
    _, _, cases = run._plan(args)
    got = run.spend_check(["cloud-opus", "sohot-code"], cases)
    n = len(run.cases_for("cloud-opus", cases))
    assert n and got["estimate"] == pytest.approx(n * (10 ** 6 * 4e-06 + 10 ** 5 * 2e-05))
    with pytest.raises(SystemExit, match="api_budget"):
        run._execute(run.parse_args(["--modality", "code", "--candidates", "cloud-opus"]))
    assert "api spend estimate $" in capsys.readouterr().out
    assert run.spend_check(["sohot-code"], cases) is None


def test_soh_api_spend_and_the_morning_line_report_dollars_for_this_ledger(capsys):
    from harness import cli, morning
    from harness.commands import morning as morning_cmd
    conn = ms.connect()
    try:
        api_spend.record(conn, api_spend.row(_kwargs(cost=12.5, tags=("job:9",)), None, OPUS))
    finally:
        conn.close()
    assert cli.main(["api-spend"]) == 0
    out = capsys.readouterr().out
    assert "$12.50 of $200.00 (api_budget)" in out and "$187.50 left" in out and "job:9" in out
    assert cli.main(["api-spend", "--start", "2026-10-25"]) == 0
    capsys.readouterr()
    conn = ms.connect()
    try:
        assert api_spend.start(conn) is not None
        got = morning.api_spend(conn)
    finally:
        conn.close()
    assert morning_cmd.api_spend_line(got).startswith("api spend $0.00 of $200.00")
    assert morning_cmd.api_spend_line(None) == ""

"""#1338 routing trial: the arms in the served config, verdicts reaching the gateway, and the paired report."""
import asyncio
import json

import pytest

from evals.core import Case, Result
from evals.runners.text import CompletionRunner
from harness import cli, completion, delegations, gateway, power, routes
from harness import memory_store as ms

MODEL = "Qwen2.5-7B-Instruct-Q4_K_M"
BASE = f"""model_list:
  - model_name: {MODEL}
    litellm_params: {{model: openai/{MODEL}, api_base: "http://127.0.0.1:18082/v1", api_key: x}}
  - model_name: sohot-code
    litellm_params: {{model: openai/{MODEL}, api_base: "http://127.0.0.1:18082/v1", api_key: x}}
  - model_name: cloud-opus
    litellm_params: {{model: anthropic/claude-opus-5-5, api_key: os.environ/ANTHROPIC_API_KEY,
                      input_cost_per_token: 4.0e-06}}
"""


@pytest.fixture(autouse=True)
def _empty_queue():
    routes.headers()
    yield
    routes.headers()


def _served(tmp_path, text=BASE):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(text, encoding="utf-8")
    return {e["model_name"]: e for e in gateway.served(cfg, defaults={}, nodes=[])["model_list"]}


def test_the_served_config_gives_a_lane_with_an_alias_both_arms_over_it_and_the_cloud(tmp_path):
    got = _served(tmp_path)
    for arm in routes.ARMS:
        e = got[f"sohot-code-{arm}"]
        cfg = e["litellm_params"]["complexity_router_config"]
        assert e["litellm_params"]["model"] == "auto_router/complexity_router"
        assert cfg["tiers"] == {"SIMPLE": "sohot-code", "MEDIUM": "sohot-code",
                                "COMPLEX": "cloud-opus", "REASONING": "cloud-opus"}
        assert cfg["classifier_type"] == "heuristic"
        assert "max_parallel_requests" not in e["litellm_params"]
    adaptive = got["sohot-code-adaptive"]["litellm_params"]["complexity_router_config"]
    assert adaptive["adaptive"] is True and adaptive["adaptive_eligible"] == "all"
    assert adaptive["tier_distance_penalty"] == routes.TIER_PENALTY
    assert adaptive["adaptive_weights"] == {"quality": routes.QUALITY_WEIGHT, "cost": round(1 - routes.QUALITY_WEIGHT, 6)}
    assert "adaptive" not in got["sohot-code-auto"]["litellm_params"]["complexity_router_config"]
    assert not any(n.startswith("sohot-web-") for n in got)


def test_no_arm_is_served_without_the_cloud_alias(tmp_path):
    got = _served(tmp_path, BASE.split("  - model_name: cloud-opus")[0])
    assert not [n for n in got if n.endswith(("-auto", "-adaptive"))]


@pytest.mark.parametrize("passed,cls,want", [
    (True, "", routes.PASS), (False, "content_failed", routes.FAIL),
    (False, "token_budget_exhausted", routes.FAIL), (False, "timeout", ""),
    (False, "refused_by_gateway", ""), (False, "context_exceeded", "")])
def test_only_a_reply_judged_on_its_answer_is_a_verdict(passed, cls, want):
    assert routes.verdict(passed, cls) == want


def test_queued_verdicts_ride_once_on_the_next_request_and_junk_is_dropped():
    routes.report("a-1", routes.PASS)
    routes.report("b-2", routes.FAIL)
    routes.report("c-3", "")
    sent = routes.headers()
    assert routes.parse(sent[routes.HEADER]) == [("a-1", routes.PASS), ("b-2", routes.FAIL)]
    assert routes.headers() == {}
    assert routes.parse("x=pass, =fail,y=maybe,z") == [("x", routes.PASS)]


def test_a_request_carries_the_queued_verdicts_to_the_gateway(monkeypatch):
    seen = []

    class R:
        status_code, text, headers = 200, "", {}

    monkeypatch.setattr(completion.httpx, "post", lambda url, json, timeout, headers: seen.append(headers) or R())
    routes.report("call-9", routes.FAIL)
    completion._send("http://127.0.0.1:4000", {"model": "sohot-code-adaptive"}, 5)
    completion._send("http://127.0.0.1:4000", {"model": "sohot-code-adaptive"}, 5)
    assert seen[0][routes.HEADER] == "call-9=fail"
    assert routes.HEADER not in seen[1]


def test_the_feed_forgets_its_oldest_call_past_its_cap():
    feed = routes.Feed(cap=2)
    for i in range(3):
        feed.remember(f"c{i}", "sohot-code-adaptive", "general", "sohot-code")
    assert feed.waiting() == ["c1", "c2"]
    assert feed.take("c2") == ("sohot-code-adaptive", "general", "sohot-code") and feed.take("c2") is None
    from harness import cuts
    conn = ms.connect()
    cuts.flush(conn)
    got = conn.execute(f"SELECT value, kept, dropped FROM {cuts.TABLE} WHERE knob = 'route_remembered_calls'").fetchall()
    assert [tuple(r) for r in got] == [(2.0, 2, 1)]


def test_closed_delegation_outcomes_become_verdicts_and_open_ones_do_not():
    conn = ms.connect()
    for cid, outcome in (("u", "used"), ("e", "edited"), ("d", "discarded"), ("k", None), ("x", "unknown")):
        delegations.record(conn, cid, "code")
        if outcome:
            conn.execute("UPDATE delegations SET outcome = ? WHERE call_id = ?", (outcome, cid))
    conn.commit()
    assert sorted(routes.closed(conn, ["u", "e", "d", "k", "x", "nope"])) == [
        ("d", routes.FAIL), ("e", routes.PASS), ("u", routes.PASS)]


def _runner(monkeypatch, routed, call_id="cid-1", usage=None):
    r = CompletionRunner("http://127.0.0.1:4000", "sohot-code-adaptive")
    r.last_routed, r.last_call_id, r.last_usage = routed, call_id, usage or {}
    monkeypatch.setattr("harness.models.hosted", lambda name: name == "cloud-opus")
    return r


def _case():
    return Case(id="c1", modality="code", prompt="p", assertions={})


def test_a_routed_row_records_the_cloud_share_and_reports_its_verdict(monkeypatch):
    r = _runner(monkeypatch, "cloud-opus", usage={"prompt_tokens": 30, "completion_tokens": 12})
    row = Result("c1", "sohot-code-adaptive", False, 1.0, 0, "wrong", failure_class="content_failed")
    r.graded(_case(), row)
    assert row.metrics["routed_cloud"] == 1 and row.metrics["cloud_tokens"] == 42
    assert routes.parse(routes.headers()[routes.HEADER]) == [("cid-1", routes.FAIL)]
    local = Result("c1", "sohot-code-adaptive", True, 1.0, 0, "")
    _runner(monkeypatch, "sohot-code", "cid-2", {"prompt_tokens": 9}).graded(_case(), local)
    assert local.metrics == {"routed_cloud": 0, "cloud_tokens": 0}
    assert routes.parse(routes.headers()[routes.HEADER]) == [("cid-2", routes.PASS)]


def test_an_unrouted_row_reports_nothing(monkeypatch):
    row = Result("c1", "sohot-code", True, 1.0, 0, "")
    _runner(monkeypatch, "").graded(_case(), row)
    assert row.metrics == {} and routes.headers() == {}


def test_a_reply_cut_at_the_budget_still_tells_the_arm_it_failed(monkeypatch):
    class Cut(CompletionRunner):
        def _generate(self, case):
            self.last_routed, self.last_call_id, self.last_usage = "sohot-code", "cid-cut", {}
            from evals.runners.base import RunnerError
            raise RunnerError("no answer", failure_class="token_budget_exhausted")

    monkeypatch.setattr("harness.models.hosted", lambda name: False)
    row = Cut("http://127.0.0.1:4000", "sohot-code-adaptive").run(_case())
    assert row.failure_class == "token_budget_exhausted"
    assert routes.parse(routes.headers()[routes.HEADER]) == [("cid-cut", routes.FAIL)]


def test_a_reply_that_came_back_unusable_keeps_its_call_id_and_tier(monkeypatch):
    class R:
        status_code = 200
        headers = {completion.CALL_ID_HEADER: "cid-7", routes.ROUTED_HEADER: "cloud-opus"}

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}], "usage": {}}

    monkeypatch.setattr(completion, "_post", lambda *a, **k: R())
    with pytest.raises(completion.CompletionError) as got:
        completion.complete_full("p", model="sohot-code-adaptive", gateway="http://127.0.0.1:4000")
    assert (got.value.call_id, got.value.routed) == ("cid-7", "cloud-opus")


def _store_run(conn, split="holdout"):
    rid = conn.execute("INSERT INTO runs (path, lane, tier, split, recorded_at) VALUES (?,?,?,?,?)",
                       ("r-1338", "code", "measure", split, 1.0)).lastrowid
    seq = 0

    def put(cand, verdicts, cloud=None):
        nonlocal seq
        for i, ok in enumerate(verdicts):
            seq += 1
            m = {} if cloud is None else {"routed_cloud": int(cloud[i] > 0), "cloud_tokens": cloud[i]}
            conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, repeat_index, passed, "
                         "failure_class, seconds, metrics) VALUES (?,?,?,?,?,?,?,?,?)",
                         (rid, seq, cand, f"c{i}", 1, int(ok is True),
                          "" if ok is True else ("timeout" if ok is None else "content_failed"), 2.0, json.dumps(m)))
    return rid, put


def test_the_report_pairs_each_arm_and_applies_the_adoption_rule():
    conn = ms.connect()
    rid, put = _store_run(conn)
    n = 20
    put("sohot-code", [i < 4 for i in range(n)])
    put("sohot-code-auto", [i < 5 for i in range(n)], [0] * n)
    put("sohot-code-adaptive", [i < 16 for i in range(n)], [100 if 4 <= i < 16 else 0 for i in range(n)])
    put("cloud-opus", [i < 16 for i in range(n)], [500] * n)
    conn.commit()
    got = routes.trial(conn, rid, "code")
    arms = {a["candidate"]: a for a in got["arms"]}
    assert [a["candidate"] for a in got["arms"]] == ["sohot-code", "sohot-code-auto", "sohot-code-adaptive", "cloud-opus"]
    assert arms["sohot-code-adaptive"] == {"candidate": "sohot-code-adaptive", "rows": n, "judged": n, "passed": 16,
                                           "rate": 0.8, "cut": 0, "cloud_calls": 12, "cloud_tokens": 1200,
                                           "wall_s": 40.0}
    v = {x["base"]: x for x in got["verdicts"]}
    assert (v["sohot-code"]["gained"], v["sohot-code"]["lost"]) == (12, 0)
    assert not v["sohot-code"]["adopt"], "more passes bought with cloud tokens the lane alias never spent"
    assert v["cloud-opus"]["adopt"] and "fewer cloud tokens" in v["cloud-opus"]["why"]
    assert v["cloud-opus"]["effect"] == power.effect_for("code")


def test_a_pass_gain_at_no_extra_cloud_adopts_and_a_loss_past_the_effect_does_not():
    conn = ms.connect()
    rid, put = _store_run(conn, split="dev")
    n = 30
    put("sohot-code", [i < 5 for i in range(n)])
    put("sohot-code-adaptive", [i < 20 for i in range(n)], [0] * n)
    put("cloud-opus", [i < 29 for i in range(n)], [10] * n)
    conn.commit()
    got = routes.trial(conn, rid, "code")
    v = {x["base"]: x for x in got["verdicts"]}
    assert v["sohot-code"]["adopt"] and "passes more" in v["sohot-code"]["why"]
    assert not v["cloud-opus"]["adopt"], "9 of 30 lost is far past the lane's adopt effect"
    assert got["split"] == "dev"


def test_an_unjudged_row_is_left_out_of_the_pairing():
    conn = ms.connect()
    rid, put = _store_run(conn)
    put("sohot-code", [True, None, False])
    put("sohot-code-adaptive", [True, True, True], [0, 0, 0])
    conn.commit()
    v = routes.trial(conn, rid, "code")["verdicts"][0]
    assert (v["paired"], v["gained"], v["lost"]) == (2, 1, 0)


def test_the_command_runs_the_lane_alias_and_both_arms_on_the_holdout(capsys):
    assert cli.main(["route-trial", "command", "--lane", "code", "--with", "cloud-opus"]) == 0
    out = capsys.readouterr()
    assert ("-m evals.run --modality code --candidates "
            "sohot-code,sohot-code-auto,sohot-code-adaptive,cloud-opus --split holdout") in out.out + out.err


def test_the_report_command_names_the_verdict(capsys):
    conn = ms.connect()
    rid, put = _store_run(conn)
    put("sohot-code", [False] * 4)
    put("sohot-code-adaptive", [True] * 4, [0] * 4)
    conn.commit()
    conn.close()
    assert cli.main(["route-trial", "report", "--lane", "code"]) == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert f"run {rid}  lane code  split holdout" in text
    assert "sohot-code-adaptive vs sohot-code: keep sohot-code (4 gained, 0 lost of 4, p=0.125" in text


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/routes.py:latest_run")
def test_the_report_reads_the_newest_trial_run_unless_asked_for_another(capsys):
    conn = ms.connect()
    old, put = _store_run(conn)
    put("sohot-code", [False])
    put("sohot-code-adaptive", [True], [0])
    conn.execute("UPDATE runs SET path = 'r-old' WHERE id = ?", (old,))
    new, put = _store_run(conn)
    put("sohot-code-adaptive", [True], [0])
    other = conn.execute("INSERT INTO runs (path, lane, tier, recorded_at) VALUES ('r-web', 'web', 'measure', 2.0)").lastrowid
    conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, repeat_index, passed) "
                 "VALUES (?, 1, 'sohot-web-adaptive', 'w', 1, 1)", (other,))
    conn.commit()
    assert routes.latest_run(conn, "code") == new
    assert routes.latest_run(conn, "extract") is None
    conn.close()
    assert cli.main(["route-trial", "report", "--lane", "code", "--run", str(old)]) == 0
    out = capsys.readouterr()
    assert f"run {old} " in out.out + out.err


def _feedback_module():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "route_feedback_1338", Path(__file__).resolve().parents[1] / "gateway" / "route_feedback.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_gateway_applies_header_verdicts_and_closed_delegations(monkeypatch):
    rf = _feedback_module()
    took = []
    monkeypatch.setattr(rf, "apply", lambda call_id, got: took.append((call_id, got)) or True)
    data = {"proxy_server_request": {"headers": {routes.HEADER: "a=pass,b=fail"}}}
    assert rf.sent(data) == [("a", routes.PASS), ("b", routes.FAIL)]
    asyncio.run(rf.RouteFeedback().async_pre_call_hook(None, None, data, "acompletion"))
    assert took == [("a", routes.PASS), ("b", routes.FAIL)]
    conn = ms.connect()
    delegations.record(conn, "d-1", "code")
    conn.execute("UPDATE delegations SET outcome = 'discarded' WHERE call_id = 'd-1'")
    conn.commit()
    conn.close()
    monkeypatch.setattr(rf, "FEED", routes.Feed())
    rf.FEED.remember("d-1", "sohot-code-adaptive", "general", "sohot-code")
    monkeypatch.setitem(rf._POLLED, "at", 0.0)
    took.clear()
    assert asyncio.run(rf.poll(now=routes.DELEGATION_POLL_S + 1)) == 1
    assert took == [("d-1", routes.FAIL)]
    assert asyncio.run(rf.poll(now=routes.DELEGATION_POLL_S + 2)) == 0, "polled again inside the interval"

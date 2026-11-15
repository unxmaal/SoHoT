"""soh ledger --by: counted cloud tokens by kind, agent type and cache write cause, from fixture transcripts. #2031, #2036."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from harness import cli, ledger, morning, token_flow
from harness import memory_store as ms
from harness.commands import morning as morning_cmd
from tests.test_morning_867 import _beat, _gh, _git

PLANTED = 7777
SINCE_DAY = "2026-10-08"
#: Noon UTC, so the window's first local day is SINCE_DAY in every zone a suite runs in.
SINCE_ARG = "2026-10-08T12:00Z"


def local(day: str, hour: int = 12) -> float:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00").timestamp()


T0 = local(SINCE_DAY)
SINCE = ledger.day_start(SINCE_DAY)


def rec(at: float, rid: str, *, cw=0, cr=0, inp=1, out=10, ttl="5m", tool=None, agent=None, stop="end_turn", n=0) -> dict:
    """One assistant record as Claude Code writes it: usage, the cache lifetime it wrote with, an optional tool call."""
    content = [{"type": "text", "text": "ok"}]
    if tool:
        content.append({"type": "tool_use", "id": f"toolu_{rid}", "name": tool[0], "input": tool[1]})
    other = "1h" if ttl == "5m" else "5m"
    out_rec = {"type": "assistant", "uuid": f"u-{rid}-{n}", "sessionId": "s1", "requestId": rid,
               "timestamp": datetime.fromtimestamp(at, timezone.utc).isoformat().replace("+00:00", "Z"),
               "message": {"id": f"msg_{rid}", "model": "claude-test", "stop_reason": stop, "content": content,
                           "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr,
                                     "cache_creation_input_tokens": cw,
                                     "cache_creation": {f"ephemeral_{ttl}_input_tokens": cw,
                                                        f"ephemeral_{other}_input_tokens": 0}}}}
    if agent:
        out_rec["attributionAgent"] = agent
    return out_rec


def write(root, rel: str, recs: list[dict]):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return p


def idle_stream(name: str, ttl: str, idle: float = 360.0, agent=None, tool=None) -> list[dict]:
    """A cold start, one turn of growth, then `idle` seconds and the whole context written again."""
    return [rec(T0, f"{name}1", cw=5000, ttl=ttl, agent=agent),
            rec(T0 + 20, f"{name}2", cw=300, cr=5000, ttl=ttl, agent=agent, tool=tool),
            rec(T0 + 20 + idle, f"{name}3", cw=PLANTED, cr=0, ttl=ttl, agent=agent),
            rec(T0 + 30 + idle, f"{name}4", cw=40, cr=PLANTED, ttl=ttl, agent=agent)]


def flow(root, since: float = SINCE, until=None, top: int = 10) -> dict:
    files = sorted(root.rglob("*.jsonl"))
    return token_flow.account(token_flow.read(files, since, until), top)


def cause_row(A: dict, kind: str, cause: str) -> dict:
    return next((c for c in A["causes"] if (c["kind"], c["cause"]) == (kind, cause)), {"cache_write": 0, "events": 0})


def test_a_six_minute_idle_on_a_five_minute_stream_is_exactly_one_expiry_rewrite_of_the_planted_size(tmp_path):
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", idle_stream("a", "5m", agent="sohot-fix"))
    A = flow(tmp_path)
    assert (A["expiry"]["cache_write"], A["expiry"]["events"]) == (PLANTED, 1)
    assert cause_row(A, "subagent", token_flow.EXPIRED) == {
        "kind": "subagent", "cause": token_flow.EXPIRED, "cache_write": PLANTED, "events": 1,
        "share": PLANTED / A["counted"]}
    assert A["expiry"]["share"] == PLANTED / A["counted"]
    assert A["expiry"]["median_tokens"] == PLANTED and A["expiry"]["median_idle_s"] == 360.0
    assert A["expiry"]["by_ttl"] == {"5m": PLANTED}
    assert cause_row(A, "subagent", token_flow.COLD)["cache_write"] == 5000
    assert cause_row(A, "subagent", token_flow.GROWTH) == {
        "kind": "subagent", "cause": token_flow.GROWTH, "cache_write": 340, "events": 2, "share": 340 / A["counted"]}
    assert A["top"][0]["expiry_rewrites"] == 1


def test_the_same_idle_on_a_one_hour_stream_is_no_expiry_rewrite(tmp_path):
    write(tmp_path, "proj/s1.jsonl", idle_stream("m", "1h"))
    A = flow(tmp_path)
    assert (A["expiry"]["cache_write"], A["expiry"]["events"], A["expiry"]["tools"]) == (0, 0, [])
    assert A["expiry"]["median_tokens"] is None
    assert cause_row(A, "main", token_flow.REWRITE)["cache_write"] == PLANTED
    assert A["top"][0]["expiry_rewrites"] == 0


def test_a_one_hour_stream_idle_past_the_hour_is_an_expiry_rewrite(tmp_path):
    write(tmp_path, "proj/s1.jsonl", idle_stream("m", "1h", idle=3601.0))
    A = flow(tmp_path)
    assert (A["expiry"]["cache_write"], A["expiry"]["events"]) == (PLANTED, 1)
    assert A["expiry"]["by_ttl"] == {"1h": PLANTED}


@pytest.mark.parametrize("idle,events", [(300.0, 0), (300.5, 1)])
def test_an_idle_of_exactly_the_lifetime_has_not_expired(tmp_path, idle, events):
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", idle_stream("a", "5m", idle=idle))
    assert flow(tmp_path)["expiry"]["events"] == events


def test_a_request_that_reads_as_much_as_it_writes_is_growth_however_long_the_idle(tmp_path):
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", [
        rec(T0, "a1", cw=5000), rec(T0 + 900, "a2", cw=600, cr=600)])
    A = flow(tmp_path)
    assert A["expiry"]["events"] == 0 and cause_row(A, "subagent", token_flow.GROWTH)["cache_write"] == 600


def test_a_planted_subagent_lands_in_the_subagent_row_under_its_agent_type(tmp_path):
    write(tmp_path, "proj/s1.jsonl", [rec(T0, "m1", cw=1000, inp=5, out=50, ttl="1h")])
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", [
        rec(T0 + 5, "a1", cw=2000, inp=7, out=70, agent="sohot-fix"),
        rec(T0 + 9, "a2", cw=100, cr=2000, inp=3, out=30, agent="sohot-fix")])
    write(tmp_path, "proj/s1/subagents/agent-b1.jsonl", [rec(T0 + 6, "b1", cw=400, inp=1, out=9)])
    A = flow(tmp_path)
    kinds = {k["kind"]: k for k in A["kinds"]}
    assert (kinds["main"]["counted"], kinds["main"]["streams"], kinds["main"]["requests"]) == (1055, 1, 1)
    assert (kinds["subagent"]["counted"], kinds["subagent"]["streams"], kinds["subagent"]["requests"]) == (2620, 2, 3)
    assert kinds["subagent"]["share"] == 2620 / 3675
    assert [(g["agent"], g["counted"], g["streams"]) for g in A["agents"]] == [
        ("sohot-fix", 2210, 1), (token_flow.UNNAMED, 410, 1)]
    assert [(s["stream"], s["kind"], s["agent"], s["counted"]) for s in A["top"]] == [
        ("agent-a1", "subagent", "sohot-fix", 2210), ("s1", "main", "", 1055), ("agent-b1", "subagent", "", 410)]
    assert [s["stream"] for s in flow(tmp_path, top=1)["top"]] == ["agent-a1"]


def test_a_root_that_sits_under_a_directory_named_subagents_does_not_make_every_stream_a_subagent(tmp_path, monkeypatch):
    root = tmp_path / "subagents" / "projects"
    write(root, "proj/s1.jsonl", [rec(T0, "m1", cw=1000, ttl="1h")])
    write(root, "proj/s1/subagents/agent-a1.jsonl", [rec(T0 + 5, "a1", cw=2000, agent="sohot-fix")])
    A = token_flow.gather(SINCE, root=root)
    assert [(k["kind"], k["cache_write"]) for k in A["kinds"]] == [("main", 1000), ("subagent", 2000)]
    assert (A["available"], A["files"], A["source"], A["lower_bound"]) == (True, 2, "transcripts", True)


def test_records_of_one_request_count_once_in_a_file_and_across_sibling_files(tmp_path):
    shared = [rec(T0, "x1", cw=3000, out=20, stop=None, n=0), rec(T0 + 1, "x1", cw=3000, out=90, n=1)]
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", shared + [rec(T0 + 5, "a2", cw=10, cr=3000)])
    write(tmp_path, "proj/s1/subagents/agent-b1.jsonl", shared + [rec(T0 + 6, "b2", cw=20, cr=3000)])
    reqs = token_flow.read(sorted(tmp_path.rglob("*.jsonl")), SINCE)
    assert sorted((r["stream"], r["cache_write"], r["output"], r["cause"]) for r in reqs) == [
        ("agent-a1", 10, 10, token_flow.GROWTH), ("agent-a1", 3000, 90, token_flow.COLD),
        ("agent-b1", 20, 10, token_flow.GROWTH)]
    A = token_flow.account(reqs)
    assert (A["requests"], A["tokens"]["cache_write"], A["counted"]) == (3, 3030, 3030 + 110 + 3)


def test_totals_equal_the_plain_ledger_transcript_totals_for_the_same_window(tmp_path):
    write(tmp_path, "proj/s1.jsonl", [rec(T0 - 86400, "old1", cw=900, inp=4, out=40, ttl="1h"),
                                      *idle_stream("m", "1h"),
                                      rec(T0 + 86400, "late1", cw=11, cr=9000, inp=2, out=13, ttl="1h")])
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", idle_stream("a", "5m", agent="sohot-fix")
          + [rec(T0 + 500, "a5", cw=1, cr=1, out=17, stop=None, n=0), rec(T0 + 501, "a5", cw=1, cr=1, out=170, n=1)])
    write(tmp_path, "proj/s1/subagents/agent-b1.jsonl", idle_stream("a", "5m", agent="sohot-fix")[:2]
          + [rec(T0 + 40, "b3", cw=60, cr=5300, agent="sohot-fix")])
    files = sorted(tmp_path.rglob("*.jsonl"))
    for since, until in ((SINCE, None), (SINCE, SINCE + 86400), (0.0, None), (T0 + 21, T0 + 600)):
        plain, _ = ledger._by_model(ledger.usage_messages(files, since, until), ledger._msg_tokens)
        A = token_flow.account(token_flow.read(files, since, until))
        assert A["tokens"] == plain, (since, until)
        assert A["counted"] == ledger.local_vs_cloud([], plain)["cloud"]
        assert A["requests"] == len(ledger.usage_messages(files, since, until))
        assert sum(k["counted"] for k in A["kinds"]) == A["counted"] == sum(t["tokens"] for t in A["terms"])
        assert sum(c["cache_write"] for c in A["causes"]) == plain["cache_write"]
    assert flow(tmp_path)["counted"] > 0


def test_a_stream_that_began_before_the_window_is_not_a_cold_start_inside_it(tmp_path):
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", idle_stream("a", "5m"))
    A = flow(tmp_path, since=T0 + 21)
    assert cause_row(A, "subagent", token_flow.COLD)["events"] == 0
    assert (A["expiry"]["cache_write"], A["expiry"]["events"], A["requests"]) == (PLANTED, 1, 2)


@pytest.mark.parametrize("tool,label", [
    (None, token_flow.NO_TOOL),
    (("SubagentHandback", {"message": "done"}), "SubagentHandback"),
    (("Bash", {"command": "gh pr checks 12 --watch"}), "Bash: CI wait (gh)"),
    (("Bash", {"command": "sleep 400"}), "Bash: sleep or poll loop"),
    (("Bash", {"command": "uv run pytest tests -q"}), "Bash: test suite run"),
    (("Bash", {"command": "make lint"}), "Bash: lint, gauntlet or mutation"),
    (("Bash", {"command": "make image", "run_in_background": True}), "Bash: background"),
    (("Bash", {"command": "ls"}), "Bash: other")])
def test_an_expiry_rewrite_names_the_tool_call_of_the_request_before_it(tmp_path, tool, label):
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", idle_stream("a", "5m", tool=tool))
    assert flow(tmp_path)["expiry"]["tools"] == [{"tool": label, "cache_write": PLANTED, "events": 1, "share": 1.0}]


def test_the_terms_are_disjoint_and_ordered_largest_first(tmp_path):
    write(tmp_path, "proj/s1.jsonl", [rec(T0, "m1", cw=100, inp=5, out=9000, ttl="1h")])
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", idle_stream("a", "5m", agent="sohot-fix"))
    A = flow(tmp_path)
    assert [(t["term"], t["tokens"]) for t in A["terms"][:3]] == [
        ("main output", 9000), ("subagent cache write, rewrite after expiry", PLANTED),
        ("subagent cache write, cold start", 5000)]
    assert sum(t["tokens"] for t in A["terms"]) == A["counted"]


def test_ledger_by_prints_the_headline_and_the_json_account(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    write(tmp_path, "proj/s1.jsonl", [rec(T0, "m1", cw=1000, inp=5, out=50, ttl="1h")])
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", idle_stream("a", "5m", agent="sohot-fix"))
    assert cli.main(["ledger", "--by", "--since", SINCE_ARG]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(f"cloud by cause {SINCE_DAY} .. ")
    assert out[1].startswith("counted   14,216 = 9 in + 90 out + 14,117 cache write, over 5 requests in 2 streams")
    assert out[2].startswith("expiry    7,777 rewritten after a cache expiry, 55% of counted cloud, in 1 rewrites; "
                             "median 7,777 after 6.0 min idle")
    text = "\n".join(out)
    assert "sohot-fix" in text and "subagent, rewrite after expiry" in text and token_flow.NO_TOOL in text
    assert str(tmp_path) not in text
    assert cli.main(["ledger", "--by", "--since", SINCE_ARG, "--top", "1", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert (doc["ok"], doc["counted"], doc["expiry"]["cache_write"], len(doc["top"])) == (True, 14216, PLANTED, 1)
    assert doc["window"]["first_day"] == SINCE_DAY and str(tmp_path) not in json.dumps(doc)


def test_ledger_by_with_no_transcripts_says_so_and_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path / "absent"))
    assert cli.main(["ledger", "--by", "--since", SINCE_ARG]) == 1
    assert "counted   unavailable: no Claude Code transcripts on this machine" in capsys.readouterr().out


def test_the_morning_account_spans_the_ratio_week_ending_yesterday(tmp_path):
    now = local("2026-10-15", 6)
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", [
        rec(local("2026-10-07", 23), "w0", cw=111_111, agent="sohot-fix"),  # the day before: history, not counted
        *idle_stream("a", "5m", agent="sohot-fix"),
        rec(local("2026-10-14", 23), "w8", cw=600, cr=9000, out=4000, agent="sohot-fix"),
        rec(local("2026-10-15", 1), "w9", cw=222_222, cr=9000, agent="sohot-fix")])
    m = token_flow.morning(now, root=tmp_path)
    assert (m["first_day"], m["last_day"], m["days"]) == ("2026-10-08", "2026-10-14", ledger.RATIO_DAYS)
    assert m["counted"] == 5000 + 300 + PLANTED + 40 + 600 + 4 * 10 + 4000 + 5
    assert [(t["term"], t["tokens"]) for t in m["terms"]] == [
        ("subagent cache write, rewrite after expiry", PLANTED + 5000), ("subagent output", 4040),
        ("subagent cache write, growth", 940)]
    assert m["expiry"] == {"cache_write": PLANTED + 5000, "events": 2, "share": (PLANTED + 5000) / m["counted"]}
    assert token_flow.terms_line(m) == (
        "cloud     7d 17,762 counted in transcripts; largest: subagent cache write, rewrite after expiry 12,777 (72%); "
        "subagent output 4,040 (23%); subagent cache write, growth 940 (5%); expiry rewrites 72%")


def test_morning_leads_with_the_ratio_then_the_three_largest_cloud_terms(tmp_path):
    now = local("2026-10-15", 6)
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", idle_stream("a", "5m", agent="sohot-fix"))
    d = tmp_path / "deploy"
    (d / ".git").mkdir(parents=True)
    conn = ms.connect()
    try:
        r = morning.gather(conn, now, now - 18 * 3600, beat=_beat(), gh=_gh(), git=_git(0), where=d,
                           lanes=lambda c: [], flow=lambda at: token_flow.morning(at, root=tmp_path))
        bare = morning.gather(conn, now, now - 18 * 3600, beat=_beat(), gh=_gh(), git=_git(0), where=d,
                              lanes=lambda c: [])
    finally:
        conn.close()
    lines = morning_cmd.render(r)
    assert lines[0].startswith("local:cloud ")
    assert lines[1] == ("cloud     7d 13,161 counted in transcripts; largest: subagent cache write, rewrite after expiry "
                        "7,777 (59%); subagent cache write, cold start 5,000 (38%); subagent cache write, growth 340 (3%); "
                        "expiry rewrites 59%")
    assert lines[2].startswith("since ")
    assert bare["flow"] is None and morning_cmd.render(bare)[1].startswith("since ")


def test_morning_on_a_machine_with_no_transcripts_says_the_terms_are_unread(tmp_path):
    m = token_flow.morning(local("2026-10-15", 6), root=tmp_path / "absent")
    assert token_flow.terms_line(m) == "cloud     terms n/a: no Claude Code transcripts on this machine"
    assert token_flow.terms_line(None) == ""


def _refuse_the_store(monkeypatch) -> list[str]:
    """Any store open under the account is recorded and refused."""
    from harness import store
    opened: list[str] = []

    def refuse(name):
        def boom(*a, **kw):
            opened.append(name)
            raise AssertionError(f"the account opened the store: {name}")
        return boom
    monkeypatch.setattr(ms, "connect", refuse("connect"))
    monkeypatch.setattr(store, "choose_read", refuse("choose_read"))
    monkeypatch.setattr(store, "open_ro", refuse("open_ro"))
    return opened


def _tree(root) -> dict:
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy",
                      site="harness/commands/ledger.py:gather_by:gather")
def test_ledger_by_from_any_home_opens_no_store_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path / "projects"))
    write(tmp_path, "projects/proj/s1/subagents/agent-a1.jsonl", idle_stream("a", "5m", agent="sohot-fix"))
    opened, before = _refuse_the_store(monkeypatch), _tree(tmp_path)
    assert cli.main(["ledger", "--by", "--since", SINCE_ARG]) == 0
    assert "expiry    7,777 rewritten" in capsys.readouterr().out
    assert opened == [] and _tree(tmp_path) == before


@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy",
                      site="harness/token_flow.py:morning:gather")
def test_the_morning_account_opens_no_store_and_writes_nothing(tmp_path, monkeypatch):
    write(tmp_path, "projects/proj/s1/subagents/agent-a1.jsonl", idle_stream("a", "5m", agent="sohot-fix"))
    opened, before = _refuse_the_store(monkeypatch), _tree(tmp_path)
    m = token_flow.morning(local("2026-10-15", 6), root=tmp_path / "projects")
    assert m["expiry"]["cache_write"] == PLANTED
    assert opened == [] and _tree(tmp_path) == before


def test_the_morning_command_reads_the_account():
    import inspect
    assert "flow=token_flow.morning" in inspect.getsource(morning_cmd.cmd_morning)

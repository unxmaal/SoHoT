"""#1381: do KB mistakes cluster after a compaction? Planted and uniform fixtures, the join, the exact tails."""
import itertools
import json
import random
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from harness import cli
from harness import context_mistakes as cm
from harness import context_report as cr

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
CANARY = "CANARY-7f3e-transcript-text"
KB_CANARY = "CANARY-kb-what-failed"
SESSIONS, MESSAGES, COMPACT_AT = 20, 200, (60, 140)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def at(s, i):
    return T0 + timedelta(days=s, seconds=60 * i)


def assistant(mid, when, tokens, uses=()):
    content = [{"type": "text", "text": CANARY}] + [
        {"type": "tool_use", "id": uid, "name": f"mcp__mcm-engine__{tool}", "input": {"what_failed": CANARY}}
        for uid, tool in uses]
    return {"type": "assistant", "timestamp": iso(when), "message": {
        "id": mid, "role": "assistant", "content": content,
        "usage": {"input_tokens": tokens, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                  "output_tokens": 1}}}


def result(uid, when):
    return {"type": "user", "timestamp": iso(when), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "content": f"Stored negative knowledge: {CANARY}"}]}}


def compact(when):
    return [{"type": "system", "subtype": "compact_boundary", "timestamp": iso(when)},
            {"type": "user", "isCompactSummary": True, "timestamp": iso(when),
             "message": {"role": "user", "content": CANARY}}]


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def stream(s, marks, tool="add_negative", extra=None, compact_at=COMPACT_AT, n=MESSAGES):
    """One session's records: n messages, compactions before compact_at, a KB call at each message in marks."""
    lines, rows, ctx = [], [], 20_000
    for i in range(n):
        if i in compact_at:
            lines += compact(at(s, i) - timedelta(seconds=30))
            ctx = 20_000
        if extra and i in extra:
            lines.append(extra[i])
        uses = [(f"u{s}-{i}", tool)] if i in marks else []
        lines.append(assistant(f"m{s}-{i}", at(s, i), ctx, uses))
        if uses:
            lines.append(result(f"u{s}-{i}", at(s, i) + timedelta(seconds=3)))
            rows.append((cm.MISTAKE_TOOLS.get(tool), at(s, i) + timedelta(seconds=2)))
        ctx += 4_000
    return lines, rows


def kb_pages(rows):
    """scroll_entries page text for (kind, time) rows, ids in order, with KB text that must never be printed."""
    out = []
    for n, (kind, when) in enumerate(rows, 1):
        out.append(f"#{n} [{kind}] {KB_CANARY}\n  hash=abc | updated={when.isoformat(sep=' ')}\n  what_failed: {KB_CANARY}")
    return "\n\n".join(out) + "\n\n--- page: n entries (cap 100). next: scroll_entries('negative', after_id=9)\n"


def build(tmp_path, marks_of):
    rows = []
    for s in range(SESSIONS):
        lines, got = stream(s, marks_of(s))
        write(tmp_path / "proj" / f"s{s:02d}.jsonl", lines)
        rows += got
    kb = tmp_path / "kb.txt"
    kb.write_text(kb_pages(rows), encoding="utf-8")
    return kb


def window(got, w=10, cls="mistakes"):
    return next(r for r in got["windows"] if r["window"] == w and r["class"] == cls)


def planted(s):
    return {COMPACT_AT[s % 2] + (s % 7)} if s < 12 else {5 + 11 * s % 50}


def uniform(seed):
    rng = random.Random(seed)
    return lambda s: set(rng.sample(range(MESSAGES), 1))


def test_planted_clustered_mistakes_are_detected(tmp_path):
    kb = build(tmp_path, planted)
    got = cm.measure(tmp_path, cm.load_rows(str(kb)))
    w = window(got)
    assert (got["messages"], got["joined"], got["compactions"]) == (SESSIONS * MESSAGES, SESSIONS, 2 * SESSIONS)
    assert w["message_share"] == 0.1 and w["events"] == 12
    assert w["p_binomial"] < 0.01 and w["p_session"] < 0.01
    assert got["left_out"] == {}


def test_uniformly_placed_mistakes_report_no_clustering(tmp_path):
    kb = build(tmp_path, uniform(3))
    w = window(cm.measure(tmp_path, cm.load_rows(str(kb))))
    assert w["events_total"] == SESSIONS and w["p_binomial"] > 0.05 and w["p_session"] > 0.05


def test_uniform_placements_are_calibrated():
    msgs = [{"session": s, "pos": (i - 59 if 60 <= i < 140 else i - 139 if i >= 140 else None), "ctx": 0}
            for s in range(SESSIONS) for i in range(MESSAGES)]
    rng, small, draws = random.Random(11), Counter(), 1000
    for _ in range(draws):
        r = cm._test(msgs, rng.sample(msgs, 30), lambda m: m["pos"] is not None and m["pos"] <= 10)
        small["binomial"] += r["p_binomial"] < 0.05
        small["session"] += r["p_session"] < 0.05
    assert max(small.values()) / draws <= 0.05


def test_a_session_title_summary_is_not_a_compaction(tmp_path):
    title = {"type": "summary", "summary": CANARY, "leafUuid": "x"}
    lines, rows = stream(0, {65}, extra={64: title}, compact_at=())
    write(tmp_path / "proj" / "s.jsonl", lines)
    kb = tmp_path / "kb.txt"
    kb.write_text(kb_pages(rows), encoding="utf-8")
    got = cm.measure(tmp_path, cm.load_rows(str(kb)))
    assert got["compactions"] == 0 and got["positions"] == [] and window(got)["messages"] == 0


def test_a_kb_row_joins_its_call_by_kind_and_time(tmp_path):
    lines, rows = stream(0, {65})
    sub, sub_rows = stream(1, {3}, compact_at=(), n=5)
    write(tmp_path / "proj" / "s.jsonl", lines)
    write(tmp_path / "proj" / "s" / "subagents" / "a.jsonl", sub)
    far = T0 + timedelta(days=40)
    wrong_kind = ("error", rows[0][1])
    kb = tmp_path / "kb.txt"
    kb.write_text(kb_pages(rows + sub_rows + [("negative", far), wrong_kind]), encoding="utf-8")
    got = cm.measure(tmp_path, cm.load_rows(str(kb)))
    assert got["joined"] == 1 and got["positions"] == [(6, 20_000 + 4_000 * 5, "negative")]
    assert got["left_out"] == {"negative sub": 1, "negative no call": 1, "error no call": 1}
    calls = [{"tool": "add_negative", "at": 100.0, "kind": "main", "session": "s", "pos": 1, "ctx": 0}]
    assert cm.join([{"kind": "negative", "id": 1, "at": 100.0 + cm.MATCH_S}], calls)[0]
    assert not cm.join([{"kind": "negative", "id": 1, "at": 100.0 + cm.MATCH_S + 1}], calls)[0]


def test_the_poisson_binomial_tail_matches_enumeration():
    ps = [0.1, 0.5, 0.25, 0.9, 0.05]
    for k in range(len(ps) + 2):
        brute = sum(
            __import__("math").prod(p if x else 1 - p for p, x in zip(ps, xs))
            for xs in itertools.product((0, 1), repeat=len(ps)) if sum(xs) >= k)
        assert abs(cm.upper_tail(ps, k) - brute) < 1e-12
    assert abs(cm.upper_tail([0.1] * 15, 10) - sum(
        __import__("math").comb(15, i) * 0.1 ** i * 0.9 ** (15 - i) for i in range(10, 16))) < 1e-15


def test_headless_and_resumed_copies_are_counted_once(tmp_path):
    lines, rows = stream(0, {65})
    write(tmp_path / "proj" / "a.jsonl", lines)
    write(tmp_path / "proj" / "b.jsonl", lines)
    hl, hl_rows = stream(5, {2}, compact_at=(), n=4)
    write(tmp_path / "proj" / "h.jsonl", [{**r, "entrypoint": "sdk-cli"} for r in hl])
    kb = tmp_path / "kb.txt"
    kb.write_text(kb_pages(rows + hl_rows), encoding="utf-8")
    got = cm.measure(tmp_path, cm.load_rows(str(kb)))
    assert (got["messages"], got["joined"], got["compactions"]) == (MESSAGES, 1, 2)
    assert got["left_out"] == {"negative headless": 1}


def test_no_transcript_text_reaches_the_output(tmp_path, monkeypatch, capsys):
    kb = build(tmp_path, planted)
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    assert cli.main(["context", "--mistakes", "--kb", str(kb)]) == 0
    assert cli.main(["context", "--mistakes", "--kb", str(kb), "--json"]) == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert "after compaction" in text and "<= 10" in text
    assert CANARY not in text and KB_CANARY not in text and "CANARY" not in text
    got = json.loads(out.out.strip().splitlines()[-1])
    assert got["ok"] and got["joined"] == SESSIONS and got["windows"][0]["window"] == cm.WINDOWS[0]


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:SOH_MCM_URL")
def test_the_kb_source_falls_back_to_soh_mcm_url(tmp_path, monkeypatch, capsys):
    kb = build(tmp_path, planted)
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    monkeypatch.setenv("SOH_MCM_URL", str(kb))
    assert cli.main(["context", "--mistakes", "--json"]) == 0
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert got["source"] == "file" and got["joined"] == SESSIONS


def test_mistakes_needs_a_kb_source(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    monkeypatch.delenv("SOH_MCM_URL", raising=False)
    assert cli.main(["context", "--mistakes", "--json"]) == 2
    assert "--kb" in capsys.readouterr().out


def test_rows_are_paged_from_the_mcp_url_read_only():
    pages = {"negative": [kb_pages([("negative", T0)]), ""], "error": [kb_pages([("error", T0), ("error", T0)]), ""]}
    seen = []

    def post(url, body, session):
        seen.append((body.get("method"), (body.get("params") or {}).get("name"), session))
        if body.get("method") != "tools/call":
            return "sid", ""
        args = body["params"]["arguments"]
        text = pages[args["entity_type"]][1 if args["after_id"] else 0]
        return None, "event: message\ndata: " + json.dumps(
            {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": text}]}})

    rows = cm.fetch_rows("http://kb.invalid/mcp", post=post)
    assert sorted((r["kind"], r["id"]) for r in rows) == [("error", 1), ("error", 2), ("negative", 1)]
    assert {name for _, name, _ in seen if name} == {"scroll_entries"}
    assert all(sid == "sid" for method, _, sid in seen if method != "initialize")


def test_labelled_streams_keep_streams_unchanged(tmp_path):
    lines, _ = stream(0, {65})
    write(tmp_path / "proj" / "a.jsonl", lines)
    sub, _ = stream(1, {1}, compact_at=(), n=3)
    write(tmp_path / "proj" / "a" / "subagents" / "x.jsonl", sub)
    kinds = [k for _, k, _, _ in cr.labelled_streams(tmp_path, 0.0)]
    assert kinds == ["main", "sub"] and len(list(cr.streams(tmp_path, 0.0))) == 2
    assert len(list(cr.streams(tmp_path, 0.0, main_only=True))) == 1

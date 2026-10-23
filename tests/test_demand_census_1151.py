"""Demand census over synthetic Claude Code transcripts: units, counts, the draw, the estimator and redaction. #1151."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evals import redact
from evals.analysis import demand as d
from evals.analysis.demand import __main__ as cli

NOW = 1_790_000_000.0
T0 = NOW - 3 * 86400
HOME = "/" + "Users/alice/projects/github/acme"
SECRET = "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx"
KNOWN = redact.Known(accounts=("alice",), names=("Zebulon", "Quackenbush"))


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _user(t, content, **kw):
    return {"type": "user", "timestamp": _iso(t), "message": {"role": "user", "content": content}, **kw}


def _typed(t, text, pid, **kw):
    return _user(t, text, promptId=pid, origin={"kind": "human"}, userType="external", **kw)


def _asst(t, mid, tin, tout, *blocks, **kw):
    usage = {"input_tokens": tin, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
             "output_tokens": tout}
    return {"type": "assistant", "timestamp": _iso(t), "message": {"id": mid, "usage": usage,
                                                                   "content": list(blocks)}, **kw}


def _text(s):
    return {"type": "text", "text": s}


def _use(name, **args):
    return {"type": "tool_use", "id": f"tu-{name}-{len(args)}", "name": name, "input": args}


def _write(path: Path, recs, tail=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs) + tail, encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    """One live session with every record kind and a subagent, one headless session, one stale session."""
    root = tmp_path / "projects"
    main = root / "-Users-alice-projects" / "s1.jsonl"
    request = f"Fix the widget, key {SECRET}, notes in {HOME}/widget/notes.md, ask Zebulon Quackenbush"
    split = [_asst(T0 + 10, "m1", 1000, 40, _text("Looking")),
             _asst(T0 + 10, "m1", 1150, 60, _use("Edit", file_path=f"{HOME}/widget/pkg/a.py"))]
    _write(main, [
        _typed(NOW - 20 * 86400, "an old request", "p0"),
        _asst(NOW - 20 * 86400 + 5, "m0", 10, 10, _text("old")),
        _typed(T0, request, "p1", cwd=f"{HOME}/widget-123"),
        *split,
        _user(T0 + 20, [{"type": "tool_result", "tool_use_id": "tu-Edit-1", "content": "ok"}], promptId="p1",
              toolUseResult={"ok": True}),
        _user(T0 + 30, "caveat", isMeta=True),
        _user(T0 + 40, "a task finished", origin={"kind": "task-notification"}),
        _user(T0 + 50, "suggested", origin={"kind": "human"}, promptSource="suggestion_accepted"),
        {"type": "system", "timestamp": _iso(T0 + 60), "content": "x"},
        {"type": "attachment", "timestamp": _iso(T0 + 60), "attachment": {"type": "other"}},
        _asst(T0 + 2000, "m2", 500, 300, _use("Agent", description="dig", prompt="dig into the parser")),
        _user(T0 + 3000, "Now summarise the log for me", userType="external"),
        _asst(T0 + 3005, "m3", 200, 25, _text("Summary")),
        _user(T0 + 3010, "This session is being continued", isCompactSummary=True),
        _asst(T0 + 3020, "m5", 300, 999, _text("mirror"), isSidechain=True),
        _typed(T0 + 4000, "thanks", "p3"),
        _typed(NOW + 100, "after the window end", "p4"),
        _asst(NOW + 105, "m9", 10, 10, _text("late")),
    ], tail='{"type": "user", "timest')
    _write(main.parent / "s1" / "subagents" / "agent-aaa.jsonl", [
        _user(T0 + 2001, f"Dig into the parser under {HOME}/x for {SECRET}", promptId="p1"),
        _asst(T0 + 2010, "m5", 300, 700, _use("Write", file_path=f"{HOME}/widget/pkg/b.py"),
              _use("Write", file_path=f"{HOME}/widget/pkg/c.py", content="x"),
              _use("Bash", command=f"git -C {HOME}/widget status")),
        _asst(T0 + 2030, "m6", 400, 1500, _text("Done: parser fixed for Zebulon")),
    ])
    _write(main.parent / "s1" / "subagents" / "agent-bbb.jsonl", [
        {"type": "fork-context-ref", "timestamp": _iso(T0 + 2500)},
        _user(T0 + 2500, "forked: carry on", promptId="p1"),
        _asst(T0 + 2000, "m2", 500, 300, _text("copied from main")),
        _asst(T0 + 2030, "m6", 400, 1500, _text("copied from the first subagent")),
        _asst(T0 + 2510, "m7", 50, 70, _text("own work")),
    ])
    _write(root / "-private-tmp" / "h1.jsonl", [
        _typed(T0, "headless", "h", entrypoint="sdk-cli"), _asst(T0 + 1, "h1", 5, 5, _text("x"), entrypoint="sdk-cli")])
    stale = root / "-Users-alice-projects" / "s0.jsonl"
    _write(stale, [_typed(T0, "stale", "s"), _asst(T0 + 1, "s1", 5, 5, _text("x"))])
    os.utime(stale, (NOW - 30 * 86400, NOW - 30 * 86400))
    return root


def test_units_split_at_typed_requests_and_count_each_message_once(root):
    units, skipped = d.scan(root, NOW)
    assert skipped == {"before_window": 1, "headless_session": 1, "no_model_turn": 1, "stale_file": 1}
    r1, sub, fork, r2 = units
    assert (r1.kind, sub.kind, fork.kind, r2.kind) == ("main", "subagent", "subagent", "main")
    assert (fork.tokens_in, fork.tokens_out) == (50, 70)
    assert (r1.tokens_in, r1.tokens_out) == (1650, 360)
    assert (sub.tokens_in, sub.tokens_out) == (700, 2200)
    assert (r2.tokens_in, r2.tokens_out) == (200, 25)
    assert r1.active_s == 660 and sub.active_s == 29 and r2.active_s == 10
    assert dict(r1.tools) == {"Edit": 1, "Agent": 1} and len(r1.edited) == 1
    assert len(sub.edited) == 2 and sub.tools["Bash"] == 1
    assert [u.candidate for u in units] == ["orchestration", "multi_file", "chat", "chat"]
    assert [u.size for u in units] == ["S", "M", "S", "S"]
    assert (r1.project, sub.project, fork.project, r2.project) == ("widget", "widget", "other", "other")
    assert r2.request == "Now summarise the log for me"
    assert (r1.next_request_s, sub.next_request_s, r2.next_request_s) == (1000, 970, 990)
    assert sub.request.startswith("Dig into the parser")


def test_repo_of_folds_worktrees():
    assert d.repo_of("/x/github/acme/widget-123/pkg") == "acme/widget"
    assert d.repo_of("/x/github/acme/widget-921b") == "acme/widget"
    assert d.repo_of("/x/github/acme/widget-688-scan/a.py") == "acme/widget"
    assert d.repo_of("/x/github/acme/mogrix-site/a") == "acme/mogrix-site"
    assert d.repo_of("/x/elsewhere/a.py") is None


def test_media_candidate_reads_tool_and_file_names():
    u = d.Unit("k", "main", "s", "main", 0.0)
    u.tools["mcp:soh.image"] = 1
    assert d.candidate(u) == "media"
    v = d.Unit("k", "main", "s", "main", 0.0)
    v.edited.add("/a/logo.svg")
    v.calls = 1
    assert d.candidate(v) == "media"


def test_census_packets_and_frame_hold_no_planted_secret_path_or_name(root, tmp_path):
    out = tmp_path / "work"
    frame = d.census(out, root, NOW, n=4, known=KNOWN)
    assert frame["population"] == 4 and frame["n"] == 4
    assert frame["totals"]["tokens_out"] == 2655 and frame["totals"]["kinds"] == {"main": 2, "subagent": 2}
    for name in ("packets-a.jsonl", "packets-b.jsonl", "frame.json"):
        body = (out / name).read_text(encoding="utf-8")
        for planted in (SECRET, "alice", "Zebulon", "Quackenbush", "/Users/"):
            assert planted not in body, (name, planted)
        assert redact.detect(body, KNOWN) == {}
    rows = [json.loads(x) for x in (out / "packets-a.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == ["P001", "P002", "P003", "P004"]
    b = [json.loads(x)["id"] for x in (out / "packets-b.jsonl").read_text().splitlines()]
    assert b == ["P004", "P003", "P002", "P001"]
    assert all("key" not in r and "stratum" not in r for r in rows)


def test_census_refuses_a_tracked_directory(root):
    with pytest.raises(ValueError, match="tracked tree"):
        d.census(d.ROOT / "evals" / "analysis" / "demand" / "work", root, NOW, n=4, known=KNOWN)


def test_allocate_floor_then_proportional_to_tokens_and_capped():
    got = d.allocate({"a": (100, 9000), "b": (100, 1000), "c": (1, 0)}, total=12, floor=1)
    assert got == {"a": 9, "b": 2, "c": 1}
    assert d.allocate({"a": (2, 5), "b": (3, 5)}, total=50) == {"a": 2, "b": 3}


def test_separate_ratio_estimate_by_hand():
    strata = {"A": {"N": 10, "tokens_out": 1000}, "B": {"N": 5, "tokens_out": 3000}}
    sample = [{"id": "1", "stratum": "A", "tokens_out": 100}, {"id": "2", "stratum": "A", "tokens_out": 300},
              {"id": "3", "stratum": "B", "tokens_out": 50}]
    labels = {"1": {"shape": "x"}, "2": {"shape": "y"}, "3": {"shape": "x"}}
    is_x = lambda L: L["shape"] == "x"  # noqa: E731
    assert d.estimate(sample, strata, labels, is_x, "tokens_out") == pytest.approx((250 + 3000) / 4000)
    assert d.estimate(sample, strata, labels, is_x, "count") == pytest.approx(10 / 15)


def test_strata_sampled_once_still_carry_variance():
    strata = {f"s{i}": {"N": 10, "tokens_out": 100} for i in range(8)}
    sample = [{"id": str(i), "stratum": f"s{i}", "tokens_out": 10} for i in range(8)]
    labels = {str(i): {"shape": "x" if i % 2 else "y"} for i in range(8)}
    lo, hi = d.boot_ci(sample, strata, labels, lambda L: L["shape"] == "x", "tokens_out")
    assert lo < 0.5 < hi


def test_kappa_interval_brackets_kappa():
    a = ["x"] * 30 + ["y"] * 30
    b = ["x"] * 25 + ["y"] * 35
    k, lo, hi = d.kappa_ci(a, b, reps=400)
    assert k == pytest.approx(0.833, abs=1e-3) and lo <= k <= hi < 1.0
    assert d.kappa_ci(a, a, reps=50)[0] == 1.0


def _labels(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _row(pid, shape, fit="fits_now", latency="soon", gist="a parser fix"):
    return {"id": pid, "shape": shape, "fit": fit, "fit_reason": f"one file, key {SECRET}", "latency": latency,
            "gist": gist}


def test_report_kappa_table_and_manifest(root, tmp_path, capsys, monkeypatch):
    out = tmp_path / "work"
    d.census(out, root, NOW, n=4, known=KNOWN)
    a = _labels(tmp_path / "a.jsonl", [_row("P001", "small_code_edit"), _row("P002", "orchestration_chat"),
                                       _row("P003", "multi_file_code", "does_not_fit"),
                                       _row("P004", "summarise_digest", latency="queued")])
    b = _labels(tmp_path / "b.jsonl", [_row("P001", "small_code_edit"), _row("P002", "orchestration_chat"),
                                       _row("P003", "investigation_debug", "does_not_fit"),
                                       _row("P004", "summarise_digest", latency="queued")])
    frame = json.loads((out / "frame.json").read_text())
    got = d.report(frame, d.load_labels(a), d.load_labels(b))
    assert got["kappa"]["shape"]["agree"] == 3 and got["kappa"]["fit"]["kappa"] == 1.0
    assert [x["id"] for x in got["disagreements"]] == ["P003"] and got["unsettled"] == 1
    for m in d.MEASURES:
        assert sum(c[m] for c in got["cells"]) == pytest.approx(1.0, abs=1e-3)
    assert sum(r["tokens_out"] for r in got["margins"]["shape"]) == pytest.approx(1.0, abs=1e-3)
    settled = _labels(tmp_path / "s.jsonl", [_row("P003", "investigation_debug", "does_not_fit")])
    fin = d.final_labels(d.load_labels(a), d.load_labels(b), d.load_labels(settled))
    assert fin["P003"]["shape"] == "investigation_debug" and fin["P003"]["settled"]
    dest = tmp_path / "dest"
    monkeypatch.setattr(d, "public_repo", lambda repo: False)
    assert frame["repos"] == {"widget": "acme/widget"}
    assert cli.main(["report", str(out), "--a", str(a), "--b", str(b), "--write", str(dest)]) == 0
    rows = [json.loads(x) for x in (dest / "manifest.jsonl").read_text().splitlines()]
    assert {r["key"] for r in rows} == {r["key"] for r in frame["sample"]}
    assert {r["stratum"].split("/")[0] for r in rows} == {"private-1", "other"}
    for name in ("manifest.jsonl", "strata.json", "census.txt"):
        body = (dest / name).read_text()
        assert "widget" not in body and "acme" not in body, name
        assert SECRET not in body and "alice" not in body and redact.detect(body, redact.known_here()) == {}
    assert "kappa" in capsys.readouterr().out


def test_write_refuses_a_name_in_a_gist(root, tmp_path):
    out = tmp_path / "work"
    d.census(out, root, NOW, n=4, known=KNOWN)
    rows = [_row(p, "small_code_edit", gist="asked Bartholomew for the parser") for p in ("P001", "P002", "P003", "P004")]
    a = d.load_labels(_labels(tmp_path / "a.jsonl", rows))
    frame = json.loads((out / "frame.json").read_text())
    got = d.report(frame, a, a)
    with pytest.raises(ValueError, match="Bartholomew"):
        d.write(tmp_path / "dest", frame, got, d.manifest(frame, a, a, None, KNOWN), KNOWN, public=lambda r: True)
    assert not (tmp_path / "dest").exists()


def test_load_labels_refuses_off_set_and_repeats(tmp_path):
    with pytest.raises(ValueError, match="shape"):
        d.load_labels(_labels(tmp_path / "x.jsonl", [_row("P001", "poetry")]))
    with pytest.raises(ValueError, match="twice"):
        d.load_labels(_labels(tmp_path / "y.jsonl", [_row("P001", "media"), _row("P001", "media")]))


def test_a_later_round_overrides_only_the_keys_it_carries(tmp_path):
    first = _labels(tmp_path / "a.jsonl", [_row("P001", "media", latency="soon"), _row("P002", "media")])
    second = _labels(tmp_path / "a2.jsonl", [{"id": "P001", "latency": "queued"}])
    got = d.load_rounds([first, second])
    assert (got["P001"]["shape"], got["P001"]["latency"], got["P002"]["latency"]) == ("media", "queued", "soon")
    with pytest.raises(ValueError, match="latency"):
        d.load_rounds([first, _labels(tmp_path / "bad.jsonl", [{"id": "P001", "latency": "never"}])])
    with pytest.raises(ValueError, match="P009"):
        d.load_rounds([first, _labels(tmp_path / "new.jsonl", [{"id": "P009", "latency": "soon"}])])


def test_codebook_prints_every_label(capsys):
    assert cli.main(["codebook"]) == 0
    printed = capsys.readouterr().out
    assert all(v in printed for table in d.CLOSED.values() for v in table)

"""Shadow replay of census units over synthetic transcripts: selection, prompt rebuild, checks, judge, report. #1161."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evals import redact
from evals.analysis import demand as d
from evals.analysis.demand import __main__ as cli
from evals.analysis.demand import replay as rp
from harness import delegate

NOW = 1_790_000_000.0
T0 = NOW - 86400
HOME = "/" + "Users/alice/projects/github/acme/widget"
SECRET = "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx"
KNOWN = redact.Known(accounts=("alice",), names=("Zebulon", "Quackenbush"))
BASE = "def count(xs):\n    return len(xs) - 1\n"
FIXED = "def count(xs):\n    return len(xs)\n"
GOOD_DIFF = ("```diff\n--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1,2 +1,2 @@\n def count(xs):\n-    return len(xs) - 1\n"
             "+    return len(xs)\n```\n")
WRONG_DIFF = GOOD_DIFF.replace("+    return len(xs)\n", "+    return len(xs) + 1\n")


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _typed(t, text):
    return {"type": "user", "timestamp": _iso(t), "message": {"role": "user", "content": text},
            "origin": {"kind": "human"}, "userType": "external", "promptId": f"p{t}"}


def _asst(t, mid, *blocks):
    return {"type": "assistant", "timestamp": _iso(t),
            "message": {"id": mid, "stop_reason": "end_turn", "content": list(blocks),
                        "usage": {"input_tokens": 100, "output_tokens": 50}}}


def _use(tid, name, **args):
    return {"type": "tool_use", "id": tid, "name": name, "input": args}


def _result(t, tid, body):
    return {"type": "user", "timestamp": _iso(t), "toolUseResult": {"ok": True},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": body}]}}


def _text(s):
    return {"type": "text", "text": s}


def _write(path: Path, recs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


@pytest.fixture
def world(tmp_path):
    """A session with a summary request, an edit request and a later request, a subagent that reports through
    SubagentHandback, and a manifest naming them plus does-not-fit and media units."""
    root = tmp_path / "projects"
    main = root / "-Users-alice-projects" / "s1.jsonl"
    numbered = "".join(f"{i:6d}\t{line}\n" for i, line in enumerate(BASE.splitlines(), 1))
    _write(main, [
        _typed(T0, f"Summarise the log for Zebulon Quackenbush, key {SECRET}"),
        _asst(T0 + 5, "m1", _use("r1", "Read", file_path=f"{HOME}/pkg/a.py")),
        _result(T0 + 6, "r1", numbered),
        _asst(T0 + 10, "m2", _text("SUMMARY: 3 errors in 12 runs, all timeouts")),
        _typed(T0 + 100, "Fix the off-by-one in count"),
        _asst(T0 + 105, "m3", _use("e1", "Edit", file_path=f"{HOME}/pkg/a.py",
                                   old_string="return len(xs) - 1", new_string="return len(xs)")),
        _result(T0 + 106, "e1", "ok"),
        _asst(T0 + 110, "m4", _text("FIXED the count")),
        _typed(T0 + 200, "LATER request that no earlier unit may see"),
        _asst(T0 + 205, "m5", _text("later reply")),
        _asst(T0 + 210, "m6", _use("a1", "Agent", prompt="pick A or B")),
    ])
    _write(main.parent / "s1" / "subagents" / "agent-x.jsonl", [
        {"type": "user", "timestamp": _iso(T0 + 211), "message": {"role": "user", "content": "Pick option A or B"}},
        _asst(T0 + 215, "s1", _use("h1", "SubagentHandback", message="HANDBACK: pick B, it is faster")),
    ])
    keys = {"sum": d.unit_key("s1", "main", T0), "edit": d.unit_key("s1", "main", T0 + 100),
            "later": d.unit_key("s1", "main", T0 + 200), "sub": d.unit_key("s1", "agent-x", T0 + 211)}

    def row(pid, key, shape, fit):
        return {"id": pid, "key": key, "kind": "subagent" if key == keys["sub"] else "main", "weight": 2.0,
                "final": {"shape": shape, "fit": fit, "latency": "soon"}}
    rows = [row("P001", keys["sum"], "summarise_digest", "fits_with_harness_work"),
            row("P002", keys["edit"], "small_code_edit", "fits_now"),
            row("P003", keys["later"], "multi_file_code", "does_not_fit"),
            row("P004", keys["sub"], "triage_decide", "fits_with_harness_work"),
            row("P005", "0" * 16, "media", "does_not_fit"),
            row("P006", "1" * 16, "orchestration_chat", "fits_now")]
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return {"root": root, "manifest": manifest, "out": tmp_path / "out", "rows": rows}


def _packets(world, controls=1):
    rp.prepare(world["out"], world["manifest"], world["root"], NOW, controls=controls, known=KNOWN)
    return {p["id"]: p for p in rp._jsonl(world["out"] / "packets.jsonl")}


def test_the_fitting_units_are_replayed_and_the_control_never_draws_a_media_unit(world):
    got = rp.select(world["rows"], controls=5)
    assert [r["id"] for r in got] == ["P001", "P002", "P003", "P004", "P006"]
    assert [r["control"] for r in got] == [False, False, True, False, False]
    assert rp.select(world["rows"], controls=1) == rp.select(world["rows"], controls=1)


def test_a_prompt_holds_the_context_up_to_its_request_and_nothing_after(world):
    ps = _packets(world)
    summary, edit, sub = ps["P001"], ps["P002"], ps["P004"]
    assert summary["prompt"].rstrip().endswith(rp.TAIL.strip())
    assert "Summarise the log" in summary["prompt"] and "SUMMARY: 3 errors" not in summary["prompt"]
    assert "SUMMARY: 3 errors" in summary["reference"] and summary["result"].startswith("SUMMARY")
    assert "Fix the off-by-one" in edit["prompt"] and "SUMMARY: 3 errors" in edit["prompt"]
    assert "FIXED" not in edit["prompt"] and "LATER" not in edit["prompt"] and "LATER" not in edit["reference"]
    assert "FIXED the count" in edit["reference"]
    assert sub["prompt"].count("Pick option A or B") == 1 and sub["result"] == "HANDBACK: pick B, it is faster"
    assert (summary["lane"], edit["lane"], sub["lane"], ps["P003"]["lane"]) == ("extract", "code", "decide", "code")
    assert ps["P003"]["control"] and not summary["control"]


def test_no_planted_secret_or_name_survives_and_the_hash_is_of_the_rebuilt_prompt(world):
    ps = _packets(world)
    blob = json.dumps(ps)
    for planted in (SECRET, "Zebulon", "Quackenbush", "alice"):
        assert planted not in blob
    assert all(not rp.findings(p, KNOWN) for p in ps.values())
    again = _packets(world)
    assert again["P001"]["prompt_sha256"] == ps["P001"]["prompt_sha256"] != ps["P001"]["redacted_sha256"]


def test_a_unit_whose_transcript_is_gone_is_reported_missing(world):
    meta = rp.prepare(world["out"], world["manifest"], world["root"], NOW, known=KNOWN)
    assert meta["missing"] == ["P006"]
    assert meta["selected"] == 5


def test_packets_are_refused_inside_the_tracked_tree(world):
    with pytest.raises(ValueError, match="tracked tree"):
        rp.prepare(d.ROOT / "evals" / "replay-out", world["manifest"], world["root"], NOW, known=KNOWN)


def test_a_redaction_finding_left_in_a_packet_stops_prepare(world, monkeypatch):
    monkeypatch.setattr(rp, "_red", lambda text, known: text)
    with pytest.raises(ValueError, match="redaction left findings"):
        rp.prepare(world["out"], world["manifest"], world["root"], NOW, known=KNOWN)


def test_an_edited_file_carries_its_read_text_before_and_its_text_after(world):
    edit = _packets(world)["P002"]
    assert edit["files"] == {"pkg/a.py": {"base": BASE, "post": FIXED}}
    assert _packets(world)["P001"]["files"] == {}


def test_a_diff_that_leaves_the_file_as_the_session_did_is_graded_by_the_check(world):
    edit = _packets(world)["P002"]
    assert rp.check(edit, GOOD_DIFF)["grader"] == "check"
    assert rp.check(edit, WRONG_DIFF) is None
    assert rp.check(edit, "just change it") is None
    assert rp.check(_packets(world)["P001"], GOOD_DIFF) is None


def test_local_replies_resume_and_a_refusal_is_the_rows_error(world):
    ps = list(_packets(world).values())
    asked = []

    def ask(lane, prompt):
        asked.append(lane)
        if lane == "decide":
            raise delegate.Refused("the prompt fills the context")
        return {"text": f"reply on {lane}", "model": "m", "spec": "s", "seconds": 2.0, "ttft_s": 0.1}
    rows = rp.run_local(world["out"], ps, 1, ask)
    assert len(rows) == len(ps) == len(asked)
    by = {r["id"]: r for r in rows}
    assert by["P004"]["error"].startswith("the prompt fills") and by["P001"]["temperature"] == 0.0
    assert len(rp.run_local(world["out"], ps, 1, ask)) == len(ps) and len(asked) == len(ps)


def test_a_shape_no_text_lane_serves_is_an_error_row_without_a_call(world):
    p = dict(_packets(world)["P001"], id="PX", lane="", shape="media")
    rows = rp.run_local(world["out"], [p], 1, lambda *a: pytest.fail("asked"))
    assert rows[0]["error"].startswith("no text lane")


def test_a_judge_reply_without_a_grade_is_asked_again_then_left_ungraded():
    replies = iter(["no idea", '{"grade": "usable_with_edits", "reason": "close"}'])
    assert rp.judge({"prompt": "", "reference": ""}, "x", lambda *a: next(replies))["grade"] == "usable_with_edits"
    got = rp.judge({"prompt": "", "reference": ""}, "x", lambda *a: "maybe")
    assert got["grade"] is None and "no grade" in got["reason"]
    assert rp.parse_grade('sure: {"grade": "not_usable", "reason": "off\\ntask"}') == ("not_usable", "off task")


def test_a_corrupt_plant_moves_every_number_and_flips_every_word():
    assert rp.corrupt("Yes, 3 tests pass and it should merge") == "No, 7 tests fail and it should not merge"
    assert rp.corrupt("nothing here to move") is None


def test_plants_are_another_units_answer_a_corruption_a_written_wrong_one_or_the_record(world):
    ps = list(_packets(world).values())
    me = ps[0]
    assert rp.plant("swap", me, ps) in {p["result"] for p in ps if p["id"] != me["id"] and p["shape"] != me["shape"]}
    assert rp.plant("corrupt", me, ps) == "SUMMARY: 7 errors in 25 runs, all timeouts"
    seen = []
    assert rp.plant("wrong", me, ps, lambda prompt, system: seen.append(system) or "WRONG") == "WRONG"
    assert seen == [rp.WRONG_SYSTEM]
    assert rp.plant(rp.SELF, me, ps) == me["reference"]


def _judges(strict: bool):
    """A judge that grades by whether the candidate is the record (strict) or accepts anything."""
    def ask(prompt, system):
        if system == rp.WRONG_SYSTEM:
            return "a confident wrong answer"
        record = prompt.split("## What the session's assistant actually did\n", 1)[1].split("\n\n## The candidate")[0]
        good = prompt.endswith(record) or not strict
        return json.dumps({"grade": "usable_as_is" if good else "not_usable", "reason": "r"})
    return ask


def test_calibration_passes_a_judge_that_rejects_plants_and_fails_one_that_accepts_all(world):
    ps = list(_packets(world).values())
    good = rp.calibration_summary(rp.calibrate(world["out"], ps, _judges(True), jobs=2, known=KNOWN))
    assert good["passes"] and good["planted"]["rate"] == 1.0 and good[rp.SELF]["rate"] == 1.0
    assert good["planted"]["n"] == good["swap"]["n"] + good["corrupt"]["n"] + good["wrong"]["n"]
    (world["out"] / "calibration.jsonl").unlink()
    lax = rp.calibration_summary(rp.calibrate(world["out"], ps, _judges(False), known=KNOWN))
    assert not lax["passes"] and lax["planted"]["rate"] == 0.0


def test_calibration_resumes_without_asking_again(world):
    ps = list(_packets(world).values())
    rows = rp.calibrate(world["out"], ps, _judges(True), known=KNOWN)
    assert rp.calibrate(world["out"], ps, lambda *a: pytest.fail("asked again"), known=KNOWN) == rows


def test_grading_takes_the_check_then_the_judge_and_a_failed_reply_is_not_usable(world):
    ps = _packets(world)
    rp._write_jsonl(world["out"] / "replies-1.jsonl", [
        {"id": "P002", "text": GOOD_DIFF, "seconds": 3.0}, {"id": "P001", "text": "a summary", "seconds": 1.0},
        {"id": "P004", "error": "refused", "failure_class": "refused"}])
    asked = []
    rows = rp.grade(world["out"], list(ps.values()), 1,
                    lambda prompt, system: asked.append(1) or '{"grade": "usable_with_edits", "reason": "ok"}')
    by = {r["id"]: r for r in rows}
    assert (by["P002"]["grader"], by["P001"]["grader"], by["P004"]["grader"]) == ("check", "judge", "error")
    assert by["P004"]["grade"] == "not_usable" and len(asked) == 1


def _row(pid, shape, lane, grade, seconds, control=False, weight=1.0):
    return {"id": pid, "shape": shape, "lane": lane, "control": control, "weight": weight, "grade": grade,
            "seconds": seconds}


def test_the_report_rates_each_cell_counts_gpu_time_and_checks_the_acceptance():
    packets = [{k: v for k, v in _row(f"P{i}", s, lane, None, None, c, w).items() if k not in ("grade", "seconds")}
               for i, (s, lane, c, w) in enumerate([("extract_classify", "extract", False, 1.0),
                                                    ("extract_classify", "extract", False, 3.0),
                                                    ("triage_decide", "decide", False, 1.0),
                                                    ("multi_file_code", "code", True, 1.0)])]
    replies = {1: [{"id": "P0", "seconds": 1800.0}, {"id": "P1", "seconds": 1800.0}, {"id": "P2", "seconds": 3600.0},
                   {"id": "P3", "seconds": 10.0}],
               2: []}
    g1 = [{"id": "P0", "grade": "usable_as_is", "grader": "judge"},
          {"id": "P1", "grade": "usable_with_edits", "grader": "judge"},
          {"id": "P2", "grade": "not_usable", "grader": "error"}, {"id": "P3", "grade": "not_usable"}]
    g2 = [dict(g1[0]), dict(g1[1], grade="usable_as_is"), dict(g1[2]), dict(g1[3])]
    cal = [{"id": "P0", "plant": "swap", "grade": "not_usable"}, {"id": "P0", "plant": "wrong", "grade": "not_usable"},
           {"id": "P0", "plant": "corrupt", "grade": None, "skipped": True},
           {"id": "P0", "plant": rp.SELF, "grade": "usable_as_is"}]
    got = rp.report(packets, replies, {1: g1, 2: g2}, cal)
    ext = got["cells"]["extract_classify x extract"]
    assert ext["n"] == 2 and ext["as_is"]["k"] == 1 and ext["usable"]["k"] == 2 and ext["gpu_s"] == 3600.0
    assert ext["as_is"]["ci"][0] < 0.5 < ext["as_is"]["ci"][1]
    assert (ext["p50_s"], ext["p90_s"]) == (1800.0, 1800.0)
    assert got["fit"]["n"] == 3 and got["control"]["n"] == 1 and got["control_near_zero"]
    assert got["per_gpu_hour"] == {"as_is": 0.5, "usable": 1.0, "gpu_hours": 2.0}
    assert got["weighted_as_is"] == 0.2
    assert got["agreement"]["k"] == 3 and got["agreement"]["n"] == 4 and not got["agreement"]["passes"]
    assert got["reachable"]["n"] == 1 and got["reachable"]["as_is"]["k"] == 1
    cs = got["calibration"]
    assert cs["planted"]["k"] == 2 and cs["planted"]["n"] == 2 and cs["skipped"] == 1 and cs["passes"]
    body = rp.text(got)
    assert "PASS" in body and "FAIL" in body and "per GPU-hour" in body


def test_a_control_with_usable_answers_is_not_near_zero():
    packets = [{"id": "P0", "shape": "multi_file_code", "lane": "code", "control": True, "weight": 1.0}]
    got = rp.report(packets, {1: [{"id": "P0", "seconds": 5.0}]}, {1: [{"id": "P0", "grade": "usable_as_is"}]}, [])
    assert not got["control_near_zero"] and not got["calibration"]["passes"] and "agreement" not in got
    assert got["reachable"] is None


def test_the_command_runs_every_step_end_to_end(world, monkeypatch, capsys):
    monkeypatch.setattr(redact, "known_here", lambda *a: KNOWN)
    monkeypatch.setattr(rp, "claude", lambda prompt, system, model=rp.JUDGE_MODEL: _judges(True)(prompt, system))
    monkeypatch.setattr(rp, "ask_local", lambda lane, prompt: {"text": GOOD_DIFF if "off-by-one" in prompt else "x",
                                                                "seconds": 4.0, "model": "local-m"})
    rc = cli.main(["replay", "--out", str(world["out"]), "--root", str(world["root"]), "--manifest",
                   str(world["manifest"]), "--now", str(NOW), "--controls", "1",
                   "--steps", "prepare,calibrate,local,grade,report"])
    out = capsys.readouterr().out
    assert rc == 0 and "prepared 4 of 5 units" in out and "planted wrong answers rejected" in out
    assert "replays 1 and 2 grade alike on 4/4" in out
    assert (world["out"] / "report.txt").read_text(encoding="utf-8") in out
    assert cli.main(["replay", "--out", str(world["out"]), "--steps", "nope"]) == 2


def test_a_partial_or_capped_read_gives_no_base_text_to_check_against():
    from evals.session_cut import Event
    numbered = "".join(f"{i:6d}\t{line}\n" for i, line in enumerate(BASE.splitlines(), 1))
    edit = [Event(9, "call", "Edit", input={"file_path": f"{HOME}/pkg/a.py", "old_string": "return len(xs) - 1",
                                           "new_string": "return len(xs)"}, ref="e")]
    for args, body in (({"offset": 1}, numbered), ({"limit": 2}, numbered), ({}, numbered + "[... 9 more bytes]")):
        context = [Event(1, "call", "Read", input={"file_path": f"{HOME}/pkg/a.py", **args}, ref="r"),
                   Event(2, "result", "Read", body, ref="r")]
        assert rp.edits(context, edit) == {}
    whole = [Event(1, "call", "Read", input={"file_path": f"{HOME}/pkg/a.py"}, ref="r"),
             Event(2, "result", "Read", numbered, ref="r")]
    assert rp.edits(whole, edit) == {"pkg/a.py": {"base": BASE, "post": FIXED}}
    stale = [Event(9, "call", "Edit", input={"file_path": f"{HOME}/pkg/a.py", "old_string": "not there",
                                            "new_string": "x"}, ref="e")]
    assert rp.edits(whole, stale) == {}


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="evals/analysis/demand/replay.py:GROUP")
@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="evals/analysis/demand/replay.py:LANE")
def test_every_census_shape_routes_to_a_served_text_lane_or_is_named_as_not_text():
    from harness import gateway
    assert set(rp.GROUP) | set(rp.NOT_TEXT) == set(d.SHAPES) and not set(rp.GROUP) & set(rp.NOT_TEXT)
    assert set(rp.LANE) == set(rp.GROUP.values())
    assert set(rp.LANE.values()) <= set(gateway.TEXT_LANES)

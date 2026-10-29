"""soh baseline: each workload as all local, all Claude and hybrid, from stored rows and the replay summary. #687."""
from __future__ import annotations

import json
import random
import sqlite3

import pytest

from evals import redact
from evals import workload_baseline as B
from evals.analysis.demand import replay as rp

SECRET = "zebra-quartz-unrelated-7731"


def _items(rng, n):
    return [{"case": f"c{i}", "local": rng.random() < 0.4, "claude": rng.random() < 0.8, "keep": rng.random() < 0.5}
            for i in range(n)]


def test_the_local_and_claude_arms_equal_their_executors():
    rng = random.Random(687)
    for _ in range(50):
        items = _items(rng, 30)
        got = B.cascade(items, {})
        assert got["local"]["k"] == sum(i["local"] for i in items)
        assert got["claude"]["k"] == sum(i["claude"] for i in items)
        assert got["local"]["n"] == got["claude"]["n"] == 30


def test_a_gate_that_never_escalates_equals_all_local_and_one_that_always_escalates_equals_all_claude():
    rng = random.Random(688)
    tokens = {f"c{i}": (100 + i, 10 + i) for i in range(30)}
    for _ in range(50):
        items = _items(rng, 30)
        keep = B.cascade([{**i, "keep": True} for i in items], tokens)
        send = B.cascade([{**i, "keep": False} for i in items], tokens)
        assert keep["hybrid"]["k"] == keep["local"]["k"] and keep["to_claude"] == 0
        assert keep["hybrid_tokens"] == {"in": 0, "out": 0}
        assert send["hybrid"]["k"] == send["claude"]["k"] and send["to_claude"] == 30
        assert send["hybrid_tokens"] == send["claude_tokens"] == {"in": sum(t[0] for t in tokens.values()),
                                                                  "out": sum(t[1] for t in tokens.values())}
        assert keep["accepted_wrong"] == sum(not i["local"] for i in items) and send["accepted_wrong"] == 0


def test_no_hybrid_beats_the_oracle():
    rng = random.Random(689)
    for _ in range(100):
        items = _items(rng, 25)
        got = B.cascade(items, {})
        oracle = sum(i["local"] or i["claude"] for i in items)
        assert got["hybrid"]["k"] <= oracle
        assert got["to_claude"] == sum(not i["keep"] for i in items)


def test_an_unknown_claude_answer_makes_the_hybrid_a_pair_of_bounds():
    items = [{"case": "a", "local": True, "claude": None, "keep": True},
             {"case": "a", "local": False, "claude": None, "keep": False},
             {"case": "b", "local": False, "claude": None, "keep": False}]
    got = B.cascade(items, {})
    assert got["claude"] is None and got["claude_tokens"] is None
    assert got["hybrid"] is None and got["hybrid_bounds"] == [1, 3]
    assert got["to_claude"] == 2


def _record(i, shape, grade, *, control=False, self_grade="usable_as_is", seconds=30.0):
    return [{"kind": "unit", "id": i, "shape": shape, "lane": "code", "control": control},
            {"kind": "reply", "id": i, "candidate": "adopted", "repeat": 1, "grade": grade, "grader": "judge",
             "seconds": seconds, "prompt_tokens": 10, "completion_tokens": 5, "model": "m"},
            {"kind": "self", "id": i, "grade": self_grade}]


def _manifest(ids):
    return [{"id": i, "stratum": "s", "tokens_in": 1000, "tokens_out": 100, "final": {"shape": shape}}
            for i, shape in ids]


def test_a_shape_no_table_names_still_gets_its_own_row():
    recs = (_record("P1", "orchestration_chat", "usable_with_edits")
            + _record("P2", "brand_new_shape", "not_usable", self_grade="not_usable"))
    rows = B.replay_rows(recs, _manifest([("P1", "orchestration_chat"), ("P2", "brand_new_shape")]),
                         {"s": {"N": 2, "tokens_out": 200}})
    by = {r["workload"]: r for r in rows}
    assert "replay brand_new_shape" in by and by["replay brand_new_shape"]["n"] == 1
    assert by["replay brand_new_shape"]["local"]["k"] == 0
    assert by["replay all fitting"]["n"] == 2 and by["replay all fitting"]["local"]["k"] == 1


def test_replay_rows_count_controls_apart_and_take_the_first_repeat():
    recs = _record("P1", "small_code_edit", "usable_as_is") + _record("P9", "small_code_edit", "usable_as_is",
                                                                      control=True)
    recs.append({"kind": "reply", "id": "P1", "candidate": "adopted", "repeat": 2, "grade": "not_usable",
                 "grader": "judge", "seconds": 999.0})
    rows = B.replay_rows(recs, _manifest([("P1", "small_code_edit"), ("P9", "small_code_edit")]),
                         {"s": {"N": 2, "tokens_out": 200}})
    r = next(r for r in rows if r["workload"] == "replay small_code_edit")
    assert r["n"] == 1 and r["local"]["k"] == 1 and r["local_gpu_min"] == 0.5
    assert r["hybrid"]["k"] == 1 and r["to_claude"] == 0 and r["claude_tokens"] == {"in": 1000, "out": 100}


def test_a_unit_whose_own_record_was_never_graded_leaves_the_claude_arm_unknown():
    recs = _record("P1", "orchestration_chat", "not_usable")
    recs = [r for r in recs if r["kind"] != "self"]
    (r, _) = B.replay_rows(recs, _manifest([("P1", "orchestration_chat")]), {"s": {"N": 1, "tokens_out": 100}})
    assert r["claude"] is None and r["hybrid"] is None and r["hybrid_bounds"] == [0, 1]


def _packet(i, shape, control=False):
    return {"id": i, "key": f"k{i}", "kind": "main", "control": control, "weight": 1.0, "shape": shape,
            "fit": "fits_with_harness_work", "latency": "soon", "group": rp.GROUP[shape], "lane": rp.LANE[rp.GROUP[shape]],
            "prompt": f"quoted {SECRET}", "reference": f"record {SECRET}", "result": f"final {SECRET}", "files": {}}


def _replay_dir(tmp_path):
    out = tmp_path / "replay"
    out.mkdir()
    packets = [_packet("P1", "orchestration_chat"), _packet("P2", "triage_decide"), _packet("P3", "small_code_edit", True)]
    rp._write_jsonl(out / "packets.jsonl", packets)

    def local(lane, prompt, model):
        return {"text": f"reply {SECRET}", "model": "m", "spec": "s", "seconds": 12.0, "prompt_tokens": 7,
                "completion_tokens": 3}
    grades = iter(["usable_with_edits", "not_usable", "not_usable"] + ["usable_as_is"] * 20)

    def judge(prompt, system):
        return json.dumps({"grade": next(grades), "reason": f"because {SECRET}"})
    for rep in (1, 2):
        rp.run_local(out, packets, rep, local)
    rp.grade(out, packets, 1, judge, jobs=1)
    rp.grade(out, packets, 2, judge, jobs=1)
    rp.calibrate(out, packets, judge, jobs=1, known=redact.Known(accounts=("alice",), names=()))
    return out


def test_the_replay_summary_holds_no_text(tmp_path):
    recs = B.summarise(_replay_dir(tmp_path))
    assert SECRET not in json.dumps(recs)
    kinds = {r["kind"] for r in recs}
    assert kinds == {"meta", "unit", "reply", "self"}
    replies = [r for r in recs if r["kind"] == "reply"]
    assert len(replies) == 6 and all(r["grade"] in rp.GRADES for r in replies)
    assert {r["id"]: r["grade"] for r in replies if r["repeat"] == 1}["P1"] == "usable_with_edits"
    assert all(r["seconds"] == 12.0 and r["completion_tokens"] == 3 for r in replies)
    assert {r["id"] for r in recs if r["kind"] == "self"} == {"P1", "P2", "P3"}


def test_the_summary_round_trips_through_save(tmp_path):
    recs = B.summarise(_replay_dir(tmp_path))
    path = tmp_path / "replay.jsonl"
    B.save(recs, path)
    assert B.load_summary(path) == recs


def _rows(cand, codes, seconds=5.0, tokens=None):
    """codes: P resolved; C applied and wrong; I did not apply; E the harness never ran."""
    fc = {"P": "", "C": "content_failed", "I": "invalid_patch", "E": "environment_error"}
    out = []
    for i, c in enumerate(codes):
        m = {"resolved": int(c == "P"), "patch_applied": int(c in "PC")}
        if tokens:
            m.update(prompt_tokens=tokens[0], cache_read_tokens=0, cache_creation_tokens=tokens[1],
                     completion_tokens=tokens[2])
        out.append({"candidate": cand, "case_id": f"t{i}-spec", "passed": c == "P", "failure_class": fc[c],
                    "detail": "", "seconds": seconds, "metrics": m})
    return out


def _adopt(conn, lane, run_id, at=1):
    cid = conn.execute("SELECT candidate_id FROM results WHERE run_id = ? LIMIT 1", (run_id,)).fetchone()[0]
    conn.execute("INSERT INTO adoptions (lane, candidate_id, run_id, how, adopted_at) VALUES (?, ?, ?, 'by-hand', ?)",
                 (lane, cid, run_id, at))
    conn.commit()


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="evals/workload_baseline.py:_adopted")
@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="evals/workload_baseline.py:_newest")
def test_the_local_run_is_taken_on_the_claude_runs_exam(store_run, tmp_path):
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "s.db")
    orn = {"ornith": "llamacpp:ornith"}
    adopted = store_run("a", "repo", rows=_rows("ornith", "PIC"), conn=conn, cases_digest="X",
                        generated="2026-10-01T00:00:00", specs=orn)
    store_run("b", "repo", rows=_rows("other", "PPP"), conn=conn, cases_digest="X", generated="2026-10-02T00:00:00",
              specs={"other": "llamacpp:other"})
    store_run("c", "repo", rows=_rows("ornith", "PPP"), conn=conn, cases_digest="Y", generated="2026-10-04T00:00:00",
              specs=orn)
    cloud = store_run("d", "repo", rows=_rows("claude-code:opus", "PPC", tokens=(2, 3000, 600)), conn=conn,
                      cases_digest="X", generated="2026-10-03T00:00:00")
    _adopt(conn, "repo", adopted)
    (r,) = B.lane_rows(conn, ["repo"])
    other = conn.execute("SELECT id FROM runs WHERE path LIKE '%b'").fetchone()[0]
    _adopt(conn, "repo", other, at=2)
    assert B.lane_rows(conn, ["repo"])[0]["runs"]["local"] == other
    newer = store_run("e", "repo", rows=_rows("claude-code:opus", "PPP"), conn=conn, cases_digest="Y",
                      generated="2026-10-05T00:00:00")
    assert B.lane_rows(conn, ["repo"])[0]["runs"]["claude"] == newer
    conn.close()
    assert (r["runs"]["local"], r["runs"]["claude"]) == (adopted, cloud)
    assert (r["local"]["k"], r["claude"]["k"], r["n"]) == (1, 2, 3)
    # gate visible: t0 applied and resolved (kept), t1 did not apply (sent, Claude resolves), t2 applied wrong (kept)
    assert (r["hybrid"]["k"], r["to_claude"], r["accepted_wrong"]) == (2, 1, 1)
    assert r["claude_tokens"] == {"in": 9006, "out": 1800} and r["hybrid_tokens"] == {"in": 3002, "out": 600}
    assert r["local_gpu_min"] == 0.25


def test_a_lane_with_no_stored_claude_run_says_so_instead_of_reading_zero(store_run, tmp_path):
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "s.db")
    store_run("a", "claims", rows=_rows("qwen", "PPCE"), conn=conn)
    rows = B.lane_rows(conn, ["claims", "music"])
    conn.close()
    claims, music = rows
    assert claims["claude"] is None and claims["hybrid"] is None and claims["claude_tokens"] is None
    assert claims["n"] == 3 and claims["local"]["k"] == 2
    assert "no stored claude run" in claims["note"]
    assert music["n"] == 0 and "no stored run" in music["note"]
    line = B.text({"rows": rows, "sources": {}})
    claims_line = next(x for x in line.splitlines() if x.startswith("claims"))
    assert "no stored claude run" in line and "0/0" not in claims_line


def test_a_repeated_run_pairs_on_its_first_repeat(store_run, tmp_path):
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "s.db")

    def rows(cand, bits):
        return [{"candidate": cand, "case_id": f"t{i // 2}#{i % 2 + 1}", "passed": b, "seconds": 6.0,
                 "failure_class": "" if b else "wrong", "metrics": {"completion_tokens": 9}} for i, b in enumerate(bits)]
    store_run("a", "extract", rows=rows("local-large", [True, False, False, True]), conn=conn, cases_digest="X")
    store_run("b", "extract", rows=rows("claude-code:opus", [True, True, True, True]), conn=conn, cases_digest="X")
    (r,) = B.lane_rows(conn, ["extract"])
    conn.close()
    assert (r["n"], r["local"]["k"], r["claude"]["k"], r["local_gpu_min"]) == (2, 1, 2, 0.2)
    assert r["claude_tokens"] == {"in": 0, "out": 18} and "claude input tokens not stored" in r["note"]


def test_a_shapes_share_counts_only_its_fitting_units():
    recs = _record("P1", "orchestration_chat", "usable_with_edits")
    man = [{"id": "P1", "stratum": "s", "tokens_out": 100, "final": {"shape": "orchestration_chat",
                                                                     "fit": "fits_with_harness_work"}},
           {"id": "P2", "stratum": "s", "tokens_out": 300, "final": {"shape": "orchestration_chat",
                                                                     "fit": "does_not_fit"}}]
    rows = B.replay_rows(recs, man, {"s": {"N": 2, "tokens_out": 400}})
    assert [r["share"] for r in rows] == [0.25, 0.25]


def test_decide_fields_under_the_gate_go_to_claude(store_run, tmp_path):
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "s.db")
    rows = [{"candidate": "imajev", "case_id": "q1", "passed": False, "seconds": 2.0, "failure_class": "",
             "metrics": {"decide_correct": 2, "decide_fields": 3, "decisions": [[0.99, 1], [0.6, 1], [0.5, 0]]}},
            {"candidate": "imajev", "case_id": "q2", "passed": True, "seconds": 2.0, "failure_class": "",
             "metrics": {"decide_correct": 2, "decide_fields": 2, "decisions": [[0.97, 1], [0.96, 1]]}}]
    store_run("a", "decide", rows=rows, conn=conn)
    (r,) = B.lane_rows(conn, ["decide"], gate=0.95)
    conn.close()
    assert r["n"] == 5 and r["local"]["k"] == 4 and r["unit"] == "fields"
    assert r["to_claude"] == 2 and r["hybrid"] is None and r["hybrid_bounds"] == [3, 5]
    assert r["accepted_wrong"] == 0


def test_the_bar_decides_keep_or_return_only_when_set():
    hi = {"k": 45, "n": 50, "ci": [0.79, 0.96]}
    lo = {"k": 5, "n": 50, "ci": [0.04, 0.21]}
    mid = {"k": 25, "n": 50, "ci": [0.36, 0.64]}
    assert [B.verdict(x, 0.5) for x in (hi, lo, mid)] == ["keep", "return", "undecided"]
    assert [B.verdict(x, None) for x in (hi, lo, mid)] == ["", "", ""]
    assert B.verdict({"k": 0, "n": 0, "ci": [0.0, 1.0]}, 0.5) == "undecided"


def test_the_store_file_is_byte_identical_after_a_run(store_run, tmp_path, capsys):
    from harness import cli
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "s.db")
    store_run("a", "repo", rows=_rows("ornith", "PIC"), conn=conn, cases_digest="X")
    store_run("d", "repo", rows=_rows("claude-code:opus", "PPC", tokens=(2, 30, 6)), conn=conn, cases_digest="X")
    conn.close()
    path = tmp_path / "s.db"
    summary = tmp_path / "replay.jsonl"
    B.save(_record("P1", "orchestration_chat", "usable_with_edits"), summary)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in _manifest([("P1", "orchestration_chat")])),
                        encoding="utf-8")
    strata = tmp_path / "strata.json"
    strata.write_text(json.dumps({"strata": {"s": {"N": 1, "tokens_out": 100}}}), encoding="utf-8")
    before = path.read_bytes()
    assert cli.main(["baseline", "--json", "--store", str(path), "--summary", str(summary), "--manifest",
                     str(manifest), "--strata", str(strata), "--lane", "repo", "--bar", "0.5"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT count(*) FROM results").fetchone()[0] == 6
    names = [r["workload"] for r in got["rows"]]
    assert names == ["replay orchestration_chat", "replay all fitting", "repo"]
    assert got["rows"][-1]["verdict"] in ("keep", "return", "undecided")
    assert cli.main(["baseline", "--store", str(tmp_path / "missing.db"), "--summary", str(summary)]) == 1

"""#2191: a cold /status build reads each case file, transcript and source file once per change, and asks the store for each lane's rows once."""
import hashlib
import json
import time

import pytest
import yaml

from evals import core
from harness import features, file_index, holdout, lane_gate, power, reply_cap, runs, token_flow
from harness import memory_store as ms
from tests.test_token_flow_2031 import SINCE, idle_stream, write

NOW = 2_000_000_000.0


def _case(root, cid, prompt="say hi"):
    (root / f"{cid}.yaml").write_text(yaml.safe_dump({
        "id": cid, "modality": "svg", "prompt": prompt, "methods": ["llm"], "assert": {"min_shapes": 1}}), encoding="utf-8")


def _load(root):
    with core.case_index(root):
        return core.load_cases(root)


def _restart():
    """What a new process starts with: nothing in memory, the index file on disk."""
    core._PARSED.clear()
    core._SEEDED.clear()
    core._BUNDLE_DIGESTS.clear()


@pytest.fixture
def root(tmp_path):
    d = tmp_path / "cases"
    d.mkdir()
    for i in range(5):
        _case(d, f"c{i}")
    return d


def _parsed_by(fn):
    before = core._PARSES[0]
    got = fn()
    return got, core._PARSES[0] - before


def test_a_restart_parses_no_case_file_the_index_holds(root):
    first, n = _parsed_by(lambda: _load(root))
    assert n == 5
    _restart()
    again, n = _parsed_by(lambda: _load(root))
    assert n == 0
    assert [c.id for c in again] == [c.id for c in first]
    assert [c.prompt for c in again] == [c.prompt for c in first]


@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates", site="harness/file_index.py:write")
def test_editing_one_case_file_parses_only_that_file(root):
    _load(root)
    _restart()
    _case(root, "c2", prompt="say hello, a longer prompt")
    got, n = _parsed_by(lambda: _load(root))
    assert n == 1
    assert {c.id: c.prompt for c in got}["c2"] == "say hello, a longer prompt"
    _restart()
    _, n = _parsed_by(lambda: _load(root))
    assert n == 0


def test_a_removed_case_file_leaves_the_index(root):
    _load(root)
    (root / "c4.yaml").unlink()
    _case(root, "c0", prompt="say it again")
    _restart()
    _load(root)
    _restart()
    kept = file_index.read(core._index_name(root), core._INDEX_FORMAT)["parsed"]
    assert sorted(k[0].rsplit("/", 1)[-1] for k in kept) == ["c0.yaml", "c1.yaml", "c2.yaml", "c3.yaml"]


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/file_index.py:read:except")
@pytest.mark.parametrize("junk", [b"", b"not a pickle", b"\x80\x05N."])
def test_an_unreadable_index_is_ignored_not_trusted(root, junk):
    _load(root)
    file_index.file_for(core._index_name(root)).write_bytes(junk)
    _restart()
    got, n = _parsed_by(lambda: _load(root))
    assert n == 5 and len(got) == 5


def test_an_index_of_another_format_is_ignored(root, monkeypatch):
    _load(root)
    _restart()
    monkeypatch.setattr(core, "_INDEX_FORMAT", core._INDEX_FORMAT + 1)
    _, n = _parsed_by(lambda: _load(root))
    assert n == 5


def test_a_bundle_digest_survives_a_restart(root):
    key = (f"{root.as_posix()}/bundle", (("f", 1, 2),))

    def run():
        with core.case_index(root):
            core._BUNDLE_DIGESTS[key] = "abc123"
            core._PARSES[0] += 1

    run()
    _restart()
    with core.case_index(root):
        assert core._BUNDLE_DIGESTS.get(key) == "abc123"


def test_the_holdout_split_reads_its_cases_through_the_index(root):
    holdout.splits(root)
    _restart()
    holdout._cases.cache_clear()
    holdout._splits.cache_clear()
    _, n = _parsed_by(lambda: holdout.splits(root))
    assert n == 0


def _scans(monkeypatch):
    calls = []
    real = token_flow._scan
    monkeypatch.setattr(token_flow, "_scan", lambda p: calls.append(p.name) or real(p))
    return calls


def test_a_restart_scans_only_the_transcripts_that_grew(tmp_path, monkeypatch):
    for name in ("a", "b", "c"):
        write(tmp_path, f"proj/{name}.jsonl", idle_stream(name, "5m"))
    files = sorted(tmp_path.rglob("*.jsonl"))
    calls = _scans(monkeypatch)
    first = token_flow.read(files, SINCE)
    assert sorted(calls) == ["a.jsonl", "b.jsonl", "c.jsonl"]
    token_flow._SCANS.clear()
    calls.clear()
    assert token_flow.read(files, SINCE) == first
    assert calls == []
    write(tmp_path, "proj/b.jsonl", idle_stream("b", "5m") + idle_stream("bb", "5m"))
    token_flow._SCANS.clear()
    again = token_flow.read(files, SINCE)
    assert calls == ["b.jsonl"]
    assert len(again) > len(first)


def test_scanned_transcripts_give_what_reading_every_line_gave(tmp_path):
    write(tmp_path, "proj/s1/subagents/agent-x.jsonl", idle_stream("x", "5m", agent="sohot-fix", tool=("Bash", {"command": "sleep 5"})))
    write(tmp_path, "proj/s1.jsonl", idle_stream("m", "1h"))
    files = sorted(tmp_path.rglob("*.jsonl"))
    got = token_flow.read(files, SINCE, root=tmp_path)
    token_flow._SCANS.clear()
    assert token_flow.read(files, SINCE, root=tmp_path) == got
    assert {r["agent"] for r in got} == {"", "sohot-fix"}
    assert any(r["after"] == "Bash: sleep or poll loop" for r in got)


def test_the_switch_readers_scan_reads_each_source_file_once_per_change(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "harness").mkdir(parents=True)
    src = ('SWITCH_ENV = "SOHOT_X"\n\n\ndef enabled(environ=None):\n    return (environ or {}).get(SWITCH_ENV) != "0"\n')
    (root / "harness" / "x.py").write_text(src, encoding="utf-8")
    (root / "harness" / "y.py").write_text("A = 1\n", encoding="utf-8")
    calls = []
    real = features._readers_in
    monkeypatch.setattr(features, "_readers_in", lambda p: calls.append(p.name) or real(p))
    first = features.switch_readers(root)
    assert first == (("harness.x", "enabled", "SOHOT_X"),)
    features._scan.cache_clear()
    calls.clear()
    assert features.switch_readers(root) == first and calls == []
    (root / "harness" / "y.py").write_text("A = 22\n", encoding="utf-8")
    features._scan.cache_clear()
    assert features.switch_readers(root) == first
    assert calls == ["y.py"]


def test_pinned_roots_stamp_the_case_files_once(root, monkeypatch):
    stamped = []
    real = holdout._stamped
    monkeypatch.setattr(holdout, "_stamped", lambda r=None: stamped.append(r) or real(r))
    with holdout.pinned():
        holdout._roots()
        holdout._roots()
        holdout._roots()
    assert len(stamped) == 1
    holdout._roots()
    assert len(stamped) == 2


def test_a_pin_does_not_hold_an_edited_case_after_the_block(root):
    a = holdout.splits(root)["svg"]
    _case(root, "c9")
    b = holdout.splits(root)["svg"]
    assert "c9" not in a.dev + a.holdout and "c9" in b.dev + b.holdout


def test_one_gate_per_store_and_lane_inside_a_remembered_block(monkeypatch):
    calls = []
    monkeypatch.setattr(lane_gate, "_gate_for", lambda conn, lane, split=None: calls.append(lane) or None)
    conn = object()
    with lane_gate.remembered():
        lane_gate.gate_for(conn, "code")
        lane_gate.gate_for(conn, "CODE")
        lane_gate.gate_for(conn, "svg")
        lane_gate.gate_for(object(), "code")
    assert calls == ["code", "svg", "code"]
    lane_gate.gate_for(conn, "code")
    lane_gate.gate_for(conn, "code")
    assert calls == ["code", "svg", "code", "code", "code"]


LANE = "svg"


def _seed(conn):
    specs = ("alpha", "beta")
    for n, budget in enumerate((8000, 16000)):
        for spec in specs:
            rows = [{"candidate": spec, "case_id": f"c{i}", "passed": (i + n) % 3 != 0, "seconds": 1.0 + i / 10,
                     "failure_class": "", "limit": "", "metrics": {"completion_tokens": 100 + i}} for i in range(12)]
            runs.record(conn, f"runs/r{n}{spec}-{LANE}", {"receipt": {"modality": LANE, "max_tokens": budget,
                        "budget_ladder": [], "sampling": {LANE: {}}}, "specs": {spec: spec}, "rows": rows}, at=1_000.0 + n)
    return specs


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _same(a, b):
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null", site="harness/power.py:prefetched:runs")
def test_a_prefetched_store_answers_every_lane_query_as_the_store_does(conn):
    specs = _seed(conn)
    plain_rows = {s: power._candidate_rows(conn, LANE, s) for s in specs}
    plain_keys = {s: power.served_keys(conn, LANE, s) for s in specs}
    plain_stored = reply_cap.stored(conn, LANE)
    assert plain_stored and all(plain_rows.values())
    with power.prefetched(conn):
        assert power.measured(conn, LANE)
        assert _same({s: power._candidate_rows(conn, LANE, s) for s in specs}, plain_rows)
        assert _same({s: power.served_keys(conn, LANE, s) for s in specs}, plain_keys)
        assert _same(reply_cap.stored(conn, LANE), plain_stored)
        assert power.measured(object(), LANE) is None
    assert power.measured(conn, LANE) is None


def test_a_candidate_row_carries_the_receipt_of_its_run(conn):
    _seed(conn)
    rows = power._candidate_rows(conn, LANE, "alpha")
    by_run = {r["run_id"]: r["receipt"] for r in rows}
    assert len(by_run) == 2
    assert {json.loads(v)["max_tokens"] for v in by_run.values()} == {8000, 16000}
    assert all(r["receipt"] == by_run[r["run_id"]] for r in rows)


def test_the_lane_gate_says_the_same_with_one_query_set_as_with_one_per_lane(conn):
    _seed(conn)
    splits = holdout.splits()
    plain = {lane: lane_gate._gate_for(conn, lane) for lane in sorted(splits)}
    got = lane_gate.status(conn, NOW)
    seen = {g["lane"]: g for g in got["closed"] + got["opened"]}
    assert set(seen) == {lane for lane, g in plain.items() if g is not None}
    for lane, g in plain.items():
        if g is not None:
            assert _same({k: v for k, v in seen[lane].items() if k in g.as_dict()}, g.as_dict())
    assert hashlib.sha256(json.dumps(got, sort_keys=True, default=str).encode()).hexdigest() == hashlib.sha256(
        json.dumps(lane_gate.status(conn, NOW), sort_keys=True, default=str).encode()).hexdigest()


def test_the_lane_gate_reads_each_lanes_measure_rows_in_a_fixed_number_of_queries(conn, monkeypatch):
    _seed(conn)
    holdout.splits()
    sql = []
    real = type(conn).execute

    def spy(self, text, *a, **k):
        sql.append(text)
        return real(self, text, *a, **k)

    monkeypatch.setattr(type(conn), "execute", spy)
    lane_gate.status(conn, NOW)
    reading = [s for s in sql if "FROM results" in s]
    assert len(reading) <= 2, reading


def test_a_model_entry_is_a_private_copy_of_the_shared_config(tmp_path):
    from harness import gateway, models
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"model_list": [{"model_name": "alpha", "litellm_params": {"model": "openai/a"}}]}), encoding="utf-8")
    got = models.entry("alpha", cfg)
    got["litellm_params"]["model"] = "changed"
    got["extra"] = 1
    again = models.entry("alpha", cfg)
    assert again["litellm_params"]["model"] == "openai/a" and "extra" not in again
    assert gateway.load(cfg, share=True) is gateway.load(cfg, share=True)
    assert gateway.load(cfg) is not gateway.load(cfg, share=True)


def test_the_discover_guard_finds_a_live_run_by_its_progress_file(tmp_path):
    from harness import sweep_guard
    runs_dir = tmp_path / sweep_guard.RUNS
    for name in ("a", "b"):
        (runs_dir / name).mkdir(parents=True)
    (runs_dir / "loose-file").write_text("x", encoding="utf-8")
    (runs_dir / "a" / sweep_guard.PROGRESS).write_text(json.dumps({"pid": 0}), encoding="utf-8")
    seen = []
    from harness import run_state
    real = run_state.of
    try:
        run_state.of = lambda path, **k: seen.append(path.name) or real(path, **k)
        sweep_guard.running(tmp_path, alive=lambda pid: False)
    finally:
        run_state.of = real
    assert seen == ["a"]

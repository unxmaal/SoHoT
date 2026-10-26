"""#730: pass thresholds set above a known-good instrument's measured noise floor on clean known inputs."""
from __future__ import annotations

import json

import pytest

from harness import floors
from harness import knobs
from harness import memory_store as ms


def _item(errors, units, stratum="all", case="c", run=1):
    return {"errors": errors, "units": units, "stratum": stratum, "case": case, "run": run}


def _run(conn, lane, path, receipt=None, environment=None):
    cur = conn.execute("INSERT INTO runs (path, lane, recorded_at, receipt, environment) VALUES (?, ?, 0, ?, ?)",
                       (path, lane, json.dumps(receipt or {}), json.dumps(environment or {})))
    return cur.lastrowid


def _row(conn, run, seq, candidate, case, *, passed=1, output=None, metrics=None, detail=""):
    conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, passed, output, metrics, detail) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (run, seq, candidate, case, passed, output, json.dumps(metrics or {}), detail))


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def test_a_known_good_instrument_sets_the_floor_at_its_pass_share_quantile():
    items = [_item(0, 10, case=f"c{i}") for i in range(18)] + [_item(1, 10, case="a"), _item(3, 10, case="b")]
    got = floors.floor(items, share=0.95, min_items=10)
    assert got["floor"] == pytest.approx(0.1)
    assert got["n"] == 20 and got["strata"]["all"]["zero_share"] == 0.9


def test_a_short_stratum_with_a_worse_tail_raises_the_floor():
    long = [_item(0, 20, "18+", f"l{i}") for i in range(20)]
    short = [_item(0, 5, "1-10", f"s{i}") for i in range(9)] + [_item(1, 5, "1-10", "s9")]
    got = floors.floor(long + short, share=0.9, min_items=10)
    assert got["strata"]["18+"]["quantile"] == 0.0
    assert got["strata"]["1-10"]["quantile"] == 0.0
    got = floors.floor(long + short, share=0.95, min_items=10)
    assert got["floor"] == pytest.approx(0.2)


def test_a_stratum_under_the_minimum_pools_with_its_neighbour():
    items = ([_item(0, 10, "1-10", f"a{i}") for i in range(4)] + [_item(0, 10, "11-17", f"b{i}") for i in range(30)]
             + [_item(5, 10, "18+", "c0")])
    got = floors.floor(items, share=0.95, min_items=10)
    assert list(got["strata"]) == ["1+"] and got["n"] == 35 and got["complete"] is True
    assert got["floor"] == 0.0
    mid = floors.floor([_item(0, 10, "1-10", f"a{i}") for i in range(4)] + [_item(0, 10, "11-17", f"b{i}") for i in range(12)]
                       + [_item(0, 20, "18+", f"c{i}") for i in range(19)] + [_item(10, 20, "18+", "c19")], 0.95, 10)
    assert list(mid["strata"]) == ["1-17", "18+"] and mid["strata"]["1-17"]["n"] == 16
    assert mid["floor"] == 0.0
    inner = floors.floor([_item(0, 10, "1-10", f"a{i}") for i in range(12)] + [_item(0, 15, "11-17", f"b{i}") for i in range(3)]
                         + [_item(0, 20, "18+", f"c{i}") for i in range(20)], 0.95, 10)
    assert list(inner["strata"]) == ["1-10", "11+"] and inner["strata"]["11+"]["n"] == 23
    one = floors.floor([_item(1, 10)], share=0.95, min_items=10)
    assert one["floor"] is None and one["complete"] is False


def test_the_derived_threshold_is_the_smallest_knob_value_at_or_above_the_floor():
    assert floors.derived(0.071, (0.1, 0.2, 0.3)) == 0.1
    assert floors.derived(0.1, (0.0, 0.05, 0.1, 0.25)) == 0.1
    assert floors.derived(0.111, (0.1, 0.2, 0.3)) == 0.2
    assert floors.derived(0.0, (0.0, 0.05)) == 0.0
    assert floors.derived(0.5, (0.1, 0.2)) is None
    assert floors.derived(None, (0.1, 0.2)) is None


def test_stt_floor_reads_the_reference_ears_stored_hypotheses_rescored_with_the_current_normaliser(store):
    refs = {"u1": "MISTER SMITH WENT HOME", "u2": "THE COLOUR WAS RED", "u3": "ONE TWO THREE"}
    run = _run(store, "stt", "r1", environment={"versions": {"mlx-audio": "0.5.3"}})
    _row(store, run, 0, floors.REFERENCE["stt"], "u1", passed=0, output="Mr. Smith went home.")
    _row(store, run, 1, floors.REFERENCE["stt"], "u2", passed=0, output="the color was red")
    _row(store, run, 2, "parakeet-tdt-0.6b-v2", "u3", output="one two three")
    _row(store, run, 3, floors.REFERENCE["stt"], "gone", output="anything")
    items = floors.stt_items(store, refs)
    assert [(i["case"], i["errors"], i["units"]) for i in items] == [("u1", 0, 4), ("u2", 0, 4)]


def test_tts_floor_leaves_out_four_digit_counts_read_year_style(store):
    prompts = {"t1": "Anna counted 12 boxes, then 40 more.", "t2": "If 3789 birds flew north, where did 8269 stay?",
               "t3": "The 7 songs played, then 83 encores followed."}
    run = _run(store, "tts", "r1")
    voice = floors.REFERENCE["tts"]
    _row(store, run, 0, voice, "t1", metrics={"wer": 0.0, "wer_errors": 0, "wer_words": 7})
    _row(store, run, 1, voice, "t2", passed=0, metrics={"wer": 0.3, "wer_errors": 6, "wer_words": 20},
         detail="word error rate 0.30 over the limit of 0.2; heard 'If thirty seven eighty nine birds flew north'")
    _row(store, run, 2, voice, "t3", passed=0, metrics={"wer": 0.25, "wer_errors": 2, "wer_words": 8},
         detail="word error rate 0.25 over the limit of 0.2; heard 'The seven songs played, then eighty three encores followed.'")
    items = floors.tts_items(store, prompts)
    assert [(i["case"], i["errors"]) for i in items] == [("t1", 0), ("t3", 0)]


def test_ocr_floor_reads_only_clean_renders(store):
    cases = {"o1": {"degrade": "none"}, "o2": {"degrade": "speckle"}, "o3": {"degrade": "none"}}
    run = _run(store, "ocr", "r1", environment={"macos": "27.0.1"})
    for seq, case in enumerate(("o1", "o2", "o3")):
        _row(store, run, seq, floors.REFERENCE["ocr"], case, metrics={"cer": 0.1, "cer_errors": seq, "cer_chars": 20})
    items = floors.ocr_items(store, cases)
    assert [i["case"] for i in items] == ["o1", "o3"]
    assert floors.versions(store, "ocr", items) == {"macos": {"27.0.1": 2}}


def test_identical_inputs_rerun_with_a_different_error_count_are_counted_as_rerun_noise():
    items = [_item(0, 10, case="a", run=1), _item(0, 10, case="a", run=2),
             _item(0, 10, case="b", run=1), _item(2, 10, case="b", run=2), _item(1, 10, case="c", run=1)]
    assert floors.reruns(items) == {"repeated": 2, "differ": 1, "cases": ["b"]}
    within = [{**_item(0, 10, case="d", run=7), "rep": 0}, {**_item(3, 10, case="d", run=7), "rep": 1}]
    assert floors.reruns(within) == {"repeated": 1, "differ": 1, "cases": ["d"]}


def test_the_session_gap_lands_in_the_sparsest_band_of_observed_gaps(store):
    at = 0.0
    for _ in range(40):
        for _ in range(5):
            at += 1.0
            store.execute("INSERT INTO gateway_requests (at, client) VALUES (?, 'probe')", (at,))
        at += 300.0
    got = floors.session_gap(store, (60.0, 120.0, 300.0, 1800.0), window=1.5)
    assert got["density"][300.0] == 39 and got["density"][120.0] == 0
    assert got["derived"] == 60.0


def test_a_knob_whose_default_is_not_its_derived_value_fails_the_command(store, tmp_path, capsys):
    from harness.commands import floors as cmd
    refs = {f"u{i}": "ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN" for i in range(12)}
    run = _run(store, "stt", "r1")
    for i in range(12):
        _row(store, run, i, floors.REFERENCE["stt"], f"u{i}", output="one two three four five six seven eight nine then")
    store.commit()
    args = type("A", (), {"store": str(tmp_path / "s.db"), "action": "derive"})()
    assert cmd.cmd_floors(args, refs=refs, prompts={}, cases={}) == 1
    rows = floors.report(store, refs=refs, prompts={}, cases={})
    stt = next(r for r in rows if r["knob"] == "stt_max_wer")
    assert (stt["status"], stt["derived"]) == ("derived", 0.1) != (stt["status"], stt["current"])
    assert stt["agrees"] is False


def test_a_provisional_floor_never_fails_and_a_complete_one_above_the_range_does():
    few = floors.floor([_item(9, 10, "1-10", f"a{i}") for i in range(3)], share=0.95, min_items=10)
    assert floors.status(few, floors.derived(few["floor"], (0.0, 0.1))) == "provisional"
    assert floors.agrees(few, 0.0, 0.1) is True
    high = floors.floor([_item(9, 10, "1-10", f"a{i}") for i in range(12)], share=0.95, min_items=10)
    assert floors.status(high, floors.derived(high["floor"], (0.0, 0.1))) == "above range"
    assert floors.agrees(high, None, 0.1) is False


def test_an_empty_store_derives_nothing_and_passes(store, tmp_path):
    from harness.commands import floors as cmd
    store.commit()
    args = type("A", (), {"store": str(tmp_path / "s.db"), "action": "derive"})()
    assert cmd.cmd_floors(args, refs={}, prompts={}, cases={}) == 0
    assert all(r["derived"] is None for r in floors.report(store, refs={}, prompts={}, cases={})
               if r["knob"] != "usage_session_gap")


def test_the_tts_receipt_names_its_ear():
    from evals import run
    from harness import audio
    got = run.instruments(["tts:mlx-community/Kokoro-82M-bf16,voice=bm_george"])
    assert got["ear"] == audio.transcriber("server").label
    got = run.instruments(["tts:mlx-community/Kokoro-82M-bf16,voice=bm_george,ear=whisper:fr"])
    assert got["ear"] == audio.transcriber("whisper", language="fr").label
    assert "ear" not in run.instruments(["stt:mlx-community/parakeet-tdt-0.6b-v2"])


def test_plant_writes_clean_ocr_renders_whose_reference_reads_back_exactly(tmp_path):
    from evals.core import load_cases, score
    written = floors.plant(tmp_path, count=6)
    cases = load_cases(tmp_path)
    assert len(cases) == len(written) == 6 + len(floors.PLANT_WORD_SIZES)
    for c in cases:
        assert c.input_file.is_file()
        assert score(c, c.assertions["text"]).passed
        assert not score(c, "").passed
    import yaml
    att = [yaml.safe_load(p.read_text(encoding="utf-8"))["attribution"] for p in written]
    assert {a["degrade"] for a in att} == {"none"} and {a["style"] for a in att} == {"plain"}
    from PIL import Image

    from evals.importers import ocr_synth
    for p, a in zip(written, att):
        case = yaml.safe_load(p.read_text(encoding="utf-8"))
        fresh = ocr_synth.render(case["assert"]["text"], a["size"], "plain", a["seed"], "none")
        assert Image.open(tmp_path / case["input_file"]).tobytes() == fresh.tobytes(), case["id"]


def test_every_threshold_knob_has_a_unit_a_range_and_its_evidence():
    for name in floors.THRESHOLDS:
        k = knobs.KNOBS[name]
        assert k.unit == "share", name
        assert k.default() in k.values, name
        assert "#730" in k.note and "floor" in k.note, name
    assert knobs.KNOBS["usage_session_gap"].unit == "s"


def test_the_night_runs_measure_each_reference_twice_in_the_env_its_ear_needs(tmp_path):
    runs = floors.night(tmp_path)
    assert not any("--repeat" in r for r in runs)
    specs = [r[r.index("--candidates") + 1] for r in runs]
    assert all(specs.count(s) == 2 for s in specs) and len(set(specs)) == 5
    assert sum("backend=whisper" in s or "ear=whisper" in s for s in specs) == 4
    for r, s in zip(runs, specs):
        assert (r[0] == "env") is ("whisper" in s.split(",", 1)[-1]), r
    assert runs[-1][runs[-1].index("--cases") + 1] == str(tmp_path)


def test_a_tts_run_read_back_by_another_ear_stays_out_of_the_default_ears_floor(store):
    prompts = {"t1": "Anna counted 12 boxes, then 40 more."}
    voice = floors.REFERENCE["tts"]
    m = {"wer": 0.0, "wer_errors": 0, "wer_words": 7}
    for i, spec in enumerate(("tts:mlx-community/Kokoro-82M-bf16", "tts:mlx-community/Kokoro-82M-bf16,ear=whisper")):
        run = store.execute("INSERT INTO runs (path, lane, recorded_at, specs) VALUES (?, 'tts', 0, ?)",
                            (f"r{i}", json.dumps({voice: spec}))).lastrowid
        _row(store, run, 0, voice, "t1", metrics=m)
    named = _run(store, "tts", "r9", receipt={"instruments": {"ear": "whisper:whisper-large-v3-mlx"}})
    _row(store, named, 0, voice, "t1", metrics=m)
    assert [i["run"] for i in floors.tts_items(store, prompts)] == [1]
    assert len(floors.tts_items(store, prompts, ear=floors.run_ear("{}", json.dumps({voice: "tts:x,ear=whisper"}), voice))) == 2


def test_a_default_that_allows_the_same_errors_on_every_measured_length_agrees():
    word = floors.floor([_item(0, 4, "1-15", f"w{i}") for i in range(10)], share=0.95, min_items=10)
    assert word["units"] == [4]
    pick = floors.derived(word["floor"], (0.0, 0.05, 0.1, 0.25))
    assert pick == 0.0 and floors.agrees(word, pick, 0.1) is True
    assert floors.agrees(word, pick, 0.25) is False
    long = floors.floor([_item(0, 20, "18+", f"l{i}") for i in range(10)], share=0.95, min_items=10)
    assert floors.agrees(long, 0.0, 0.1) is False


def test_rerun_noise_names_the_inputs_whose_reruns_differ():
    items = [_item(1, 14, case="t419", run=588), _item(0, 14, case="t419", run=600),
             _item(0, 14, case="t1", run=588), _item(0, 14, case="t1", run=600)]
    assert floors.reruns(items) == {"repeated": 2, "differ": 1, "cases": ["t419"]}

"""`soh hear --worst` and `--rates`: stored speech clips, read-only (#94, #91)."""
import hashlib
import json
import struct
import wave

import pytest

from harness import cli, clips, paths, runs
from harness import memory_store as ms


def wav(path, seconds, rate=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(rate * seconds))
    return path


def case(root, lane, cid, prompt, audio=None):
    d = root / lane
    d.mkdir(parents=True, exist_ok=True)
    body = f"id: {cid}\nmodality: {lane}\nprompt: {prompt}\n"
    if audio:
        body += f"audio_file: {audio}\n"
    (d / f"{cid}.yaml").write_text(body, encoding="utf-8")


def record(conn, name, lane, rows):
    run = paths.runs() / name
    run.mkdir(parents=True, exist_ok=True)
    runs.record(conn, run, {"receipt": {"modality": lane}, "environment": ms.this_machine(),
                            "rows": rows})
    return run


@pytest.fixture
def cases(tmp_path):
    root = tmp_path / "cases"
    case(root, "stt", "u1", "the cat sat", "/corpus/u1.flac")
    case(root, "stt", "u2", "a dog ran", "/corpus/u2.flac")
    case(root, "stt", "u3", "birds sing loudly", "/corpus/u3.flac")
    case(root, "tts", "pangram", "one two three four five six seven eight nine")
    return root


@pytest.fixture
def store(cases):
    conn = ms.connect()
    try:
        stt = [{"case_id": "u1", "candidate": "a", "passed": False, "output": "the bat sat",
                "metrics": {"wer": 0.33}},
               {"case_id": "u1", "candidate": "b", "passed": False, "output": "a cat sat",
                "metrics": {"wer": 0.33}},
               {"case_id": "u2", "candidate": "a", "passed": False, "output": "fog",
                "metrics": {"wer": 1.0}},
               {"case_id": "u2", "candidate": "b", "passed": True, "output": "a dog ran",
                "metrics": {"wer": 0.0}},
               {"case_id": "u3", "candidate": "a", "passed": True, "output": "birds sing loudly",
                "metrics": {"wer": 0.0}},
               {"case_id": "u3", "candidate": "b", "passed": True, "output": "birds sing loudly",
                "metrics": {"wer": 0.0}},
               {"case_id": "u3", "candidate": "c", "passed": False,
                "output": "E5RT exception zero shape error birds sing loudly", "metrics": {"wer": 9.0}}]
        record(conn, "r-stt", "stt", stt)
        run = paths.runs() / "r-tts"
        good = wav(run / "good.wav", 3.6)
        bad = wav(run / "bad.wav", 12.0)
        record(conn, "r-tts", "tts", [
            {"case_id": "pangram", "candidate": "k", "passed": True, "artifact": str(good),
             "metrics": {"wer": 0.0}},
            {"case_id": "pangram", "candidate": "c", "passed": False, "artifact": str(bad),
             "metrics": {"wer": 0.5},
             "detail": "word error rate 0.50 over the limit of 0.15; heard 'one two three and more'"}])
    finally:
        conn.close()
    return ms.db_path()


def test_stt_worst_ranks_clips_by_mean_wer_across_candidates(store, cases):
    got = clips.worst("stt", n=10, store=store, cases_dir=cases)
    assert [c["case_id"] for c in got] == ["u2", "u1"]
    top = got[0]
    assert top["reference"] == "a dog ran"
    assert top["hypothesis"] == "fog", "the worst candidate's hearing, not the best"
    assert top["audio"] == "/corpus/u2.flac"
    assert top["mean_wer"] == pytest.approx(0.5) and top["candidates"] == 2


def test_a_clip_every_candidate_got_right_is_not_listed(store, cases):
    """u3: one candidate's broken instrument (log text in the transcript) is not
    a wrong reference. The median across candidates is what a bad reference moves."""
    assert "u3" not in [c["case_id"] for c in clips.worst("stt", n=10, store=store, cases_dir=cases)]


def test_n_limits_the_list(store, cases):
    assert len(clips.worst("stt", n=1, store=store, cases_dir=cases)) == 1


def test_tts_worst_lists_each_clip_with_what_the_ear_heard(store, cases):
    got = clips.worst("tts", n=10, store=store, cases_dir=cases)
    assert len(got) == 1
    assert got[0]["reference"].startswith("one two three")
    assert got[0]["hypothesis"] == "one two three and more"
    assert got[0]["audio"].endswith("bad.wav")


def test_the_same_audio_in_two_receipts_is_listed_once(store, cases):
    copy = paths.runs() / "legacy-copy"
    src = paths.runs() / "r-tts" / "bad.wav"
    wav(copy / "bad.wav", 12.0)
    assert (copy / "bad.wav").read_bytes() == src.read_bytes()
    (copy / "results.json").write_text(json.dumps({"rows": [
        {"case_id": "pangram", "candidate": "c", "passed": False, "artifact": "bad.wav",
         "metrics": {"wer": 0.5}}]}), encoding="utf-8")
    assert len(clips.worst("tts", n=10, store=store, cases_dir=cases)) == 1


def test_every_listed_clip_carries_a_way_to_play_it(store, cases):
    for lane in ("stt", "tts"):
        for c in clips.worst(lane, n=10, store=store, cases_dir=cases):
            assert c["play"].endswith(c["audio"].split("/")[-1])


@pytest.mark.parametrize("detail,heard", [
    ("word error rate 0.47; heard \"Le frais c'est...\"", "Le frais c'est..."),
    ("word error rate 0.44; heard 'porter ce vieux whisky'", "porter ce vieux whisky"),
    ("", ""),
    ("tts failed: HTTP 500", ""),
])
def test_heard_is_parsed_from_a_failure_detail(detail, heard):
    assert clips.heard(detail) == heard


def test_rates_split_passing_from_failing_tts_clips(store, cases):
    got = clips.rates(store=store, cases_dir=cases)
    assert got["passing"]["n"] == 1 and got["failing"]["n"] == 1
    assert got["passing"]["max"] == pytest.approx(0.4)
    assert got["failing"]["max"] == pytest.approx(12.0 / 9)


def test_a_legacy_run_not_in_the_store_is_read_from_its_receipt(store, cases):
    legacy = paths.runs() / "legacy-tts"
    wav(legacy / "slow.wav", 9.0)
    (legacy / "results.json").write_text(json.dumps({"rows": [
        {"case_id": "pangram", "candidate": "z", "passed": True,
         "artifact": ".logs/old/slow.wav", "metrics": {"wer": 0.0}}]}), encoding="utf-8")
    got = clips.rates(store=store, cases_dir=cases)
    assert got["passing"]["n"] == 2
    assert got["passing"]["max"] == pytest.approx(1.0)


def test_reading_never_writes_the_store(store, cases):
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    clips.worst("stt", n=10, store=store, cases_dir=cases)
    clips.rates(store=store, cases_dir=cases)
    assert hashlib.sha256(store.read_bytes()).hexdigest() == before


def test_the_cli_prints_the_worst_clips(store, cases, capsys):
    rc = cli.main(["hear", "--worst", "stt", "-n", "2", "--cases", str(cases),
                   "--store", str(store)])
    out = capsys.readouterr()
    assert rc == 0
    text = out.out + out.err
    assert "u2" in text and "a dog ran" in text and "fog" in text

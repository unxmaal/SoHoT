"""The stt, tts and ocr holdouts grown to what the continuous signed-rank gate needs. #2190."""
import hashlib
import json

import pytest
import yaml

from evals import importers
from evals.core import load_cases
from evals.importers import librispeech, ocr_synth, tts_synth
from harness import continuous, holdout

#: Live `soh lane-gate status`, 2026-11-28: holdout each lane needed, and the incumbent's per-draw spread it implied.
TARGET = {"stt": 295, "tts": 194, "ocr": 369}
LIVE_SD = {"stt": 0.1094, "tts": 0.133, "ocr": 0.306}
#: OS reader's spread over this import's ocr holdout, 2026-11-28 (the live figure is 0.306 on the 140 older cases).
OCR_SD_ON_NEW = 0.330
#: Room over the target for the spread of the new cases to differ from the measured one.
MARGIN = 1.1
#: The manifest before this import: its 480 test-clean lines, which must stay byte for byte.
OLD_CLEAN = 480
OLD_CLEAN_SHA256 = "ecfee6ae39af3717b23eff20947e1a74a7b928530eb897eaff85c67017fb31da"


def _holdout(lane, cases):
    return len(holdout.assign(lane, cases).holdout)


def _stt_cases(tmp_path):
    entries = librispeech.manifest()
    cache = tmp_path / "cache"
    cache.mkdir()
    for e in entries:
        (cache / f"{e['uid']}.flac").write_bytes(b"x")
    importers.run("librispeech", root=tmp_path / "cases", rows=librispeech.rows(entries, cache))
    return load_cases(tmp_path / "cases" / "stt")


def test_each_lane_holds_out_its_target_with_room_to_spare(tmp_path):
    got = {"stt": _holdout("stt", _stt_cases(tmp_path)),
           "tts": _holdout("tts", load_cases(importers.CASES / "tts")),
           "ocr": _holdout("ocr", load_cases(importers.CASES / "ocr"))}
    for lane, n in got.items():
        assert n >= TARGET[lane] * MARGIN, (lane, n)


@pytest.mark.parametrize("lane,sd", [("stt", LIVE_SD["stt"] * 1.15), ("tts", LIVE_SD["tts"] * 1.1),
                                     ("ocr", OCR_SD_ON_NEW)])
def test_the_continuous_model_reaches_power_point_eight_at_that_holdout(lane, sd, tmp_path):
    cases = (_stt_cases(tmp_path) if lane == "stt" else load_cases(importers.CASES / lane))
    n = _holdout(lane, cases)
    power = continuous.Model(continuous.metric_of(lane), sd).power_cells(n, continuous.effect_for(lane), 0.05)
    assert power >= 0.8, (lane, n, power)


def test_the_stt_manifest_adds_test_other_and_keeps_every_test_clean_line_as_it_was():
    entries = librispeech.manifest()
    clean = [e for e in entries if librispeech.config_of(e) == "clean"]
    other = [e for e in entries if librispeech.config_of(e) == "other"]
    assert len(clean) == librispeech.N and len(other) == librispeech.N_OTHER
    assert len({e["uid"] for e in entries}) == len(entries)
    assert all("config" not in e for e in clean) and {e["config"] for e in other} == {"other"}
    lines = "".join(json.dumps(e, sort_keys=True) + "\n" for e in clean[:OLD_CLEAN])
    assert hashlib.sha256(lines.encode()).hexdigest() == OLD_CLEAN_SHA256


def test_a_test_other_clip_is_read_from_its_own_config_and_says_so(tmp_path, monkeypatch):
    seen = []

    def page(offset, length, config="clean"):
        seen.append((config, offset))
        if offset:
            return []
        return [{"row_idx": i, "row": {"id": f"{config}-1-{i:04d}", "text": "one two three four",
                                       "audio": [{"src": f"https://x/{librispeech.REVISION}/{config}/{i}.flac"}]}}
                for i in range(3)]

    class Reply:
        content = b"flac"

        def raise_for_status(self):
            return self
    monkeypatch.setattr(librispeech, "_page", page)
    monkeypatch.setattr(librispeech, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr("httpx.get", lambda url, timeout=None: Reply())
    got = librispeech.build_manifest(tmp_path / "cache", n=2, n_other=2)
    assert {c for c, _ in seen} == {"clean", "other"}
    assert [librispeech.config_of(e) for e in got].count("other") == 2
    row = librispeech.rows(got, tmp_path)[-1]
    att = librispeech.convert(row).case["attribution"]
    assert att["item"].startswith("test.other row")
    getter_pages = []
    monkeypatch.setattr(librispeech, "_page", lambda o, n, c="clean": getter_pages.append(c) or [])
    with pytest.raises(ValueError, match="no row"):
        librispeech.audio_getter("other")(7)
    assert getter_pages == ["other"]


def test_new_cases_do_not_let_a_planted_wrong_output_pass_and_the_incumbent_still_misses():
    for mod, lane in ((tts_synth, "tts"), (ocr_synth, "ocr")):
        cases = load_cases(importers.CASES / lane / f"{lane}_synth")
        got = importers.negative_control(cases, mod.RESPONDERS, mod.passes)
        assert all(passed == 0 for name, (passed, _) in got.items() if name != "reference"), (lane, got)
        assert got["reference"][0] == len(cases) == mod.COUNT


@pytest.mark.usefixtures("real_ocr")
def test_the_os_reader_is_not_at_zero_error_on_the_new_ocr_cases():
    from evals.core import score
    from harness.checks import ocr
    if ocr.available_backend() is None:
        pytest.skip("no OCR backend on this machine")
    new = [c for c in load_cases(importers.CASES / "ocr" / "ocr_synth")
           if int(c.id[-4:]) >= 440 and yaml.safe_load(c.source.read_text(encoding="utf-8"))["attribution"]["degrade"] != "none"][::25]
    cers = [score(c, "\n".join(ocr.read(c.input_file))).metrics["cer"] for c in new]
    assert len(new) >= 20 and any(x > 0 for x in cers) and any(x == 0 for x in cers)


def test_importing_the_grown_generators_twice_gives_identical_old_items(tmp_path):
    for mod, lane in ((tts_synth, "tts"), (ocr_synth, "ocr")):
        small = {r["item"]: r for r in mod.fetch(count=40)}
        big = {r["item"]: r for r in mod.fetch(count=mod.COUNT)}
        assert all(big[i] == small[i] for i in small), lane


def test_fetch_downloads_each_config_through_that_configs_getter(tmp_path, monkeypatch):
    blobs = {"clean": b"fLaC-clean", "other": b"fLaC-other"}
    entries = [{"uid": f"1-1-000{i}", "row": i, "text": "ONE TWO THREE", "config": c,
                "sha256": hashlib.sha256(blobs[c]).hexdigest(), "bytes": 10}
               for i, c in enumerate(("other", "clean"))]
    entries[1].pop("config")
    monkeypatch.setenv("LIBRISPEECH_CACHE", str(tmp_path))
    monkeypatch.setattr(librispeech, "manifest", lambda: entries)
    monkeypatch.setattr(librispeech, "audio_getter", lambda config="clean": lambda row: blobs[config])
    got = librispeech.fetch()
    assert [p.read_bytes() for p in (tmp_path / f"{e['uid']}.flac" for e in entries)] == [blobs["other"], blobs["clean"]]
    assert len(got) == 2

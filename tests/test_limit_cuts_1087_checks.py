"""The reply checks' and the scripts' limits record a limit_cuts row when they bind, and only then (#1087)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from harness import cuts, limit_trace

REPO = Path(__file__).resolve().parents[1]


def _spooled(home: Path | None = None) -> list[tuple]:
    path = home / cuts.SPOOL if home is not None else cuts._spool_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [(r["knob"], r["kept"], r["dropped"]) for r in map(json.loads, lines)]


def _knobs(home: Path | None = None) -> list[str]:
    return [k for k, _, _ in _spooled(home)]


class _Tokenizer:
    def __init__(self, n):
        self.n = n

    def __call__(self, prompt):
        return {"input_ids": list(range(self.n))}


class _Processor:
    def __init__(self, n):
        self.tokenizer = _Tokenizer(n)


def test_a_prompt_past_clips_text_window_is_a_cut_of_its_tail():
    from harness.checks import adherence
    site = "harness/checks/adherence.py:_score_pickscore->processor(max_length)"
    adherence._truncated(_Processor(40), "short", 40)
    assert _spooled() == []
    adherence._truncated(_Processor(100), "long", 77)
    assert _spooled() == [(site, 77, 23)]


def _decide_rows(candidate, n):
    from evals.core import Result
    return [Result("c", candidate, True, 0.0, 0, "", metrics={"decisions": [[0.9, 1]] * n})]


def test_a_candidate_with_too_few_decisions_for_an_ece_is_a_cut_once_per_run():
    from evals import core
    from harness.checks import decide
    core.ece_withheld(_decide_rows("full", decide.MIN_ECE_N) + _decide_rows("none", 0))
    core.summarize(_decide_rows("few", 3))
    assert _spooled() == []
    core.ece_withheld(_decide_rows("few", 3))
    assert _spooled() == [("harness/checks/decide.py:MIN_ECE_N", 0, 3)]


def _png(path: Path, noisy: bool) -> Path:
    from PIL import Image
    im = Image.new("RGB", (64, 64), (128, 128, 128))
    if noisy:
        im.putdata([((i * 37) % 256, (i * 11) % 256, (i * 5) % 256) for i in range(64 * 64)])
    im.save(path)
    return path


def test_a_blank_image_is_a_cut_of_the_stddev_floor_and_a_drawn_one_is_not(tmp_path):
    from PIL import Image
    from harness.checks import image
    assert image.check(_png(tmp_path / "drawn.png", True)).ok
    with Image.open(_png(tmp_path / "drawn2.png", True)) as im:
        assert not image.blank(im)
    assert _spooled() == []
    assert not image.check(_png(tmp_path / "blank.png", False)).ok
    with Image.open(tmp_path / "blank.png") as im:
        assert image.blank(im)
    assert _knobs() == ["harness/checks/image.py:MIN_STDDEV"] * 2


def _audio(tmp_path, size):
    path = tmp_path / f"a{size}.wav"
    path.write_bytes(b"\0" * size)
    return path


def test_audio_too_small_to_hold_speech_or_music_is_a_cut_of_the_byte_floor(tmp_path):
    from harness.checks import music, speech
    big = _audio(tmp_path, speech.MIN_AUDIO_BYTES)
    assert speech.check(big, "hello", transcriber=lambda p: "hello").ok
    assert _spooled() == []
    small = _audio(tmp_path, speech.MIN_AUDIO_BYTES - 1)
    assert not speech.check(small, "hello", transcriber=lambda p: "hello").ok
    assert not music.check(small, "hello", transcriber=lambda p: "hello").ok
    assert _knobs() == ["harness/checks/speech.py:MIN_AUDIO_BYTES"] * 2


def test_an_instrumental_that_sings_and_a_track_off_its_length_are_cuts(tmp_path, monkeypatch):
    from harness import audio
    from harness.checks import music
    track = _audio(tmp_path, 10 * music.MIN_AUDIO_BYTES)
    monkeypatch.setattr(audio, "audio_seconds", lambda p: 30.0)
    words = " ".join(["la"] * music.INSTRUMENTAL_WORDS_MAX)
    assert music.check(track, "", expect_vocals=False, duration_s=30.0, transcriber=lambda p: words).ok
    assert _spooled() == []
    sung = words + " la"
    assert not music.check(track, "", expect_vocals=False, transcriber=lambda p: sung).ok
    assert not music.check(track, "", expect_vocals=False, duration_s=20.0, transcriber=lambda p: "").ok
    assert _knobs() == ["harness/checks/music.py:INSTRUMENTAL_WORDS_MAX", "harness/checks/music.py:DURATION_TOLERANCE"]


def test_a_pii_reply_under_the_f1_mark_is_a_cut_and_a_clean_empty_one_is_not():
    from harness.checks import pii
    text = "Call Ann Lee at home today"
    gold = [(5, 12)]
    assert pii.check(json.dumps({"spans": [[5, 12]]}), text, gold).ok
    assert pii.check(json.dumps({"spans": []}), "nothing here", []).ok
    assert not pii.check(json.dumps({"spans": [[0, 4]]}), "nothing here", []).ok
    assert _spooled() == []
    assert not pii.check(json.dumps({"spans": [[0, 4]]}), text, gold).ok
    assert _knobs() == ["harness/checks/pii.py:PASS_F1"]


def test_an_ocr_retry_past_its_timeout_is_a_cut(monkeypatch, tmp_path):
    from harness.checks import ocr

    def ok(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, '["hi"]', "")

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(ocr.subprocess, "run", ok)
    assert ocr._fresh_read("vision", tmp_path / "x.png") == ["hi"]
    assert _spooled() == []
    monkeypatch.setattr(ocr.subprocess, "run", slow)
    with pytest.raises(ocr.OcrTransient):
        ocr._fresh_read("vision", tmp_path / "x.png")
    assert _spooled() == [("harness/checks/ocr.py:_fresh_read->subprocess.run(timeout)", 0, 1)]


def test_a_blank_render_is_a_cut_of_the_ink_floor_it_was_held_to(monkeypatch):
    from harness.checks import render
    monkeypatch.setattr(render, "chrome_path", lambda: "/bin/chrome")
    monkeypatch.setattr(render, "_first_available", lambda names: "/bin/rsvg")
    monkeypatch.setattr(render, "ink_html", lambda html: 0.01)
    monkeypatch.setattr(render, "ink", lambda svg: 0.01)
    assert render.check_html("<p>x</p>").ok and render.check("<svg/>").ok
    assert _spooled() == []
    monkeypatch.setattr(render, "ink_html", lambda html: 0.0)
    monkeypatch.setattr(render, "ink", lambda svg: 0.0)
    assert not render.check_html("<p></p>").ok and not render.check("<svg/>").ok
    assert _knobs() == ["harness/checks/render.py:check_html(min_ink)", "harness/checks/render.py:MIN_INK"]


def test_a_profile_still_held_after_every_attempt_is_a_cut(monkeypatch, tmp_path):
    from harness.checks import render
    real = shutil.rmtree
    calls = []

    def held(path, ignore_errors=False):
        calls.append(ignore_errors)
        if ignore_errors:
            return real(path, ignore_errors=True)
        if len(calls) < 2:
            raise OSError("in use")
        return real(path)

    monkeypatch.setattr(render.shutil, "rmtree", held)
    (tmp_path / "a").mkdir()
    render._remove_tree(tmp_path / "a", attempts=3, delay=0)
    assert _spooled() == []
    calls.clear()
    monkeypatch.setattr(render.shutil, "rmtree", lambda path, ignore_errors=False: (
        calls.append(ignore_errors), None if ignore_errors else (_ for _ in ()).throw(OSError("in use"))))
    render._remove_tree(tmp_path / "b", attempts=3, delay=0)
    assert calls == [False, False, False, True]
    assert _spooled() == [("harness/checks/render.py:_remove_tree(attempts)", None, None)]


def test_a_taskkill_past_its_timeout_is_a_cut(monkeypatch):
    from harness.checks import render

    class Proc:
        pid = 1

    monkeypatch.setattr(render.sys, "platform", "win32")
    monkeypatch.setattr(render.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0))
    render._kill_tree(Proc())
    assert _spooled() == []

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(render.subprocess, "run", slow)
    render._kill_tree(Proc())
    assert _knobs() == ["harness/checks/render.py:_kill_tree->subprocess.run(timeout)"]


def test_a_screenshot_still_growing_at_the_deadline_is_a_cut_of_the_timeout_it_was_given(tmp_path, fake_chrome):
    from harness.checks import render
    done = tmp_path / "done.png"
    render._shoot(fake_chrome.argv(done), done, str(tmp_path), timeout=10, timeout_knob="chrome_render_timeout")
    assert done.exists() and fake_chrome.now < 10 and _spooled() == []
    missing, started = tmp_path / "missing.png", fake_chrome.now
    render._shoot(fake_chrome.argv(missing, writes=False), missing, str(tmp_path), timeout=1)
    assert not missing.exists() and fake_chrome.now - started >= 1 and _spooled() == []
    growing = tmp_path / "growing.png"
    render._shoot(fake_chrome.argv(growing, grows=True), growing, str(tmp_path), timeout=1)
    assert _knobs() == ["harness/checks/render.py:_shoot(timeout)"]


NS = 'xmlns="http://www.w3.org/2000/svg"'


def _doc(body: str) -> str:
    return f'<svg {NS} viewBox="0 0 100 100">{body}</svg>'


def test_an_svg_miss_a_wider_tolerance_could_pass_is_a_cut_of_that_tolerance():
    from harness.checks import svg
    minute = '<line x1="50" y1="50" x2="50" y2="85" stroke="#000001"/>'
    want = {"cx": 50, "cy": 50, "hour": 90, "minute": 180}
    assert svg.structure(_doc(minute + '<line x1="50" y1="50" x2="70" y2="50" stroke="#000001"/>'),
                         {"hands": want}) == ""
    assert "expected 2 hands" in svg.structure(_doc(minute), {"hands": want})
    assert _spooled() == []
    assert "spills" in svg.structure(_doc('<circle cx="98" cy="50" r="5"/>'), {"inside": True})
    assert "hour hand" in svg.structure(_doc(minute + '<line x1="50" y1="50" x2="70" y2="60" stroke="#000001"/>'),
                                        {"hands": want})
    assert _knobs() == ["svg_coord_tolerance", "svg_angle_tolerance"]


def test_a_video_off_its_frame_count_or_too_still_is_a_cut(monkeypatch, tmp_path):
    from PIL import Image
    from harness.checks import video
    monkeypatch.setattr(video, "probe", lambda p: video.VideoInfo(64, 64, 25, 1.0))
    noisy = Image.new("L", (8, 8))
    noisy.putdata([(i * 37) % 256 for i in range(64)])
    monkeypatch.setattr(video, "_sample", lambda p: [noisy, noisy])
    monkeypatch.setattr(video, "motion", lambda p: 0.5)
    assert video.check(tmp_path / "v.mp4", frames=25 + video.FRAME_TOLERANCE).ok
    assert _spooled() == []
    assert not video.check(tmp_path / "v.mp4", frames=25 + video.FRAME_TOLERANCE + 1).ok
    monkeypatch.setattr(video, "motion", lambda p: 0.0)
    assert not video.check(tmp_path / "v.mp4").ok
    assert _knobs() == ["harness/checks/video.py:FRAME_TOLERANCE", "harness/checks/video.py:MIN_MOTION"]


def test_an_ffprobe_or_ffmpeg_past_its_timeout_is_a_cut_and_still_raised(monkeypatch, tmp_path):
    from harness.checks import video
    clip = tmp_path / "v.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr(video.shutil, "which", lambda name: "/bin/" + name)

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(video.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "bad"))
    with pytest.raises(video.VideoError):
        video.probe(clip)
    with pytest.raises(video.VideoError):
        video._sample(clip)
    assert _spooled() == []
    monkeypatch.setattr(video.subprocess, "run", slow)
    with pytest.raises(subprocess.TimeoutExpired):
        video.probe(clip)
    with pytest.raises(subprocess.TimeoutExpired):
        video._sample(clip)
    assert _knobs() == ["harness/checks/video.py:probe->subprocess.run(timeout)",
                        "harness/checks/video.py:_sample->subprocess.run(timeout)"]


def test_the_cuts_cli_records_what_a_script_hands_it():
    assert cuts.main(["scripts/slots-sweep.sh:SWEEP_BUDGET_S", "configs", "--dropped", "2"]) == 0
    assert _spooled() == [("scripts/slots-sweep.sh:SWEEP_BUDGET_S", None, 2)]


def test_the_scanner_reads_a_scripts_literal_cut_and_flags_one_it_cannot_read(monkeypatch):
    text = ('x=1\n  uv run python -m harness.cuts scripts/a.sh:LIMIT "what" || true\n'
            'python -m harness.cuts "$name" what\n')
    assert limit_trace.shell_cuts_in(text, "scripts/a.sh") == [
        ("scripts/a.sh:LIMIT", "scripts/a.sh:2"), ("$name", "scripts/a.sh:3")]
    with monkeypatch.context() as m:
        m.setattr(limit_trace, "_modules", lambda root: [])
        m.setattr(limit_trace, "_scripts", lambda root: [("scripts/a.sh", text)])
        assert limit_trace.named() == {"scripts/a.sh:LIMIT": ["scripts/a.sh:2"]}
        assert limit_trace.unnamed() == ["scripts/a.sh:3"]
    named = limit_trace.named()
    for site in ("scripts/env.sh:HF_MIN_FREE_GB", "scripts/slots-sweep.sh:SWEEP_BUDGET_S", "scripts/smoke.sh:READY_TIMEOUT"):
        assert site in named


def _bash():
    from tests.shells import BASH
    if not BASH or not shutil.which("uv"):
        pytest.skip("needs bash and uv")
    return BASH


def _env(home: Path, **extra) -> dict:
    env = {**os.environ, "LOCALHARNESS_HOME": str(home), **extra}
    env.pop("HF_HOME", None)
    return env


def test_a_weights_root_refused_for_free_space_is_a_cut_of_the_floor(tmp_path):
    bash = _bash()
    root = tmp_path / "hf"
    root.mkdir()
    ok = subprocess.run([bash, "-c", "source scripts/env.sh"], cwd=REPO, capture_output=True, text=True,
                        encoding="utf-8", timeout=120, env=_env(tmp_path, HF_ROOT=str(root), HF_MIN_FREE_GB="0"))
    assert ok.returncode == 0, ok.stderr
    assert _spooled(tmp_path) == []
    refused = subprocess.run([bash, "-c", "source scripts/env.sh"], cwd=REPO, capture_output=True, text=True,
                             encoding="utf-8", timeout=120,
                             env=_env(tmp_path, HF_ROOT=str(root), HF_MIN_FREE_GB="999999999"))
    assert refused.returncode != 0 and "FATAL" in refused.stderr
    assert _knobs(tmp_path) == ["scripts/env.sh:HF_MIN_FREE_GB"]


def _sweep(bash, tmp_path, configs: str, budget: str):
    root = tmp_path / "hf"
    root.mkdir(exist_ok=True)
    return subprocess.run([bash, "scripts/slots-sweep.sh", "stem", "4096", configs], cwd=REPO, capture_output=True,
                          text=True, encoding="utf-8", timeout=120,
                          env=_env(tmp_path, HF_ROOT=str(root), HF_MIN_FREE_GB="0", SWEEP_BUDGET_S=budget,
                                   SWEEP_OUT=str(tmp_path / "out")))


def test_slot_configs_past_the_sweep_budget_are_one_cut_of_the_budget(tmp_path):
    bash = _bash()
    none = _sweep(bash, tmp_path, "", "2100")
    assert none.returncode == 0, none.stderr
    assert _spooled(tmp_path) == []
    late = _sweep(bash, tmp_path, "1:1:unified:1 2:2:unified:2", "-1")
    assert late.returncode == 0 and late.stdout.count("skipped: past the") == 2, late.stdout + late.stderr
    assert _spooled(tmp_path) == [("scripts/slots-sweep.sh:SWEEP_BUDGET_S", None, 2)]


def test_a_gateway_never_ready_within_the_smoke_timeout_is_a_cut(tmp_path):
    from tests.test_gateway_key import _smoke
    _bash()
    r = _smoke({"SOHOT_GATEWAY_KEY": "sk-right", "GATEWAY_PORT": "9", "READY_TIMEOUT": "1"}, tmp_path)
    assert r.returncode != 0 and "gateway not serving" in r.stdout
    assert _knobs(tmp_path) == ["scripts/smoke.sh:READY_TIMEOUT"]

"""Real-Vision OCR tests retry a transient a bounded number of times, never a real failure. #600."""

import pytest

from tests.ocr_retry import retrying
from harness.checks.ocr import OcrTransient


def test_a_transient_twice_then_success_passes():
    calls = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) < 3:
            raise OcrTransient("e5rtError")
        return ["OPEN"]

    assert retrying(fake, attempts=3)("a.png") == ["OPEN"]
    assert len(calls) == 3


def test_a_transient_every_time_fails_after_the_bound_naming_the_class():
    calls = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        raise OcrTransient("e5rtError")

    with pytest.raises(pytest.fail.Exception, match="OcrTransient"):
        retrying(fake, attempts=3)("a.png")
    assert len(calls) == 3


def test_a_non_transient_error_fails_at_once():
    calls = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("Vision failed: other")

    with pytest.raises(RuntimeError, match="other"):
        retrying(fake, attempts=3)("a.png")
    assert len(calls) == 1


def test_the_real_ocr_fixture_scores_a_render_through_a_transient(tmp_path, monkeypatch, real_ocr):
    from harness.checks import ocr
    from tests.test_harness_checks_ocr import E5RT, _fake_vision, _noise
    calls = _fake_vision(monkeypatch, [OcrTransient(E5RT), OcrTransient(E5RT), ["OPEN"]])
    r = ocr.check(_noise(tmp_path / "a.png"), expect="OPEN")
    assert r.ok and r.cer == 0.0
    assert calls == ["in-process", "fresh", "in-process"]

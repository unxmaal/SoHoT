"""Bounded retry of Apple Vision's transient for tests that use the real OCR. #600."""

import functools

import pytest

from harness.checks.ocr import OcrTransient

ATTEMPTS = 3


def retrying(read, attempts=ATTEMPTS):
    @functools.wraps(read)
    def wrapped(*args, **kwargs):
        for _ in range(attempts):
            try:
                return read(*args, **kwargs)
            except OcrTransient as exc:
                last = exc
        # pytest.fail is a BaseException, so ocr.check cannot turn it into a scored row.
        pytest.fail(f"OcrTransient on all {attempts} attempts, the machine's Vision is busy: {last}")
    return wrapped

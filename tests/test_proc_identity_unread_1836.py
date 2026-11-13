"""An unreadable start time is "cannot say", never "a different process". #1836."""
import os
import sys

import pytest

from harness import exclusive, proc_identity



def _me():
    return proc_identity.identity(os.getpid())


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/proc_identity.py:_proc:except")
def test_a_live_process_whose_start_time_cannot_be_read_is_not_called_a_different_one(monkeypatch):
    rec = _me()
    monkeypatch.setattr(proc_identity, "_proc", lambda pid: None)
    assert proc_identity.same(rec) is None


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")
@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/proc_identity.py:same:except")
def test_a_group_lookup_that_fails_for_another_reason_cannot_say(monkeypatch):
    def denied(pid):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(os, "getpgid", denied)
    assert proc_identity.same(_me()) is None


def test_a_live_holder_with_an_unreadable_start_time_keeps_its_gpu_lease(monkeypatch):
    rec = dict(_me(), job_id=None)
    monkeypatch.setattr(proc_identity, "_proc", lambda pid: None)
    assert exclusive._holder_alive(rec)


def test_a_holder_that_is_gone_is_still_dead():
    import subprocess
    p =subprocess.Popen([sys.executable, "-c", "pass"])
    rec = dict(proc_identity.identity(p.pid), job_id=None)
    p.wait()
    assert proc_identity.same(rec) is False
    assert not exclusive._holder_alive(rec)

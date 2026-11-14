"""A pending gpu job that waited on memory past memory_wait_named is named in soh morning and soh jobs list with what it needs, what is admissible now and what holds the rest. #1993."""
import time

import pytest

from harness import admission, cli, containers, cuts, interactive, memory, memory_wait, morning, pressure
from harness import memory_store as ms
from harness import workqueue as wq
from tests.test_morning_867 import _beat, _gh, _git

HUGE = ["uv", "run", "python", "-m", "evals.run", "--modality", "music", "--candidates", "llamacpp:Huge-46B"]
BIG = ["uv", "run", "python", "-m", "evals.run", "--modality", "code", "--candidates", "llamacpp:Big-30B"]
SMALL = ["uv", "run", "python", "-m", "evals.run", "--modality", "code", "--candidates", "llamacpp:Small-4B"]
SIZES = {"llamacpp:Huge-46B": 46.0, "llamacpp:Big-30B": 30.0, "llamacpp:Small-4B": 4.0}
GIB = 1024 ** 3
PINS = {"code": {"stem": "Ornith-1.5-35B-Q4_K_M", "bytes": int(21.2 * GIB)},
        "decide": {"stem": "imajev-4b-Q8_0", "bytes": int(4.9 * GIB)},
        "extract": {"stem": "Qwen2.5-7B-Instruct-Q4_K_M", "bytes": int(6.6 * GIB)},
        "web": {"stem": "Qwen2.5-7B-Instruct-Q4_K_M", "bytes": int(6.6 * GIB)}}


@pytest.fixture
def machine(monkeypatch):
    """The live Studio's admission numbers when job 1624 waited, set below."""
    monkeypatch.setattr(admission, "admit", admission.admit.real)
    monkeypatch.setattr(memory, "available_gb", lambda: 40.0)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 77.8)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda conn=None: 18.0)
    monkeypatch.setattr(memory, "pinned_gb", lambda: 32.8)
    monkeypatch.setattr(containers, "vm_gb", lambda *a, **k: 3.8)
    monkeypatch.setattr(interactive, "reserved_bytes", lambda: int(32.8 * GIB))
    monkeypatch.setattr(interactive, "pinned", lambda: dict(PINS))
    monkeypatch.setattr(pressure, "sample", lambda: pressure.Pressure(level=pressure.NORMAL))
    monkeypatch.setattr(admission, "spec_gb", lambda spec: SIZES.get(spec))
    monkeypatch.setattr(admission, "_resident", lambda: [])


def plant(argv, title, hours, now=None):
    """A pending job added `hours` before now."""
    conn = ms.connect()
    job = wq.add(argv, title=title, conn=conn)
    conn.execute("UPDATE jobs SET created_at = ? WHERE id = ?", ((now or time.time()) - hours * 3600.0, wq._key(job["id"])))
    conn.commit()
    conn.close()
    return job


def test_a_job_past_the_knob_is_named_with_its_need_room_and_holders(machine):
    now = float(int(time.time()))
    old = plant(HUGE, "reverify music", 94, now=now)
    plant(BIG, "young eval", 1, now=now)
    plant(SMALL, "fits now", 30, now=now)
    conn = ms.connect()
    got = memory_wait.waiting(conn, now)
    assert [w["id"] for w in got] == [old["id"]]
    w = got[0]
    assert w["need_gb"] == 46.0 and w["admissible_gb"] == 22.0 and w["waited_s"] == 94 * 3600
    assert w["line"] == (f"job {old['id']} (reverify music) has waited 94 h and memory does not admit it: needs 46.0 GiB "
                         "(llamacpp:Huge-46B 46.0); 22.0 GiB is admissible now (40.0 GiB free); of the 77.8 GiB "
                         "ceiling the rest is held by a 18.0 GiB reserve, 32.8 GiB pinned models (Ornith-1.5-35B-Q4_K_M "
                         "21.2, Qwen2.5-7B-Instruct-Q4_K_M 6.6, imajev-4b-Q8_0 4.9), 3.8 GiB Docker VM")
    assert wq.jobs(conn)[0]["state"] == wq.PENDING


def test_the_knob_decides_which_waits_are_long(machine, monkeypatch):
    now = float(int(time.time()))
    plant(HUGE, "reverify music", 5, now=now)
    conn = ms.connect()
    assert memory_wait.waiting(conn, now) == []
    monkeypatch.setattr(memory_wait, "LONG_S", 4 * 3600.0)
    assert len(memory_wait.waiting(conn, now)) == 1
    monkeypatch.setattr(memory_wait, "LONG_S", 6 * 3600.0)
    assert memory_wait.waiting(conn, now + 3600.0) != []


def test_the_wait_counts_from_its_last_requeue_or_start_time(machine):
    now = float(int(time.time()))
    job = plant(HUGE, "requeued", 94, now=now)
    conn = ms.connect()
    conn.execute("UPDATE jobs SET started_at = ? WHERE id = ?", (now - 2 * 3600.0, wq._key(job["id"])))
    conn.commit()
    assert memory_wait.waiting(conn, now) == []
    conn.execute("UPDATE jobs SET started_at = NULL, not_before = ? WHERE id = ?", (now - 10 * 3600.0, wq._key(job["id"])))
    conn.commit()
    assert [w["waited_s"] for w in memory_wait.waiting(conn, now)] == [10 * 3600]


def test_the_morning_brief_names_the_long_wait_only(machine, tmp_path):
    now = float(int(time.time()))
    old = plant(HUGE, "reverify music", 94, now=now)
    young = plant(BIG, "young eval", 1, now=now)
    later = plant(BIG, "later eval", 1, now=now)
    conn = ms.connect()
    conn.execute("UPDATE jobs SET not_before = ? WHERE id = ?", (now + 3600.0, wq._key(later["id"])))
    conn.commit()
    r = morning.gather(conn, now, now - 12 * 3600.0, beat=_beat(), gh=_gh(), git=_git(), where=tmp_path / "none",
                       lanes=lambda c: [])
    named = [x for x in r["needs"] if "memory does not admit it" in x]
    assert len(named) == 1 and named[0].startswith(f"job {old['id']} (reverify music) has waited 94 h and memory does not admit it")
    assert "22.0 GiB is admissible now" in named[0] and "3.8 GiB Docker VM" in named[0]
    assert not any(young["id"] in x for x in r["needs"])
    assert [w["id"] for w in r["memory_waits"]] == [old["id"]]
    cuts.flush(conn)
    cut = conn.execute("SELECT value, dropped, what FROM limit_cuts WHERE knob = 'memory_wait_named'").fetchall()
    assert [(c[0], c[1]) for c in cut] == [(memory_wait.LONG_S, 1)] and young["id"] in cut[0][2]


def test_soh_jobs_list_names_the_long_wait_only(machine, capsys):
    old = plant(HUGE, "reverify music", 94)
    young = plant(BIG, "young eval", 1)
    assert cli.main(["jobs", "list"]) == 0
    out = capsys.readouterr()
    text = out.out + out.err
    named = [x.strip() for x in text.splitlines() if "memory does not admit it" in x]
    assert len(named) == 1 and named[0].startswith(f"job {old['id']} (reverify music) has waited 94 h and memory does not admit it")
    assert "needs 46.0 GiB" in named[0] and "32.8 GiB pinned models (Ornith-1.5-35B-Q4_K_M 21.2" in named[0]
    assert f"job {young['id']}" not in text


def test_a_pinned_set_served_elsewhere_names_no_models_here(machine, monkeypatch):
    now = float(int(time.time()))
    plant(HUGE, "reverify music", 94, now=now)
    monkeypatch.setattr(interactive, "reserved_bytes", lambda: 0)
    monkeypatch.setattr(memory, "pinned_gb", lambda: 0.0)
    (w,) = memory_wait.waiting(ms.connect(), now)
    assert w["pinned"] == [] and ", 0.0 GiB pinned models, 3.8 GiB Docker VM" in w["line"]


def test_a_small_job_held_by_pressure_names_the_pressure(machine, monkeypatch):
    now = float(int(time.time()))
    small = plant(SMALL, "small eval", 30, now=now)
    conn = ms.connect()
    assert memory_wait.waiting(conn, now) == []
    monkeypatch.setattr(pressure, "sample", lambda: pressure.Pressure(level=pressure.WARN))
    (w,) = memory_wait.waiting(conn, now)
    assert w["id"] == small["id"] and w["line"].endswith("3.8 GiB Docker VM; memory pressure level 2, not normal")


def test_a_report_that_cannot_price_says_so(machine, monkeypatch, tmp_path):
    now = float(int(time.time()))
    plant(HUGE, "reverify music", 94, now=now)

    def down(job, resident=None):
        raise RuntimeError("router down")
    monkeypatch.setattr(admission, "need", down)
    lines = [w["line"] for w in morning.memory_waits(ms.connect(), now)]
    assert lines == ["jobs waiting on memory not read: RuntimeError: router down"]

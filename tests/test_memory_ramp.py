"""How far memory can be pushed before macOS pushes back. #299."""

import pytest

from harness import cli, ramp
from harness.pressure import Pressure, NORMAL, WARN


class Box:
    """A fake machine whose pressure turns once enough is allocated."""

    def __init__(self, warn_at=None, swap_at=None, fail_at=None, free=80):
        self.held, self.released = 0.0, False
        self.warn_at, self.swap_at, self.fail_at, self.free = (
            warn_at, swap_at, fail_at, free)

    def allocate(self, gb):
        if self.fail_at is not None and self.held + gb > self.fail_at:
            raise RuntimeError("[metal] out of memory")
        self.held += gb

    def release(self):
        self.released, self.held = True, 0.0

    def sample(self):
        level = WARN if self.warn_at and self.held >= self.warn_at else NORMAL
        swaps = 5 if self.swap_at and self.held >= self.swap_at else 0
        return Pressure(free_pct=int(self.free - self.held * 2), level=level,
                        swapouts=swaps, wired_gb=self.held)


def run(box, **kw):
    kw.setdefault("cap_gb", 30)
    return ramp.run(step_gb=1, settle_s=0, allocate=box.allocate,
                    release=box.release, sample=box.sample,
                    sleep=lambda s: None, available=lambda: 20.0, **kw)


def test_it_stops_at_the_first_warning_and_gives_the_memory_back():
    box = Box(warn_at=9)
    got = run(box)
    assert got["stopped"] == "pressure warn"
    assert got["warn_at_gb"] == 9
    assert got["last_normal_gb"] == 8
    assert box.released and box.held == 0


def test_a_machine_that_never_complains_stops_at_the_cap():
    """Negative control: no signal turns, so the cap is what ends it."""
    box = Box()
    got = run(box, cap_gb=5)
    assert got["stopped"] == "cap"
    assert got["warn_at_gb"] is None and got["last_normal_gb"] == 5
    assert box.released


def test_compressor_swapping_out_is_a_stop_even_at_normal_pressure():
    got = run(Box(swap_at=6))
    assert got["stopped"] == "compressor swapping"
    assert got["warn_at_gb"] == 6


def test_the_free_floor_stops_it_before_the_kernel_warns():
    got = run(Box(), floor_pct=40)
    assert got["stopped"] == "free below floor"


def test_an_allocation_the_gpu_refuses_ends_the_ramp_and_still_releases():
    box = Box(fail_at=12)
    got = run(box)
    assert got["stopped"].startswith("allocation failed")
    assert got["last_normal_gb"] == 12 and box.released


def test_every_step_carries_both_free_memory_figures():
    """#299's data point was these two disagreeing by 11 GB."""
    got = run(Box(warn_at=2))
    assert {"free_pct", "available_gb", "level", "swapouts", "wired_gb",
            "gb"} <= set(got["steps"][0])
    assert got["baseline"]["available_gb"] == 20.0


MAC = {"fingerprint": "Mac14,12/macOS/arm64", "hw_model": "Mac14,12",
       "os": "macOS-26.5.1-arm64-arm-64bit", "arch": "arm64"}
STUDIO = {"fingerprint": "Mac17,15/macOS/arm64", "hw_model": "Mac17,15",
          "os": "macOS-27.0.1-arm64-arm-64bit", "arch": "arm64"}


@pytest.fixture
def store(monkeypatch):
    """A store whose `this machine` is MAC; no test reads the real one. #415."""
    from harness import memory_store as ms
    monkeypatch.setattr(ms, "_THIS_MACHINE", dict(MAC))
    conn = ms.connect()
    yield conn
    conn.close()


def _mid(conn, facts):
    from harness import memory_store as ms
    return ms.remember_machine(conn, facts)


def test_the_result_is_kept_per_machine(store):
    ramp.save(store, {"warn_at_gb": 9}, _mid(store, MAC))
    ramp.save(store, {"warn_at_gb": 40}, _mid(store, STUDIO))
    assert ramp.runs(store, _mid(store, MAC))[-1]["warn_at_gb"] == 9
    assert ramp.runs(store, _mid(store, STUDIO))[-1]["warn_at_gb"] == 40
    assert store.execute("SELECT COUNT(*) FROM memory_limits").fetchone()[0] == 2


def test_lh_memory_ramp_is_a_command():
    args = cli.build_parser().parse_args(["memory", "ramp", "--step-gb", "2"])
    assert args.func is cli.cmd_memory and args.step_gb == 2.0


def test_an_unknown_total_refuses_rather_than_measuring_nothing(monkeypatch):
    """The first live run capped at 0 - 4 GB and recorded 'cap' with no steps."""
    from harness import memory
    monkeypatch.setattr(memory, "_unified_total_gb", lambda: 0.0)
    monkeypatch.setattr(memory, "system_memory_gb", lambda: 0.0)
    box = Box()
    with pytest.raises(ValueError):
        ramp.run(step_gb=1, settle_s=0, allocate=box.allocate,
                 release=box.release, sample=box.sample,
                 sleep=lambda s: None, available=lambda: 20.0)


def test_the_default_cap_comes_from_unified_memory(monkeypatch):
    from harness import memory
    monkeypatch.setattr(memory, "_unified_total_gb", lambda: 32.0)
    monkeypatch.setattr(memory, "system_memory_gb", lambda: 0.0)
    got = ramp.run(step_gb=1, settle_s=0, allocate=Box().allocate,
                   release=lambda: None, sample=Box().sample,
                   sleep=lambda s: None, available=lambda: 20.0)
    assert got["cap_gb"] == 28.0


# --- the guard reads what was measured ----------------------------------------

def test_runs_accumulate_per_machine(store):
    mac = _mid(store, MAC)
    ramp.save(store, {"margin_gb": 2.2, "measured_at": "2026-10-01T00:00:00"}, mac)
    ramp.save(store, {"margin_gb": 3.8, "measured_at": "2026-10-02T00:00:00"}, mac)
    assert [r["margin_gb"] for r in ramp.runs(store, mac)] == [2.2, 3.8]
    assert ramp.runs(store, None) == []


def test_the_margin_is_available_at_start_minus_the_last_normal_step():
    got = run(Box(warn_at=9))
    assert got["margin_gb"] == 20.0 - 8


def test_a_run_ended_by_the_cap_measured_no_margin():
    assert run(Box(), cap_gb=5)["margin_gb"] is None


def test_the_reserve_is_the_largest_measured_margin(store):
    """The guard reads the store, this machine's rows only. #299, #415."""
    from harness import memory
    assert memory.measured_reserve_gb(store) == memory.DEFAULT_RESERVE_GB
    mac = _mid(store, MAC)
    ramp.save(store, {"margin_gb": 2.2}, mac)
    ramp.save(store, {"margin_gb": 3.8}, mac)
    ramp.save(store, {"margin_gb": None}, mac)
    assert memory.measured_reserve_gb(store) == 3.8
    ramp.save(store, {"margin_gb": 9.0}, _mid(store, STUDIO))
    assert memory.measured_reserve_gb(store) == 3.8
    # Opened by the guard itself, from the same home.
    assert memory.measured_reserve_gb() == 3.8


def test_a_memory_limits_file_is_not_read(store):
    from harness import memory, paths
    (paths.home() / "memory-limits.json").write_text(
        '{"Mac14,12/macOS-26.5.1-arm64-arm-64bit/arm64": [{"margin_gb": 7.0}]}',
        encoding="utf-8")
    assert memory.measured_reserve_gb(store) == memory.DEFAULT_RESERVE_GB


def test_a_measured_margin_below_the_floor_is_not_trusted(store):
    from harness import memory
    ramp.save(store, {"margin_gb": 0.1}, _mid(store, MAC))
    assert memory.measured_reserve_gb(store) == memory.MIN_RESERVE_GB

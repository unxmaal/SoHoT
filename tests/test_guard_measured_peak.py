"""The guard uses a measured peak when one exists. #322."""
from harness import memory

GIB_KB = 1024 ** 2


def test_a_measured_peak_is_found_by_spec(store_run):
    store_run("svg-three-way", "svg", {"omnisvg:4B": {"peak_kb": 23361307},
                                       "local-large": {"peak_kb": 0}})
    got = memory.measured_peak_gb("omnisvg:4B")
    assert round(got, 1) == 22.3


def test_the_largest_of_several_runs_wins(store_run):
    store_run("a", "svg", {"omnisvg:4B": {"peak_kb": 10 * GIB_KB}})
    store_run("b", "svg", {"omnisvg:4B": {"peak_kb": 20 * GIB_KB}})
    assert memory.measured_peak_gb("omnisvg:4B") == 20.0


def test_another_machines_peak_is_not_this_machines(store_run):
    """#322: the peak was pooled across machines; a 96 GB box's number is not
    this one's."""
    store_run("a", "svg", {"omnisvg:4B": {"peak_kb": 10 * GIB_KB}})
    store_run("b", "svg", {"omnisvg:4B": {"peak_kb": 40 * GIB_KB}},
              hw_model="Another,1")
    assert memory.measured_peak_gb("omnisvg:4B") == 10.0


def test_a_server_side_model_has_no_measured_peak(store_run):
    """Negative control: peak_kb 0 is 'not measured here', not 'free'."""
    store_run("a", "svg", {"local-large": {"peak_kb": 0}})
    assert memory.measured_peak_gb("local-large") is None
    assert memory.measured_peak_gb("never-run") is None


def test_the_guard_refuses_on_the_measured_peak_not_the_disk_size(monkeypatch):
    monkeypatch.setattr(memory, "cache_path", lambda repo: "/x")
    monkeypatch.setattr(memory, "size_gb", lambda p: 7.2)
    monkeypatch.setattr(memory, "available_gb", lambda: 12.0)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 24.0)
    monkeypatch.setattr(memory, "measured_peak_gb", lambda spec, runs=None: 22.3)
    ok, why = memory.check_model("OmniSVG/OmniSVG1.1_4B", spec="omnisvg:4B",
                                 reserve_gb=3.8)
    assert not ok and "22.3" in why


def test_without_a_measurement_the_disk_size_still_decides(monkeypatch):
    monkeypatch.setattr(memory, "cache_path", lambda repo: "/x")
    monkeypatch.setattr(memory, "size_gb", lambda p: 7.2)
    monkeypatch.setattr(memory, "available_gb", lambda: 12.0)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 24.0)
    monkeypatch.setattr(memory, "measured_peak_gb", lambda spec, runs=None: None)
    ok, _ = memory.check_model("org/m", spec="org/m", reserve_gb=3.8)
    assert ok


def test_the_screen_passes_the_spec_to_the_guard():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "harness" / "cli.py"
            ).read_text(encoding="utf-8")
    assert 'memory.check_model(r["name"], spec=r["candidate"])' in text

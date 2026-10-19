"""#1008: a package the runner's venv lacks is a runtime gap that waits on that package, never the candidate broken."""
import pytest

from harness import coherence, reasons, runner_gaps, screen
from harness import memory_store as ms
from harness.memory_store import revisit, transitions

SPEC = "diffusers:Photoroom/prxpixel-t2i"
# Verdict 12777's detail, as the 2026-10-19 day loop wrote it.
FTFY = ("it ran and passed nothing: fox-snow: exit 1: NameError: name 'ftfy' is not defined; "
        "product-shot: exit 1: NameError: name 'ftfy' is not defined")


@pytest.mark.parametrize("text,dist", [
    (FTFY, "ftfy"),
    ("fox-snow: exit 1: ModuleNotFoundError: No module named 'ftfy'", "ftfy"),
    ("exit 1: NameError: name 'BeautifulSoup' is not defined", "beautifulsoup4"),
    ("ModuleNotFoundError: No module named 'google.protobuf'", "protobuf"),
    ("hf-task venv lacks a package: No module named 'torchvision'", "torchvision"),
])
def test_a_runner_package_the_venv_lacks_is_a_runtime_gap(text, dist):
    assert reasons.missing_package(text) == dist
    cls = reasons.classify(text, reasons.RUNNER, SPEC)
    assert cls == reasons.MISSING_PACKAGE
    assert reasons.CLASSES[cls] == ("declined", reasons.RUNTIME)


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/reasons.py:RUNNER_PACKAGES")
@pytest.mark.parametrize("text,cls", [
    # A bug in the candidate's own code is still the candidate's.
    ("fox-snow: exit 1: RuntimeError: mat1 and mat2 shapes cannot be multiplied (77x768 and 1024x320)",
     reasons.CRASHED),
    ("fox-snow: exit 1: NameError: name 'hidden_states' is not defined", reasons.CRASHED),
    # Our own package missing is the harness, as before.
    ("Error while finding module specification for 'evals.run' (ModuleNotFoundError: No module named 'evals')",
     reasons.HARNESS_ERROR),
])
def test_a_name_no_runner_package_binds_keeps_its_class(text, cls):
    assert reasons.missing_package(text) == ""
    assert reasons.classify(text, reasons.RUNNER, SPEC) == cls


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/runner_gaps.py:RUNNER_VENVS")
def test_the_screen_declines_it_until_the_runner_venv_has_the_package():
    v = screen.decide_class(reasons.MISSING_PACKAGE, FTFY.removeprefix("it ran and passed nothing: "), SPEC)
    assert (v.outcome, v.reason, v.until, v.failure_class) == (
        "declined", reasons.RUNTIME, "package:ftfy@diffusers-cuda", reasons.MISSING_PACKAGE)
    assert not transitions.incoherent(v.outcome, v.reason, v.until)
    assert runner_gaps.package_until("No module named 'ftfy'", "hf-ocr:org/m") == "package:ftfy@hf-task"
    assert runner_gaps.package_until("No module named 'ftfy'", "mflux:org/m") == "package:ftfy"


def _venv(root, *dists):
    site = root / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    for d in dists:
        (site / f"{d}.dist-info").mkdir()
    return root


def test_the_package_until_is_met_once_that_venv_has_it(tmp_path, monkeypatch):
    monkeypatch.setenv("DIFFUSERS_VENV", str(_venv(tmp_path / "d", "diffusers-0.40.0", "torch-2.6.0")))
    monkeypatch.setenv("HF_TASK_VENV", str(_venv(tmp_path / "h", "ftfy-6.3.1")))
    assert not revisit.until_met("package:ftfy@diffusers-cuda", {})
    assert revisit.until_met("package:ftfy@hf-task", {})
    (tmp_path / "d" / "lib" / "python3.12" / "site-packages" / "ftfy-6.3.1.dist-info").mkdir()
    assert revisit.until_met("package:ftfy@diffusers-cuda", {})
    assert revisit.until_met("package:invisible-watermark@hf-task", {}) is False
    (tmp_path / "h" / "lib" / "python3.12" / "site-packages" / "invisible_watermark-0.2.0.dist-info").mkdir()
    assert revisit.until_met("package:invisible-watermark@hf-task", {})
    assert revisit.until_met("package:ftfy@diffusers-cuda", {"packages": {"diffusers-cuda": {"ftfy"}}})
    assert not revisit.until_met("package:ftfy@diffusers-cuda", {"packages": {"hf-task": {"ftfy"}}})
    assert not revisit.until_met("package:", {})
    assert revisit.until_met("package:pytest", {})
    assert not revisit.until_met("package:no-such-dist-1008", {})


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _broken(conn, name, detail):
    ms.record(conn, ms.Seen(name=name, source="t", registry=ms.HUGGINGFACE, lane="image", resolved=name))
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    transitions._write(conn, pid, name, {"outcome": "broken", "tier": "screen", "detail": detail,
                                         "decided_at": 1792406712.0, "until": "", "reason": "candidate",
                                         "failure_class": reasons.CRASHED})
    conn.commit()


def test_coherence_re_decides_a_broken_screen_its_detail_now_calls_a_runtime_gap(store):
    _broken(store, "Photoroom/prxpixel-t2i", FTFY)
    _broken(store, "org/really-broken", "it ran and passed nothing: fox-snow: exit 1: RuntimeError: shape mismatch")
    found = coherence.changes(store)
    assert [c["name"] for c in found] == ["Photoroom/prxpixel-t2i"]
    assert found[0]["now"] == ["declined", "screen", "runtime", "package:ftfy"]
    coherence.apply(store, found)
    held = store.execute("SELECT p.state, v.reason, v.until, v.failure_class FROM proposals p "
                         "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?",
                         ("Photoroom/prxpixel-t2i",)).fetchone()
    assert tuple(held) == ("declined", "runtime", "package:ftfy", reasons.MISSING_PACKAGE)
    assert coherence.changes(store) == []
    assert store.execute("SELECT state FROM proposals WHERE name = 'org/really-broken'").fetchone()[0] == "broken"

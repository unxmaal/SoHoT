"""Gauntlet FT (#1780): each decision here reads a field its writer sets, so rewording the sentence beside it changes nothing."""
from __future__ import annotations

import io
import subprocess
import sys
import time
import urllib.error

import pytest

from harness import context, cuts, deploy_switch, disk, feeds, inventory_time, lane_probe, node_deploy
from harness import inspect as ins
from tests.test_context import GIB, QWEN3_4B
from tests.test_node_deploy_1692 import NEW, Fake, _follow, _node, _yaml, deployed  # noqa: F401


def _reworded(fn):
    """fn with every refusal's sentence replaced, its kind kept."""
    def wrapped(*a, **kw):
        got = fn(*a, **kw)
        return got._replace(why="no room was found for this plan") if got.refused else got
    return wrapped


# --- FT-6: Choice.refused ----------------------------------------------------------------------------

def test_a_one_slot_cap_refusal_stays_refused_by_the_shared_pool_whatever_it_says(monkeypatch):
    args = (QWEN3_4B, 4 * GIB, 40 * GIB, 2, 8192, "f16", GIB // 2)
    assert context.choose_slots(*args).refused == context.SLOT_CAP
    monkeypatch.setattr(context, "choose_slots", _reworded(context.choose_slots))
    got = context.shared_pool(*args)
    assert got.ctx == 0 and got.refused == context.SLOT_CAP, got


def test_a_floor_refusal_is_named_the_floor_cut_whatever_it_says():
    low = context.choose(QWEN3_4B, 15 * GIB, 16 * GIB, 1)
    assert low.refused == context.FLOOR_CUT
    low = low._replace(why="too little KV room for a useful context")
    assert context._bound(QWEN3_4B, 15 * GIB, 16 * GIB, 16 * GIB, None, 1, "f16", None, low) == "floor"


def test_a_served_plan_and_a_slot_plan_are_not_refused():
    assert context.choose(QWEN3_4B, 4 * GIB, 40 * GIB, 1).refused == ""
    assert context.choose_slots(QWEN3_4B, 4 * GIB, 40 * GIB, 2, 8192).refused == ""


# --- FT-7: a timeout is a type, not the words "timed out" ---------------------------------------------

def test_a_switch_step_that_ran_out_of_time_is_noted_whatever_its_runner_says(monkeypatch):
    monkeypatch.setattr(deploy_switch, "run", lambda *a, **kw: (None, deploy_switch.TimedOut("ran out of its hour")))
    rec: dict = {}
    why = deploy_switch._step(rec, ["true"], ".", 60.0, io.StringIO(), "install",
                              site_knob="harness/deploy_switch.py:INSTALL_TIMEOUT_S", end=time.monotonic() + 3600)
    assert rec["timed_out"] == [{"site": "harness/deploy_switch.py:INSTALL_TIMEOUT_S", "what": "install"}]
    assert why == "install ran out of its hour"


def test_a_step_that_could_not_start_is_not_a_timeout_even_when_it_says_so(monkeypatch):
    monkeypatch.setattr(deploy_switch, "run", lambda *a, **kw: (None, "timed out: could not run: no such file"))
    rec: dict = {}
    deploy_switch._step(rec, ["true"], ".", 60.0, io.StringIO(), "install",
                        site_knob="harness/deploy_switch.py:INSTALL_TIMEOUT_S", end=time.monotonic() + 3600)
    assert "timed_out" not in rec


def test_the_switch_runner_returns_a_timeout_by_type(tmp_path):
    with open(tmp_path / "switch.log", "w", encoding="utf-8") as log:
        rc, why = deploy_switch.run([sys.executable, "-c", "import time; time.sleep(30)"], ".", 0.5, log)
        assert rc is None and isinstance(why, deploy_switch.TimedOut)
        rc, why = deploy_switch.run([str(tmp_path / "missing")], ".", 5.0, log)
        assert rc is None and why and not isinstance(why, deploy_switch.TimedOut)


def test_the_node_ssh_runner_returns_a_timeout_by_type(monkeypatch):
    def slow(*a, **kw):
        raise subprocess.TimeoutExpired("ssh", 1.0)
    monkeypatch.setattr(node_deploy.subprocess, "run", slow)
    rc, said = node_deploy._ssh(["ssh"], "", 1.0)
    assert rc is None and isinstance(said, deploy_switch.TimedOut)


def test_a_node_install_that_ran_out_of_time_is_cut_whatever_its_runner_says(deployed, tmp_path, monkeypatch):  # noqa: F811
    got = []
    monkeypatch.setattr(cuts, "cut", lambda knob, *a, **kw: got.append(knob))
    f = _yaml(tmp_path, _node("styx", deploy={"ssh": "ops@styx.invalid"}))
    _follow(deployed, f, Fake(install={NEW: (None, deploy_switch.TimedOut("the install outlived its hour"))}))
    assert "harness/node_deploy.py:INSTALL_TIMEOUT_S" in got


# --- FT-10: display filters --------------------------------------------------------------------------

def test_soh_families_counts_the_family_term_from_the_standing_not_the_words_of_its_why(monkeypatch):
    from harness import family, rank, report
    from harness.commands import families
    fam = family.Family("code", "fam", "org/fam", lost=[f"org/fam-{i}" for i in range(family.LOSSES_TO_DEMOTE)])
    fam.demoted = True
    st = family.Standing(parents_of={"org/fam-ft": ["org/fam"]}, families={("code", "fam"): fam})
    rows = [{"name": "org/fam-ft", "lane": "code"}, {"name": "org/other", "lane": "code"}]
    monkeypatch.setattr(report, "ms_judgeable", lambda conn: rows)
    monkeypatch.setattr(rank, "serving", lambda: {})
    monkeypatch.setattr(rank, "lanes_with_receipts", lambda conn: set())
    monkeypatch.setattr(rank, "rank", lambda rs, **kw: [{**r, "value": 0.0, "value_why": "worded otherwise"} for r in rs])
    q = families.queue(None, st, "code")
    assert [bool(r["family_term"]) for r in q] == [True, False]
    r = {"losses_to_demote": family.LOSSES_TO_DEMOTE, "records": [], "lane": "code", "queue": q, "plan_lane": "",
         "nights": 7, "tonight": {"n": 1, "with": [], "without": [], "families": {}, "lines": []}}
    text = "\n".join(families.render(r, head=5))
    assert "1 of 2 row(s) take the family term" in text
    assert f"org/fam-ft: {q[0]['family_why']}" in text


def test_soh_disk_marks_an_entry_inside_its_grace_whatever_the_grace_says(tmp_path, monkeypatch):
    now = time.time()
    monkeypatch.setattr(disk, "_graced", lambda e, at: "held a day after its rejection" if disk._young(e, at) else "")
    e = disk.Entry(kind="hub", path=str(tmp_path / "x"), name="org/x", size=1, group=disk.REJECTED,
                   decided_at=now - 3600)
    inv = disk.Inventory(hub=str(tmp_path), gguf=str(tmp_path), entries=[e], incomplete=[], problems=[])
    line = next(ln for ln in disk.table(inv, now).splitlines() if "org/x" in ln)
    assert line.endswith("(<24 h)")


def test_an_hour_with_a_probe_of_a_model_not_loaded_reads_idle_however_the_probe_words_it(monkeypatch):
    monkeypatch.setattr(lane_probe, "NOT_RESIDENT", "nothing has loaded the model")
    probes = [{"outcome": lane_probe.SKIPPED, "reason": f"memory is tight, and {lane_probe.NOT_RESIDENT} yet"}]
    assert inventory_time._residency(probes) == inventory_time.IDLE
    assert inventory_time._residency([{"outcome": lane_probe.SKIPPED, "reason": "residency unknown"}]) \
        == inventory_time.IDLE_UNRECORDED


# --- FT-11: a registry 404 is its status, not the words "HTTP 404" ------------------------------------

def test_a_registry_404_is_gone_whatever_the_error_says():
    def gone(url):
        raise feeds.FeedError("the registry said it has nothing there", status=404)

    def down(url):
        raise feeds.FeedError("HTTP 404 was not the problem, the host is down")
    with pytest.raises(ins.Gone):
        ins.hf_model("org/model", fetch=gone)
    with pytest.raises(ins.InspectError) as caught:
        ins.hf_model("org/model", fetch=down)
    assert not isinstance(caught.value, ins.Gone)


@pytest.mark.parametrize("code,kind", [(404, feeds.FeedError), (429, feeds.RateLimitedFeed)])
def test_a_fetch_carries_the_http_code_that_ended_it(monkeypatch, code, kind):
    def answer(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "no", {}, None)
    monkeypatch.setattr(feeds.urllib.request, "urlopen", answer)
    with pytest.raises(kind) as caught:
        feeds.fetch("https://example.invalid/x", retries=1, sleep=lambda s: None)
    assert caught.value.status == code

"""A verb called from another gets the namespace its own parser builds; a crashing repair never ends the sweep. #974."""
import argparse
import contextlib
import io
from pathlib import Path

import pytest

from harness import inspect as ins
from harness import neighbors
from harness import machine as _machine
from harness import memory_store as ms
from harness import reasons
from harness.commands import common, discover as discover_cmd, loop as loop_cmd, screen as screen_cmd
from harness.memory import Accelerator
from tests.gauntlet import scanners

REPO = Path(__file__).resolve().parent.parent
CARD = {"pipeline_tag": "text-generation", "library_name": "transformers", "tags": ["custom", "text-generation"],
        "config": {"model_type": "custom"}, "siblings": [{"rfilename": "m.safetensors", "size": 1024 ** 3}]}


def _runtime_decline(conn, name):
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights", lane="code", why="seeded",
                            registry=ms.HUGGINGFACE, resolved=name))
    ms.decide(conn, name, "declined", tier=ms.SCREEN, until="version:mlx-lm>0.32.0", reason=reasons.RUNTIME,
              detail="the installed runtime could not load it: Model type custom not supported.")


def test_the_runtime_decline_reread_runs_the_real_inspect_to_completion(monkeypatch):
    m = _machine.Machine(frozenset({"mlx", "cpu"}), Accelerator("unified", 32.0, 25.0, "Mac14,12"))
    monkeypatch.setattr(_machine, "detect", lambda *a, **k: m)
    monkeypatch.setattr(ins, "hf_model", lambda name, fetch=None: CARD)
    monkeypatch.setattr(neighbors, "neighbors", lambda **k: pytest.fail("the reread inspected the crowd"))
    conn = ms.connect()
    try:
        _runtime_decline(conn, "org/custom")
        conn.commit()
        assert ms.cards_to_reread(conn) == ["org/custom"]
    finally:
        conn.close()
    with contextlib.redirect_stdout(io.StringIO()):
        loop_cmd._reread_runtime_declines(argparse.Namespace(budget=5))
    conn = ms.connect()
    try:
        assert ms.cards_to_reread(conn) == [], "the real inspect read the card"
    finally:
        conn.close()


def test_a_repair_that_raises_is_a_failed_step_and_inspect_still_runs(monkeypatch):
    def _reopen_unranked():
        raise RuntimeError("store went away")

    for name in ("_reopen_stale_too_big", "_reopen_upstream_committed", "_rederive_attachments"):
        monkeypatch.setattr(loop_cmd, name, lambda: None)
    monkeypatch.setattr(loop_cmd, "_reopen_unranked", _reopen_unranked)
    monkeypatch.setattr(loop_cmd, "_reread_runtime_declines", lambda a: None)
    ran = []
    monkeypatch.setattr(discover_cmd, "cmd_discover",
                        lambda a: ran.append(next(t for _, t, _ in loop_cmd.LOOP_STEPS if getattr(a, t))) or 0)
    monkeypatch.setattr(loop_cmd, "_spend_and_settle", lambda a, rc, failed=None, sweep=None: rc)
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        rc = loop_cmd._run_loop_held(common.parsed("discover", "--loop", "--run"))
    assert ran == ["sweep", "inspect", "queue"]
    assert rc == 1
    assert "_reopen_unranked failed (RuntimeError: store went away)" in out.getvalue()
    assert "inspect (_reopen_unranked)" in err.getvalue()


def test_the_loop_fetch_gets_the_fetch_parsers_namespace_with_the_loops_lane_and_budget(monkeypatch):
    from harness import disk
    from harness.commands import measure as measure_cmd
    got = []
    monkeypatch.setattr(disk, "sweep", lambda *a, **k: {})
    for name in ("_reopen_retests", "_reopen_missing_in_snapshot", "_reverify", "_sweeps"):
        monkeypatch.setattr(loop_cmd, name, lambda *a, **k: {})
    monkeypatch.setattr(screen_cmd, "screenable_backlog", lambda want="": [])
    monkeypatch.setattr(screen_cmd, "cmd_fetch", lambda a: got.append(a) or 0)
    monkeypatch.setattr(discover_cmd, "cmd_discover", lambda a: 0)
    monkeypatch.setattr(measure_cmd, "measurable", lambda store, top, want="": [])
    monkeypatch.setattr(measure_cmd, "resume_first", lambda store, fresh, want="": fresh)
    monkeypatch.setattr(ms, "connect", lambda *a, **k: type("S", (), {"close": lambda s: None})())
    a = common.parsed("discover", "--loop", "--run", "--lane", "image", "--budget-gib", "7", "--top", "2")
    with contextlib.redirect_stdout(io.StringIO()):
        loop_cmd._loop_spend(a, 0)
    fetch = vars(got[0])
    assert fetch["command"] == "fetch" and set(vars(common.parsed("fetch"))) <= set(fetch)
    assert (fetch["run"], fetch["limit"], fetch["lane"], fetch["budget_gib"]) == (True, 2, "image", 7.0)


def test_common_parsed_holds_every_field_of_the_verbs_parser_with_overrides_on_top():
    a = common.parsed("discover", "--inspect", repos=["org/x"], top=1)
    assert a.inspect and a.repos == ["org/x"] and a.top == 1 and a.json is False and a.from_store is False


def test_a_hand_made_namespace_handed_to_a_verb_is_found():
    src = ("import argparse\nfrom harness.commands import discover as discover_cmd\n"
           "def f(a):\n"
           "    discover_cmd._report_inspect(argparse.Namespace(repos=[], top=1))\n"
           "    sub = argparse.Namespace(limit=1)\n"
           "    screen_cmd.cmd_fetch(sub)\n"
           "    loop_cmd._spend_and_settle(argparse.Namespace(**vars(a)), 0)\n"
           "    cmd_discover(argparse.Namespace(sweep=True))\n")
    got = scanners.handmade_namespaces(src, "harness/commands/x.py")
    assert [g.split(":")[1] for g in got] == ["4", "5", "7", "8"]


def test_a_parsed_namespace_or_one_never_handed_to_a_verb_is_left_alone():
    src = ("import argparse\nfrom harness.commands import common\n"
           "def f(a):\n"
           "    discover_cmd._report_inspect(common.parsed('discover', '--inspect', repos=[]))\n"
           "    sub = argparse.Namespace(limit=1)\n"
           "    sub = common.parsed('fetch', limit=1)\n"
           "    screen_cmd.cmd_fetch(sub)\n"
           "    other = argparse.Namespace(x=1)\n"
           "    print(other)\n")
    assert scanners.handmade_namespaces(src, "harness/commands/x.py") == []
    fires = src.replace("    print(other)\n", "    screen_cmd.cmd_fetch(other)\n")
    assert len(scanners.handmade_namespaces(fires, "harness/commands/x.py")) == 1


def test_no_verb_is_handed_a_hand_made_namespace():
    found = scanners.scan_tree(REPO, scanners.handmade_namespaces, scanners.is_python,
                               lambda rel: rel.startswith("harness/"))
    assert not found, ("a hand-made Namespace misses whatever field its writer forgot, and the verb reading it "
                       "crashes; the discovery loop died that way at inspect (#974):\n  " + "\n  ".join(found))
    seen = {k for k, _ in (h for rel in scanners.SAME_PARSER for h in scanners.namespace_handoffs(
        (REPO / rel.partition(":")[0]).read_text(encoding="utf-8"), rel.partition(":")[0]))}
    assert set(scanners.SAME_PARSER) <= seen, f"pinned but gone, so drop: {set(scanners.SAME_PARSER) - seen}"

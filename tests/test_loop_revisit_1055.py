"""#1055: the loop's discover step reopens a refusal whose until is met; a spent until never loops; every UNTIL key has a reader."""
import ast
import importlib
import inspect
import re

import pytest

from harness import adopt, fetching, heartbeat, holdout, live_audit, reasons
from harness import memory_store as ms
from harness.commands import loop as loop_cmd
from harness.memory_store import revisit, transitions

T = 1791000000.0
GROWN = 643
SVG = "cases:svg>3"


@pytest.fixture
def grown(monkeypatch):
    split = holdout.Split("svg", tuple(f"d{i}" for i in range(GROWN - 195)), tuple(f"h{i}" for i in range(195)),
                          False)
    one = holdout.Split("other", ("o",), ("o",), True)
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: split if lane == "svg" else one)
    return split


def _declined(conn, name, until, lane="svg", tier=ms.ADOPT, detail="svg: lane too small", at=T):
    got = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()
    if got is None:
        ms.record(conn, ms.Seen(name=name, source="t", lane=lane, resolved=name))
        ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=at)
        got = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()
    transitions._write(conn, got[0], name, {"outcome": "declined", "tier": tier, "reason": reasons.LIMIT,
                                            "until": until, "detail": detail, "decided_at": at})
    conn.commit()


def _state(conn, name):
    return tuple(conn.execute("SELECT p.state, v.tier, v.until FROM proposals p "
                              "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone())


def test_one_loop_discover_step_reopens_a_met_cases_until_to_the_measure_queue(grown, capsys):
    conn = ms.connect()
    _declined(conn, "OmniSVG/OmniSVG1.1_4B", SVG)
    conn.close()
    heartbeat.start()
    got = loop_cmd._reopen_revisitable()
    assert [r["name"] for r in got] == ["OmniSVG/OmniSVG1.1_4B"]
    assert "OmniSVG/OmniSVG1.1_4B  (cases:svg>3)" in capsys.readouterr().out
    conn = ms.connect()
    try:
        assert _state(conn, "OmniSVG/OmniSVG1.1_4B") == ("screened", ms.SCREEN, "")
    finally:
        conn.close()
    assert heartbeat.marked(heartbeat.REOPENED_REVISITABLE) is not None


def test_the_discover_step_runs_the_revisit_repair_before_inspect():
    src = inspect.getsource(loop_cmd._run_loop_held)
    assert "_reopen_revisitable" in src
    assert src.index("_reread_runtime_declines") < src.index("_reopen_revisitable") < src.index("cmd_discover(sub)")


def test_a_re_decline_under_the_same_met_until_is_spent_and_never_reopens_again(grown, capsys):
    conn = ms.connect()
    _declined(conn, "Photoroom/prxpixel-t2i", "package:ftfy@diffusers-cuda", lane="image", tier=ms.SCREEN)
    facts = {"packages": {"diffusers-cuda": ("ftfy",)}}
    assert ms.requeue_revisitable(conn, facts) == ["Photoroom/prxpixel-t2i"]
    _declined(conn, "Photoroom/prxpixel-t2i", "package:ftfy@diffusers-cuda", lane="image", tier=ms.SCREEN,
              detail="ftfy still missing", at=T + 60)
    assert ms.revisitable(conn, facts) == []
    assert [r["name"] for r in ms.revisitable(conn, facts, spent=True)] == ["Photoroom/prxpixel-t2i"]
    assert ms.requeue_revisitable(conn, facts) == []
    conn.close()


def test_a_reopen_for_another_cause_does_not_spend_the_until(grown):
    conn = ms.connect()
    _declined(conn, "org/m", SVG)
    transitions.retract(conn, "org/m", "a parent's download ranking retired it")
    _declined(conn, "org/m", SVG, at=T + 60)
    assert [r["name"] for r in ms.revisitable(conn)] == ["org/m"]
    conn.close()


def test_the_cases_writer_after_a_reopen_counts_the_grown_lane_so_it_is_not_met(grown):
    conn = ms.connect()
    _declined(conn, "OmniSVG/OmniSVG1.1_8B", SVG)
    ms.requeue_revisitable(conn)
    split = {"dev": list(grown.dev), "holdout": list(grown.holdout)}
    again = adopt.cases_until("svg", adopt.decided_cases("svg", split, {"cases": 195, "side": "holdout"}))
    assert again == f"cases:svg>{GROWN}"
    _declined(conn, "OmniSVG/OmniSVG1.1_8B", again, at=T + 60)
    assert ms.revisitable(conn) == [] and ms.revisitable(conn, spent=True) == []
    conn.close()


def test_a_terminal_format_wait_reopens_only_once_a_runner_of_its_lane_reads_it(monkeypatch):
    conn = ms.connect()
    _declined(conn, "org/escha", "format:eschamoe", lane="code", tier=ms.SCREEN)
    _declined(conn, "org/nolane", "format:.safetensors", lane="", tier=ms.SCREEN)
    assert ms.revisitable(conn, {"runtimes": "mlx"}) == []
    monkeypatch.setattr(fetching, "RUNNER_FORMATS", (*fetching.RUNNER_FORMATS, "eschamoe"))
    assert [r["name"] for r in ms.revisitable(conn, {"runtimes": "mlx"})] == ["org/escha"]
    conn.close()


def _audit():
    return {c["name"]: c for c in live_audit.audit(ms.db_path())["checks"]}["revisitable"]


def test_the_audit_warns_on_a_met_until_until_the_loop_requeue_has_run_then_fails(grown):
    conn = ms.connect()
    _declined(conn, "OmniSVG/OmniSVG1.1_4B", SVG)
    conn.close()
    got = _audit()
    assert got["ok"] and got["warn"] and heartbeat.REOPENED_REVISITABLE in got["detail"]
    heartbeat.start()
    heartbeat.mark(heartbeat.REOPENED_REVISITABLE, T + 60)
    heartbeat.finish(0)
    got = _audit()
    assert not got["ok"] and "OmniSVG/OmniSVG1.1_4B" in got["detail"]
    loop_cmd._reopen_revisitable()
    got = _audit()
    assert got["ok"] and not got["warn"]


def test_the_audit_names_a_spent_until_as_a_warning(grown):
    conn = ms.connect()
    _declined(conn, "org/m", SVG)
    ms.requeue_revisitable(conn)
    _declined(conn, "org/m", SVG, at=T + 60)
    conn.close()
    got = _audit()
    assert got["ok"] and got["warn"] and "already reopened once" in got["detail"] and "org/m" in got["detail"]


def _read_by_until_met() -> set[str]:
    tree = ast.parse(inspect.getsource(revisit.until_met))
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "key":
            for c in node.comparators:
                for e in (c.elts if isinstance(c, (ast.Tuple, ast.List, ast.Set)) else [c]):
                    if isinstance(e, ast.Constant):
                        keys.add(e.value)
    return keys


_READER = re.compile(r"\b([a-z_]+)\.([a-z_]+)\b reads it, not until_met")


def test_every_until_key_is_read_by_until_met_or_names_the_reader_that_handles_it():
    read = _read_by_until_met()
    assert read <= set(revisit.UNTIL), read - set(revisit.UNTIL)
    for key in sorted(set(revisit.UNTIL) - read):
        m = _READER.search(revisit.UNTIL[key])
        assert m, f"until key {key!r}: until_met never reads it and UNTIL names no '<module>.<function> reads it'"
        fn = next((getattr(mod, m.group(2), None) for mod in _modules(m.group(1))), None)
        assert callable(fn), f"until key {key!r}: UNTIL names {m.group(0)!r}, which does not exist"


def _modules(name):
    for where in (f"harness.{name}", f"harness.memory_store.{name}"):
        try:
            yield importlib.import_module(where)
        except ModuleNotFoundError:
            continue

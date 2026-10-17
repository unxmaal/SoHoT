"""Every until key a writer records is one revisit reads, with the meaning the writer meant. #928."""
import argparse
import ast
import re
import subprocess
from pathlib import Path

from harness import cli, memory, screen
from harness import memory_store as ms
from harness.commands import screen as screen_cmd
from harness.memory_store import revisit

ROOT = Path(__file__).resolve().parent.parent
_HEAD = re.compile(r"^([a-z_]+):")


def _sources():
    for top in ("harness", "evals"):
        for p in sorted((ROOT / top).rglob("*.py")):
            if "migrations" not in p.parts:
                yield p, ast.parse(p.read_text(encoding="utf-8"))


def _written_keys() -> set[str]:
    """The keys of every until literal that reaches an until position, following called functions' returns."""
    trees = list(_sources())
    consts, defs = {}, {}
    for _, tree in trees:
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        consts[t.id] = node.value.value
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.setdefault(node.name, []).append(node)
    keys, pending, done = set(), [], set()

    def head(text):
        m = _HEAD.match(text or "")
        if m:
            keys.add(m.group(1))

    def visit(e):
        if isinstance(e, ast.Constant) and isinstance(e.value, str):
            head(e.value)
        elif isinstance(e, ast.JoinedStr) and e.values and isinstance(e.values[0], ast.Constant):
            head(e.values[0].value)
        elif isinstance(e, ast.BinOp):
            visit(e.left)
        elif isinstance(e, ast.BoolOp):
            for v in e.values:
                visit(v)
        elif isinstance(e, ast.IfExp):
            visit(e.body), visit(e.orelse)
        elif isinstance(e, ast.Name) and e.id in consts:
            head(consts[e.id])
        elif isinstance(e, ast.Call):
            f = e.func
            pending.append(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))

    def until_target(t):
        if isinstance(t, ast.Name):
            return "until" in t.id
        return isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and "until" in t.value.id

    for _, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "until":
                visit(node.value)
            elif isinstance(node, ast.Assign) and any(until_target(t) for t in node.targets):
                visit(node.value)
            elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Verdict" \
                    and len(node.args) > 3:
                visit(node.args[3])
    while pending:
        name = pending.pop()
        if name in done:
            continue
        done.add(name)
        for fn in defs.get(name, []):
            for r in ast.walk(fn):
                if isinstance(r, ast.Return) and r.value is not None:
                    visit(r.value)
    return keys


def test_every_until_key_written_is_one_revisit_reads():
    written = _written_keys()
    assert written <= set(revisit.UNTIL), written - set(revisit.UNTIL)
    assert set(revisit.UNTIL) <= written, set(revisit.UNTIL) - written


def test_the_gpu_fault_until_and_its_reader_both_mean_total_ram():
    v = screen.decide_class("gpu_fault", facts={"memory_gb": 96})
    assert not ms.until_met(v.until, {"memory_gb": 96})
    assert ms.until_met(v.until, {"memory_gb": 128})


def _deferral(monkeypatch, tmp_path, free, ceiling, need=26.5, reserve=18.0):
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    ms.record(conn, ms.Seen(name="Photoroom/prxpixel-t2i", source="t", kind="weights",
                            lane="image", why="seeded"))
    conn.close()
    plan = [{"name": "Photoroom/prxpixel-t2i", "state": screen.READY,
             "candidate": "x:prx", "modality": "image", "why_not": ""}]
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(screen_cmd, "snapshot_gap", lambda r, store: "")
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: need)
    monkeypatch.setattr(memory, "available_gb", lambda: free)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: ceiling)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda conn=None: reserve)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("a deferral must not screen")))
    cli._report_screen(argparse.Namespace(lane="", top=5, limit=1, run=True, json=False))
    conn = ms.connect()
    try:
        return dict(conn.execute(
            "SELECT p.state AS outcome, v.reason, v.until FROM proposals p JOIN verdicts v "
            "ON v.id = p.state_verdict_id WHERE p.name = ?", ("Photoroom/prxpixel-t2i",)).fetchone())
    finally:
        conn.close()


def test_a_memory_deferral_waits_for_the_room_its_candidate_needs(monkeypatch, tmp_path):
    """26.5 GB needed, 13.4 GB free, a 77.8 GB ceiling on a 96 GB Studio: met only once room opens."""
    row = _deferral(monkeypatch, tmp_path, free=13.4, ceiling=77.8)
    assert (row["outcome"], row["reason"]) == ("queued", "memory")
    studio = {"memory_gb": 96.0, "ceiling_gb": 66.0}
    assert not ms.until_met(row["until"], studio)
    monkeypatch.setattr(memory, "available_gb", lambda: 50.0)
    assert ms.until_met(row["until"], studio)


def test_a_candidate_this_machine_can_never_hold_never_reopens(monkeypatch, tmp_path):
    row = _deferral(monkeypatch, tmp_path, free=13.4, ceiling=30.0)
    monkeypatch.setattr(memory, "available_gb", lambda: 90.0)
    assert not ms.until_met(row["until"], {"memory_gb": 96.0, "ceiling_gb": 66.0})


def test_an_unknown_need_records_no_until():
    assert memory.wait_for("definitely-not/a-cached-repo-9f3a") == ""

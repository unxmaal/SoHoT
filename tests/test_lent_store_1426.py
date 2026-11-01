"""Every read-only, replay or dry-run command reads only the store it is given and writes nothing to this home's. #1426."""
from __future__ import annotations

import argparse
import sqlite3
import time
import traceback
from pathlib import Path

import pytest

from harness import blame_audit as ba, cli, cuts, live_audit, runs
from harness import memory_store as ms
from tests.test_blame_since_1293 import _decided

S = "<copy>"

#: command -> (argv lists, ms.connect calls the command makes itself); S stands for the copy's path.
RUNS = {
    "adopt": ([["adopt", "--from-measurement", "--lane", "code", "--dry-run"]], 1),
    "baseline": ([["baseline", "--store", S]], 0),
    "benchmarks": ([["benchmarks", "--calibrate", "--db", S]], 0),
    "blame": ([["blame", "sample", "--dir", "<tmp>", "--db", S]], 0),
    "climb": ([["climb", "code", "x/Model-9B", "--store", S]], 0),
    "coherence": ([["coherence", "--db", S]], 0),
    "degenerate": ([["degenerate", "redecide", "--db", S]], 0),
    "discover-why": ([["discover-why", "x/Model-9B", "--budget", "0", "--db", S]], 0),
    "fetch": ([["fetch", "--replay", "3"]], 0),
    "floors": ([["floors", "--store", S]], 0),
    "hear": ([["hear", "--rates", "--store", S]], 0),
    "knobs": ([["knobs", k, "--store", S] for k in ("effects", "engine-timeouts", "reply-caps")], 0),
    "lane-feed": ([["lane-feed", "code", "--store", S]], 0),
    "load-log": ([["load-log", "--db", S]], 0),
    "measure-order": ([["measure-order", "--store", S], ["measure-order", "--replay", "2", "--store", S]], 0),
    "repo-report": ([["repo-report", "--plan", "--store", S]], 0),
    "repo-route": ([["repo-route", "--local", "1", "--cloud", "2", "--store", S]], 0),
    "repo-screen": ([["repo-screen", "pick", "--store", S]], 0),
    "reuse-replay": ([["reuse-replay", "1", "--store", S]], 0),
    "reverify": ([["reverify", "--dry-run"]], 1),
    "store": ([["store", "dry-run", S]], 1),
    "votes": ([["votes", "--store", S]], 0),
    "weedout-replay": ([["weedout-replay", "--store", S], ["weedout-replay", "--simulate", "2", "--store", S]], 0),
    "yield-stop": ([["yield-stop", "code", "x/Model-9B", "--store", S]], 0),
}
#: Commands with such a flag that are not read-only, and why.
EXEMPT = {
    "watchdog": "its dry run is how the deployed unit runs: it probes lanes and records what it would do (#814)",
}
FLAGS = ("--store", "--db", "--replay", "--dry-run")

#: "command --flag" -> (argv lists, own ms.connect calls) for each flag that selects a read-only mode; run on a seeded home. #1432.
READ_ONLY = {
    "adopt --power": ([["adopt", "--power"], ["adopt", "--power", "--lane", "code"]], 0),
    "adopt --table": ([["adopt", "--power", "--table"]], 0),
    "discover --winners": ([["discover", "--winners"]], 0),
    "discover --coverage": ([["discover", "--coverage"]], 0),
    "discover --queue": ([["discover", "--queue"]], 0),
    "discover --recurrence": ([["discover", "--recurrence"]], 0),
    "discover --evidence": ([["discover", "--evidence"]], 0),
    "discover --revisit": ([["discover", "--revisit"]], 0),
    "discover --gap": ([["discover", "--gap"]], 0),
    "knobs --by-binding": ([["knobs", "backlog", "--by-binding", "--store", S]], 0),
    "delegated --report": ([["delegated", "--report"]], 0),
    "sensitivity --list": ([["sensitivity", "--list"]], 0),
    "sensitivity --sweeps": ([["sensitivity", "--sweeps"]], 0),
    "sensitivity --inventory": ([["sensitivity", "--inventory"]], 0),
    "specs --untested": ([["specs", "--untested"]], 0),
    "hear --suspect": ([["hear", "--suspect", "--store", S]], 0),
    "load-log --idle": ([["load-log", "--idle", "--db", S]], 0),
    "repo-report --arms": ([["repo-report", "--arms", "--store", S]], 0),
    "verify --all": ([["verify", "--all"]], 0),
    "context --carried": ([["context", "--carried", "--root", "<tmp>"]], 0),
    "context --referenced": ([["context", "--referenced", "--root", "<tmp>"]], 0),
    "context --mistakes": ([["context", "--mistakes", "--root", "<tmp>"]], 0),
}
#: Flags that only shape another mode's output or scope; that mode is held here or below.
MODIFIERS = {
    "prompt --quiet", "rubric --no-browser", "judge --no-browser", "discover --platform", "discover --no-verify",
    "discover --no-control", "discover --from-store", "discover --requeue", "discover --judge",
    "inventory time --no-effort", "inventory time --hours", "inventory weight --no-ci", "inventory weight --markdown",
    "context --main-only",
    "morning --no-model", "claude-news --no-record", "benchmarks --force", "benchmarks --passages",
    "cases --reextract", "jobs --night", "disk --yes", "fetch --hold-router", "adopt --unscreened",
    "judge --all-machines",
}
#: Flags whose mode writes, downloads, runs a model or reads the network by design, so it is not run here.
NOT_RUN = {
    "discover --sources": "probes each feed over the network",
    "adopt --from-measurement": "adopts the measured incumbent; its --dry-run is held in RUNS",
    "discover --external": "asks the registries", "discover --loop": "the discovery loop",
    "discover --sweep": "reads every source and records it", "discover --benchmarks": "sweeps the registries",
    "discover --quants": "follows bases on the hub", "discover --papers": "reads a feed and records it",
    "discover --posts": "reads a feed and records it", "discover --triage": "drafts with a model under --run",
    "discover --feeds": "reads a feed and records it", "discover --control": "scores with a judge model",
    "discover --neighbors": "reads GitHub", "discover --inspect": "clones and records",
    "discover --screen": "screens weights", "discover --run": "runs the screen",
    "fetch --run": "downloads", "fetch --day": "the daytime download job", "report --export": "writes a report file",
    "report --publish": "pushes the report", "repo-screen --write": "writes the anchors file",
    "gateway --rotate": "replaces the key", "canary --run": "plants canaries", "review --file": "files findings",
    "claude-news --notify": "records and notifies", "ledger --record": "upserts ledger_days",
    "runtimes --watch": "reads PyPI and GitHub releases and records proposals",
    "runtimes --trial": "trial-installs a runtime release",
    "ledger --sample-power": "appends a power reading", "morning --notify": "notifies (the morning unit)",
    "sweep-check --notify": "records the check", "craft --revalidate": "runs the installed release",
    "delegated --close": "records outcomes", "disk --record": "writes download rows",
    "store --keep": "keeps a migrated copy", "benchmarks --sweep": "reads the registries now",
    "degenerate --apply": "writes verdicts", "load-log --apply": "writes excerpts and verdicts",
    "coherence --apply": "writes verdicts", "watchdog --act": "takes actions", "judge --force": "adopts",
    "verify --run": "runs lanes", "gauntlet --offline": "audits the committed snapshot, no store",
    "chaos --yes-break-things": "kills a scratch server", "benchmarks --calibrate": "held in RUNS",
    "repo-report --plan": "held in RUNS", "hear --rates": "held in RUNS",
    "unverified --hook": "asks a model and writes its log and block state",
    "unverified --settings": "prints a settings block, no store",
}


def _flagged(parser, path=()):
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            for name, sub in act.choices.items():
                yield from _flagged(sub, (*path, name))
    flag = any(o in FLAGS for a in parser._actions for o in a.option_strings)
    action = any("dry-run" in (a.choices or ()) for a in parser._actions if not a.option_strings)
    if path and (flag or action):
        yield path[0]


def test_every_command_with_a_store_replay_or_dry_run_flag_is_held_here():
    assert set(_flagged(cli.build_parser())) == set(RUNS) | set(EXEMPT)


def _counts(path: Path) -> dict:
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


@pytest.fixture
def home_store():
    ms.connect().close()
    return ms.db_path()


@pytest.fixture
def copy(tmp_path):
    conn = ms.connect(tmp_path / "copy.db")
    try:
        # More terminal verdicts than blame's second labeller takes, so a blame sample cuts.
        _decided(conn, "copy", [("inspect", "declined", "machine", ba.SECOND_N + 5)], time.time() - 86400)
    finally:
        conn.close()
    return tmp_path / "copy.db"


@pytest.fixture
def held(monkeypatch, home_store):
    """Run a callable; fail when it opens a store through ms.connect past `own`, or writes this home's store."""
    opened = []
    real = ms.connect

    def spy(*a, **kw):
        here = [f for f in traceback.extract_stack()[:-1] if "/harness/" in f.filename and "memory_store" not in f.filename]
        opened.append(" <- ".join(f"{Path(f.filename).stem}.{f.name}" for f in here[-1:-4:-1]))
        return real(*a, **kw)

    monkeypatch.setattr(ms, "connect", spy)

    def check(run, own: int = 0):
        before = _counts(home_store)
        opened.clear()
        run()
        assert len(opened) <= own, f"reopened the store through ms.connect: {opened}"
        assert _counts(home_store) == before, "wrote this home's store"
        assert not (home_store.parent / cuts.SPOOL).exists(), "spooled a cut for this home's store"
    return check


@pytest.mark.parametrize("name", sorted(RUNS))
def test_a_read_only_command_reads_only_the_store_it_is_given(name, copy, held, tmp_path):
    argvs, own = RUNS[name]
    for argv in argvs:
        argv = [str(copy) if x == S else str(tmp_path / "out") if x == "<tmp>" else x for x in argv]
        held(lambda: cli.main(argv), own)


def _modes(parser, path=()):
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            for name, sub in act.choices.items():
                yield from _modes(sub, (*path, name))
    for act in parser._actions if path else ():
        flag = act.option_strings[-1] if act.option_strings else ""
        if isinstance(act, argparse._StoreTrueAction) and flag not in ("--json", *FLAGS):
            yield f"{' '.join(path)} {flag}"


def test_every_mode_flag_is_held_here_or_says_why_not():
    found = set(_modes(cli.build_parser()))
    listed = set(READ_ONLY) | MODIFIERS | set(NOT_RUN)
    assert not found - listed, f"a new mode flag: add it to READ_ONLY, MODIFIERS or NOT_RUN: {sorted(found - listed)}"
    assert not listed - found, f"listed flags no command takes: {sorted(listed - found)}"


@pytest.fixture
def seeded_home(home_store):
    conn = ms.connect()
    try:
        _decided(conn, "home", [("inspect", "declined", "machine", ba.SECOND_N + 5)], time.time() - 86400)
    finally:
        conn.close()
    return home_store


@pytest.mark.parametrize("mode", sorted(READ_ONLY))
def test_a_read_only_mode_with_no_store_flag_writes_nothing_and_reopens_nothing(mode, seeded_home, copy, held, tmp_path):
    argvs, own = READ_ONLY[mode]
    for argv in argvs:
        argv = [str(copy) if x == S else str(tmp_path) if x == "<tmp>" else x for x in argv]
        held(lambda: cli.main(argv), own)


def _reconnects(store, lend: bool):
    conn = live_audit.open_readonly(store)
    try:
        if lend:
            with ms.lend(conn), runs.store() as c:
                c.execute("SELECT 1")
        else:
            with runs.store() as c:
                c.execute("SELECT 1")
    finally:
        conn.close()


def test_a_reader_that_reopens_the_store_fails_and_one_that_takes_the_lent_connection_passes(copy, held):
    with pytest.raises(AssertionError, match="reopened"):
        held(lambda: _reconnects(copy, lend=False))
    held(lambda: _reconnects(copy, lend=True))


def _cuts(store, lend: bool):
    conn = live_audit.open_readonly(store)
    try:
        if lend:
            with ms.lend(conn):
                cuts.cut("power_plateau", "a read-only report's plan", kept=1, dropped=1)
        else:
            cuts.cut("power_plateau", "a read-only report's plan", kept=1, dropped=1)
    finally:
        conn.close()


def test_a_cut_outside_a_lend_reaches_this_homes_store_and_one_inside_records_nothing(copy, held):
    with pytest.raises(AssertionError, match="wrote this home's store"):
        held(lambda: _cuts(copy, lend=False))
    held(lambda: _cuts(copy, lend=True))

"""#2086: a measured adapter runs on the engine that loads it, whoever hands measure its row; no engine is a decline."""
import argparse

import pytest

from harness import adopt, paused, reasons
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from tests.test_resume_813 import Eval, _sweep

INC = "llamacpp:imajev-4b-Q8_0"
NIMBLE = "bespokelabs/Bespoke-Nimble-9B"
ORPHAN = "someone/plain-qwen-lora"


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: INC)
    monkeypatch.setattr(measure_cmd.paths, "home", lambda: tmp_path)
    conn = ms.connect()
    try:
        for name in (NIMBLE, ORPHAN):
            ms.record(conn, ms.Seen(name=name, source="t", lane="decide", resolved=name))
            conn.execute("UPDATE proposals SET attaches_to = 'lora', library = 'peft' WHERE name = ?", (name,))
            ms.decide(conn, name, "screened", tier=ms.SCREEN, reason="candidate")
        conn.commit()
    finally:
        conn.close()


def _ns(**kw):
    return argparse.Namespace(**{"lane": "", "repeat": 1, "effect": 0.4, "power_budget_min": 60.0, **kw})


def _candidates(argv):
    return argv[argv.index("--candidates") + 1].split(",")


def test_a_paused_adapter_resumes_on_its_adapter_engine_not_the_bare_repo(monkeypatch, world, capsys):
    conn = ms.connect()
    try:
        paused.save(conn, lane="decide", inc_spec=INC, spec=f"nimble:{NIMBLE}", proposal=NIMBLE, out="/x",
                    ident={}, plan={}, done=1, total=2, looks=[])
        row = measure_cmd.resume_first(conn, [])[0]
    finally:
        conn.close()
    measure_cmd._measure(_ns(dry_run=True), row, [], _sweep())
    out = capsys.readouterr().out
    assert f"--candidates {INC},nimble:{NIMBLE}" in out
    assert "--gateway" not in out


def test_a_named_adapter_challenger_launches_on_its_adapter_engine(monkeypatch, world):
    fake = Eval()
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    monkeypatch.setattr(measure_cmd.test_weights, "refused", lambda name, sweep: None)
    measure_cmd._measure(_ns(), {"name": NIMBLE, "lane": "decide"}, [], _sweep())
    assert fake.argvs and _candidates(fake.argvs[0]) == [INC, f"nimble:{NIMBLE}"]


def test_an_adapter_no_engine_loads_is_declined_with_the_reason_and_never_launched(monkeypatch, world):
    fake = Eval()
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    sweep = _sweep()
    assert measure_cmd._measure(_ns(), {"name": ORPHAN, "lane": "decide"}, [], sweep) == 0
    assert fake.argvs == []
    conn = ms.connect()
    try:
        got = dict(conn.execute("SELECT v.outcome, v.tier, v.reason, v.detail FROM proposals p JOIN verdicts v "
                                "ON v.id = p.state_verdict_id WHERE p.name = ?", (ORPHAN,)).fetchone())
    finally:
        conn.close()
    assert (got["outcome"], got["tier"], got["reason"]) == ("declined", ms.MEASURE, reasons.RUNTIME)
    assert "no decide engine is known to load this lora" in got["detail"]
    assert any(ORPHAN in line and "not measured" in line for line in sweep.lines)


def test_a_dry_run_declines_nothing(monkeypatch, world):
    assert measure_cmd._measure(_ns(dry_run=True), {"name": ORPHAN, "lane": "decide"}, [], _sweep()) == 0
    conn = ms.connect()
    try:
        assert ms.latest(conn, ORPHAN)["outcome"] == "screened"
    finally:
        conn.close()

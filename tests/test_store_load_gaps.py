"""Schema 17 reopens screen verdicts that were a runtime's load failure. #293."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import memory_store as ms  # noqa: E402

GAP = ('it ran and passed nothing: chunk-bytes: gateway returned HTTP 404: '
       '{"error": "Model type gpt_x not supported."}')
MISSING = ('it ran and passed nothing: chunk-bytes: gateway returned HTTP 404: '
           '{"error": "[Errno 2] No such file or directory: \'x\'"}')


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def seed(conn, name, detail):
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights", lane="code",
                            why="seeded"))
    ms.decide(conn, name, "broken", tier=ms.SCREEN, detail=detail)


def latest(conn, name):
    return conn.execute(
        "SELECT v.outcome, v.until FROM verdicts v JOIN proposals p "
        "ON p.id = v.proposal_id WHERE p.name = ? ORDER BY v.id DESC LIMIT 1",
        (name,)).fetchone()


def migrate(store, tmp_path):
    store.execute("INSERT OR REPLACE INTO meta VALUES ('schema', '16')")
    store.commit()
    store.close()
    return ms.connect(tmp_path / "s.db")


def test_an_architecture_gap_becomes_declined_until_a_newer_runtime(store, tmp_path):
    seed(store, "org/gap", GAP)
    again = migrate(store, tmp_path)
    try:
        outcome, until = latest(again, "org/gap")
        assert outcome == "declined"
        assert until.startswith("version:mlx-lm>")
    finally:
        again.close()


def test_a_missing_file_stays_broken(store, tmp_path):
    """THE NEGATIVE CONTROL."""
    seed(store, "org/missing", MISSING)
    again = migrate(store, tmp_path)
    try:
        assert latest(again, "org/missing")[0] == "broken"
    finally:
        again.close()


def test_a_newer_runtime_reopens_it(store, tmp_path):
    seed(store, "org/gap", GAP)
    again = migrate(store, tmp_path)
    try:
        _, until = latest(again, "org/gap")
        newer = until.split(">")[1] + ".1"
        assert ms.until_met(until, {"versions": {"mlx-lm": newer}})
    finally:
        again.close()


def test_a_runtime_upgrade_on_the_same_machine_is_revisitable(store):
    """The other predicates wait on a different machine; this one waits on an
    upgrade of the machine that refused."""
    ms.record(store, ms.Seen(name="org/gap", source="t", kind="weights",
                             lane="code", why="seeded"))
    ms.decide(store, "org/gap", "declined", tier=ms.SCREEN, detail=GAP,
              until="version:mlx-lm>0.31.3")
    here = ms.this_machine()
    newer = dict(here, versions={"mlx-lm": "0.31.4"})
    same = dict(here, versions={"mlx-lm": "0.31.3"})
    assert [r["name"] for r in ms.revisitable(store, newer)] == ["org/gap"]
    assert ms.revisitable(store, same) == []

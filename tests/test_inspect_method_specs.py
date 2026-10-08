"""inspect answers a method spec from its base and asks no registry about it. #642."""
import pytest

from harness import cli, github, inspect as ins, paths, reasons
from harness import memory_store as ms
from harness.memory_store import Seen

ARGS = type("A", (), {"repos": [], "from_store": True, "top": 10, "budget": 10,
                      "shard": "", "judge": False, "json": False})


@pytest.fixture
def asked(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    names = []

    def touch(name, *_a, **_kw):
        names.append(name)
        raise ins.InspectError(f"{name}: registry asked")

    class Client:
        stale: list = []
        spent = 0

        def __init__(self, **kw):
            pass

        def repo(self, name):
            names.append(name)
            raise github.GitHubError(f"{name}: registry asked")

    monkeypatch.setattr(github, "Client", Client)
    monkeypatch.setattr(ins, "hf_model", touch)
    monkeypatch.setattr(ins, "inspect_model", touch)
    monkeypatch.setattr(ins, "inspect", touch)
    return names


def _crossing(conn, spec):
    ms.record(conn, Seen(name=spec, source="method-crossing", registry="",
                         resolved=spec))
    ms.decide(conn, spec, "queued", tier=ms.INSPECT,
              detail="a registered method", reason=reasons.CANDIDATE)


def _size(conn, name):
    return conn.execute("SELECT size_bytes FROM proposals WHERE name = ?",
                        (name,)).fetchone()["size_bytes"]


def test_a_method_inherits_its_bases_inspect_verdict_with_no_registry_call(asked):
    conn = ms.connect()
    ms.record(conn, Seen(name="org/base", source="recap",
                         registry=ms.HUGGINGFACE, resolved="org/base"))
    ms.decide(conn, "org/base", "declined", tier=ms.INSPECT,
              detail="too-big: 40.0 GiB", reason=reasons.CANDIDATE)
    ms.set_size(conn, "org/base", 40 * 2**30)
    _crossing(conn, "best-of:3:org/base")
    conn.close()

    assert cli._report_inspect(ARGS()) == 0
    assert "best-of:3:org/base" not in asked
    conn = ms.connect()
    assert ms.latest(conn, "best-of:3:org/base")["outcome"] == "declined"
    assert _size(conn, "best-of:3:org/base") == 40 * 2**30
    conn.close()


def test_a_method_over_an_unregistered_incumbent_stays_queued_unasked(asked):
    conn = ms.connect()
    _crossing(conn, "plan:local-large")
    conn.close()

    assert cli._report_inspect(ARGS()) == 0
    assert asked == []
    conn = ms.connect()
    assert ms.latest(conn, "plan:local-large") == {"outcome": "queued",
                                                  "tier": ms.INSPECT}
    conn.close()

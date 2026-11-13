"""A delegation from a scratch eval home is answered where the machine's home answers it: its interactive server and adopted model. #1711."""
import pytest

from harness import adopt, delegate, interactive, paths, router, serving
from harness import memory_store as ms
from tests.conftest import store_state

URL = "http://127.0.0.1:18083"
ORNITH = "Ornith-1.5-35B-Q4_K_M"


def _plan():
    entry = {"stem": ORNITH, "path": f"/m/{ORNITH}.gguf", "ctx": 27648, "slots": 2, "weights": 1, "kv": 1,
             "bytes": 21 * 1024 ** 3, "spec": f"llamacpp:{ORNITH}", "served": f"llamacpp:{ORNITH}", "why": "pinned"}
    return {"url": URL, "bytes": entry["bytes"], "lanes": {"code": entry}, "skipped": {}}


@pytest.fixture
def machine(monkeypatch):
    """The machine's home as its services leave it: a store with an adoption, the plan its interactive server runs."""
    monkeypatch.delenv(interactive.KEY_ENV, raising=False)
    home = paths.home()
    conn = ms.connect()
    ms.record(conn, ms.Seen(name="org/new", source="feeds", lane="tts", kind="weights", resolved="org/new"))
    adopt.record(conn, adopt.Verdict("tts", "old", "org/new", True, "won"))
    conn.close()
    interactive.write(_plan())
    asked = []
    monkeypatch.setattr(router, "statuses", lambda get=None, base="": asked.append(serving.bare(base)) or (
        {ORNITH: "loaded"} if serving.bare(base) == URL else {}))
    return home, asked


def _scratch(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.ENV_VAR)
    return paths.eval_home(tmp_path / "scratch")


def _files(home):
    """Every file and its mtime but a SQLite reader's own -shm/-wal, which store_state reads instead."""
    return sorted((p.relative_to(home).as_posix(), p.stat().st_mtime_ns) for p in home.rglob("*")
                  if not p.name.endswith(("-shm", "-wal")))


def test_a_scratch_eval_home_routes_a_pinned_lane_to_the_machine_s_interactive_server(machine, tmp_path, monkeypatch):
    live, asked = machine
    outside = delegate.route("code")
    assert outside[1].base == URL and outside[1].model == ORNITH
    scratch = _scratch(tmp_path, monkeypatch)
    assert paths.home() == scratch and interactive.plan_path() == live / interactive.PLAN_NAME
    spec, where = delegate.route("code")
    assert (spec, where.base, where.model) == (outside[0], URL, ORNITH), "answered as the machine's home answers it"
    assert interactive.served_ctx(ORNITH) == 27648
    assert interactive.preset_path(URL) == live / "interactive-preset-18083.ini"
    assert asked and set(asked) == {URL}


def test_a_scratch_eval_home_serves_the_machine_s_adopted_model(machine, tmp_path, monkeypatch):
    assert adopt.serving_default("tts", "CONST") == "org/new"
    assert adopt.serving_default("web", "CONST") == "CONST"
    _scratch(tmp_path, monkeypatch)
    assert adopt.serving_default("tts", "CONST") == "org/new"
    assert adopt.serving_default("web", "CONST") == "CONST", "a lane the machine never adopted serves its constant"
    assert delegate.lane_model("tts") == "org/new"


def test_a_scratch_eval_home_reads_adoptions_only_through_the_read_only_connection(machine, tmp_path, monkeypatch,
                                                                                    capsys):
    _scratch(tmp_path, monkeypatch)

    def read_write(*a, **kw):
        raise AssertionError("opened the machine's store read-write")

    monkeypatch.setattr(ms, "connect", read_write)
    assert adopt.serving_default("tts", "CONST") == "org/new"
    assert capsys.readouterr().err == ""


def test_a_scratch_eval_home_sends_the_key_the_machine_s_server_demands(machine, tmp_path, monkeypatch):
    live, _ = machine
    secret = tmp_path / "key"
    secret.write_text("s3cret\n", encoding="utf-8")
    (live / interactive.KEY_ENV).write_text(str(secret), encoding="utf-8")
    _scratch(tmp_path, monkeypatch)
    assert interactive.key() == "s3cret"


def test_a_scratch_eval_home_writes_nothing_in_the_machine_s_home(machine, tmp_path, monkeypatch):
    live, _ = machine
    before, files = store_state(live / "discovery.db"), _files(live)
    scratch = _scratch(tmp_path, monkeypatch)
    delegate.route("code")
    delegate.lane_model("tts")
    with pytest.raises(interactive.NotOwnPlan):
        interactive.write({"lanes": {}})
    with pytest.raises(interactive.NotOwnPlan):
        interactive.clear()
    assert store_state(live / "discovery.db") == before and _files(live) == files
    assert not (scratch / interactive.PLAN_NAME).exists()


@pytest.mark.sqlite_store
def test_a_scratch_eval_home_whose_machine_has_no_store_serves_the_typed_default(tmp_path, monkeypatch, capsys):
    _scratch(tmp_path, monkeypatch)
    assert not (paths.machine_home() / "discovery.db").exists()
    assert adopt.serving_default("tts", "CONST") == "CONST"
    assert not (paths.machine_home() / "discovery.db").exists()
    assert capsys.readouterr().err == "", "no store is nothing adopted, not a store that could not be read"


def test_outside_a_scratch_eval_home_the_plan_is_this_home_s_own(tmp_path, monkeypatch):
    assert interactive.plan_path() == paths.home() / interactive.PLAN_NAME
    interactive.write(_plan())
    assert interactive.pinned()["code"]["stem"] == ORNITH
    interactive.clear()
    assert interactive.read() == {}

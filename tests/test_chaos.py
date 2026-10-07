"""`soh chaos`: fault scenarios that run only when explicitly asked, on a scratch home. #492."""
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness import chaos, cli, exclusive, fetching, paths, reasons, screen
from harness import memory_store as ms
from harness.commands import chaos as chaos_cmd

REPO = Path(__file__).resolve().parents[1]


def tree(root: Path) -> dict:
    """Every path under root with its size and mtime, to prove nothing changed."""
    out = {}
    for p in sorted(root.rglob("*")):
        st = p.stat()
        out[str(p.relative_to(root))] = (p.is_dir(), st.st_size, st.st_mtime_ns)
    return out


@pytest.fixture(autouse=True)
def _no_rank_reads(monkeypatch):
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts", lambda *a, **k: set())


@pytest.fixture
def scratch_parent(tmp_path):
    d = tmp_path / "scratch-parent"
    d.mkdir()
    return d


@contextlib.contextmanager
def lock_taken():
    yield True


@contextlib.contextmanager
def lock_refused():
    yield False


def one_object(capsys) -> dict:
    out = capsys.readouterr().out
    assert out.strip().count("\n") == 0, out
    return json.loads(out)


# --- refusals ---------------------------------------------------------------

def test_refuses_without_the_confirmation_flag():
    why = chaos.refusal(False, {}, {})
    assert chaos.CONFIRM_FLAG in why


@pytest.mark.parametrize("env,modules", [
    ({"PYTEST_CURRENT_TEST": "t"}, {}),
    ({}, {"pytest": object()}),
])
def test_refuses_under_pytest(env, modules):
    assert "pytest" in chaos.refusal(True, env, modules)


@pytest.mark.parametrize("var", ["CI", "GITHUB_ACTIONS", "BUILDKITE", "JENKINS_URL"])
def test_refuses_under_ci(var):
    assert "CI" in chaos.refusal(True, {var: "true"}, {})


def test_a_confirmed_run_outside_ci_and_pytest_is_not_refused():
    """Negative control: the guard is not simply always on."""
    assert chaos.refusal(True, {"CI": ""}, {}) == ""


def test_cli_without_the_flag_refuses_and_runs_nothing(capsys, monkeypatch):
    ran = []
    monkeypatch.setattr(chaos, "default_scenarios", lambda: ran.append(1) or [])
    assert cli.main(["chaos", "--json"]) == 1
    got = one_object(capsys)
    assert got["ok"] is False and got["verb"] == "chaos"
    assert chaos.CONFIRM_FLAG in got["error"] and ran == []


def test_cli_with_the_flag_still_refuses_under_pytest(capsys, monkeypatch):
    ran = []
    monkeypatch.setattr(chaos, "default_scenarios", lambda: ran.append(1) or [])
    monkeypatch.setattr(chaos, "machine_lock", lambda: ran.append("lock") or lock_taken())
    assert cli.main(["chaos", chaos.CONFIRM_FLAG, "--json"]) == 1
    got = one_object(capsys)
    assert "pytest" in got["error"] and ran == []


def test_cli_refuses_when_the_machine_lock_is_held(capsys, monkeypatch):
    ran = []
    monkeypatch.setattr(chaos, "environment", lambda: ({}, {}))
    monkeypatch.setattr(chaos, "default_scenarios", lambda: ran.append(1) or [])
    monkeypatch.setattr(chaos, "machine_lock", lock_refused)
    assert cli.main(["chaos", chaos.CONFIRM_FLAG, "--json"]) == 1
    got = one_object(capsys)
    assert "machine lock" in got["error"] and ran == []


def test_try_held_takes_a_free_lock_and_refuses_a_held_one():
    with exclusive.try_held("chaos") as got:
        assert got is True
        fd = os.open(exclusive.lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            assert exclusive._take(fd) is False
        finally:
            os.close(fd)
    fd = os.open(exclusive.lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        assert exclusive._take(fd) is True
        with exclusive.try_held("chaos") as got:
            assert got is False
        exclusive._release(fd)
    finally:
        os.close(fd)


# --- scratch home isolation and cleanup ---------------------------------------

def test_every_scenario_runs_on_a_scratch_home_and_the_live_home_is_untouched(
        scratch_parent, monkeypatch):
    live = paths.home()
    (live / "discovery.db").write_bytes(b"live store, never opened")
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(live / "gguf"))
    before = tree(live)
    hf_before = os.environ["HF_HOME"]
    seen = {}

    def probe(ctx):
        seen["home"] = paths.home()
        seen["ctx"] = ctx.home
        seen["hf"] = os.environ["HF_HOME"]
        seen["gguf"] = os.environ["LLAMACPP_MODELS_DIR"]
        conn = ms.connect()
        try:
            ms.record(conn, ms.Seen(name="org/scratch", source="chaos"))
        finally:
            conn.close()
        return True, "probed"

    got = chaos.run_all([chaos.Scenario("probe", probe)], live=live,
                        parent=scratch_parent)
    assert got == [chaos.Result("probe", True, "probed")]
    for key in ("home", "hf", "gguf"):
        p = Path(seen[key]).resolve()
        assert p != live and live not in p.parents
        assert scratch_parent.resolve() in p.parents
    assert seen["home"] == seen["ctx"]
    assert tree(live) == before
    assert paths.home() == live and os.environ["HF_HOME"] == hf_before
    assert os.environ["LLAMACPP_MODELS_DIR"] == str(live / "gguf")
    assert list(scratch_parent.iterdir()) == []


def test_a_scratch_parent_inside_the_live_home_is_refused(monkeypatch):
    live = paths.home()
    ran = []
    with pytest.raises(chaos.ChaosRefused):
        chaos.run_all([chaos.Scenario("x", lambda ctx: ran.append(1) or (True, ""))],
                      live=live, parent=live / "inside")
    assert ran == []


def test_a_failing_scenario_is_cleaned_up_and_the_next_still_runs(scratch_parent):
    live = paths.home()
    homes = []

    def boom(ctx):
        homes.append(ctx.home)
        (ctx.home / "debris").write_text("x", encoding="utf-8")
        raise RuntimeError("scenario blew up")

    def fails(ctx):
        homes.append(ctx.home)
        return False, "assertion failed"

    def passes(ctx):
        homes.append(ctx.home)
        return True, "fine"

    got = chaos.run_all([chaos.Scenario("boom", boom), chaos.Scenario("fails", fails),
                         chaos.Scenario("passes", passes)],
                        live=live, parent=scratch_parent)
    assert [(r.name, r.ok) for r in got] == [("boom", False), ("fails", False),
                                            ("passes", True)]
    assert "scenario blew up" in got[0].detail
    assert all(not h.exists() for h in homes)
    assert len(set(homes)) == 3
    assert paths.home() == live


def test_no_service_restart_can_happen_inside_a_scenario(scratch_parent, monkeypatch):
    from harness import disk, gateway, gguf
    calls = []
    monkeypatch.setattr(gguf, "refresh_router", lambda: calls.append("router"))
    monkeypatch.setattr(gateway, "refresh_gateway", lambda: calls.append("gateway"))

    def restarts(ctx):
        gguf.refresh_router()
        gateway.refresh_gateway()
        disk.sweep()
        return True, ""

    got = chaos.run_all([chaos.Scenario("r", restarts)], live=paths.home(),
                        parent=scratch_parent)
    assert got[0].ok and calls == []
    gguf.refresh_router()
    assert calls == ["router"]


# --- scenario 1: a model server killed mid-screen ----------------------------

def sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


def fake_server(started):
    def start(ctx):
        proc = sleeper()
        started.append(proc)
        return chaos.Server(url="http://127.0.0.1:1/v1", proc=proc)
    return start


def screen_that_sees(cls):
    def run(ctx, row, server, kill_now):
        kill_now()
        assert server.proc.poll() is not None or server.proc.wait(10) is not None
        return screen.decide_class(cls, "the server died mid-request",
                                   row["candidate"])
    return run


def server_mechanics(started, cls=reasons.SERVER_DEAD, **kw):
    base = dict(start=fake_server(started), screen=screen_that_sees(cls),
                recover_seconds=0.0)
    base.update(kw)
    return chaos.ServerKill(**base)


def test_server_kill_records_a_harness_fault_and_reports_the_lane_down(scratch_parent):
    started = []
    got = chaos.run_all([chaos.server_kill(server_mechanics(started))],
                        live=paths.home(), parent=scratch_parent)
    assert got[0].ok, got[0].detail
    assert "harness" in got[0].detail and "down" in got[0].detail
    assert started[0].poll() is not None


def test_server_kill_fails_when_the_screen_blames_the_candidate(scratch_parent):
    started = []
    got = chaos.run_all([chaos.server_kill(server_mechanics(started,
                                                            cls=reasons.CRASHED))],
                        live=paths.home(), parent=scratch_parent)
    assert not got[0].ok and "broken" in got[0].detail
    assert started[0].poll() is not None


def test_server_kill_kills_the_server_even_when_the_screen_raises(scratch_parent):
    started = []

    def raises(ctx, row, server, kill_now):
        raise RuntimeError("screen crashed")

    got = chaos.run_all([chaos.server_kill(server_mechanics(started, screen=raises))],
                        live=paths.home(), parent=scratch_parent)
    assert not got[0].ok and "screen crashed" in got[0].detail
    started[0].wait(10)
    assert started[0].poll() is not None


def test_server_kill_passes_when_the_server_comes_back(scratch_parent):
    started = []
    got = chaos.run_all([chaos.server_kill(server_mechanics(
        started, alive=lambda server: True))],
        live=paths.home(), parent=scratch_parent)
    assert got[0].ok and "came back" in got[0].detail


def test_the_default_stub_server_is_a_child_that_can_be_killed(tmp_path):
    server = chaos.start_stub_server(tmp_path)
    try:
        assert server.proc.poll() is None and server.url.startswith("http://127.0.0.1:")
    finally:
        chaos.kill(server)
    assert server.proc.poll() is not None


# --- scenario 2: a scratch disk filled below the floor ------------------------

def disk_mechanics(fetch_calls, *, base=10_000_000, **kw):
    def free(path):
        return base - sum(p.stat().st_size for p in Path(path).rglob("*")
                          if p.is_file())

    def snapshot(repo_id):
        fetch_calls.append(repo_id)
        return "/nowhere"

    m = dict(free=free, fill_bytes=4096, size=64, snapshot=snapshot)
    m.update(kw)
    return chaos.DiskFill(**m)


def test_disk_fill_refuses_the_fetch_with_a_non_candidate_reason_and_cleans_up(
        scratch_parent):
    calls, homes = [], []
    scen = chaos.disk_fill(disk_mechanics(calls))
    inner = scen.run
    scen = chaos.Scenario(scen.name, lambda ctx: homes.append(ctx.home) or inner(ctx))
    got = chaos.run_all([scen], live=paths.home(), parent=scratch_parent)
    assert got[0].ok, got[0].detail
    assert calls == []
    assert reasons.CANDIDATE not in got[0].detail.split("reason=")[1].split()[0]
    assert not homes[0].exists()


def test_disk_fill_fails_when_the_fetch_ignores_the_floor(scratch_parent):
    calls = []
    got = chaos.run_all([chaos.disk_fill(disk_mechanics(
        calls, fetch=lambda conn, **kw: fetching.run(conn, **{**kw, "floor": 0})))],
                        live=paths.home(), parent=scratch_parent)
    assert not got[0].ok and calls


def test_disk_fill_removes_the_filler_when_the_fetch_raises(scratch_parent):
    fillers = []

    def fill(path, n):
        f = chaos.fill(path, n)
        fillers.append(f)
        return f

    def broken_fetch(conn, **kw):
        raise RuntimeError("fetch fell over")

    m = disk_mechanics([], fill=fill, fetch=broken_fetch)
    got = chaos.run_all([chaos.disk_fill(m)], live=paths.home(), parent=scratch_parent)
    assert not got[0].ok and "fetch fell over" in got[0].detail
    assert fillers and not fillers[0].exists()


def test_fill_writes_a_real_file_of_the_asked_size(tmp_path):
    f = chaos.fill(tmp_path, 8192)
    assert f.stat().st_size == 8192 and f.parent == tmp_path


def test_fetching_run_honours_a_floor_it_is_given(tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    conn = ms.connect(tmp_path / "d.db")
    try:
        chaos.seed(conn, "org/tiny", 1000)
        got = fetching.run(conn, free=5000, floor=4500,
                           snapshot=lambda repo_id: pytest.fail("downloaded"))
    finally:
        conn.close()
    assert got and not got[0]["ok"] and "floor" in got[0]["why"]


# --- scenario 3: the HF client loses the network ------------------------------

def net_mechanics(entered, **kw):
    @contextlib.contextmanager
    def endpoint():
        entered.append("in")
        try:
            yield "http://127.0.0.1:9"
        finally:
            entered.append("out")

    def registry(url):
        raise OSError("[Errno 54] Connection reset by peer")

    def snapshot_for(url):
        def snapshot(repo_id):
            raise ConnectionResetError("[Errno 54] Connection reset by peer")
        return snapshot

    m = dict(endpoint=endpoint, registry_for=lambda url: registry,
             snapshot_for=snapshot_for)
    m.update(kw)
    return chaos.NetworkDrop(**m)


def test_network_drop_leaves_the_candidate_queued_with_a_failed_download(
        scratch_parent):
    entered = []
    got = chaos.run_all([chaos.network_drop(net_mechanics(entered))],
                        live=paths.home(), parent=scratch_parent)
    assert got[0].ok, got[0].detail
    assert entered == ["in", "out"]
    assert "queued" in got[0].detail


def test_network_drop_fails_when_inspect_settles_the_candidate(scratch_parent):
    got = chaos.run_all([chaos.network_drop(net_mechanics(
        [], registry_for=lambda url: lambda u: (_ for _ in ()).throw(
            Exception("HTTP 404"))))],
        live=paths.home(), parent=scratch_parent)
    assert not got[0].ok and "Gone" in got[0].detail


def test_network_drop_closes_the_endpoint_when_a_step_raises(scratch_parent):
    entered = []

    def snapshot_for(url):
        raise RuntimeError("could not build a client")

    got = chaos.run_all([chaos.network_drop(net_mechanics(
        entered, snapshot_for=snapshot_for))],
        live=paths.home(), parent=scratch_parent)
    assert not got[0].ok and entered == ["in", "out"]


# --- the command ----------------------------------------------------------------

def fake_scenarios(*oks):
    return [chaos.Scenario(f"s{i}", lambda ctx, ok=ok: (ok, "said so"))
            for i, ok in enumerate(oks)]


@pytest.fixture
def unguarded(monkeypatch, scratch_parent):
    monkeypatch.setattr(chaos, "environment", lambda: ({}, {}))
    monkeypatch.setattr(chaos, "machine_lock", lock_taken)
    monkeypatch.setattr(chaos, "SCRATCH_PARENT", scratch_parent)


def test_json_shape_when_every_scenario_passes(capsys, monkeypatch, unguarded):
    monkeypatch.setattr(chaos, "default_scenarios", lambda: fake_scenarios(True, True))
    assert cli.main(["chaos", chaos.CONFIRM_FLAG, "--json"]) == 0
    got = one_object(capsys)
    assert got == {"ok": True, "verb": "chaos",
                   "results": [{"name": "s0", "ok": True, "detail": "said so"},
                               {"name": "s1", "ok": True, "detail": "said so"}]}


def test_json_shape_when_a_scenario_fails(capsys, monkeypatch, unguarded):
    monkeypatch.setattr(chaos, "default_scenarios", lambda: fake_scenarios(True, False))
    assert cli.main(["chaos", chaos.CONFIRM_FLAG, "--json"]) == 1
    got = one_object(capsys)
    assert got["ok"] is False and [r["ok"] for r in got["results"]] == [True, False]


def test_only_runs_the_named_scenario(capsys, monkeypatch, unguarded):
    monkeypatch.setattr(chaos, "default_scenarios", lambda: fake_scenarios(True, False))
    assert cli.main(["chaos", chaos.CONFIRM_FLAG, "--only", "s0", "--json"]) == 0
    assert [r["name"] for r in one_object(capsys)["results"]] == ["s0"]


def test_only_with_an_unknown_name_is_an_error(capsys, monkeypatch, unguarded):
    monkeypatch.setattr(chaos, "default_scenarios", lambda: fake_scenarios(True))
    assert cli.main(["chaos", chaos.CONFIRM_FLAG, "--only", "nope", "--json"]) == 1
    assert "nope" in one_object(capsys)["error"]


def test_human_output_says_pass_or_fail_per_scenario(capsys, monkeypatch, unguarded):
    monkeypatch.setattr(chaos, "default_scenarios", lambda: fake_scenarios(True, False))
    assert cli.main(["chaos", chaos.CONFIRM_FLAG]) == 1
    out = capsys.readouterr().out
    assert "PASS  s0" in out and "FAIL  s1" in out


def test_the_default_scenarios_are_the_three_named_ones():
    assert [s.name for s in chaos.default_scenarios()] == [
        "server-kill", "disk-fill", "network-drop"]


# --- nothing schedules it -------------------------------------------------------

SCHEDULERS = [REPO / "scripts" / "launchd.sh", REPO / "Makefile",
              *sorted((REPO / ".github" / "workflows").glob("*.yml")),
              *sorted((REPO / "scripts").glob("serve-*.sh")),
              REPO / "scripts" / "services.sh"]


def scheduled(text: str) -> bool:
    return "chaos" in text.lower()


def test_the_schedule_scanner_fires_on_a_chaos_line():
    assert scheduled("\tuv run soh chaos --yes-break-things\n")
    assert not scheduled("\tuv run pytest tests/ -q\n")


def test_nothing_schedules_chaos():
    assert all(p.exists() for p in SCHEDULERS[:3])
    assert [str(p.relative_to(REPO)) for p in SCHEDULERS
            if scheduled(p.read_text(encoding="utf-8"))] == []

"""The audio server gives back what a screen loaded, frees it on removal, and the watchdog restarts it past its footprint limit when idle (#1671)."""
import asyncio
import io
import json
import os
import subprocess

import pytest

from harness import audio_models, morning, paths, tts_server
from harness import memory_store as ms
from harness import watchdog as wd, watchdog_hands
from harness.commands import morning as morning_cmd
from tests.test_watchdog import NIGHT, Fake, P

UV = "uv run --no-project --with mlx-audio==0.5.3 python -m harness.tts_server --host 0.0.0.0 --port 8890"
PY = "~/.cache/uv/builds-v0/.tmpX/bin/python -m harness.tts_server --host 0.0.0.0 --port 8890"
SPEECH = "/usr/bin/python3 -m evals.run --modality tts --candidates tts:OpenMOSS-Team/MOSS-TTS-v1.5"
BASE = "http://127.0.0.1:18890/v1"
MOSS = "OpenMOSS-Team/MOSS-TTS-v1.5"
KOKORO = "mlx-community/Kokoro-82M-bf16"
#: A live group no test may signal (conftest refuses it), so a stop that reaches a real killpg fails on every host.
GROUP = getattr(os, "getpgrp", os.getpid)()


# --- the server wrapper ----------------------------------------------------------

class Provider:
    def __init__(self, models):
        self.models = dict(models)

    async def remove_model(self, name):
        return self.models.pop(name, None) is not None


def test_a_removed_model_empties_the_mlx_cache_and_a_missing_one_does_not():
    cleared = []

    class Mine(Provider):
        pass
    tts_server.free_on_remove(Mine, lambda: cleared.append(1))
    p = Mine({MOSS: object()})
    assert asyncio.run(p.remove_model(MOSS)) is True
    assert cleared == [1], "the stock server keeps a removed model's bytes in MLX's cache (5.1 GiB measured)"
    assert asyncio.run(p.remove_model(MOSS)) is False
    assert cleared == [1]


# --- reading and releasing -------------------------------------------------------

class Server:
    """A stub audio server: GET /models lists what it holds, DELETE /models removes one."""

    def __init__(self, held, fail=False):
        self.held, self.fail, self.deleted = list(held), fail, []

    def __call__(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        method = "GET" if isinstance(req, str) else req.get_method()
        if method == "DELETE":
            if self.fail:
                raise OSError("connection refused")
            name = url.split("model_name=", 1)[1].replace("%2F", "/")
            self.deleted.append(name)
            self.held.remove(name)
            return _Resp(204, b"")
        return _Resp(200, json.dumps({"data": [{"id": m} for m in self.held]}).encode())


class _Resp(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(body)
        self.status = status


def test_the_model_a_spec_loads_is_its_repo_on_an_audio_lane_only():
    assert audio_models.model_of(f"tts:{MOSS},voice=a") == MOSS
    assert audio_models.model_of("stt:mlx-community/parakeet-tdt-0.6b-v2") == "mlx-community/parakeet-tdt-0.6b-v2"
    assert audio_models.model_of("llamacpp:Ornith-1.5-35B-Q4_K_M") == ""
    assert audio_models.model_of(MOSS) == ""


def test_a_screened_candidate_is_deleted_from_the_server():
    s = Server([KOKORO, MOSS])
    said = []
    assert audio_models.release_spec(f"tts:{MOSS},voice=a", "screened x", base=BASE, keep={KOKORO},
                                     opener=s, say=said.append) is True
    assert s.deleted == [MOSS] and s.held == [KOKORO]
    assert "unloaded" in said[0]


@pytest.mark.parametrize("spec, keep", [(f"tts:{KOKORO}", {KOKORO}), ("tts:not/held", set()),
                                        ("llamacpp:Ornith", set())])
def test_a_served_unheld_or_non_audio_model_is_left_alone(spec, keep):
    s = Server([KOKORO, MOSS])
    assert audio_models.release_spec(spec, "screened x", base=BASE, keep=keep, opener=s, say=lambda *_: None) is False
    assert s.deleted == []


def test_unreadable_protection_keeps_the_model(monkeypatch):
    from harness import router
    monkeypatch.setattr(router, "kept", lambda: (_ for _ in ()).throw(RuntimeError("store down")))
    s = Server([MOSS])
    assert audio_models.release(MOSS, "x", base=BASE, opener=s, say=lambda *_: None) is False
    assert s.deleted == []


def test_a_failed_delete_is_said_and_not_claimed():
    said = []
    assert audio_models.release(MOSS, "x", base=BASE, keep=set(), opener=Server([MOSS], fail=True),
                                say=said.append) is False
    assert "could not unload" in said[0]


def test_the_suite_never_asks_the_live_audio_server():
    assert audio_models.loaded() is None


@pytest.mark.parametrize("text, gib", [("Physical footprint:         42.9G\n", 42.9),
                                       ("Physical footprint:         512M\n", 0.5),
                                       ("Physical footprint:         1.5T\n", 1536.0),
                                       ("no such process\n", None)])
def test_the_footprint_is_vmmaps_physical_footprint_in_gib(text, gib):
    got = audio_models.footprint_gib(5, run=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, text, ""))
    assert got == gib


def test_the_server_is_the_python_under_the_units_uv():
    procs = [P(100, 1, 100, 60, UV), P(101, 100, 100, 60, PY), P(102, 101, 100, 60, "/bin/sh -c ffmpeg")]
    assert audio_models.server_pid(100, procs) == 101
    assert audio_models.server_pid(None, procs) is None
    assert audio_models.server_pid(100, [P(100, 1, 100, 60, "/bin/sleep 9")]) is None


def test_a_connection_held_by_the_server_is_a_request_in_flight():
    assert audio_models.in_flight("p101\nn127.0.0.1:8890->127.0.0.1:5000\n", 101) is True
    assert audio_models.in_flight("p7\nn127.0.0.1:5000->127.0.0.1:8890\n", 101) is False
    assert audio_models.in_flight("", 101) is False
    assert audio_models.in_flight(None, 101) is None


# --- the watchdog ----------------------------------------------------------------

class Tts(Fake):
    """The 2026-11-09 Studio: the tts unit's server at 43 GiB holding three screened candidates."""

    def __init__(self, tmp_path, gib=43.0, connections="", procs=()):
        super().__init__(tmp_path, procs=[P(100, 1, 100, 82800, UV), P(101, 100, 100, 82800, PY), *procs])
        self.gib, self.connections = gib, connections

    def launchd_pid(self, service):
        return 100 if service == "tts" else None

    def footprint(self, pid):
        return self.gib if pid == 101 else None


class Hands(watchdog_hands.Hands):
    def __init__(self):
        super().__init__(run=self._run, environ={}, platform="darwin")
        self.argv, self.stopped = [], []

    def _group(self, s):
        self.stopped.append(s.pgid)
        return wd.Said(f"group {s.pgid}: term")

    def _run(self, argv, **kw):
        self.argv.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")


def _wake(probes, monkeypatch):
    monkeypatch.setattr(audio_models, "loaded", lambda *a, **k: [KOKORO, MOSS])
    conn, hands = ms.connect(), Hands()
    try:
        wd.wake(conn, probes, hands, act=True, now=NIGHT, say=lambda *_: None)
        rows = [dict(r) for r in conn.execute("SELECT criterion, action, evidence, outcome FROM watchdog_actions "
                                              "WHERE criterion = 'tts_footprint'")]
    finally:
        conn.close()
    return rows, hands


def test_an_idle_server_past_the_limit_is_restarted_the_way_launchd_does(tmp_path, monkeypatch):
    rows, hands = _wake(Tts(tmp_path), monkeypatch)
    assert [(r["action"], r["outcome"]) for r in rows] == [("restart", "restarted tts")]
    assert json.loads(rows[0]["evidence"])["footprint_gib"] == 43.0
    assert json.loads(rows[0]["evidence"])["loaded"] == [KOKORO, MOSS]
    assert hands.argv[-1][-2:] == ["restart", "tts"] and hands.argv[-1][1] == str(paths.REPO / "scripts" / "launchd.sh")


def test_a_request_in_flight_keeps_the_server_up(tmp_path, monkeypatch):
    rows, hands = _wake(Tts(tmp_path, connections="p101\nn127.0.0.1:8890->127.0.0.1:5000\n"), monkeypatch)
    assert rows == [] and hands.argv == []


def test_an_eval_on_an_audio_lane_keeps_the_server_up(tmp_path, monkeypatch):
    probes = Tts(tmp_path, procs=[P(GROUP, 1, GROUP, 600, SPEECH)])
    probes.runs = [{"state": "running", "pid": GROUP, "done": 1, "total": 9, "specs": {"m": f"tts:{MOSS}"},
                    "started_at": NIGHT - 600, "last_progress_at": NIGHT - 30}]
    rows, hands = _wake(probes, monkeypatch)
    assert rows == [] and hands.argv == []
    assert hands.stopped == [GROUP]


@pytest.mark.parametrize("gib", [audio_models.FOOTPRINT_MAX_GB, 1.0, None])
def test_a_server_at_or_under_the_limit_or_unread_is_left_alone(tmp_path, monkeypatch, gib):
    rows, _ = _wake(Tts(tmp_path, gib=gib), monkeypatch)
    assert rows == []


def test_unknown_connections_keep_the_server_up(tmp_path, monkeypatch):
    probes = Tts(tmp_path)
    probes.connections = None
    rows, _ = _wake(probes, monkeypatch)
    assert rows == []


def test_no_tts_unit_here_is_no_finding(tmp_path, monkeypatch):
    rows, _ = _wake(Fake(tmp_path), monkeypatch)
    assert rows == []


# --- soh morning -----------------------------------------------------------------

def test_morning_shows_the_footprint_and_asks_for_a_person_past_the_limit():
    t = {"pid": 101, "footprint_gib": 43.0, "limit_gib": 16.0, "in_flight": False, "loaded": [KOKORO, MOSS]}
    r = morning.gather(ms.connect(), NIGHT, NIGHT - 86400, gh=lambda argv: "", git=lambda argv: "",
                       lanes=lambda conn: [], stalls=lambda conn: [], tts=lambda: t)
    assert f"tts       43.0 GiB footprint (limit 16); holds {KOKORO}, {MOSS}" in morning_cmd.render(r)
    assert any("tts server holds 43.0 GiB" in n for n in r["needs"])
    quiet = {**t, "footprint_gib": 1.0}
    assert audio_models.over(quiet) == ""
    assert audio_models.line({**t, "footprint_gib": None}).startswith("footprint unreadable")

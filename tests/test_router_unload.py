"""Discovery gives back the models it loaded into llama-server's router. #444."""
import argparse
import os

import pytest

from harness import adopt, cli, exclusive, router


class FakeRouter:
    """GET /models and POST /models/unload, as llama-server's router answers."""

    def __init__(self, **models):
        self.models = dict(models)
        self.unloads = []

    def get(self, path):
        assert path == "/models"
        return {"data": [{"id": k, "status": {"value": v}}
                         for k, v in self.models.items()]}

    def post(self, path, body):
        assert path == "/models/unload"
        self.unloads.append(body["model"])
        self.models[body["model"]] = "unloaded"
        return {"success": True}


@pytest.fixture
def fake(monkeypatch):
    r = FakeRouter(**{"command-a-plus-IQ1_S": "loaded",
                      "Qwen2.5-7B-Instruct-Q4_K_M": "loaded",
                      "Idle-Q4_K_M": "unloaded"})
    monkeypatch.setattr(router, "_get", r.get)
    monkeypatch.setattr(router, "_post", r.post)
    monkeypatch.setattr(router, "protected",
                        lambda *a, **k: {"Qwen2.5-7B-Instruct-Q4_K_M"})
    return r


def test_a_screened_candidate_is_unloaded_and_the_unload_is_said(fake):
    said = []
    got = router.release_spec("llamacpp:command-a-plus-IQ1_S", "screened x",
                              say=said.append)
    assert got == ["command-a-plus-IQ1_S"]
    assert fake.unloads == ["command-a-plus-IQ1_S"]
    assert said == ["  router: unloaded command-a-plus-IQ1_S (screened x)"]


def test_a_lane_default_is_never_unloaded(fake):
    assert router.release_spec("llamacpp:Qwen2.5-7B-Instruct-Q4_K_M", "x") == []
    assert fake.unloads == []


def test_a_model_not_resident_is_not_asked_about(fake):
    assert router.release_spec("llamacpp:Idle-Q4_K_M", "x") == []
    assert router.release_spec("mlx-community/whatever", "x") == []
    assert fake.unloads == []


def test_nothing_is_unloaded_while_a_run_holds_the_machine(fake):
    fd = os.open(exclusive.lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    assert exclusive._take(fd)
    try:
        said = []
        assert router.release_spec("llamacpp:command-a-plus-IQ1_S", "x",
                                   say=said.append) == []
        assert "a run is in flight" in said[0]
    finally:
        exclusive._release(fd)
        os.close(fd)
    assert fake.unloads == []
    assert router.release_spec("llamacpp:command-a-plus-IQ1_S", "x") != []


def test_unreadable_keepers_unload_nothing(fake, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store locked")
    monkeypatch.setattr(router, "protected", boom)
    said = []
    assert router.settle("end", say=said.append) == []
    assert fake.unloads == [] and "could not be read" in said[0]


def test_settle_leaves_only_what_is_protected(fake):
    assert router.settle("the loop is done") == ["command-a-plus-IQ1_S"]
    assert [k for k, v in fake.models.items() if v == "loaded"] == [
        "Qwen2.5-7B-Instruct-Q4_K_M"]


def test_an_unreachable_router_is_left_alone(monkeypatch):
    def down(path):
        raise OSError("connection refused")
    monkeypatch.setattr(router, "_get", down)
    assert router.settle("end") == []


def test_protected_reads_aliases_defaults_and_adoptions(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "model_list:\n"
        "  - model_name: eval-7b\n"
        "    litellm_params:\n"
        "      model: openai/Qwen2.5-7B-Instruct-Q4_K_M\n"
        "      api_base: http://127.0.0.1:8082/v1\n", encoding="utf-8")
    monkeypatch.setattr(adopt, "lane_defaults",
                        lambda conn=None: {"code": "llamacpp:Default-Q4_K_M",
                                           "image": "mflux:flux"})
    monkeypatch.setattr(adopt, "everywhere",
                        lambda conn: {"code": {"llamacpp:Winner-Q4_K_M"}})
    got = router.protected(config=cfg)
    assert {"Qwen2.5-7B-Instruct-Q4_K_M", "Default-Q4_K_M",
            "Winner-Q4_K_M"} <= got
    assert "command-a-plus-IQ1_S" not in got


def test_the_port_follows_llamacpp_port(monkeypatch):
    monkeypatch.setenv("LLAMACPP_PORT", "8099")
    assert router.url() == "http://127.0.0.1:8099"
    monkeypatch.delenv("LLAMACPP_PORT")
    assert router.url() == "http://127.0.0.1:8082"


# --- the tiers call it -------------------------------------------------------

def test_the_measure_unloads_its_challenger_however_it_ends(monkeypatch):
    released = []
    monkeypatch.setattr(router, "release_spec",
                        lambda spec, why, **k: released.append(spec))

    def measure(a, row, loaded):
        loaded.append("llamacpp:Challenger-Q4_K_M")
        raise RuntimeError("the run died")
    monkeypatch.setattr(cli, "_measure", measure)
    with pytest.raises(RuntimeError):
        cli._measure_and_adopt(argparse.Namespace(), {"name": "org/c"})
    assert released == ["llamacpp:Challenger-Q4_K_M"]


def test_the_loop_ends_by_settling_the_router(monkeypatch):
    settled = []
    monkeypatch.setattr(router, "settle", lambda why, **k: settled.append(why))

    def spend(a, rc):
        raise RuntimeError("the measure died")
    monkeypatch.setattr(cli, "_loop_spend", spend)
    with pytest.raises(RuntimeError):
        cli._spend_and_settle(argparse.Namespace(), 0)
    assert settled == ["the discovery loop is done"]


class _Done:
    returncode = 0
    stderr = ""


def test_the_screen_unloads_each_candidate_it_ran(monkeypatch, tmp_path):
    import subprocess

    from harness import memory, screen
    from harness import memory_store as ms
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    ms.record(conn, ms.Seen(name="org/c-GGUF", source="t", kind="weights",
                            lane="code", why="seeded"))
    conn.close()
    plan = [{"name": "org/c-GGUF", "state": screen.READY, "modality": "code",
             "candidate": "llamacpp:C-Q4_K_M", "why_not": ""}]
    monkeypatch.setattr(cli, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen"])
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: _Done())
    monkeypatch.setattr(cli, "_receipt_at", lambda out: None)
    released = []
    monkeypatch.setattr(router, "release_spec",
                        lambda spec, why, **k: released.append((spec, why)))
    cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True,
                                          json=False))
    assert released == [("llamacpp:C-Q4_K_M", "screened org/c-GGUF")]


def test_the_suite_never_reaches_the_real_router():
    assert router._get("/models") == {"data": []}

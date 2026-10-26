"""#1282: image-text-to-text cards the text runner cannot build go to the vision lane, labelled through mlx-vlm and llama-server's mmproj."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from evals import vision
from harness import fetching, inspect as ins, lanes, reasons, runner_gaps, screen
from harness import memory_store as ms
from harness.checks import shot_scale as ss
from harness.commands import vision as cmd
from harness.memory_store import revisit

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "evals" / "cases" / "vision"
#: One public, synthetic stand-in frame committed with #1207: the only image these tests read.
FRAME = next(SHIPPED.glob("synthetic-a/*.png"))


def _card(mtype="", tags=(), task="image-text-to-text", library="transformers"):
    return {"pipeline_tag": task, "tags": list(tags), "library_name": library,
            **({"config": {"model_type": mtype}} if mtype else {})}


# --- routing -------------------------------------------------------------------

def test_an_image_text_to_text_card_with_no_ocr_tag_lands_in_vision():
    assert ins.lane_and_source(_card("lfm2_vl")) == ("vision", "card")
    assert ins.lane_and_source(_card("mage_vl", ["vision-language"])) == ("vision", "card")


def test_an_image_text_to_text_card_with_an_ocr_tag_stays_in_ocr():
    assert ins.lane_and_source(_card("lfm2_vl", ["ocr"]))[0] == "ocr"


@pytest.mark.parametrize("card", [
    _card("qwen3_5"), _card("gemma4"), _card(), _card("lfm2_vl", ["gguf"]), _card("lfm2_vl", ["svg"]),
], ids=["mlx-lm-builds-qwen3_5", "mlx-lm-builds-gemma4", "no-type", "gguf", "svg-tag"])
def test_an_image_text_to_text_card_whose_type_mlx_lm_builds_stays_in_code(card):
    assert ins.lane_and_source(card)[0] != "vision"
    assert ins.lane_and_source(_card("qwen3_5"))[0] == "code"


def test_the_vision_route_is_the_same_question_as_the_text_gap():
    for mtype in ("lfm2_vl", "qwen3_5", "cohere_compass", "gemma4"):
        card = {"hf_task": "image-text-to-text", "model_type": mtype}
        gap = runner_gaps.text_gap(card)[1] == f"runner:{runner_gaps.VLM_RUNNER}"
        assert gap == ins.vision_card({"pipeline_tag": "image-text-to-text", "config": {"model_type": mtype}})


# --- the store -------------------------------------------------------------------

def _store(tmp_path):
    return ms.connect(tmp_path / "d.db")


def _seed(conn, name, card, outcome, tier, detail, until="", reason="", lane="code"):
    ms.record(conn, ms.Seen(name=name, source="t", resolved=name, kind="weights", lane=lane,
                            registry=ms.HUGGINGFACE, why="seeded"))
    conn.execute("UPDATE proposals SET hf_task = ?, library = ?, card_tags = ?, model_type = ? WHERE name = ?",
                 (card.get("hf_task", ""), card.get("library", ""), json.dumps(card.get("tags", [])),
                  card.get("model_type", ""), name))
    ms.decide(conn, name, outcome, tier=tier, detail=detail, until=until, reason=reason)


def _row(conn, name):
    return dict(conn.execute("SELECT p.lane, p.lane_source, p.state, v.tier, v.reason, v.detail FROM proposals p "
                             "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone())


def _gateway(error):
    return f'the installed runtime could not load it: chunk-bytes: warm-up: gateway returned HTTP 404: {{"error": "{error}"}}'


def test_a_code_lane_runtime_decline_waiting_on_mlx_vlm_moves_to_vision_and_is_requeued(tmp_path):
    conn = _store(tmp_path)
    try:
        vlm = {"hf_task": "image-text-to-text", "library": "transformers"}
        _seed(conn, "LiquidAI/LFM2.5-VL-3B", {**vlm, "model_type": "lfm2_vl"}, "declined", ms.SCREEN,
              _gateway("Model type lfm2_vl not supported."), until="runner:mlx-vlm", reason=reasons.RUNTIME)
        # mlx-lm builds qwen3_5, so only the screen's own failure says the text runner cannot load this one.
        _seed(conn, "Hcompany/Holo-3.1-0.8B", {**vlm, "model_type": "qwen3_5"}, "declined", ms.SCREEN,
              _gateway("Received 1 parameters not in model: language_model.lm_head.weight."),
              until="runner:mlx-vlm", reason=reasons.RUNTIME)
        _seed(conn, "Qwen/Qwen3.5-0.8B", {**vlm, "model_type": "qwen3_5"}, "screened", ms.SCREEN, "3 case(s) passed")
        # A text runner's format gap is not a vision question: it waits on a format, in code.
        _seed(conn, "org/Qwen3.5-int8", {**vlm, "model_type": "qwen3_5"}, "declined", ms.SCREEN,
              _gateway("Received 984 parameters not in model: lm_head.weight_int8"), until="format:weight_int8",
              reason=reasons.RUNTIME)
        _seed(conn, "org/any", {"hf_task": "any-to-any", "model_type": "lfm2_vl"}, "declined", ms.SCREEN,
              _gateway("Model type lfm2_vl not supported."), until="runner:mlx-vlm", reason=reasons.RUNTIME)
        _seed(conn, "LiquidAI/LFM2-VL-1.6B", {**vlm, "model_type": "lfm2_vl"}, "queued", "fetch",
              "needs its own runner: no runner in the code lane can load it", reason=reasons.HARNESS)
        moved = revisit.relane_to_vision(conn)
        conn.commit()
        assert {m["name"] for m in moved} == {"LiquidAI/LFM2.5-VL-3B", "Hcompany/Holo-3.1-0.8B",
                                              "LiquidAI/LFM2-VL-1.6B"}
        for name in ("LiquidAI/LFM2.5-VL-3B", "Hcompany/Holo-3.1-0.8B"):
            got = _row(conn, name)
            assert got["lane"] == "vision" and got["state"] == "queued" and got["tier"] == ms.INSPECT, got
            assert got["reason"] == reasons.REOPENED
        assert _row(conn, "Hcompany/Holo-3.1-0.8B")["lane_source"] == lanes.SCREENED_SOURCE
        assert _row(conn, "LiquidAI/LFM2.5-VL-3B")["lane_source"] == "card"
        assert _row(conn, "LiquidAI/LFM2-VL-1.6B")["lane"] == "vision"
        assert _row(conn, "LiquidAI/LFM2-VL-1.6B")["tier"] == "fetch", "a queued row moves lane, not state"
        assert _row(conn, "Qwen/Qwen3.5-0.8B")["lane"] == "code"
        assert _row(conn, "org/Qwen3.5-int8")["lane"] == "code" and _row(conn, "org/Qwen3.5-int8")["state"] == "declined"
        assert _row(conn, "org/any")["lane"] == "code", "the vision exam feeds one image; any-to-any is out of scope"
        assert revisit.relane_to_vision(conn) == [], "a second pass moves nothing"
    finally:
        conn.close()


def test_a_lane_the_screen_moved_is_not_moved_back_by_inspect(tmp_path):
    conn = _store(tmp_path)
    try:
        _seed(conn, "Hcompany/Holo-3.1-0.8B", {"hf_task": "image-text-to-text", "model_type": "qwen3_5"},
              "declined", ms.SCREEN, _gateway("Received 1 parameters not in model"),
              until="runner:mlx-vlm", reason=reasons.RUNTIME)
        revisit.relane_to_vision(conn)
        assert not ms.set_lane(conn, "Hcompany/Holo-3.1-0.8B", "code", source="card")
        assert _row(conn, "Hcompany/Holo-3.1-0.8B")["lane"] == "vision"
        _seed(conn, "org/other", {"hf_task": "text-generation"}, "queued", ms.INSPECT, "fits", lane="svg")
        assert ms.set_lane(conn, "org/other", "code", source="card"), "a card still corrects a guess"
    finally:
        conn.close()


def test_fetch_does_not_download_a_vision_candidate_and_names_the_command_that_runs_it(tmp_path, monkeypatch):
    monkeypatch.setattr(fetching.rank, "unrunnable", lambda row, m=None: "")
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts", lambda *a, **k: set())
    conn = _store(tmp_path)
    try:
        name = "LiquidAI/LFM2-VL-1.6B"
        _seed(conn, name, {"hf_task": "image-text-to-text", "model_type": "lfm2_vl", "library": "transformers"},
              "queued", ms.INSPECT, "fits", reason=reasons.CANDIDATE, lane="vision")
        ms.set_size(conn, name, fetching.GIB)
        asked = []
        done = fetching.run(conn, limit=5, free=900 * fetching.GIB,
                            snapshot=lambda *a, **k: asked.append(a) or "",
                            listing=lambda repo: [{"rfilename": "model.safetensors", "size": 100}])
        assert asked == [] and not done[0]["ok"]
        got = _row(conn, name)
        assert got["state"] == "queued" and got["tier"] == "fetch" and got["reason"] == reasons.HARNESS
        assert got["detail"] == f"the vision lane runs by hand: soh vision run --candidate hf-vlm:{name}", got["detail"]
        assert screen.runner_gap("vision", name, conn=conn).startswith("the vision lane runs by hand")
    finally:
        conn.close()


@pytest.mark.parametrize("name,card,spec", [
    ("org/Mage-VL-4bit", {"library": "mlx", "model_type": "mage_vl", "tags": ["mlx"]}, "mlx-vlm:org/Mage-VL-4bit"),
    ("org/VL-GGUF", {"library": "gguf", "tags": ["gguf"]}, "llamacpp-vlm:org/VL-GGUF"),
    ("org/LFM2-VL", {"library": "transformers", "model_type": "lfm2_vl"}, "hf-vlm:org/LFM2-VL"),
    ("org/drive", {"library": "transformers", "model_type": "mage_vl"}, "mlx-vlm:org/drive"),
])
def test_a_vision_candidate_is_spelled_for_the_labeller_that_loads_its_weights(name, card, spec, monkeypatch):
    monkeypatch.setattr(runner_gaps, "native_in_transformers", lambda t: t == "lfm2_vl")
    assert vision.candidate_for(name, card) == spec


def test_the_mlx_vlm_snapshot_names_the_types_the_pin_builds():
    pin, types = runner_gaps.mlx_vlm_types()
    versions = (ROOT / "scripts" / "versions.sh").read_text(encoding="utf-8")
    assert pin.startswith("mlx-vlm==") and f'MLX_VLM_PIN="{pin}"' in versions
    assert {"lfm2_vl", "qwen2_5_vl", "smolvlm", "granite4_vision"} <= types
    assert "qwen_drive" not in types


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:MLX_VLM_VENV")
def test_the_mlx_vlm_snapshot_is_rewritten_from_the_venv_source_without_importing_it(tmp_path, monkeypatch):
    site = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    pkg = site / "mlx_vlm"
    (pkg / "models" / "smolvlm").mkdir(parents=True)
    (pkg / "models" / "smolvlm" / "__init__.py").write_text("raise SystemExit('imported')\n", encoding="utf-8")
    (pkg / "models" / "base.py").write_text("", encoding="utf-8")
    (pkg / "utils.py").write_text("raise SystemExit('imported')\nMODEL_REMAPPING = {'lfm2-vl': 'lfm2_vl'}\n",
                                  encoding="utf-8")
    (site / "mlx_vlm-9.9.9.dist-info").mkdir()
    monkeypatch.setenv("MLX_VLM_VENV", str(tmp_path / "venv"))
    out = tmp_path / "types.txt"
    assert runner_gaps.write_mlx_vlm(path=out) == 0
    assert out.read_text(encoding="utf-8").splitlines() == ["# mlx-vlm==9.9.9", "lfm2-vl", "smolvlm"]
    monkeypatch.setenv("MLX_VLM_VENV", str(tmp_path / "none"))
    assert runner_gaps.write_mlx_vlm(path=out) == 1


# --- candidates ------------------------------------------------------------------

@pytest.mark.parametrize("candidate,want", [
    ("hf-vlm:org/m", ("hf-vlm", "org/m", "", "", {})),
    ("mlx-vlm:org/m@abc,device=cpu", ("mlx-vlm", "org/m", "abc", "", {"device": "cpu"})),
    ("llamacpp-vlm:org/m-GGUF:Q8_0,device=gpu", ("llamacpp-vlm", "org/m-GGUF", "", "Q8_0", {"device": "gpu"})),
])
def test_a_vision_candidate_parses_into_kind_repo_revision_quant_and_options(candidate, want):
    assert cmd.parse_candidate(candidate) == want


@pytest.mark.parametrize("candidate", ["mlx-vlm:", "mlx-vlm:org/m,device=tpu", "mlx-vlm:org/m,steps=4",
                                       "vlm:org/m", "hf-vlm:org/m:Q4"])
def test_a_vision_candidate_the_labellers_cannot_take_is_refused(candidate, tmp_path):
    with pytest.raises(ValueError):
        cmd.labeller_for(candidate, tmp_path)


def _frames(n=3):
    return vision.load(SHIPPED)[:n]


def test_the_hf_vlm_labeller_puts_the_model_on_the_cpu_when_asked(tmp_path, monkeypatch):
    seen = []

    def fake_run(argv, check=False):
        seen.append(argv)
        out = Path(argv[argv.index("--out") + 1])
        out.write_text("".join(json.dumps({"id": f.id, "reply": "CU"}) + "\n" for f in _frames()), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(cmd.subprocess, "run", fake_run)
    assert cmd.labeller_for("hf-vlm:org/m,device=cpu", tmp_path)(_frames()) == ["CU"] * 3
    argv = seen[0]
    assert argv[argv.index("--device") + 1] == "cpu"
    assert argv[argv.index("--max-new-tokens") + 1] == str(vision.REPLY_MAX_TOKENS)
    seen.clear()
    cmd.labeller_for("hf-vlm:org/m", tmp_path / "gpu")(_frames())
    assert "--device" not in seen[0], "the default device is the accelerator hf-task picks"


# --- mlx-vlm ---------------------------------------------------------------------

@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:MLX_VLM_BIN")
def test_the_mlx_vlm_labeller_answers_every_frame_and_resumes(tmp_path, monkeypatch):
    from harness import mlx_vlm_label
    monkeypatch.delenv("MLX_VLM_BIN", raising=False)
    frames = _frames()
    out = tmp_path / "vlm-answers.jsonl"
    out.write_text(json.dumps({"id": frames[0].id, "reply": "CU"}) + "\n", encoding="utf-8")
    asked, argvs = [], []

    def fake_load(model, revision=None, device="gpu"):
        assert device == "cpu" and model == "org/m" and revision == "abc"

        def ask(image, prompt, max_tokens):
            asked.append(image)
            assert max_tokens == vision.REPLY_MAX_TOKENS and prompt == ss.PROMPT
            return "MS", False
        return ask

    def fake_run(argv, check=False):
        argvs.append(argv)
        assert Path(argv[0]) == ROOT / "scripts" / "mlx-vlm.sh"
        rc = mlx_vlm_label.main(argv[1:], load=fake_load, config=lambda model, revision: {"model_type": "smolvlm"})
        return subprocess.CompletedProcess(argv, rc)
    monkeypatch.setattr(cmd.subprocess, "run", fake_run)
    got = cmd.labeller_for("mlx-vlm:org/m@abc,device=cpu", tmp_path)(frames)
    assert got == ["CU", "MS", "MS"]
    assert asked == [str(f.path) for f in frames[1:]], "the frame already answered is not asked again"
    assert argvs[0][argvs[0].index("--device") + 1] == "cpu"


def test_the_mlx_vlm_labeller_refuses_a_config_that_names_its_own_model_file(tmp_path):
    from harness import hf_task, mlx_vlm_label
    frames = tmp_path / "frames.jsonl"
    frames.write_text(json.dumps({"id": "f0", "image": str(FRAME)}) + "\n", encoding="utf-8")
    loaded = []
    rc = mlx_vlm_label.main(["--model", "org/own", "--frames", str(frames), "--prompt", "p",
                             "--out", str(tmp_path / "a.jsonl")],
                            load=lambda *a, **k: loaded.append(a),
                            config=lambda model, revision: {"model_type": "x", "model_file": "modeling_x.py"})
    assert rc == hf_task.NEEDS_OWN_RUNNER and loaded == []
    assert not (tmp_path / "a.jsonl").exists()


def test_a_reply_cut_at_the_token_budget_is_recorded_as_the_limit(tmp_path):
    from harness import mlx_vlm_label
    frames = tmp_path / "frames.jsonl"
    frames.write_text(json.dumps({"id": "f0", "image": str(FRAME)}) + "\n", encoding="utf-8")
    out = tmp_path / "a.jsonl"
    rc = mlx_vlm_label.main(["--model", "org/m", "--frames", str(frames), "--prompt", "p", "--out", str(out)],
                            load=lambda *a, **k: (lambda image, prompt, max_tokens: ("let me think", True)),
                            config=lambda model, revision: {})
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"id": "f0", "reply": "let me think", "cut": True}


# --- llama-server with an mmproj -------------------------------------------------------

SIBLINGS = [{"rfilename": n, "size": s} for n, s in (
    ("Model-Q4_K_M.gguf", 900), ("Model-Q8_0.gguf", 1700), ("Model-F16.gguf", 3000),
    ("mmproj-Model-F16.gguf", 600), ("mmproj-Model-Q8_0.gguf", 300), ("README.md", 1))]


def test_the_llamacpp_vlm_labeller_picks_the_quant_and_its_mmproj():
    from harness import llama_vlm
    assert llama_vlm.pick(SIBLINGS) == ("Model-Q4_K_M.gguf", "mmproj-Model-F16.gguf")
    assert llama_vlm.pick(SIBLINGS, "Q8_0") == ("Model-Q8_0.gguf", "mmproj-Model-F16.gguf")
    with pytest.raises(ValueError, match="mmproj"):
        llama_vlm.pick([s for s in SIBLINGS if not s["rfilename"].startswith("mmproj")])
    with pytest.raises(ValueError, match="IQ1_S"):
        llama_vlm.pick(SIBLINGS, "IQ1_S")


class FakeServer:
    def __init__(self, argv):
        self.argv, self.ended, self.returncode = argv, False, None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.ended = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.ended = True


class FakeHttp:
    def __init__(self, reply="LS", finish="stop"):
        self.posts, self.reply, self.finish, self.health = [], reply, finish, 0

    def get(self, url, timeout=None):
        self.health += 1
        return type("R", (), {"status_code": 503 if self.health == 1 else 200})()

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        body = {"choices": [{"message": {"content": self.reply}, "finish_reason": self.finish}]}
        return type("R", (), {"status_code": 200, "json": lambda self: body,
                              "raise_for_status": lambda self: None})()


def _llama(tmp_path, monkeypatch, candidate, http):
    from harness import llama_vlm
    started = []

    def popen(argv, **kw):
        started.append(FakeServer(argv))
        return started[-1]
    monkeypatch.setattr(llama_vlm, "files", lambda repo, quant="", revision=None: (
        tmp_path / "Model-Q4_K_M.gguf", tmp_path / "mmproj-Model-F16.gguf"))
    monkeypatch.setattr(llama_vlm, "_popen", popen)
    monkeypatch.setattr(llama_vlm, "_http", http)
    monkeypatch.setattr(llama_vlm.time, "sleep", lambda s: None)
    got = cmd.labeller_for(candidate, tmp_path)(_frames(2))
    return got, started


def test_the_llamacpp_vlm_labeller_starts_llama_server_with_the_model_and_its_mmproj(tmp_path, monkeypatch):
    http = FakeHttp()
    got, started = _llama(tmp_path, monkeypatch, "llamacpp-vlm:org/Model-GGUF", http)
    assert got == ["LS", "LS"] and len(started) == 1
    argv = started[0].argv
    assert Path(argv[0]).name == "llama-server"
    assert argv[argv.index("-m") + 1] == str(tmp_path / "Model-Q4_K_M.gguf")
    assert argv[argv.index("--mmproj") + 1] == str(tmp_path / "mmproj-Model-F16.gguf")
    assert argv[argv.index("--host") + 1] == "127.0.0.1"
    assert argv[argv.index("-c") + 1] == str(vision.LLAMACPP_CTX)
    assert "--offline" in argv and "--device" not in argv
    assert started[0].ended, "the private server is stopped once every frame is answered"
    url, body, timeout = http.posts[0]
    assert url.endswith("/v1/chat/completions") and timeout == vision.REQUEST_TIMEOUT_S
    parts = body["messages"][0]["content"]
    assert parts[0]["type"] == "image_url" and parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[1] == {"type": "text", "text": ss.PROMPT}
    assert body["temperature"] == 0 and body["max_tokens"] == vision.REPLY_MAX_TOKENS


def test_the_llamacpp_vlm_labeller_puts_the_model_on_the_cpu_when_asked(tmp_path, monkeypatch):
    _, started = _llama(tmp_path, monkeypatch, "llamacpp-vlm:org/Model-GGUF,device=cpu", FakeHttp())
    argv = started[0].argv
    assert argv[argv.index("--device") + 1] == "none" and "--no-mmproj-offload" in argv
    assert argv[argv.index("-ngl") + 1] == "0"


def test_a_llama_server_that_never_answers_is_the_harness_and_is_stopped(tmp_path, monkeypatch):
    from harness import llama_vlm
    server = FakeServer(["llama-server"])
    monkeypatch.setattr(llama_vlm, "_popen", lambda argv, **kw: server)
    monkeypatch.setattr(llama_vlm, "_http", type("H", (), {"get": lambda self, u, timeout=None: (_ for _ in ()).throw(
        OSError("refused"))})())
    clock = iter(range(0, 10_000, 100))
    monkeypatch.setattr(llama_vlm.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(llama_vlm.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match=f"{vision.LLAMACPP_START_S}"):
        with llama_vlm.serve(tmp_path / "m.gguf", tmp_path / "mm.gguf"):
            pass
    assert server.ended


def test_a_cut_llama_reply_is_kept_and_marked(tmp_path, monkeypatch):
    _llama(tmp_path, monkeypatch, "llamacpp-vlm:org/Model-GGUF", FakeHttp(reply="thinking", finish="length"))
    lines = [json.loads(x) for x in (tmp_path / "vlm-answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(x["cut"] is True and x["reply"] == "thinking" for x in lines)


# --- compare ---------------------------------------------------------------------

def _run(tmp_path, name, answers, truth, films):
    d = tmp_path / name
    d.mkdir()
    (d / "answers.jsonl").write_text("".join(
        json.dumps({"id": f"x{i}", "film": f, "truth": t, "answer": a, "reply": a}) + "\n"
        for i, (a, t, f) in enumerate(zip(answers, truth, films))), encoding="utf-8")
    return d


def test_compare_reports_the_kappa_difference_with_an_interval(tmp_path):
    import random
    rng = random.Random(3)
    truth = [rng.choice(ss.LADDER) for _ in range(400)]
    films = ["a" if i % 2 else "b" for i in range(400)]
    good = [t if rng.random() < 0.8 else rng.choice(ss.LADDER) for t in truth]
    same = list(good)
    bad = [rng.choice(ss.LADDER) for _ in truth]
    a, b, c = (_run(tmp_path, n, x, truth, films) for n, x in (("a", good), ("b", same), ("c", bad)))
    alike = cmd.compare(a, b)
    assert alike["diff"] == 0.0 and alike["agree"] == 1.0 and alike["low"] <= 0.0 <= alike["high"]
    apart = cmd.compare(a, c)
    assert apart["diff"] > 0.5 and 0.0 < apart["low"] < apart["diff"] < apart["high"], apart
    assert apart["n"] == 400 and apart["films"] == 2
    assert apart["knobs"] == {"vision_compare_draws": vision.COMPARE_DRAWS, "vision_compare_level": vision.COMPARE_LEVEL}


def test_compare_refuses_two_runs_over_different_frames(tmp_path):
    a = _run(tmp_path, "a", ["CU"] * 3, ["CU"] * 3, ["a"] * 3)
    b = tmp_path / "b"
    b.mkdir()
    (b / "answers.jsonl").write_text(json.dumps({"id": "y0", "film": "a", "truth": "CU", "answer": "CU"}) + "\n",
                                     encoding="utf-8")
    with pytest.raises(ValueError, match="no frame"):
        cmd.compare(a, b)


def test_a_run_records_the_labeller_limits_it_ran_under(tmp_path):
    got = vision.run_exam(_frames(), vision.size_labeller, tmp_path / "r", "size",
                          knobs={"vision_reply_max_tokens": vision.REPLY_MAX_TOKENS})
    assert got["knobs"]["vision_reply_max_tokens"] == vision.REPLY_MAX_TOKENS
    rows = [json.loads(x) for x in (tmp_path / "r" / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {"film", "truth"} <= set(rows[0])


def test_a_run_limited_to_one_film_labels_only_its_frames(tmp_path, capsys):
    seen = []
    rc = cmd.run_command(cases=str(SHIPPED), candidate="size", out=str(tmp_path / "r"), film="synthetic-b",
                         label=lambda fr: seen.extend(fr) or vision.size_labeller(fr))
    assert rc == 0 and seen and {f.film for f in seen} == {"synthetic-b"}
    with pytest.raises(ValueError, match="no frame of film"):
        cmd.run_command(cases=str(SHIPPED), candidate="size", out=str(tmp_path / "s"), film="nope")


def test_no_test_here_reads_a_private_frame():
    assert FRAME.is_relative_to(SHIPPED) and os.path.getsize(FRAME) < 10_000

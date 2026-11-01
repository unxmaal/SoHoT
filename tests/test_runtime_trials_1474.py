"""Runtime upgrades as candidates: watch, sandboxed trial install, re-screen of waiting declines, paired verdict, surfacing. #1474."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from harness import morning, reasons
from harness import memory_store as ms
from harness import runtime_trials as rtt
from harness.commands import morning as morning_cmd

REPO = Path(__file__).resolve().parents[1]
MLX = rtt.RUNTIMES["mlx-lm"]
LLAMA = rtt.RUNTIMES["llama.cpp"]
INCUMBENT = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
NOW = 1_800_000_000.0
ROOMY = 10 ** 15


def _store(tmp_path):
    return ms.connect(tmp_path / "d.db")


def _decline(conn, name, lane, model_type, until):
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights", lane=lane, why="seeded"))
    conn.execute("UPDATE proposals SET model_type = ? WHERE name = ?", (model_type, name))
    from harness import candidates
    cid = candidates.ensure(conn, name, proposal=name, lane=lane)
    ms.decide(conn, name, "declined", tier=ms.SCREEN, until=until, reason=reasons.RUNTIME, candidate_id=cid,
              detail=f"the installed runtime could not load it: Model type {model_type} not supported.")


def _channels(latest=None):
    """PyPI and GitHub fakes: every runtime's newest release is its pin unless `latest` plants a newer one."""
    latest = latest or {}
    asked = []

    def get_json(url):
        asked.append(url)
        pkg = re.search(r"pypi/([^/]+)/json", url).group(1)
        rt = rtt.RUNTIMES[pkg]
        return {"info": {"version": latest.get(pkg) or rtt.repo_pin(rt) or "0.0.1"}}

    def gh(path):
        asked.append(path)
        return json.dumps({"tag_name": f"b{latest.get('llama.cpp', '1')}"})
    return get_json, gh, asked


def _uv(version="0.33.0", types=("llama", "zaya"), fail=""):
    """A fake run for the sandboxed uv steps: `uv venv` makes a venv, `uv pip install` plants the mlx_lm source."""
    calls = []

    def run(argv, cwd=None, env=None, **kw):
        calls.append({"argv": [str(a) for a in argv], "cwd": cwd, "env": env})
        cmd = [str(a) for a in argv[5:]]
        if fail and fail in " ".join(cmd):
            return subprocess.CompletedProcess(argv, 1, "", "No solution found when resolving dependencies")
        if cmd[1] == "venv":
            (Path(cmd[-1]) / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
        elif cmd[1:3] == ["pip", "install"]:
            site = Path(cmd[cmd.index("--python") + 1]).parents[1] / "lib" / "python3.12" / "site-packages"
            (site / f"mlx_lm-{version}.dist-info").mkdir()
            (site / "mlx_lm" / "models").mkdir(parents=True)
            for t in types:
                (site / "mlx_lm" / "models" / f"{t}.py").write_text("", encoding="utf-8")
            (site / "mlx_lm" / "utils.py").write_text("MODEL_REMAPPING = {'mistral': 'llama'}\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "ok\n", "")
    run.calls = calls
    return run


def _rows(old, new, spec=INCUMBENT, rt=MLX, pin="0.32.0", version="0.33.0"):
    return ([{"candidate": rtt.arm(spec, rt, pin), "case_id": f"c{i}", "passed": v} for i, v in enumerate(old)]
            + [{"candidate": rtt.arm(spec, rt, version), "case_id": f"c{i}", "passed": v} for i, v in enumerate(new)])


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setattr(rtt, "can_sandbox", lambda platform=None: True)


def _night(conn, tmp_path, run, measure, notify):
    get_json, gh, _ = _channels({"mlx-lm": "0.33.0"})
    watched = rtt.watch(conn, {"mlx-lm": "0.32.0"}, get_json=get_json, gh=gh, now=NOW)
    tried = rtt.trial(conn, run=run, measure=measure, notify=notify, home=tmp_path / "home", platform="darwin",
                      machine="arm64", incumbent_of={"code": INCUMBENT}.get, now=NOW, free=ROOMY)
    return watched, tried


def test_a_planted_release_is_proposed_trialled_rescreened_and_bumped_only_when_incumbents_hold(tmp_path, sandbox):
    conn = _store(tmp_path)
    _decline(conn, "Zyphra/ZAYA1-8B", "code", "zaya", "runner:transformers")
    _decline(conn, "convaiinnovations/laya", "decide", "laya", "version:mlx-lm>0.32.0")
    _decline(conn, "TokenRhythm/NeoHorse-1-4B", "code", "qwen3_5_text", "runner:transformers")
    _decline(conn, "ampixa/sanoTTS", "tts", "", "version:mlx-audio>0.5.3")
    run, measured, pushed = _uv(), [], []

    def measure(rt, version, t, served):
        measured.append((rt.name, version, served))
        return {"code": _rows([True] * 12 + [False] * 8, [True] * 13 + [False] * 7)}
    watched, tried = _night(conn, tmp_path, run, measure, lambda *a: pushed.append(a) or "notified")
    assert [w["runtime"] for w in watched if w["proposed"]] == ["mlx-lm"]
    assert measured == [("mlx-lm", "0.33.0", [("code", INCUMBENT)])]
    (got,) = tried
    assert got["outcome"] == rtt.HELD, got
    assert got["body"].startswith("Bump mlx-lm 0.32.0 -> 0.33.0, `mlx-lm` in uv.lock.")
    assert f"| code | {INCUMBENT} | 1 | 0 |" in got["body"]
    assert "- Zyphra/ZAYA1-8B (code, zaya)" in got["body"] and "laya" not in got["body"].split("reopened")[1]
    assert pushed == []
    row = conn.execute("SELECT outcome, evidence FROM runtime_trials WHERE runtime = 'mlx-lm'").fetchone()
    screens = {r["name"]: r["screen"] for r in json.loads(row["evidence"])["rescreen"]}
    assert screens == {"Zyphra/ZAYA1-8B": rtt.BUILDS, "convaiinnovations/laya": rtt.MISSING}
    assert json.loads(row["evidence"])["body"] == got["body"]


def test_a_planted_regression_keeps_the_pin_names_the_lane_and_pushes(tmp_path, sandbox):
    conn = _store(tmp_path)
    pushed = []

    def measure(rt, version, t, served):
        return {"code": _rows([True] * 20, [False] * 20)}
    _, (got,) = _night(conn, tmp_path, _uv(), measure, lambda *a: pushed.append(a) or "notified")
    assert (got["outcome"], got["lane"], got["body"]) == (rtt.REGRESSED, "code", "")
    assert "regressed the code lane's incumbent" in got["detail"] and "the pin stays at 0.32.0" in got["detail"]
    assert pushed and pushed[0][0] == rtt.NOTIFY_TITLE and "code lane" in pushed[0][1]


def test_a_loss_short_of_significance_keeps_the_pin_without_a_push(tmp_path, sandbox):
    conn = _store(tmp_path)
    pushed = []

    def measure(rt, version, t, served):
        return {"code": _rows([True] * 3 + [False] * 17, [True] * 1 + [False] * 19)}
    _, (got,) = _night(conn, tmp_path, _uv(), measure, lambda *a: pushed.append(a) or "notified")
    assert (got["outcome"], got["lane"], got["body"], pushed) == (rtt.KEPT, "code", "", [])


def test_an_unmeasured_incumbent_leaves_the_pin_and_says_which_lane_waits(tmp_path, sandbox):
    conn = _store(tmp_path)
    _, (got,) = _night(conn, tmp_path, _uv(), None, lambda *a: "notified")
    assert got["outcome"] == rtt.UNMEASURED and "incumbents of code are measured" in got["detail"], got


def test_a_blocked_install_is_a_push_and_a_morning_need(tmp_path, sandbox):
    conn = _store(tmp_path)
    pushed = []
    _, (got,) = _night(conn, tmp_path, _uv(fail="pip install"), None, lambda *a: pushed.append(a) or "notified")
    assert got["outcome"] == rtt.BLOCKED and "No solution found" in got["detail"], got
    assert pushed and "did not trial-install" in pushed[0][1]
    r = morning.gather(conn, NOW + 60, NOW - 3600, gh=lambda argv: "[]", git=None, where=None,
                       lanes=lambda c: [], stalls=lambda c: [])
    assert [v["outcome"] for v in r["runtimes"]] == [rtt.BLOCKED]
    assert any(n.startswith("runtime mlx-lm 0.32.0 -> 0.33.0 blocked") for n in r["needs"]), r["needs"]
    assert "runtimes  1 upgrade verdict(s)" in morning_cmd.render(r)


def test_every_verdict_reaches_the_morning_brief_but_only_pushed_ones_are_needs(tmp_path, sandbox):
    conn = _store(tmp_path)
    _night(conn, tmp_path, _uv(), None, lambda *a: "notified")
    r = morning.gather(conn, NOW + 60, NOW - 3600, gh=lambda argv: "[]", git=None, where=None,
                       lanes=lambda c: [], stalls=lambda c: [])
    assert [v["outcome"] for v in r["runtimes"]] == [rtt.UNMEASURED]
    assert not any(n.startswith("runtime ") for n in r["needs"])
    assert any("mlx-lm 0.32.0 -> 0.33.0 unmeasured" in ln for ln in morning_cmd.render(r))


def test_the_trial_installs_the_exact_release_from_pypi_into_its_own_dir_under_sandbox_exec(tmp_path, sandbox):
    run = _uv()
    t = rtt.install(MLX, "0.33.0", run=run, home=tmp_path / "home", platform="darwin", machine="arm64")
    assert t.installed and t.dir == (tmp_path / "home" / rtt.TRIALS_DIR / "mlx-lm-0.33.0").resolve(), t
    from evals import repo
    for c in run.calls:
        assert c["argv"][:2] == [repo.SANDBOX_EXEC, "-f"] and c["argv"][4] == f"TASK={t.dir}"
        assert c["cwd"] == t.dir and Path(c["env"]["HOME"]).is_relative_to(t.dir)
        assert Path(c["env"]["UV_CACHE_DIR"]).is_relative_to(t.dir) and c["env"]["UV_NO_CONFIG"] == "1"
    venv, pip, smoke = (c["argv"][5:] for c in run.calls)
    assert venv[-1] == str(t.dir / "venv")
    assert pip[-3:] == ["--index-url", rtt.PYPI_INDEX, "mlx-lm==0.33.0"] and "--no-config" in pip
    assert smoke[1:] == ["-c", "import mlx_lm"]
    profiles = [Path(c["argv"][2]).read_text(encoding="utf-8") for c in run.calls]
    assert "(deny network*)" not in profiles[1] and "(deny network*)" in profiles[2]
    assert all("(deny file-write*)" in p for p in profiles)
    assert rtt.built(MLX, t.site) == {"llama", "zaya", "mistral"}


def test_a_trial_holding_another_version_than_asked_is_blocked(tmp_path):
    t = rtt.install(MLX, "0.33.0", run=_uv(version="0.32.9"), home=tmp_path, platform="darwin", machine="arm64")
    assert not t.installed and "holds mlx-lm 0.32.9, not 0.33.0" in t.why


def test_the_watch_proposes_once_skips_prereleases_and_survives_an_unreachable_channel(tmp_path):
    conn = _store(tmp_path)
    get_json, gh, _ = _channels({"mlx-lm": "0.33.0", "diffusers": "0.41.0rc1"})

    def flaky(url):
        if "mlx-audio" in url:
            raise OSError("connection reset")
        return get_json(url)
    first = {w["runtime"]: w for w in rtt.watch(conn, {"mlx-lm": "0.32.0"}, get_json=flaky, gh=gh, now=NOW)}
    again = {w["runtime"]: w for w in rtt.watch(conn, {"mlx-lm": "0.32.0"}, get_json=flaky, gh=gh, now=NOW)}
    assert first["mlx-lm"]["proposed"] and not again["mlx-lm"]["proposed"]
    assert not first["diffusers"]["proposed"] and "could not read pypi" in first["mlx-audio"]["why"]
    assert first["mflux"]["why"] == "not pinned or installed here"
    assert [r["runtime"] for r in rtt.proposed(conn)] == ["mlx-lm"]


def test_the_repo_pins_are_read_where_the_deploy_pins_them():
    text = (REPO / "scripts" / "versions.sh").read_text(encoding="utf-8")
    assert rtt.repo_pin(rtt.RUNTIMES["mlx-vlm"]) == re.search(r'^MLX_VLM_PIN="mlx-vlm==([^"]+)"', text, re.M).group(1)
    assert rtt.repo_pin(LLAMA) == re.search(r'^LLAMACPP_BUILD="b(\d+)"', text, re.M).group(1)
    lock = (REPO / "uv.lock").read_text(encoding="utf-8")
    assert rtt.repo_pin(MLX) == re.search(r'^name = "mlx-lm"\nversion = "([^"]+)"', lock, re.M).group(1)
    assert rtt.repo_pin(rtt.RUNTIMES["mflux"]) == ""
    assert rtt.pinned(LLAMA, {"llama.cpp": "11146"}) == "11146"


def test_only_a_final_release_past_the_pin_is_newer():
    assert rtt.newer("0.33.0", "0.32.0") and rtt.newer("11200", "11146")
    assert not rtt.newer("0.32.0", "0.32.0") and not rtt.newer("0.31.9", "0.32.0")
    assert not rtt.newer("0.33.0rc1", "0.32.0") and not rtt.newer("0.33.0.dev1", "0.32.0")
    assert not rtt.newer("0.33.0", "") and not rtt.newer("garbage", "0.32.0")


def test_the_declines_a_runtime_unblocks_are_the_ones_whose_until_names_it(tmp_path):
    conn = _store(tmp_path)
    _decline(conn, "a/zaya", "code", "zaya", "runner:transformers")
    _decline(conn, "a/qwen", "code", "qwen3_5_text", "runner:transformers")
    _decline(conn, "a/vlm", "code", "lfm2_vl", "runner:mlx-vlm")
    _decline(conn, "a/k2", "code", "", "version:llama.cpp>11146")
    _decline(conn, "a/ocr", "ocr", "hrm_text", "version:hf-task/transformers>5.17.0")
    names = {n: [r["name"] for r in rtt.waiting(conn, rtt.RUNTIMES[n])] for n in rtt.RUNTIMES}
    assert names["mlx-lm"] == ["a/zaya"] and names["mlx-vlm"] == ["a/vlm"] and names["llama.cpp"] == ["a/k2"]
    assert names["transformers"] == ["a/zaya", "a/qwen", "a/ocr"] and names["mflux"] == []


def test_a_load_is_the_only_screen_for_a_runtime_whose_source_names_no_types(tmp_path):
    got = rtt.rescreen(LLAMA, [{"name": "a/k2", "lane": "code", "until": "version:llama.cpp>1", "model_type": ""}],
                       rtt.built(LLAMA, tmp_path))
    assert [g["screen"] for g in got] == [rtt.UNKNOWN]


def test_each_lane_spec_maps_to_the_runtime_that_serves_it(monkeypatch):
    from harness import serving
    engines = {"q3-30b": serving.LLAMACPP, "claude": serving.HOSTED}
    monkeypatch.setattr(serving, "engine_for", lambda spec, *a, **k: engines.get(spec, serving.DEFAULT))
    assert rtt.runtime_of(INCUMBENT) == "mlx-lm" and rtt.runtime_of("q3-30b") == "llama.cpp"
    assert rtt.runtime_of("claude") == "" and rtt.runtime_of("mlx-community/Kokoro-82M-bf16", "tts") == "mlx-audio"
    assert rtt.runtime_of("llamacpp:unsloth/Qwen3-4B-GGUF") == "llama.cpp"
    assert rtt.runtime_of("diffusers:org/x") == "diffusers" and rtt.runtime_of("mflux:dev") == "mflux"
    assert rtt.runtime_of("hf-ocr:org/x") == "transformers" and rtt.runtime_of("tts:org/x") == "mlx-audio"
    assert rtt.runtime_of("rerank:org/x") == "" and rtt.runtime_of("bm25") == ""


def _release(tag, name, url, digest=""):
    return json.dumps({"tag_name": tag, "assets": [{"name": name, "browser_download_url": url, "digest": digest}]})


def _llama_run(payload=b"zip"):
    calls = []

    def run(argv, cwd=None, env=None, **kw):
        cmd = [str(a) for a in argv[5:]]
        calls.append(cmd)
        if cmd[0] == "/usr/bin/curl":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(payload)
        elif cmd[0] in ("/usr/bin/tar", "/usr/bin/ditto"):
            (Path(cmd[-1]) / "bin").mkdir(parents=True)
            (Path(cmd[-1]) / "bin" / "llama-server").write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "version: 11200\n", "")
    run.calls = calls
    return run


def test_llama_cpp_installs_the_release_asset_from_its_github_release_and_checks_its_digest(tmp_path):
    name = "llama-b11200-bin-macos-arm64.tar.gz"
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/b11200/{name}"
    run = _llama_run()
    gh = lambda path: _release("b11200", name, url, "sha256:" + hashlib.sha256(b"zip").hexdigest())  # noqa: E731
    t = rtt.install(LLAMA, "11200", run=run, gh=gh, home=tmp_path, platform="darwin", machine="arm64")
    assert t.installed, t.why
    assert run.calls[0][:5] == ["/usr/bin/curl", "-fsSL", "--proto", "=https", "-o"] and run.calls[0][-1] == url
    assert run.calls[1][:2] == ["/usr/bin/tar", "-xzf"] and run.calls[1][-1] == str(t.dir / "build")
    assert run.calls[-1][1:] == ["--version"] and Path(run.calls[-1][0]).is_relative_to(t.dir)
    bad = lambda path: _release("b11200", name, url, "sha256:" + "0" * 64)  # noqa: E731
    t = rtt.install(LLAMA, "11200", run=_llama_run(), gh=bad, home=tmp_path, platform="darwin", machine="arm64")
    assert not t.installed and "does not match the release's sha256" in t.why


def test_an_older_zip_release_is_unpacked_with_ditto(tmp_path):
    name = "llama-b11200-bin-macos-arm64.zip"
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/b11200/{name}"
    run = _llama_run()
    t = rtt.install(LLAMA, "11200", run=run, gh=lambda path: _release("b11200", name, url), home=tmp_path,
                    platform="darwin", machine="arm64")
    assert t.installed and run.calls[1][:3] == ["/usr/bin/ditto", "-x", "-k"], (t.why, run.calls)


def test_a_versioned_llama_cpp_release_is_read_as_the_build_it_names():
    url = "https://github.com/ggml-org/llama.cpp/releases/download/v0.8.0/nightly-tag.txt"
    gh = lambda path: _release("v0.8.0", "nightly-tag.txt", url)  # noqa: E731
    assert rtt.latest(LLAMA, gh=gh, get_text=lambda u: "b11960\n" if u == url else "") == "11960"
    assert rtt.latest(LLAMA, gh=lambda path: json.dumps({"tag_name": "b12000"})) == "12000"
    off = lambda path: _release("v0.8.0", "nightly-tag.txt", "https://example.com/nightly-tag.txt")  # noqa: E731
    with pytest.raises(ValueError, match="names no build tag"):
        rtt.latest(LLAMA, gh=off, get_text=lambda u: "b1")


def test_an_asset_served_off_the_release_channel_is_refused_before_any_download(tmp_path):
    name = "llama-b11200-bin-macos-arm64.tar.gz"
    run = _llama_run()
    gh = lambda path: _release("b11200", name, f"https://example.com/{name}")  # noqa: E731
    t = rtt.install(LLAMA, "11200", run=run, gh=gh, home=tmp_path, platform="darwin", machine="arm64")
    assert not t.installed and "outside ggml-org/llama.cpp's release downloads" in t.why and run.calls == []
    t = rtt.install(LLAMA, "11200", run=run, gh=gh, home=tmp_path, platform="linux", machine="x86_64")
    assert not t.installed and "no release asset" in t.why and run.calls == []


def test_a_host_without_sandbox_exec_installs_nothing_and_leaves_the_proposal(tmp_path, monkeypatch):
    conn = _store(tmp_path)
    get_json, gh, _ = _channels({"mlx-lm": "0.33.0"})
    rtt.watch(conn, {"mlx-lm": "0.32.0"}, get_json=get_json, gh=gh, now=NOW)
    run = _uv()
    got = rtt.trial(conn, run=run, home=tmp_path, platform="linux")
    assert [g["outcome"] for g in got] == [rtt.PROPOSED] and run.calls == []
    assert [r["runtime"] for r in rtt.proposed(conn)] == ["mlx-lm"]


def test_a_disk_under_the_floor_installs_nothing_and_leaves_the_proposal(tmp_path, sandbox):
    from harness import fetching
    conn = _store(tmp_path)
    get_json, gh, _ = _channels({"mlx-lm": "0.33.0"})
    rtt.watch(conn, {"mlx-lm": "0.32.0"}, get_json=get_json, gh=gh, now=NOW)
    run = _uv()
    got = rtt.trial(conn, run=run, home=tmp_path, platform="darwin", free=fetching.DISK_FLOOR - 1)
    assert [g["outcome"] for g in got] == [rtt.PROPOSED] and "disk floor" in got[0]["detail"] and run.calls == []
    assert [r["runtime"] for r in rtt.proposed(conn)] == ["mlx-lm"]


def test_one_release_per_loop_is_trialled_and_older_trial_dirs_are_pruned(tmp_path, sandbox):
    conn = _store(tmp_path)
    old = rtt.trial_dir(MLX, "0.32.5", tmp_path / "home")
    old.mkdir(parents=True)
    get_json, gh, _ = _channels({"mlx-lm": "0.33.0", "mlx-audio": "0.6.0"})
    rtt.watch(conn, {"mlx-lm": "0.32.0"}, get_json=get_json, gh=gh, now=NOW)
    tried = rtt.trial(conn, run=_uv(), home=tmp_path / "home", platform="darwin", machine="arm64",
                      incumbent_of=lambda lane: "", free=ROOMY)
    assert [t["runtime"] for t in tried] == ["mlx-lm"] and [r["runtime"] for r in rtt.proposed(conn)] == ["mlx-audio"]
    assert tried[0]["outcome"] == rtt.HELD and "no incumbent could regress" in tried[0]["body"]
    assert not old.exists() and rtt.trial_dir(MLX, "0.33.0", tmp_path / "home").exists()


def test_the_loop_trials_runtimes_in_its_guarded_repairs_and_a_refused_channel_proposes_nothing(tmp_path, monkeypatch,
                                                                                                capsys):
    from harness.commands import loop
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    assert loop._trial_runtimes() == []
    out = capsys.readouterr().out
    assert "=== runtime upgrades ===" in out and "could not read" in out
    assert "_trial_runtimes" in (REPO / "harness" / "commands" / "loop.py").read_text(encoding="utf-8").split(
        "def _run_loop_held")[1].split("rc = _repair")[0]

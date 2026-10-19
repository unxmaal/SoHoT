"""#1024: a whisper repo screens in the uv whisper group's own env, and every package until names a package some deploy step installs."""
import sys

import pytest

from harness import live_audit, paths, reasons, reverify, runner_gaps, screen, verify
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from harness.memory_store import revisit, transitions

WHISPER = "mlx-community/whisper-large-v3-mlx"
IN_PROCESS = f"stt:{WHISPER},backend=whisper"
NO_PROCESSOR = ("it ran and passed nothing: 1089-134686-0001: stt response had no 'text': {'error': {'message': "
                "'Processor not found. Make sure the model was loaded with a HuggingFace processor.', "
                "'type': 'ValueError'}}")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.delenv("WHISPER_VENV", raising=False)
    return tmp_path


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _group_env(home):
    return ["env", "-u", "VIRTUAL_ENV", f"UV_PROJECT_ENVIRONMENT={home / 'venvs' / 'whisper'}",
            "uv", "run", "--group", "whisper", "python", "-m", "evals.run"]


def test_whisper_large_v3_screens_through_the_whisper_runner_in_the_groups_env(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    row, = screen.plan([{"name": WHISPER, "lane": "stt"}], missing=lambda target: [])
    assert (row["state"], row["candidate"]) == (screen.READY, IN_PROCESS)
    argv = screen.argv(row)
    assert argv[:11] == _group_env(home)
    assert argv[argv.index("--candidates") + 1] == IN_PROCESS
    # The env's own venv is never this interpreter's, and nothing is installed before the run builds it.
    assert not (home / "venvs" / "whisper").exists()
    assert revisit.until_met("package:mlx-whisper@whisper", {})


def test_an_mlx_audio_spec_keeps_this_interpreter(home):
    row = {"name": "mlx-community/parakeet-tdt-0.6b-v2", "modality": "stt",
           "candidate": "stt:mlx-community/parakeet-tdt-0.6b-v2"}
    assert screen.argv(row)[:3] == [sys.executable or "python", "-m", "evals.run"]


def test_where_the_group_cannot_install_it_the_screen_names_the_missing_env(home, monkeypatch, store):
    monkeypatch.setattr(sys, "platform", "linux")
    assert screen.candidate_for("stt", WHISPER) == f"stt:{WHISPER}"
    cls = reasons.classify(NO_PROCESSOR, reasons.RUNNER, f"stt:{WHISPER}")
    v = screen.decide_class(cls, NO_PROCESSOR, f"stt:{WHISPER}")
    assert (v.outcome, v.reason, v.until) == ("declined", reasons.RUNTIME, "package:mlx-whisper@whisper")
    assert not revisit.until_met(v.until, {})
    _decline(store, WHISPER, v.until, reasons.LOAD_FAILED_LAYOUT, NO_PROCESSOR, f"stt:{WHISPER}")
    got = live_audit.unreachable_packages(store)
    assert [r["until"] for r in got] == ["package:mlx-whisper@whisper"]
    assert "no deploy step installs it" in live_audit._package_until_reachable(store)[0]


def test_every_evals_run_launch_of_a_whisper_spec_uses_the_group_env(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    class Plan:
        repeat, side, budget_s, estimate = 1, "all", None, {}
    argv = measure_cmd._argv("stt", Plan(), home / "out", "stt:mlx-community/parakeet-tdt-0.6b-v2", IN_PROCESS)
    assert argv[:11] == _group_env(home)
    item = {"spec": IN_PROCESS, "incumbent": "", "lane": "stt"}
    assert reverify.argv(item)[:11] == _group_env(home)
    task, = verify.plan([{"lane": "stt", "serves": IN_PROCESS, "unverified": True, "stale": False}])
    assert task.argv[:11] == _group_env(home)
    # A tts candidate scored by the whisper ear imports mlx-whisper too.
    assert runner_gaps.venv_of("tts:mlx-community/Kokoro-82M-bf16,voice=ff_siwis,ear=whisper:fr") == "whisper"
    assert runner_gaps.launcher(["tts:mlx-community/Kokoro-82M-bf16"], ["x"]) == ["x"]


def test_a_package_a_whisper_run_lacks_waits_on_the_whisper_env():
    text = "Traceback ...\nModuleNotFoundError: No module named 'sentencepiece'"
    assert runner_gaps.package_until(text, IN_PROCESS) == "package:sentencepiece@whisper"


def _decline(conn, name, until, cls, detail, spec):
    from harness import candidates
    ms.record(conn, ms.Seen(name=name, source="t", registry=ms.HUGGINGFACE, lane="stt", resolved=name))
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    cid = candidates.ensure(conn, spec, proposal=name, lane="stt")
    transitions._write(conn, pid, name, {"outcome": "declined", "tier": "screen", "detail": detail,
                                         "decided_at": 1792410700.0, "until": until, "reason": reasons.RUNTIME,
                                         "failure_class": cls, "candidate_id": cid, "run_id": None})
    conn.commit()


def test_the_pre_1024_whisper_until_is_rewritten_to_the_groups_env(store, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    _decline(store, WHISPER, "package:mlx-whisper", reasons.LOAD_FAILED_LAYOUT, NO_PROCESSOR, f"stt:{WHISPER}")
    assert not revisit.until_met("package:mlx-whisper", {"packages": {"": set()}})
    got, = revisit.runner_gap_rewrites(store)
    assert (got["until"], got["new"]) == ("package:mlx-whisper", "package:mlx-whisper@whisper")
    # The rewrite's own check reports it; the reachability check does not report it twice.
    assert live_audit.unreachable_packages(store) == []
    revisit.rewrite_runner_gap_untils(store)
    assert revisit.runner_gap_rewrites(store) == []
    assert live_audit.unreachable_packages(store) == []


def test_the_audit_lists_one_row_per_package_no_deploy_step_installs(store):
    _decline(store, "a/pipe", "package:ftfy@diffusers-cuda", reasons.MISSING_PACKAGE, "x", "diffusers:a/pipe")
    _decline(store, "b/pipe", "package:opencv-python@diffusers-cuda", reasons.MISSING_PACKAGE, "x", "diffusers:b/pipe")
    _decline(store, "c/pipe", "package:opencv-python@diffusers-cuda", reasons.MISSING_PACKAGE, "x", "diffusers:c/pipe")
    got = live_audit.unreachable_packages(store)
    assert len(got) == 1 and got[0]["until"] == "package:opencv-python@diffusers-cuda" and len(got[0]["ids"]) == 2


def test_installs_reads_each_venvs_deploy_step(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert {"ftfy", "beautifulsoup4", "sentencepiece", "torch", "diffusers"} <= runner_gaps.installs("diffusers-cuda")
    assert {"transformers", "sentence-transformers", "torch"} <= runner_gaps.installs("hf-task")
    assert "mlx-whisper" in runner_gaps.installs("whisper")
    assert "mlx-whisper" not in runner_gaps.installs("")
    assert runner_gaps.installs("no-such-venv") == frozenset()
    monkeypatch.setattr(sys, "platform", "linux")
    assert "mlx-whisper" not in runner_gaps.installs("whisper")
    # The CUDA branch of the script pins torch from its own index; the index URL is not a package.
    assert "torch" in runner_gaps.installs("diffusers-cuda")


#: Runner packages a screen can name that no deploy step installs; shrinks as pins land. #1024.
UNINSTALLED = ["einops", "invisible-watermark", "librosa", "note-seq", "onnx", "opencv-python", "peft",
               "protobuf", "scipy", "soundfile", "tiktoken", "timm", "torchsde"]


def test_the_runner_packages_no_deploy_step_installs_are_an_inventory_that_only_shrinks(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    got = runner_gaps.uninstalled_runner_packages()
    assert set(got) <= set(UNINSTALLED), f"a runner package with no deploy step: {sorted(set(got) - set(UNINSTALLED))}"
    assert set(UNINSTALLED) <= set(got), f"installed now, drop from UNINSTALLED: {sorted(set(UNINSTALLED) - set(got))}"
    assert "ftfy" not in got and "beautifulsoup4" not in got


def test_a_held_package_until_the_venv_already_has_is_not_unreachable(store, monkeypatch):
    _decline(store, "b/pipe", "package:opencv-python@diffusers-cuda", reasons.MISSING_PACKAGE, "x", "diffusers:b/pipe")
    monkeypatch.setattr(runner_gaps, "has_package", lambda dist, venv="": dist == "opencv-python")
    assert live_audit.unreachable_packages(store) == []

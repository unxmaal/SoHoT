"""The new-lane loops of jobs 0034-0036: a venv gap read as BROKEN, rc 1 unexplained, MLX OCR fetched. #601."""
import argparse
import contextlib
import dataclasses
import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fakes  # noqa: E402
from evals.core import load_cases  # noqa: E402
from harness import benchmarks as bm  # noqa: E402
from harness import engines, fetching, reasons, screen  # noqa: E402
from harness import memory_store as ms  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES = load_cases(ROOT / "evals" / "cases" / "ocr")
#: What transformers 5.17 raised loading PaddleOCR-VL-1.6's processor in the hf-task venv.
TORCHVISION_MISSING = (
    "\nAutoImageProcessor requires the Torchvision library but it was not found in your "
    "environment. Check out the instructions on the\ninstallation page: "
    "https://pytorch.org/get-started/locally/ and follow the ones that match your "
    "environment.\nPlease note that you may need to restart your runtime after installation.\n")
#: The detail job 0034 recorded on PaddleOCR-VL-1.6's screen verdict.
RECORDED = ("it ran and passed nothing: ocr-invoice-line: exit 1: Please note that you may "
            "need to restart your runtime after installation.")
MLX_OCR = ("mlx-community/DeepSeek-OCR-bf16", "mlx-community/DeepSeek-OCR-2-bf16",
           "mlx-community/PaddleOCR-VL-1.5-bf16")


# --- 1. a package the venv lacks is the harness ------------------------------

def test_the_recorded_backend_gap_is_the_harness_not_the_model():
    detail = RECORDED.split(": ", 2)[-1]
    got = reasons.classify(detail, candidate="hf-ocr:PaddlePaddle/PaddleOCR-VL-1.6")
    assert got == reasons.HARNESS_ERROR
    assert reasons.CLASSES[got] == ("queued", reasons.HARNESS)


def test_hf_task_names_the_missing_package_on_its_last_stderr_line(tmp_path, capsys):
    from harness import hf_task

    def lacks_torchvision(model, image, prompt):
        raise ImportError(TORCHVISION_MISSING)
    rc = hf_task.main(["ocr", "--model", "m/x", "--image", "i.png", "--out",
                       str(tmp_path / "o.txt")], read=lacks_torchvision)
    last = capsys.readouterr().err.strip().splitlines()[-1]
    assert rc == hf_task.MISSING_PACKAGE
    assert "Torchvision" in last
    assert reasons.classify(f"exit {rc}: {last}", candidate="hf-ocr:m/x") \
        == reasons.HARNESS_ERROR


def _shell_var(text: str, name: str) -> str:
    return re.search(rf'^{name}="([^"]+)"', text, re.M).group(1)


def test_the_hf_task_venv_installs_the_torchvision_its_torch_needs():
    pins = (ROOT / "scripts" / "versions.sh").read_text(encoding="utf-8")
    venv = (ROOT / "scripts" / "hf-task-venv.sh").read_text(encoding="utf-8")
    for torch_var, vision_var in (("TORCH_MPS_PIN", "TORCHVISION_MPS_PIN"),
                                  ("TORCH_CUDA_PIN", "TORCHVISION_CUDA_PIN")):
        torch = re.match(r"torch==2\.(\d+)\.\d+(\+\w+)?$", _shell_var(pins, torch_var))
        vision = re.match(r"torchvision==0\.(\d+)\.\d+(\+\w+)?$", _shell_var(pins, vision_var))
        assert torch and vision, (torch_var, vision_var)
        # torchvision 0.N pairs with torch 2.(N-15); a mismatched pair will not import.
        assert int(vision.group(1)) == int(torch.group(1)) + 15
        assert torch.group(2) == vision.group(2)
        assert f'"${vision_var}"' in venv


def test_a_failed_runner_keeps_its_stderr_tail_in_the_run_dir(tmp_path):
    from evals.runners.process import ProcessRunner
    fake = tmp_path / "fail.py"
    fake.write_text("import sys\nfor i in range(100):\n    print(f'line {i}', file=sys.stderr)\n"
                    "sys.exit(1)\n", encoding="utf-8")
    real = engines.resolve("hf-ocr:someorg/a-model")
    eng = dataclasses.replace(real, argv=lambda p, o, params: [sys.executable, str(fake)])
    sign = next(c for c in CASES if c.id == "ocr-sign-open")
    r = ProcessRunner(eng, tmp_path / "out").run(sign)
    assert r.passed is False
    kept = list((tmp_path / "out").glob("*.stderr.txt"))
    assert len(kept) == 1
    text = kept[0].read_text(encoding="utf-8")
    assert text.endswith("line 99\n")
    assert "line 60\n" in text and "line 59\n" not in text


def test_a_runner_that_succeeds_leaves_no_stderr_file(tmp_path):
    from evals.runners.process import ProcessRunner
    fake = tmp_path / "ok.py"
    fake.write_text("import sys\nprint('noise', file=sys.stderr)\n"
                    "open(sys.argv[1], 'w').write('OPEN 24 HOURS')\n", encoding="utf-8")
    real = engines.resolve("hf-ocr:someorg/a-model")
    eng = dataclasses.replace(real, argv=lambda p, o, params: [sys.executable, str(fake), str(o)])
    sign = next(c for c in CASES if c.id == "ocr-sign-open")
    ProcessRunner(eng, tmp_path / "out").run(sign)
    assert not list((tmp_path / "out").glob("*.stderr.txt"))


# --- 4. the recorded verdict is retracted ----------------------------------

def _broken(conn, name, detail):
    ms.record(conn, ms.Seen(name=name, source="t", lane="ocr", registry=ms.HUGGINGFACE,
                            resolved=name))
    ms.decide(conn, name, "broken", tier=ms.SCREEN, detail=detail, reason=reasons.CANDIDATE)


def test_schema_59_requeues_the_screen_a_missing_backend_settled(tmp_path):
    from harness.memory_store.migrations import v59
    conn = ms.connect(tmp_path / "s.db")
    try:
        _broken(conn, "PaddlePaddle/PaddleOCR-VL-1.6", RECORDED)
        _broken(conn, "org/really-broken", "it ran and passed nothing: ocr-invoice-line: CER 0.9")
        v59.data(conn)
        got = dict(conn.execute("SELECT name, state FROM proposals").fetchall())
        assert got == {"PaddlePaddle/PaddleOCR-VL-1.6": "queued", "org/really-broken": "broken"}
        assert ms.SCHEMA_VERSION >= 59
    finally:
        conn.close()


# --- 2. the loop's exit status ----------------------------------------------

def test_a_lane_with_no_benchmark_queries_is_not_a_failed_source():
    conn = ms.connect()
    asked = []
    found = bm.sweep(conn, lanes=["ocr"], get=lambda *a, **k: asked.append(a) or [], now=1.0)
    assert found == [] and asked == []
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE last_status = 'failed'"
                        ).fetchone()[0] == 0


def test_a_scoped_sweep_reports_only_its_own_lanes_failures(monkeypatch, capsys):
    from harness.commands import benchmarks as benchmarks_cmd
    conn = ms.connect()
    ms.record_source(conn, "benchmarks:huggingface:tts", kind=bm.KIND, ok=False,
                     error="HTTP 503", at=1.0)
    conn.close()
    monkeypatch.setattr(bm, "sweep", lambda conn, lanes=None, force=False: [])
    a = argparse.Namespace(lane="code", force=False, json=False)
    assert benchmarks_cmd.sweep_report(a) == 0
    a = argparse.Namespace(lane="tts", force=False, json=False)
    assert benchmarks_cmd.sweep_report(a) == 1
    assert "HTTP 503" in capsys.readouterr().out


def test_the_leftover_failure_of_a_lane_with_no_queries_does_not_fail_the_loop(monkeypatch):
    """Jobs 0034-0036 left benchmarks:*:ocr|retrieval|pii failed with KeyError text."""
    from harness.commands import benchmarks as benchmarks_cmd
    conn = ms.connect()
    ms.record_source(conn, "benchmarks:huggingface:pii", kind=bm.KIND, ok=False,
                     error="'pii'", at=1.0)
    conn.close()
    monkeypatch.setattr(bm, "sweep", lambda conn, lanes=None, force=False: [])
    for lane in ("pii", ""):
        assert benchmarks_cmd.sweep_report(
            argparse.Namespace(lane=lane, force=False, json=False)) == 0


def test_the_loop_says_which_step_made_it_exit_nonzero(monkeypatch):
    from harness.commands import discover as discover_cmd, loop
    monkeypatch.setattr(discover_cmd, "cmd_discover",
                        lambda a: 1 if getattr(a, "sweep", False) else 0)
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        rc = loop._report_loop(argparse.Namespace(run=False, lane="ocr", top=1, json=False))
    assert rc == 1
    assert "exit 1" in err.getvalue() and "sweep" in err.getvalue()


def test_a_clean_loop_says_nothing_about_failing(monkeypatch):
    from harness.commands import discover as discover_cmd, loop
    monkeypatch.setattr(discover_cmd, "cmd_discover", lambda a: 0)
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        assert loop._report_loop(argparse.Namespace(run=False, lane="ocr", top=1,
                                                    json=False)) == 0
    assert "exit" not in err.getvalue()


# --- 3. an MLX conversion has no OCR runner ---------------------------------

@pytest.mark.parametrize("repo", MLX_OCR)
def test_an_mlx_conversion_is_a_runner_gap_for_every_hf_task_engine(repo):
    card = fakes.card(repo)
    facts = {"library": card.get("library_name"), "card_tags": card["tags"],
             "hf_task": card.get("pipeline_tag")}
    for head in sorted(engines.HF_TASK_ENGINES):
        gap = engines.card_gap(f"{head}:{repo}", facts)
        assert gap.startswith("needs its own runner") and "mlx" in gap.lower(), (head, gap)


def test_the_original_paddleocr_is_still_runnable():
    card = fakes.card("PaddlePaddle/PaddleOCR-VL-1.6")
    facts = {"library": card.get("library_name"), "card_tags": card["tags"],
             "hf_task": card.get("pipeline_tag")}
    assert engines.card_gap("hf-ocr:PaddlePaddle/PaddleOCR-VL-1.6", facts) == ""


@pytest.mark.parametrize("repo", MLX_OCR)
def test_the_fetch_tier_refuses_an_mlx_ocr_conversion_before_download(tmp_path, monkeypatch,
                                                                       repo):
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    conn = ms.connect(tmp_path / "s.db")
    try:
        ms.record(conn, ms.Seen(name=repo, source="t", lane="ocr",
                                registry=ms.HUGGINGFACE, resolved=repo))
        ms.set_size(conn, repo, 6 * fetching.GIB)
        fakes.carded(conn, repo, fakes.card(repo))
        ms.decide(conn, repo, "queued", tier="inspect", detail="fits")
        got = fetching.run(conn, {repo: 6 * fetching.GIB}, limit=1, free=500 * fetching.GIB,
                           snapshot=lambda *a, **k: pytest.fail("downloaded an MLX conversion"))
        assert got and not got[0]["ok"], got
        assert screen.runner_gap("ocr", repo, conn=conn)
        assert conn.execute("SELECT state FROM proposals WHERE name = ?",
                            (repo,)).fetchone()["state"] == "queued"
    finally:
        conn.close()

"""PaddleOCR-VL aborted in the MPS backend and was recorded BROKEN. #604."""
import dataclasses
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evals.core import Receipt, artifact_name, comparable, load_cases  # noqa: E402
from harness import engines, reasons, screen  # noqa: E402
from harness import memory_store as ms  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES = load_cases(ROOT / "evals" / "cases" / "ocr")
SPEC = "hf-ocr:PaddlePaddle/PaddleOCR-VL-1.6"
NAME = "PaddlePaddle/PaddleOCR-VL-1.6"
#: The tail of the stderr job 0041 kept beside PaddleOCR-VL-1.6's screen (#602).
ABORT_TAIL = [
    "[transformers] Unrecognized keys in `rope_parameters` for 'rope_type'='default': "
    "{'mrope_section'}",
    'loc("mps_matmul"("(mpsFileLoc): /AppleInternal/Library/MPSGraphUtilities.mm":48:0)): '
    "error: incompatible dimensions",
    'loc("mps_matmul"("(mpsFileLoc): /AppleInternal/Library/MPSGraphUtilities.mm":48:0)): '
    "error: invalid shape",
    "LLVM ERROR: Failed to infer result type(s):",
    '"mps.matmul"(...) {} : (tensor<1x16x200x128xf16>, tensor<1x2x128x200xf16>) -> ( ??? )',
    "/opt/python/lib/python3.12/multiprocessing/resource_tracker.py:279: UserWarning: "
    "resource_tracker: There appear to be 1 leaked semaphore objects to clean up at shutdown",
    "  warnings.warn('resource_tracker: There appear to be %d '",
]
#: The detail job 0041 recorded: the last stderr line, which is not the abort.
RECORDED = ("it ran and passed nothing: ocr-invoice-line: exit -6:   "
            "warnings.warn('resource_tracker: There appear to be %d '")
MPSGRAPH_ASSERT = ("/AppleInternal/Library/MPSGraph/MPSGraphExecutable.mm:1203: failed "
                   "assertion `Error: MPSGraph does not support tensor dims larger than INT_MAX'")


# --- 1. an MPS backend abort is a runtime fault, not the model ---------------

def test_an_llvm_mps_abort_is_a_backend_fault_that_reopens_on_a_newer_runtime():
    got = reasons.classify("exit -6: " + " ".join(ABORT_TAIL[3:5]), candidate=SPEC)
    assert got == reasons.BACKEND_FAULT
    assert reasons.CLASSES[got] == ("declined", reasons.RUNTIME)


def test_an_mpsgraph_assertion_is_a_backend_fault():
    assert reasons.classify(MPSGRAPH_ASSERT, candidate=SPEC) == reasons.BACKEND_FAULT
    assert reasons.classify(MPSGRAPH_ASSERT, reasons.STDERR, SPEC) == reasons.BACKEND_FAULT


@pytest.mark.parametrize("text", [
    "LLVM ERROR: out of memory",
    "exit 1: ValueError: shapes (3,) and (4,) not aligned",
    # OmniSVG's oversized buffer request (RULE #218) is not MPSGraph and stays the candidate's.
    "MPSCommandBufferImageCache.mm:1420: failed assertion `Failed to allocate private "
    "MTLBuffer for size 756048461824'",
])
def test_an_abort_that_does_not_name_the_mps_backend_is_not_one(text):
    assert reasons.classify(text, candidate=SPEC) != reasons.BACKEND_FAULT


def test_the_screen_declines_a_backend_fault_with_an_until_instead_of_breaking_it():
    summary = {"hf-ocr/PaddleOCR-VL-1.6": {"total": 1, "passed": 0,
                                           "failure_classes": {reasons.BACKEND_FAULT: 1},
                                           "failures": ["ocr-invoice-line: exit -6: LLVM"]}}
    v = screen.outcome(0, summary, candidate=SPEC, key="hf-ocr/PaddleOCR-VL-1.6")
    assert (v.outcome, v.reason) == ("declined", reasons.RUNTIME)
    assert v.until.startswith("version:")
    assert "mps backend aborted" in v.detail.lower()


def _aborting_engine(tmp_path, lines, rc=134):
    fake = tmp_path / "abort.py"
    fake.write_text("import sys\n"
                    f"for line in {lines!r}:\n    print(line, file=sys.stderr)\n"
                    f"sys.exit({rc})\n", encoding="utf-8")
    real = engines.resolve("hf-ocr:someorg/a-model")
    return dataclasses.replace(real, argv=lambda p, o, params: [sys.executable, str(fake)])


def test_a_runner_reads_the_abort_not_the_warning_printed_after_it(tmp_path):
    from evals.runners.process import ProcessRunner
    case = next(c for c in CASES if c.id == "ocr-invoice-line")
    r = ProcessRunner(_aborting_engine(tmp_path, ABORT_TAIL), tmp_path / "out").run(case)
    assert r.failure_class == reasons.BACKEND_FAULT
    assert "mps.matmul" in r.detail and "LLVM ERROR" in r.detail
    assert "resource_tracker" not in r.detail


def test_a_runner_without_an_abort_still_reports_its_last_line(tmp_path):
    from evals.runners.process import ProcessRunner
    case = next(c for c in CASES if c.id == "ocr-invoice-line")
    eng = _aborting_engine(tmp_path, ["noise", "RuntimeError: boom"], rc=1)
    r = ProcessRunner(eng, tmp_path / "out").run(case)
    assert r.detail == "exit 1: RuntimeError: boom"
    assert r.failure_class == reasons.CRASHED


# --- 2. hf-task falls back to eager attention, then to the CPU ---------------

class Attempts:
    """A fake child per attempt: (rc, stderr) by (device, attn)."""

    def __init__(self, answers):
        self.answers = answers
        self.tried = []

    def __call__(self, device, attn):
        self.tried.append((device, attn))
        return self.answers[(device, attn)]


ABORT = "\n".join(ABORT_TAIL)


def test_hf_task_retries_an_mps_abort_with_eager_attention():
    from harness import hf_task
    run = Attempts({(None, ""): (-6, ABORT), (None, "eager"): (0, "")})
    assert hf_task.fall_back(run) == 0
    assert run.tried == [(None, ""), (None, "eager")]


def test_hf_task_falls_back_to_the_cpu_when_eager_attention_aborts_too():
    from harness import hf_task
    run = Attempts({(None, ""): (-6, ABORT), (None, "eager"): (-6, MPSGRAPH_ASSERT),
                    ("cpu", ""): (0, "")})
    assert hf_task.fall_back(run) == 0
    assert run.tried == [(None, ""), (None, "eager"), ("cpu", "")]


def test_hf_task_does_not_retry_a_failure_that_is_not_the_mps_backend():
    from harness import hf_task
    run = Attempts({(None, ""): (1, "ValueError: the image is empty")})
    assert hf_task.fall_back(run) == 1
    assert run.tried == [(None, "")]


def test_hf_task_returns_the_last_abort_when_every_fallback_aborts():
    from harness import hf_task
    run = Attempts({(None, ""): (-6, ABORT), (None, "eager"): (-6, ABORT),
                    ("cpu", ""): (-6, ABORT)})
    assert hf_task.fall_back(run) == -6
    assert len(run.tried) == 3


def test_hf_task_runs_each_attempt_as_its_own_process_and_relays_its_stderr(
        tmp_path, monkeypatch, capsys):
    import subprocess

    from harness import hf_task
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        aborted = "--attn" not in argv
        return subprocess.CompletedProcess(argv, -6 if aborted else 0, "",
                                           ABORT if aborted else "")
    monkeypatch.setattr(hf_task.subprocess, "run", fake_run)
    out = tmp_path / "o.txt"
    rc = hf_task.main(["ocr", "--model", "m/x", "--image", "i.png", "--out", str(out)])
    assert rc == 0
    assert len(seen) == 2
    assert seen[0][:3] == [sys.executable, "-m", "harness.hf_task"]
    assert "--one-attempt" in seen[0] and "--one-attempt" in seen[1]
    assert seen[1][seen[1].index("--attn") + 1] == "eager"
    assert "mps.matmul" in capsys.readouterr().err


def test_an_explicit_device_is_one_attempt_with_no_fallback(tmp_path, monkeypatch):
    from harness import hf_task
    got = {}

    def fake_read(model, image, prompt, *, revision=None, max_new_tokens=512,
                  device=None, attn="", runtime=None):
        got.update(device=device, attn=attn)
        runtime.update(device=device, attn="sdpa")
        return "text"
    monkeypatch.setattr(hf_task, "read_image", fake_read)
    monkeypatch.setattr(hf_task.subprocess, "run", None)
    out = tmp_path / "o.txt"
    assert hf_task.main(["ocr", "--model", "m/x", "--image", "i.png", "--out", str(out),
                         "--device", "cpu"]) == 0
    assert got == {"device": "cpu", "attn": ""}


def test_one_attempt_passes_its_attention_and_records_what_answered(tmp_path, monkeypatch):
    from harness import hf_task

    def fake_read(model, image, prompt, *, revision=None, max_new_tokens=512,
                  device=None, attn="", runtime=None):
        runtime.update(device="mps", attn=attn)
        return "Invoice #4471"
    monkeypatch.setattr(hf_task, "read_image", fake_read)
    out = tmp_path / "o.txt"
    assert hf_task.main(["ocr", "--model", "m/x", "--image", "i.png", "--out", str(out),
                         "--attn", "eager", "--one-attempt"]) == 0
    assert out.read_text(encoding="utf-8") == "Invoice #4471"
    assert json.loads(Path(hf_task.runtime_path(out)).read_text(encoding="utf-8")) == \
        {"device": "mps", "attn": "eager"}


def test_the_runner_puts_the_device_that_answered_on_its_row(tmp_path):
    from evals.runners.process import ProcessRunner
    from harness import hf_task
    fake = tmp_path / "ok.py"
    fake.write_text(
        "import json, sys\nopen(sys.argv[1], 'w').write('Invoice #4471 due 2026-11-30')\n"
        f"open(sys.argv[1] + {hf_task.RUNTIME_SUFFIX!r}, 'w').write("
        "json.dumps({'device': 'cpu', 'attn': 'sdpa'}))\n", encoding="utf-8")
    real = engines.resolve("hf-ocr:someorg/a-model")
    eng = dataclasses.replace(real, argv=lambda p, o, params: [sys.executable, str(fake), str(o)])
    case = next(c for c in CASES if c.id == "ocr-invoice-line")
    r = ProcessRunner(eng, tmp_path / "out").run(case)
    assert r.runtime == {"device": "cpu", "attn": "sdpa"}


def test_a_stale_runtime_record_from_an_earlier_run_is_not_read(tmp_path):
    from evals.runners.process import ProcessRunner
    from harness import hf_task
    fake = tmp_path / "ok.py"
    fake.write_text("import sys\nopen(sys.argv[1], 'w').write('Invoice #4471 due 2026-11-30')\n",
                    encoding="utf-8")
    real = engines.resolve("hf-ocr:someorg/a-model")
    eng = dataclasses.replace(real, argv=lambda p, o, params: [sys.executable, str(fake), str(o)])
    case = next(c for c in CASES if c.id == "ocr-invoice-line")
    runner = ProcessRunner(eng, tmp_path / "out")
    stale = tmp_path / "out" / (runner.artifact(case, ".txt") + hf_task.RUNTIME_SUFFIX)
    stale.write_text(json.dumps({"device": "mps", "attn": "eager"}), encoding="utf-8")
    assert runner.run(case).runtime == {}


# --- the device that answered is an axis comparable() sees ------------------

def test_the_receipt_names_the_device_each_candidate_answered_on():
    from evals.core import Result
    from evals.run import devices
    rows = [Result("a", "hf-ocr/X", True, 1.0, 0, "", runtime={"device": "cpu", "attn": "sdpa"}),
            Result("b", "hf-ocr/X", True, 1.0, 0, "", runtime={"device": "cpu", "attn": "sdpa"}),
            Result("a", "osocr/vision", True, 1.0, 0, "")]
    assert devices(rows) == {"hf-ocr/X": "cpu:sdpa"}
    mixed = rows + [Result("c", "hf-ocr/X", True, 1.0, 0, "",
                           runtime={"device": "mps", "attn": "eager"})]
    assert devices(mixed) == {"hf-ocr/X": "cpu:sdpa,mps:eager"}


def _ocr_receipt(**kw):
    return Receipt(modality="ocr", case_ids=("ocr-invoice-line",), repeat=1,
                   sampling={}, gateway="", tier="screen", **kw)


def test_comparable_refuses_one_candidate_answering_on_two_devices():
    ok, why = comparable(_ocr_receipt(devices={"hf-ocr/X": "mps:eager"}),
                         _ocr_receipt(devices={"hf-ocr/X": "cpu:sdpa"}))
    assert not ok
    assert "device" in why and "hf-ocr/X" in why


def test_comparable_compares_only_the_devices_both_runs_name():
    assert comparable(_ocr_receipt(devices={"hf-ocr/X": "cpu:sdpa"}),
                      _ocr_receipt())[0]
    assert comparable(_ocr_receipt(devices={"hf-ocr/X": "cpu:sdpa"}),
                      _ocr_receipt(devices={"hf-ocr/Y": "mps:sdpa"}))[0]
    assert _ocr_receipt(devices={"k": "cpu:sdpa"}).as_dict()["devices"] == {"k": "cpu:sdpa"}


def test_compare_runs_reads_the_devices_back_and_refuses(tmp_path, capsys):
    from evals.run import compare_runs
    paths = []
    for i, dev in enumerate(("mps:eager", "cpu:sdpa")):
        p = tmp_path / f"r{i}" / "results.json"
        p.parent.mkdir()
        p.write_text(json.dumps({"receipt": _ocr_receipt(devices={"hf-ocr/X": dev}).as_dict(),
                                 "summary": {}, "rows": []}), encoding="utf-8")
        paths.append(str(p))
    compare_runs(paths)
    assert "REFUSED" in capsys.readouterr().out


# --- 3. schema 60 requeues the screens the abort settled ---------------------

def _broken(conn, name, detail):
    ms.record(conn, ms.Seen(name=name, source="t", lane="ocr", registry=ms.HUGGINGFACE,
                            resolved=name))
    ms.decide(conn, name, "broken", tier=ms.SCREEN, detail=detail, reason=reasons.CANDIDATE)


def _screen_run(conn, dirname, spec, key, detail, stderr_lines):
    from harness import candidates, paths, runs
    name = spec.partition(":")[2]
    cid = candidates.ensure(conn, spec, proposal=name, lane="ocr", key=key)
    run = paths.runs() / dirname
    run.mkdir(parents=True)
    runs.record(conn, run, {"receipt": {"modality": "ocr", "tier": "screen"},
                            "specs": {key: spec},
                            "rows": [{"case_id": "ocr-invoice-line", "candidate": key,
                                      "passed": False, "detail": detail,
                                      "failure_class": "crashed", "candidate_id": cid}]})
    if stderr_lines is not None:
        (run / artifact_name(key, "ocr-invoice-line", ".stderr.txt")).write_text(
            "\n".join(stderr_lines) + "\n", encoding="utf-8")


def test_schema_60_requeues_the_screen_an_mps_abort_settled(tmp_path):
    from harness.memory_store.migrations import v60
    conn = ms.connect(tmp_path / "s.db")
    try:
        row_detail = RECORDED.split(": ", 2)[-1]
        _broken(conn, NAME, RECORDED)
        _screen_run(conn, "screen-1-ocr", SPEC, "hf-ocr/PaddleOCR-VL-1.6", row_detail,
                    ABORT_TAIL)
        # Same exit and same last line, but its kept stderr never names the MPS backend.
        _broken(conn, "org/segfaults", RECORDED)
        _screen_run(conn, "screen-2-ocr", "hf-ocr:org/segfaults", "hf-ocr/segfaults",
                    row_detail, ["Segmentation fault", ABORT_TAIL[-1]])
        # Its detail itself names the abort, with no stderr kept.
        _broken(conn, "org/said-so", "it ran and passed nothing: x: exit -6: LLVM ERROR: "
                "Failed to infer result type(s): \"mps.matmul\"(...)")
        # A stderr that names the abort but whose verdict is not broken is left alone.
        _broken(conn, "org/really-broken", "it ran and passed nothing: x: CER 0.9")
        v60.data(conn)
        got = dict(conn.execute("SELECT name, state FROM proposals").fetchall())
        assert got == {NAME: "queued", "org/segfaults": "broken",
                       "org/said-so": "queued", "org/really-broken": "broken"}
        why = conn.execute("SELECT v.detail, v.reason FROM proposals p JOIN verdicts v "
                           "ON v.id = p.state_verdict_id WHERE p.name = ?",
                           (NAME,)).fetchone()
        assert why["detail"].startswith("retracted:") and "mps" in why["detail"].lower()
        assert ms.SCHEMA_VERSION >= 60
    finally:
        conn.close()


def test_schema_60_leaves_a_missing_run_dir_alone(tmp_path):
    from harness import paths
    from harness.memory_store.migrations import v60
    conn = ms.connect(tmp_path / "s.db")
    try:
        _broken(conn, NAME, RECORDED)
        _screen_run(conn, "screen-3-ocr", SPEC, "hf-ocr/PaddleOCR-VL-1.6",
                    RECORDED.split(": ", 2)[-1], None)
        assert not list(paths.runs().glob("screen-3-ocr/*.stderr.txt"))
        v60.data(conn)
        assert conn.execute("SELECT state FROM proposals WHERE name = ?",
                            (NAME,)).fetchone()["state"] == "broken"
    finally:
        conn.close()

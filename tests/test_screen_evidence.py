"""A screen verdict must name its own run and carry its reason. #281, #282.

Every case here is constructible with no model, no GPU and no network, which is
the argument for it existing: the defects were live for weeks behind a suite of
111 files.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from evals.core import Case, Result, summarize  # noqa: E402
from evals.runners.base import BaseRunner, RunnerError  # noqa: E402
from harness import engines, reasons, screen  # noqa: E402


def ran(spec, key, failure, checker=False):
    """A one-case summary built the way evals.run builds it: a runner's error
    read once at BaseRunner.failed, or a checker's own verdict. #408."""
    case_id, _, detail = failure.partition(": ")
    if checker:
        row = Result(case_id, key, False, 0.0, 0, detail,
                     failure_class=reasons.CONTENT_FAILED)
    else:
        runner = BaseRunner()
        runner.candidate, runner.spec = key, spec
        row = runner.failed(Case(case_id, "image", "p"), RunnerError(detail))
    return summarize([row])

#: THE SPEC AND THE RECEIPT KEY ARE DIFFERENT SPELLINGS. These pairs are taken
#: from real receipts under $LOCALHARNESS_HOME/runs, not invented: an equality
#: check passed my first fixtures because I wrote both halves to match, and the
#: live run then queued every candidate. Issue #282.
SPEC = "diffusers:SupraLabs/Supra2-IMG"
KEY = "diffusers/Supra2-IMG"

PASSED = {KEY: {"total": 1, "passed": 1, "failures": []}}
FAILED = {KEY: {
    "total": 1, "passed": 0,
    "failures": ["fox-snow: exit 1: OSError: SupraLabs/Supra2-IMG does not "
                 "appear to have a file named model_index.json."]}}
SOMEBODY_ELSE = {"mflux/Z-Image-Turbo-mflux-4bit": {"total": 1, "passed": 1,
                                                    "failures": []}}


# --- #281: the reason is in the receipt, one key away -----------------------

def test_a_failing_screen_records_the_checkers_reason():
    got, why, *_ = screen.outcome(0, FAILED, candidate=SPEC)
    assert got == "broken"
    assert "model_index.json" in why, why


def test_a_failing_screen_with_no_stated_reason_still_says_it_ran():
    """The old sentence is the fallback, not the only answer."""
    bare = {"c": {"total": 1, "passed": 0, "failures": []}}
    got, why, *_ = screen.outcome(0, bare, candidate="c")
    assert got == "broken"
    assert why == "it ran and passed nothing"


def test_the_reason_is_bounded():
    """A verdict detail is capped at 600 chars and the stderr tail shares it."""
    noisy = {"c": {"total": 1, "passed": 0, "failures": ["x" * 5000]}}
    _, why, *_ = screen.outcome(0, noisy, candidate="c")
    assert len(why) < 400, len(why)


# --- #282: the receipt must belong to this run ------------------------------

def test_a_receipt_naming_another_candidate_is_not_this_runs_verdict():
    """THE DEFECT. A candidate that wrote no receipt read the newest one for
    its modality. The image lane screens the same incumbent on every sweep, so
    a fresh PASSING receipt was almost always on disk."""
    got, why, *_ = screen.outcome(0, SOMEBODY_ELSE,
                              candidate=SPEC)
    assert got == "queued", f"a foreign receipt settled a candidate: {why}"
    assert "rather than" in why


def test_a_foreign_receipt_does_not_become_a_terminal_verdict():
    """`broken` is terminal, so guessing from somebody else's run declines a
    real model forever."""
    got, *_ = screen.outcome(1, SOMEBODY_ELSE, candidate=SPEC)
    assert got not in screen.TERMINAL if hasattr(screen, "TERMINAL") else True
    assert got == "queued"


def test_the_candidates_own_receipt_is_accepted():
    """THE NEGATIVE CONTROL, and the half that decides whether this can ship.
    A mismatch check that fires on every run empties the queue and reads
    exactly like a queue that ran out."""
    got, why, *_ = screen.outcome(0, PASSED, candidate=SPEC)
    assert got == "screened", why


def test_no_receipt_at_all_is_still_broken_rather_than_queued():
    """A run that produced nothing is a fact about the candidate. Only a
    receipt belonging to SOMEBODY ELSE is the harness's fault."""
    got, *_ = screen.outcome(0, None, candidate=SPEC)
    assert got == "broken"


def test_wrong_run_is_silent_without_a_candidate_to_check():
    """Called with no candidate the check cannot fire, and must not guess."""
    assert screen.wrong_run(SOMEBODY_ELSE, "") == ""
    assert screen.wrong_run(None, "anything") == ""


def test_a_refusal_in_stderr_counts_only_when_the_run_wrote_no_receipt():
    """#408: stderr is read once by the caller and only stands in for a
    receipt that does not exist. ERROR #130: the same phrase in an engine's
    streamed stderr is the snapshot's, so a receipt always wins."""
    cls = reasons.classify("connection refused", reasons.STDERR)
    v = screen.outcome(1, None, candidate=SPEC, stderr_class=cls)
    assert (v.outcome, v.reason, v.failure_class) == (
        "queued", "harness", reasons.REFUSED_BY_GATEWAY)
    v = screen.outcome(0, SOMEBODY_ELSE, candidate=SPEC, stderr_class=cls)
    assert v.outcome == "queued" and "rather than" in v.detail


# --- argv carries the outdir, which is what makes the above reachable -------

def test_argv_can_be_told_where_to_write():
    row = {"modality": "image", "candidate": "diffusers:x/y", "name": "x/y"}
    got = screen.argv(row, outdir="/tmp/screen-1")
    assert "--out" in got
    assert got[got.index("--out") + 1] == "/tmp/screen-1"


def test_argv_without_an_outdir_is_unchanged():
    row = {"modality": "image", "candidate": "diffusers:x/y", "name": "x/y"}
    assert "--out" not in screen.argv(row)


# --- the spec is not the receipt key, and assuming so queues everything -----

def test_a_spec_matches_the_receipt_key_it_actually_produces():
    """THE DEFECT MY OWN FIXTURES HID. Both halves were mine and agreed, so an
    equality check passed the suite and queued every candidate on the machine.
    These pairs come from receipts on disk."""
    real = {
        "diffusers:SupraLabs/Supra2-IMG": "diffusers/Supra2-IMG",
        "mflux:filipstrand/Z-Image-Turbo-mflux-4bit": "mflux/z-image-turbo",
        "local-large": "local-large",
        "tts:mlx-community/Kokoro-82M-bf16,voice=am_adam":
            "Kokoro-82M-bf16/am_adam",
        "acestep:acestep-v15-turbo,steps=8": "acestep/acestep-v15-turbo@steps=8",
    }
    for spec, key in real.items():
        if spec.startswith("mflux:filipstrand"):
            continue  # an alias rename, not a spelling this check can derive
        assert screen.wrong_run({key: {}}, spec) == "", f"{spec} vs {key}"


def test_a_genuinely_foreign_receipt_is_still_caught():
    """THE POSITIVE CONTROL for the loosened check. Without it the fix above
    turns wrong_run into a function that returns "" unconditionally."""
    foreign = {"mflux/z-image-turbo": {"total": 1, "passed": 1}}
    assert screen.wrong_run(foreign, "diffusers:SupraLabs/Supra2-IMG")


# --- #293: a model the installed runtime cannot load is not broken ---------

DFLASH = "incoai/Qwen3.8-27B-DFlash2"
LOAD_FAILED = ran(DFLASH, DFLASH,
                  "chunk-bytes: gateway returned HTTP 404: {\"error\": "
                  "\"ModelArgs.__init__() missing 1 required positional "
                  "argument: 'rope_theta'\"}")
WRONG_ANSWER = ran(DFLASH, DFLASH, "chunk-bytes: expected 3 chunks, got 2",
                   checker=True)


def test_a_load_failure_waits_for_a_newer_runtime_instead_of_breaking():
    got, why, *_ = screen.outcome(0, LOAD_FAILED, candidate="incoai/Qwen3.8-27B-DFlash2")
    assert got == "declined", why
    assert "rope_theta" in why


def test_a_wrong_answer_is_still_broken():
    """THE NEGATIVE CONTROL. A model that loaded and answered badly has been
    measured, and that verdict stays terminal."""
    got, *_ = screen.outcome(0, WRONG_ANSWER, candidate="incoai/Qwen3.8-27B-DFlash2")
    assert got == "broken"


def test_the_load_failure_names_the_runtime_that_would_end_the_wait():
    until = screen.load_until()
    assert until.startswith("version:mlx-lm>"), until


def test_a_missing_file_behind_a_404_is_not_a_runtime_gap():
    """A newer runtime cannot supply a file the snapshot lacks."""
    missing = ran("org/x", "org/x",
                  "chunk-bytes: gateway returned HTTP 404: {\"error\": \"[Errno 2] "
                  "No such file or directory: 'tokenizer.json'\"}")
    v = screen.outcome(0, missing, candidate="org/x")
    assert (v.outcome, v.failure_class) == ("broken",
                                            reasons.MISSING_FILE_IN_SNAPSHOT)


def test_every_architecture_gap_spelling_in_the_store_is_recognised():
    """Read from the live store's own rows, not invented. #293."""
    for err in ("Model type gpt_x not supported.",
                "ModelArgs.__init__() missing 1 required positional argument: 'rope_theta'",
                "Received 58 parameters not in model"):
        s = ran("org/x", "org/x",
                f"chunk-bytes: gateway returned HTTP 404: {{\"error\": \"{err}\"}}")
        assert screen.outcome(0, s, candidate="org/x")[0] == "declined", err


def test_an_mflux_receipt_is_this_runs():
    """#378: mflux names the run with its quantisation, so the repo tail never
    matched and every mflux candidate requeued forever."""
    spec = "mflux:Qwen/Qwen-Image-Bench"
    key = engines.resolve(spec).name
    assert key.endswith("-q8"), key
    assert screen.wrong_run({key: {}}, spec) == ""
    assert screen.wrong_run({"mflux/Other/thing-q8": {}}, spec) != ""


@pytest.mark.parametrize("why", [
    "fox-snow: exit 1: ValueError: AutoPipeline can't find a pipeline linked to PRXPixelPipeline for None",
    "fox-snow: exit 1: ValueError: Pipeline <class 'ZImagePipeline'> expected ['vae'], but only set() were passed.",
])
def test_a_layout_stock_diffusers_cannot_assemble_is_not_broken(why):
    """#381: the loader failed, not the model, and broken is terminal."""
    v = screen.outcome(0, ran("diffusers:o/x", "diffusers/x", why),
                       candidate="diffusers:o/x")
    assert v.outcome == "declined" and "own runner" in v.detail
    assert v.reason == "runtime" and v.until.startswith("version:diffusers>")


def test_a_model_that_ran_and_failed_is_still_broken():
    """Negative control for #381."""
    s = ran("diffusers:o/x", "diffusers/x", "fox-snow: no fox in image", checker=True)
    assert screen.outcome(0, s, candidate="diffusers:o/x")[0] == "broken"


# --- #383 class 1: every consumer reads the key the engine wrote ------------

#: Valid specs per engine, bare and optioned. A new engine fails until it has one.
SAMPLES = {
    "mflux": ["mflux:Qwen/Qwen-Image-Bench", "mflux:z-image-turbo,steps=4",
              "mflux:flux2-klein-4b,quantize=none"],
    "h3": ["h3", "h3:,steps=4"],
    "diffusers": ["diffusers:stabilityai/sdxl-turbo", "diffusers:org/x,steps=4"],
    "diffusers-video": ["diffusers-video:Lightricks/LTX-Video",
                        "diffusers-video:org/v,frames=9"],
    "acestep": ["acestep:acestep-v15-turbo,steps=8",
                "acestep:ACE-Step/acestep-v15-xl"],
}
SAMPLE_SPECS = [s for specs in SAMPLES.values() for s in specs]
LANE_OF = {"image": "image", "video": "video", "music": "music"}


def test_every_engine_has_a_sample_spec():
    assert set(SAMPLES) == set(engines._BUILDERS)


@pytest.mark.parametrize("spec", SAMPLE_SPECS)
def test_the_screen_recognises_the_key_its_engine_wrote(spec):
    key = engines.resolve(spec).name
    assert screen.wrong_run({key: {}}, spec) == ""
    assert screen.wrong_run({"diffusers/someone-else": {}}, spec) != ""


def _stored(spec, proposal=""):
    """One candidates row, written the way a tier writes it. #407."""
    from harness import candidates
    from harness import memory_store as ms
    conn = ms.connect()
    if proposal:
        ms.record(conn, ms.Seen(name=proposal, source="t"))
    candidates.ensure(conn, spec, proposal=proposal)
    return conn


@pytest.mark.parametrize("spec", SAMPLE_SPECS)
def test_measure_finds_the_row_its_engine_wrote(spec):
    """#384, read through the candidates table rather than a matcher."""
    from harness import candidates, cli
    eng = engines.resolve(spec)
    conn = _stored(spec)
    try:
        key = candidates.key_for(conn, spec)
    finally:
        conn.close()
    row = cli._summary_row({eng.name: {"passed": 1}}, key)
    assert row and row["candidate"] == eng.name
    assert cli._summary_row({"diffusers/someone-else": {"passed": 1}}, key) is None


@pytest.mark.parametrize("spec", [s for s in SAMPLE_SPECS if "," not in s and ":" in s])
def test_discovery_counts_a_receipt_its_engine_wrote_as_measured(spec):
    """#384: the proposal's key comes from its stored candidate."""
    from harness import discover
    repo = spec.partition(":")[2]
    conn = _stored(spec, proposal=repo)
    try:
        assert discover._was_measured(repo, {engines.resolve(spec).name},
                                      conn=conn)
        assert not discover._was_measured(repo, {"mflux/someone/else-q8"},
                                          conn=conn)
    finally:
        conn.close()


#: A GGUF repo, its llama.cpp spec and key: no string rule turns one into the
#: other, because the stem is the file the fetch picked. #407.
GGUF_REPO = "ornith-ai/Ornith-1.5-35B-A3B-GGUF"
GGUF_SPEC = "llamacpp:Ornith-1.5-35B-Q4_K_M"


def test_every_consumer_reads_a_mapping_no_string_rule_derives():
    from harness import adopt, candidates, cli, discover
    from harness import memory_store as ms
    conn = _stored(GGUF_SPEC, proposal=GGUF_REPO)
    try:
        key = candidates.key_for(conn, GGUF_SPEC)
        assert key == GGUF_SPEC
        assert candidates.get(conn, GGUF_REPO)["spec"] == GGUF_SPEC
        assert discover._was_measured(GGUF_REPO, {key}, conn=conn)
        assert cli._summary_row({key: {"passed": 1}}, key)
        ms.decide(conn, GGUF_REPO, "screened", tier=ms.SCREEN, detail="ran")
        adopt.record(conn, adopt.Verdict("code", "q3-4b", key, False, "lost"),
                     spec=GGUF_SPEC)
        assert ms.latest(conn, GGUF_REPO)["tier"] == ms.ADOPT
        assert not conn.execute("SELECT 1 FROM proposals WHERE name = ?",
                                (GGUF_SPEC,)).fetchone()
    finally:
        conn.close()


def test_without_the_stored_row_the_mapping_is_not_guessed():
    """Negative control: the same repo with no candidates row is unmeasured."""
    from harness import discover
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        assert not discover._was_measured(GGUF_REPO, {GGUF_SPEC}, conn=conn)
    finally:
        conn.close()


# --- #383 class 5: a loader failure is not the model's fault ----------------

#: How each loader's failure reaches the summary: a process engine's last stderr
#: line, and mlx_lm.server's 404 for an architecture it cannot build.
#: Every upstream text the adapter knows as not the candidate's, as each
#: loader reports it: a process engine's last stderr line, mlx_lm.server's 404.
NOT_THE_CANDIDATE = (reasons._SERVER_DEAD + reasons._GATEWAY + reasons._HARNESS)
LOADER_FAILURES = (
    [("diffusers:o/x", "diffusers/x", f"fox-snow: exit 1: ValueError: {p}")
     for p in reasons._DIFFUSERS_LAYOUT_GAPS]
    + [(c, k, f"fox-snow: exit 1: {p}") for p in NOT_THE_CANDIDATE
       for c, k in (("diffusers:o/x", "diffusers/x"), ("o/x", "o/x"))]
    + [("diffusers:o/x", "diffusers/x", f"fox-snow: exit 1: ValueError: {p}")
       for p in reasons._ARCHITECTURE_GAPS]
    + [("o/x", "o/x", f"chunk-bytes: gateway returned HTTP 404: {{\"error\": \"{p}\"}}")
       for p in reasons._ARCHITECTURE_GAPS])


@pytest.mark.parametrize("cand,key,failure", LOADER_FAILURES)
def test_no_loader_failure_is_recorded_broken(cand, key, failure):
    summary = ran(cand, key, failure)
    assert screen.outcome(0, summary, candidate=cand)[0] != "broken", failure


@pytest.mark.parametrize("cand,key,failure,checker", [
    ("diffusers:o/x", "diffusers/x", "fox-snow: no fox in the image (clip 0.12)", True),
    ("o/x", "o/x", "fox-snow: no fox in the image (clip 0.12)", True),
    ("diffusers:o/x", "diffusers/x",
     "fox-snow: exit 1: OSError: [Errno 2] No such file or directory: 'vae/config.json'",
     False),
])
def test_a_content_or_snapshot_failure_is_still_broken(cand, key, failure, checker):
    """Negative control: the output was wrong, or the snapshot lacks a file."""
    summary = ran(cand, key, failure, checker)
    v = screen.outcome(0, summary, candidate=cand)
    assert (v.outcome, v.reason) == ("broken", "candidate")


def test_a_process_engine_decline_waits_on_its_own_runtime():
    """#385: a diffusers gap waited on mlx-lm."""
    assert screen.load_until("diffusers:o/x").startswith("version:diffusers>")
    assert screen.load_until("mflux:z-image-turbo").startswith("version:mflux>")

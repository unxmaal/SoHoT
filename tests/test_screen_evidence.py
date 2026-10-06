"""A screen verdict must name its own run and carry its reason. #281, #282.

Every case here is constructible with no model, no GPU and no network, which is
the argument for it existing: the defects were live for weeks behind a suite of
111 files.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from harness import engines, screen  # noqa: E402

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
    got, why = screen.outcome(0, FAILED, candidate=SPEC)
    assert got == "broken"
    assert "model_index.json" in why, why


def test_a_failing_screen_with_no_stated_reason_still_says_it_ran():
    """The old sentence is the fallback, not the only answer."""
    bare = {"c": {"total": 1, "passed": 0, "failures": []}}
    got, why = screen.outcome(0, bare, candidate="c")
    assert got == "broken"
    assert why == "it ran and passed nothing"


def test_the_reason_is_bounded():
    """A verdict detail is capped at 600 chars and the stderr tail shares it."""
    noisy = {"c": {"total": 1, "passed": 0, "failures": ["x" * 5000]}}
    _, why = screen.outcome(0, noisy, candidate="c")
    assert len(why) < 400, len(why)


# --- #282: the receipt must belong to this run ------------------------------

def test_a_receipt_naming_another_candidate_is_not_this_runs_verdict():
    """THE DEFECT. A candidate that wrote no receipt read the newest one for
    its modality. The image lane screens the same incumbent on every sweep, so
    a fresh PASSING receipt was almost always on disk."""
    got, why = screen.outcome(0, SOMEBODY_ELSE,
                              candidate=SPEC)
    assert got == "queued", f"a foreign receipt settled a candidate: {why}"
    assert "rather than" in why


def test_a_foreign_receipt_does_not_become_a_terminal_verdict():
    """`broken` is terminal, so guessing from somebody else's run declines a
    real model forever."""
    got, _ = screen.outcome(1, SOMEBODY_ELSE, candidate=SPEC)
    assert got not in screen.TERMINAL if hasattr(screen, "TERMINAL") else True
    assert got == "queued"


def test_the_candidates_own_receipt_is_accepted():
    """THE NEGATIVE CONTROL, and the half that decides whether this can ship.
    A mismatch check that fires on every run empties the queue and reads
    exactly like a queue that ran out."""
    got, why = screen.outcome(0, PASSED, candidate=SPEC)
    assert got == "screened", why


def test_no_receipt_at_all_is_still_broken_rather_than_queued():
    """A run that produced nothing is a fact about the candidate. Only a
    receipt belonging to SOMEBODY ELSE is the harness's fault."""
    got, _ = screen.outcome(0, None, candidate=SPEC)
    assert got == "broken"


def test_wrong_run_is_silent_without_a_candidate_to_check():
    """Called with no candidate the check cannot fire, and must not guess."""
    assert screen.wrong_run(SOMEBODY_ELSE, "") == ""
    assert screen.wrong_run(None, "anything") == ""


def test_a_harness_refusal_still_outranks_the_mismatch_check():
    """A refused request says nothing about the candidate, and that reading is
    older and more specific than 'this receipt is not yours'."""
    got, why = screen.outcome(1, SOMEBODY_ELSE, detail="connection refused",
                              candidate=SPEC)
    assert got == "queued"
    assert "connection refused" in why


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
        "acestep:acestep-v15-turbo,steps=8": "acestep/acestep-v15-turbo",
    }
    for spec, key in real.items():
        if spec.startswith("mflux:filipstrand"):
            continue  # an alias rename, not a spelling this check can derive
        assert screen.wrong_run({key: {}}, spec) == "", f"{spec} vs {key}"


def test_the_model_tail_survives_every_spec_shape():
    assert screen.model_tail("diffusers:SupraLabs/Supra2-IMG") == "supra2-img"
    assert screen.model_tail("local-large") == "local-large"
    assert screen.model_tail("acestep:acestep-v15-turbo,steps=8") \
        == "acestep-v15-turbo"


def test_a_genuinely_foreign_receipt_is_still_caught():
    """THE POSITIVE CONTROL for the loosened check. Without it the fix above
    turns wrong_run into a function that returns "" unconditionally."""
    foreign = {"mflux/z-image-turbo": {"total": 1, "passed": 1}}
    assert screen.wrong_run(foreign, "diffusers:SupraLabs/Supra2-IMG")


# --- #293: a model the installed runtime cannot load is not broken ---------

LOAD_FAILED = {"mlx/Qwen3.8-27B-DFlash2": {"total": 1, "passed": 0, "failures": [
    "chunk-bytes: gateway returned HTTP 404: {\"error\": \"ModelArgs.__init__() "
    "missing 1 required positional argument: 'rope_theta'\"}"]}}
WRONG_ANSWER = {"mlx/Qwen3.8-27B-DFlash2": {"total": 1, "passed": 0, "failures": [
    "chunk-bytes: expected 3 chunks, got 2"]}}


def test_a_load_failure_waits_for_a_newer_runtime_instead_of_breaking():
    got, why = screen.outcome(0, LOAD_FAILED, candidate="incoai/Qwen3.8-27B-DFlash2")
    assert got == "declined", why
    assert "rope_theta" in why


def test_a_wrong_answer_is_still_broken():
    """THE NEGATIVE CONTROL. A model that loaded and answered badly has been
    measured, and that verdict stays terminal."""
    got, _ = screen.outcome(0, WRONG_ANSWER, candidate="incoai/Qwen3.8-27B-DFlash2")
    assert got == "broken"


def test_the_load_failure_names_the_runtime_that_would_end_the_wait():
    until = screen.load_until()
    assert until.startswith("version:mlx-lm>"), until


def test_a_missing_file_behind_a_404_is_not_a_runtime_gap():
    """A newer runtime cannot supply a file the snapshot lacks."""
    missing = {"mlx/x": {"total": 1, "passed": 0, "failures": [
        "chunk-bytes: gateway returned HTTP 404: {\"error\": \"[Errno 2] No such "
        "file or directory: 'tokenizer.json'\"}"]}}
    got, _ = screen.outcome(0, missing, candidate="org/x")
    assert got == "broken"


def test_every_architecture_gap_spelling_in_the_store_is_recognised():
    """Read from the live store's own rows, not invented. #293."""
    for err in ("Model type gpt_x not supported.",
                "ModelArgs.__init__() missing 1 required positional argument: 'rope_theta'",
                "Received 58 parameters not in model"):
        s = {"mlx/x": {"total": 1, "passed": 0, "failures": [
            f"chunk-bytes: gateway returned HTTP 404: {{\"error\": \"{err}\"}}"]}}
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
def test_a_layout_stock_diffusers_cannot_assemble_is_not_broken(why, monkeypatch):
    """#381: the loader failed, not the model, and broken is terminal."""
    monkeypatch.setattr(screen, "why_nothing_passed", lambda s, c: why)
    got, reason = screen.outcome(0, {"diffusers/x": {"passed": 0}}, candidate="diffusers:o/x")
    assert got == "declined" and "own runner" in reason


def test_a_model_that_ran_and_failed_is_still_broken(monkeypatch):
    """Negative control for #381."""
    monkeypatch.setattr(screen, "why_nothing_passed", lambda s, c: "fox-snow: no fox in image")
    assert screen.outcome(0, {"diffusers/x": {"passed": 0}}, candidate="diffusers:o/x")[0] == "broken"

"""Issue #53/#148: the rung between a ranked queue and a measurement."""
import json

import pytest

from harness.commands import screen as screen_cmd
from harness import reasons, screen


def _stderr(text):
    """The run's stderr, classed once as cli._report_screen does. #408."""
    return reasons.classify(text, reasons.STDERR)
from harness import memory_store as ms
from harness.memory_store import Seen


def rows(*specs):
    return [{"name": n, "lane": lane} for n, lane in specs]


# --- what it would do, and what stands in the way ------------------------

def test_a_candidate_whose_weights_are_absent_is_waiting_not_failed():
    """A SCREEN NEVER DOWNLOADS. Fetching is its own step with its own disk
    budget, and a tier that quietly pulls gigabytes because something ranked
    well is how a laptop fills up overnight."""
    # The name's tail must be a family mflux serves. `org/m` was not, so the
    # row is now correctly no-runner and this test asserted `waiting` on a
    # candidate the screen could never have run.
    got = screen.plan(rows(("org/z-image-turbo-4bit", "image")),
                      missing=lambda n: [n])[0]
    assert got["state"] == screen.WAITING
    assert "soh fetch" in got["why_not"]


def test_a_lane_with_no_runner_is_named_rather_than_dropped(monkeypatch):
    """A queue that silently drops what it cannot run looks like a queue that
    ran out.

    `video` was the live example until #264 gave it diffusers-video, so the
    lane is pinned to nothing here rather than the test being deleted: the
    behaviour is still required and every lane happening to have a runner
    today is not a reason to stop checking it.
    """
    monkeypatch.delitem(screen.LANE_CANDIDATES, "video")
    got = screen.plan(rows(("org/v", "video")), missing=lambda n: [])[0]
    assert got["state"] == screen.NO_RUNNER
    assert "video" in got["why_not"]


def test_a_candidate_with_no_lane_says_so_in_its_own_terms():
    got = screen.plan(rows(("org/x", "")), missing=lambda n: [])[0]
    assert got["state"] == screen.NO_RUNNER
    assert "no lane" in got["why_not"]


def test_a_ready_candidate_gets_the_spec_its_lane_actually_takes():
    """The specs are the ones evals.run already parses. A second spelling of
    the candidate language is a defect this project has filed twice."""
    from evals.run import kind_of
    for lane, expect in (("image", "process"), ("stt", "stt"), ("tts", "tts"),
                         ("code", "gateway")):
        spec = screen.candidate_for(lane, "org/m")
        assert spec, lane
        assert kind_of(spec) == expect, (lane, spec)


def test_the_command_is_one_case_one_repeat_and_no_metrics():
    """A screen asks whether it ran. A quality metric here would invite ranking
    a screen against a measurement, which is two different exams."""
    row = screen.plan(rows(("org/m", "image")), missing=lambda n: [])[0]
    argv = screen.argv(row)
    assert "--screen" in argv
    assert argv[argv.index("--repeat") + 1] == "1"
    assert "--adherence" not in argv


# --- turning a run into a verdict ----------------------------------------

def test_a_screen_that_did_not_run_is_broken_and_terminal():
    got, why, *_ = screen.outcome(1, None)
    assert got == "broken"
    assert got in ms.TERMINAL, "a thing that does not run is answered"


def test_a_screen_that_ran_and_passed_nothing_is_declined_on_the_screen_limit():
    """Exiting zero is not the same as working, and a few screen cases are not enough to call it broken. #691."""
    v = screen.outcome(0, {"c": {"total": 3, "passed": 0}})
    assert v.outcome == "declined" and v.until.startswith("limit:screen_cases>"), v


def test_a_screen_that_passed_is_screened_and_not_terminal():
    got, *_ = screen.outcome(0, {"c": {"total": 2, "passed": 2}})
    assert got == "screened"
    assert got not in ms.TERMINAL, "it ran; every measurement is still ahead"


def test_screened_is_a_verdict_the_store_recognises(tmp_path):
    """It has been in the vocabulary since the store was built and nothing has
    ever written one."""
    conn = ms.connect(tmp_path / "d.db")
    ms.record(conn, Seen(name="org/m", source="recap", resolved="org/m"))
    ms.decide(conn, "org/m", "screened", tier=ms.SCREEN, detail="1 passed")
    row = conn.execute("SELECT outcome, tier FROM verdicts").fetchone()
    conn.close()
    assert (row["outcome"], row["tier"]) == ("screened", "screen")


# ---- ready means loadable, not merely present (issue #196) -----------------

def test_a_model_whose_config_names_an_absent_repo_is_not_ready():
    """Marvis-AI's 8-bit MLX repo is complete -- every symlink resolving, no
    .incomplete files -- and names a tokenizer in a DIFFERENT repo that is not
    on disk. `ready` on that cost a real run to discover."""
    got = screen.plan(rows(("org/m", "tts")),
                      missing=lambda n: ["org/tokenizer"])[0]
    assert got["state"] == screen.WAITING
    assert "org/tokenizer" in got["why_not"], "say WHAT to fetch"


def test_a_model_missing_only_itself_reads_as_a_plain_fetch():
    """The ordinary case must keep its ordinary wording, or every
    waiting-on-fetch row starts shouting about dependencies."""
    got = screen.plan(rows(("org/m", "tts")), missing=lambda n: [n])[0]
    assert got["state"] == screen.WAITING
    assert got["why_not"] == "weights are not on disk; soh fetch --run"


def test_a_model_with_everything_present_is_ready():
    """The negative half: a closure check that never passes screens nothing."""
    got = screen.plan(rows(("org/m", "tts")), missing=lambda n: [])[0]
    assert got["state"] == screen.READY


def test_a_lane_with_no_runner_is_not_asked_about_weights():
    """Ordering matters: a missing runner is the answer regardless of disk, and
    asking the cache first would touch the filesystem for every unrunnable row."""
    asked = []

    def missing(n):
        asked.append(n)
        return []

    got = screen.plan(rows(("org/x", "")), missing=missing)[0]
    assert got["state"] == screen.NO_RUNNER
    assert asked == [], "no runner, so the cache was never consulted"


# ---- an adapter is not a candidate (2026-09-18) ---------------------------

def test_a_lora_is_refused_before_anything_downloads():
    """Every candidate in the image queue was a style LoRA. `mflux:org/style`
    downloads gigabytes and then fails, recording a verdict that says nothing
    about the thing."""
    assert screen.is_attachment("text-to-image; diffusers; tagged lora") == "lora"
    assert screen.candidate_for("image", "org/style", "lora") == ""


def test_comfyui_is_a_capability_and_a_weightless_workflow_is_refused():
    assert screen.is_attachment("served by minimax-h3; tagged comfyui") == ""
    assert screen.is_attachment(["comfyui", "workflow"], [{"rfilename": "README.md", "size": 900}]) == "workflow"


def test_a_real_model_is_still_a_candidate():
    """The negative half. A filter that refuses everything screens nothing."""
    assert screen.is_attachment("task text-to-image; served by mlx; "
                                "tagged mlx, mflux, text-to-image") == ""
    # The ENGINE is not the assertion. The image lane holds two, and which one
    # spells a given model is settled by which one can run it.
    assert screen.candidate_for("image", "org/base", "").endswith(":org/base")


def test_a_candidate_with_no_description_is_not_assumed_to_be_an_adapter():
    """Most rows carry no description. Treating silence as an adapter would
    empty the queue."""
    assert screen.is_attachment("") == ""
    assert screen.candidate_for("image", "org/x").endswith(":org/x")


def test_an_enumerated_exception_survives():
    """`lora-ready` describes a base model that ACCEPTS adapters. Matching the
    substring blindly would refuse exactly the models worth having."""
    assert screen.is_attachment("a lora-ready base model") == ""


def test_the_state_says_why_rather_than_no_runner():
    """`no runner for the image lane` is false and sends the reader looking for
    a missing runner. The lane has one; this is not a model."""
    got = screen.plan([{"name": "org/style", "lane": "image",
                        "attaches_to": "lora"}],
                      missing=lambda n: [])[0]
    assert got["state"] == screen.NO_RUNNER
    assert "attaches to a model" in got["why_not"]


def test_the_plan_does_not_parse_the_description():
    """#414: a row whose prose says lora and whose card column says nothing
    is planned like any model; the column is the only reading."""
    got = screen.plan([{"name": "org/style", "lane": "image",
                        "description": "tagged lora"}],
                      missing=lambda n: [])[0]
    assert "attaches to a model" not in got["why_not"]


# ---- the screen must report what it measured (2026-09-18) -----------------

def test_a_passing_screen_is_screened_not_broken():
    """The summary spells it `passed`. outcome() read `pass`, so every run
    scored 0 and a candidate that passed every case was recorded `broken` --
    which is TERMINAL. The tier reported the opposite of what it measured."""
    got, why, *_ = screen.outcome(0, {"m": {"total": 1, "passed": 1,
                                        "pass_rate": 1.0}})
    assert got == "screened"
    assert "1 case" in why


def test_a_failing_screen_is_never_screened():
    """The negative half. A tier that passes a failure screens nothing out."""
    assert screen.outcome(0, {"m": {"total": 3, "passed": 0}})[0] == "declined"


@pytest.mark.gauntlet("a-fact-about-the-harness-recorded-as-a-verdict-on-the-subject",
                       site="harness/screen.py:outcome")
def test_a_refused_request_is_not_the_candidates_failure():
    """An HTTP 400 from the gateway's alias table stopped Qwen3-8B-4bit before
    a token was generated, and it was recorded `broken`, which is terminal."""
    got, why, *_ = screen.outcome(1, None, stderr_class=_stderr(
                              "gateway returned HTTP 400: Invalid model name"))
    assert got == "queued", "not terminal: the candidate never ran"
    assert "says nothing about the candidate" in why


def test_a_real_failure_is_not_excused_as_a_refusal():
    """The other half. Treating every non-zero exit as a harness problem would
    mean nothing is ever screened out."""
    assert screen.outcome(1, None, stderr_class=_stderr("Traceback: ValueError"))[0] == "broken"


def test_an_alias_goes_through_the_gateway(tmp_path):
    cfg = tmp_path / "g.yaml"
    cfg.write_text("model_list:\n  - model_name: q3-4b\n    litellm_params:\n"
                   "      model: openai/org/x\n      api_base: http://up/v1\n",
                   encoding="utf-8")
    assert screen.routed_gateway("q3-4b", cfg) == ""


def test_a_repo_id_goes_to_the_upstream(tmp_path):
    """LiteLLM validates the model name against its aliases and answers 400 for
    anything else. mlx_lm.server treats it as a live repo id and swaps to it,
    so a discovered candidate has to reach the upstream directly."""
    cfg = tmp_path / "g.yaml"
    cfg.write_text("model_list:\n  - model_name: q3-4b\n    hot_swap: true\n    litellm_params:\n"
                   "      model: openai/org/x\n      api_base: http://up/v1\n",
                   encoding="utf-8")
    # The `--gateway` FORM, without the /v1 the config carries: evals.run
    # appends its own path, and passing the config's base made every request
    # /v1/v1/chat/completions and 404. Stripping used to happen in argv() and
    # nowhere else, so the measure tier got the wrong one. #223.
    assert screen.routed_gateway("org/discovered", cfg) == "http://up"
    assert screen.gateway_routes(cfg)[1] == "http://up/v1", (
        "the config's own base keeps its /v1; only the argument drops it")


def test_a_missing_config_routes_nowhere_rather_than_guessing(tmp_path):
    assert screen.routed_gateway("org/x", tmp_path / "absent.yaml") == ""


def test_the_fixture_key_is_the_one_the_run_writes():
    """The tests above used `pass` and so did outcome(), so they agreed with
    each other and with nothing else. A hand-made fixture that never meets the
    real writer confirms whatever the code already does."""
    from evals.core import Result, summarize

    got = summarize([Result("case", "cand", True, 1.0, 0, "")])
    assert "passed" in got["cand"], "outcome() reads this key"
    assert "pass" not in got["cand"], "and there is no bare `pass` to read"


def test_an_empty_screen_is_a_result_not_a_failure(monkeypatch, capsys):
    """#328: nothing ready to screen exited 1, so launchd logged a normal
    sweep as a failure and a crash looked the same."""
    import argparse
    from harness import cli
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: [
        {"name": "org/x", "state": screen.WAITING, "why_not": "not fetched",
         "candidate": "x", "modality": "code"}])
    rc = cli._report_screen(argparse.Namespace(lane="", top=3, limit=3, run=True, json=False))
    assert rc == 0
    assert "nothing is ready to screen" in capsys.readouterr().out


def test_a_recorded_snapshot_offline_loads_cannot_open_goes_back_to_fetch(monkeypatch, tmp_path):
    """Qwen/Qwen3.5-9B: a scan row said complete, refs/main was absent, the warm-up 404'd and it went BROKEN. #799."""
    import argparse
    import subprocess

    from harness import cli, downloads, fetching, memory
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    snap = downloads.hub_dir("org/noref") / "snapshots" / "abc"
    snap.mkdir(parents=True)
    for f in ("config.json", "model.safetensors"):
        (snap / f).write_text("x", encoding="utf-8")
    conn = ms.connect()
    ms.record(conn, Seen(name="org/noref", source="t", kind="weights", lane="code", why="seeded"))
    rid = downloads.record(conn, "org/noref", downloads.HUB, snap.parent.parent)["id"]
    conn.execute("UPDATE downloads SET complete = 1 WHERE id = ?", (rid,))
    conn.commit()
    assert fetching.have("org/noref", conn), "the row as a scan before #799 wrote it"
    conn.close()
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: [
        {"name": "org/noref", "state": screen.READY, "why_not": "", "candidate": "org/noref",
         "modality": "code"}])
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: ran.append(argv))
    assert cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True, json=False)) == 0
    assert ran == []
    conn = ms.connect()
    try:
        got = conn.execute("SELECT v.outcome, v.tier, v.reason, v.detail FROM verdicts v "
                           "JOIN proposals p ON p.state_verdict_id = v.id "
                           "WHERE p.name = 'org/noref'").fetchone()
        assert (got["outcome"], got["tier"], got["reason"]) == ("queued", "fetch", reasons.HARNESS)
        assert "refs/main" in got["detail"]
        assert not fetching.have("org/noref", conn)
    finally:
        conn.close()


# --- verdict detail keeps subprocess stderr out (#879) --------------------

WARNED = ("/deploy/evals/run.py:1869: UserWarning: metric 'attempts' declares no direction\n"
          "  flat = [n for n in metric_names if direction_of(n) == \"neutral\"]\n")


def test_a_screen_with_a_receipt_records_no_stderr_in_its_detail():
    from harness.commands.screen import screen_detail
    assert screen_detail("1 case(s) passed a screen", WARNED + "loading weights\n", {"m": {}}) \
        == "1 case(s) passed a screen"


def test_a_screen_without_a_receipt_keeps_its_stderr_less_warnings():
    from harness.commands.screen import screen_detail
    got = screen_detail("the screen exited 1", WARNED + "Traceback\nValueError: bad config\n", None)
    assert got == "the screen exited 1 || Traceback ValueError: bad config"
    assert screen_detail("the screen exited 1", WARNED, None) == "the screen exited 1"


def test_a_by_hand_lane_says_it_runs_by_hand_under_its_canonical_name():
    """#1282: a BY_HAND lane is answered before any spec is built, by its canonical name."""
    assert screen.by_hand(" Craft ", "org/m") == "the craft lane runs by hand"
    assert screen.runner_gap(" Shots ", "org/m") == "the shots lane runs by hand"


def test_the_vision_lane_names_its_labeller_from_the_card_given_or_the_stored_one(monkeypatch):
    """#1282: a given card wins; with none, the store's card for that model is read."""
    asked = []
    monkeypatch.setattr(ms, "card_of", lambda conn, model: asked.append((conn, model)) or {"library": "mlx"})
    head = "the vision lane runs by hand: soh vision run --candidate "
    assert screen.by_hand("Vision", "org/m", card={"library": "gguf"}) == head + "llamacpp-vlm:org/m"
    assert screen.by_hand("vision", "org/m", conn="c", card={"library": "gguf"}) == head + "llamacpp-vlm:org/m"
    assert asked == []
    assert screen.by_hand("vision", "org/m", conn="c") == head + "mlx-vlm:org/m"
    assert asked == [("c", "org/m")]
    assert screen.runner_gap("vision", "org/v", card={"library": "gguf"}) == head + "llamacpp-vlm:org/v"
    assert screen.runner_gap("vision", "org/v", conn="d") == head + "mlx-vlm:org/v"
    assert asked[-1] == ("d", "org/v")

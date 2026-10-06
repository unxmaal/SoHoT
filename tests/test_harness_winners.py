"""The typed lane defaults against the stored runs that chose them."""
import pytest

from harness import memory_store as ms
from harness import winners


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def pin(monkeypatch, **defaults):
    """Pin the typed defaults this test is about.

    THE SPEECH DEFAULTS ARE CHOSEN BY PLATFORM -- parakeet on a Mac,
    faster-whisper on Windows -- so a test that inherits them is partly a test
    about which operating system ran it. Two of these failed on check-windows
    for exactly that, the same shape as the verdict test that inherited the
    runner's mlx runtime.
    """
    monkeypatch.setattr(winners, "typed", lambda: dict(defaults))


def test_a_default_that_appears_in_no_receipt_is_unmeasured_not_beaten(store_run, conn):
    """THE FALSE ALARM THIS EXISTS TO AVOID. The first cut took the best
    candidate across every receipt on disk and reported that extract had been
    won by a model scoring 0.7 -- because the only extract receipt here is a
    three-small-model run the typed default was never part of, while the run
    that scored it 9/10 predates receipts entirely."""
    store_run("small", "extract",
            {"q3-1.7b": {"pass_rate": 0.7, "median_s": 0.4, "total": 10}})
    rows = {r["modality"]: r for r in winners.disagreements(conn)}
    assert rows["extract"]["state"] == "unmeasured"
    assert rows["extract"]["measured"] == ""


def test_a_default_that_lost_a_run_it_was_in_is_reported(store_run, conn):
    store_run("head-to-head", "extract",
            {"local-large": {"pass_rate": 0.5, "median_s": 1.0, "total": 10},
             "q3-4b": {"pass_rate": 0.9, "median_s": 2.0, "total": 10}})
    rows = {r["modality"]: r for r in winners.disagreements(conn)}
    assert rows["extract"]["state"] == "beaten"
    assert rows["extract"]["measured"] == "q3-4b"


def test_a_default_that_won_is_not_reported_at_all(store_run, conn):
    store_run("head-to-head", "extract",
            {"local-large": {"pass_rate": 0.9, "median_s": 1.0, "total": 10},
             "q3-4b": {"pass_rate": 0.5, "median_s": 2.0, "total": 10}})
    rows = {r["modality"]: r for r in winners.disagreements(conn)}
    assert "extract" not in [r for r in rows if rows[r]["state"] == "beaten"]


def test_a_screen_never_decides_a_lane(store_run, conn):
    """A screen answers whether it ran; a measurement answers whether it is
    better. Ranking one against the other compares two different exams."""
    store_run("screened", "extract",
            {"local-large": {"pass_rate": 0.1, "median_s": 1.0},
             "q3-4b": {"pass_rate": 1.0, "median_s": 2.0}}, tier="screen")
    assert winners.beaten_in(conn) == {}


def test_a_workflow_is_not_a_model_default(store_run, conn):
    """`repair:local-large` can win a lane on merit and is still not something
    a --model default can be set to."""
    store_run("svg", "svg",
            {"local-large": {"pass_rate": 0.6, "median_s": 5.0},
             "repair/local-large": {"pass_rate": 1.0, "median_s": 8.0}})
    assert winners.beaten_in(conn)["svg"]["candidate"] == "local-large"


def test_the_faster_of_two_equals_wins(store_run, conn):
    store_run("svg", "svg",
            {"local-large": {"pass_rate": 1.0, "median_s": 9.0},
             "q3-4b": {"pass_rate": 1.0, "median_s": 2.0}})
    assert winners.beaten_in(conn)["svg"]["candidate"] == "q3-4b"


# --- a default is in a run by candidate id, not by spelling (#429) --------

def test_an_engine_default_is_found_under_the_key_its_runner_writes(store_run,
                                                                   conn):
    """`mflux:flux2-klein-4b` runs as `mflux/flux2-klein-4b-q8`; the stored
    mapping says so, so no `:`/`/` or `-q8` rule is needed."""
    store_run("img", "image", {
        "mflux/flux2-klein-4b-q8": {"pass_rate": 1.0, "median_s": 1.0}})
    got = winners.beaten_in(conn)["image"]
    assert (got["candidate"], got["match"]) == ("mflux/flux2-klein-4b-q8",
                                                "exact")


def test_a_lookalike_key_is_not_the_default(store_run, conn):
    """A string that merely resembles the default's key is another candidate."""
    store_run("img", "image", {
        "mflux/flux2-klein-4b": {"pass_rate": 1.0, "median_s": 1.0}})
    assert "image" not in winners.beaten_in(conn)


def test_a_speech_default_is_found_through_its_candidate_row(store_run, conn,
                                                             monkeypatch):
    pin(monkeypatch, stt="mlx-community/parakeet-tdt-0.6b-v2")
    store_run("stt", "stt", {
        "parakeet-tdt-0.6b-v2": {"pass_rate": 1.0, "median_s": 0.1},
        "parakeet-tdt-0.6b-v3": {"pass_rate": 0.9, "median_s": 0.1}})
    got = winners.beaten_in(conn)["stt"]
    assert (got["candidate"], got["match"]) == ("parakeet-tdt-0.6b-v2", "exact")


def test_every_typed_default_declares_which_family_it_belongs_to():
    assert set(winners.typed()) <= set(winners.FAMILIES)
    assert set(winners.typed()) == {"svg", "web", "code", "extract", "image",
                                    "video", "music", "tts", "stt", "decide", "agent"}


# --- the lane's own metric decides, not a statistic blind to it -----------

def test_the_lanes_metric_beats_pass_rate_and_latency(store_run, conn, monkeypatch):
    """NOT HYPOTHETICAL. Ranking on pass rate and then latency reported that
    parakeet-ctc had beaten parakeet-tdt-v2: both passed 300 of 300 and ctc has
    the faster median, so on those two statistics ctc wins and on WER -- the
    one the lane is about -- it loses."""
    pin(monkeypatch, stt="mlx-community/parakeet-tdt-0.6b-v2")
    store_run("stt", "stt", {
        "parakeet-tdt-0.6b-v2": {"pass_rate": 1.0, "median_s": 0.135,
                                 "total": 300, "metrics": {"wer": 0.0162}},
        "parakeet-ctc-0.6b": {"pass_rate": 1.0, "median_s": 0.116,
                              "total": 300, "metrics": {"wer": 0.0225}}})
    got = winners.beaten_in(conn)["stt"]
    assert got["candidate"] == "parakeet-tdt-0.6b-v2"


def test_a_higher_is_better_metric_runs_the_other_way(store_run, conn):
    store_run("img", "image", {
        "mflux/a": {"pass_rate": 1.0, "median_s": 1.0,
                    "metrics": {"adherence": 0.9}},
        "mflux/flux2-klein-4b-q8": {"pass_rate": 1.0, "median_s": 1.0,
                                    "metrics": {"adherence": 0.4}}})
    assert winners.beaten_in(conn)["image"]["candidate"] == "mflux/a"


def test_a_neutral_metric_is_never_ranked_on(store_run, conn):
    """`ink` as higher-is-better once crowned the worst candidate in the svg
    lane, because one big filled blob marks 85% of a canvas."""
    store_run("svg", "svg", {
        "local-large": {"pass_rate": 1.0, "median_s": 1.0,
                        "metrics": {"ink": 0.02}},
        "q3-4b": {"pass_rate": 1.0, "median_s": 2.0,
                  "metrics": {"ink": 0.85}}})
    assert winners.beaten_in(conn)["svg"]["candidate"] == "local-large"


def test_passing_less_often_loses_whatever_the_metric_says(store_run, conn,
                                                          monkeypatch):
    """A model that fails half the cases and scores well on the rest scored on
    a different, easier subset."""
    pin(monkeypatch, stt="mlx-community/parakeet-tdt-0.6b-v2")
    # A receipt key is a model, or a model and the voice it used -- never the
    # org-prefixed id the default carries.
    store_run("stt", "stt", {
        "parakeet-tdt-0.6b-v2": {"pass_rate": 1.0, "median_s": 1.0,
                                 "metrics": {"wer": 0.05}},
        "other": {"pass_rate": 0.5, "median_s": 1.0,
                  "metrics": {"wer": 0.001}}})
    got = winners.beaten_in(conn)["stt"]
    assert got["candidate"] == "parakeet-tdt-0.6b-v2"


def test_a_speech_default_is_whichever_this_platform_would_actually_use():
    """The branch is deliberate and belongs in ONE test rather than being
    assumed by several: comparing a Mac's receipts against a Windows constant
    would be the accelerator mistake in another costume."""
    import sys
    from harness import audio
    assert winners.typed()["stt"] == audio.DEFAULT_STT_MODEL
    assert winners.typed()["tts"] == audio.DEFAULT_TTS_MODEL
    if sys.platform != "win32":
        assert "parakeet" in winners.typed()["stt"]


def test_a_variant_sharing_the_served_key_is_its_own_candidate(conn,
                                                               monkeypatch):
    """#429: rows group by candidate id, so a variant's passes are not the default's."""
    from harness import candidates, paths, runs
    pin(monkeypatch, extract="local-large")
    served = candidates.ensure(conn, "local-large", key="local-large",
                               lane="extract")
    variant = candidates.ensure(conn, "local-large,temperature=0",
                                key="local-large", lane="extract")

    def row(cid, case, passed):
        return {"case_id": case, "candidate": "local-large", "passed": passed,
                "seconds": 1.0, "candidate_id": cid}

    runs.record(conn, paths.runs() / "pair", {
        "generated": "2026-10-05T12:00:00",
        "receipt": {"modality": "extract", "tier": "measure"},
        "rows": [row(served, "a", False), row(served, "b", False),
                 row(variant, "a", True), row(variant, "b", True)]})
    got = winners.beaten_in(conn)["extract"]
    assert (got["candidate_id"], got["pass_rate"], got["match"]) == \
        (variant, 1.0, "")

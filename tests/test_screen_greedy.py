"""A screen is one draw, so it must be the same draw every time. #308."""
from evals import run


def test_a_screen_samples_text_candidates_greedily():
    got = run.greedy(["q3-4b", "llamacpp:M", "org/repo"])
    assert got == ["q3-4b,temperature=0", "llamacpp:M,temperature=0",
                   "org/repo,temperature=0"]


def test_an_explicit_temperature_is_left_alone():
    assert run.greedy(["q3-4b,temperature=0.7"]) == ["q3-4b,temperature=0.7"]


def test_other_options_survive():
    assert run.greedy(["q3-4b,top_p=0.9"]) == ["q3-4b,top_p=0.9,temperature=0"]


def test_engines_without_a_temperature_are_untouched():
    """Negative control: an image spec has no sampling to pin."""
    spec = "mflux:flux2-klein-4b"
    assert run.greedy([spec]) == [spec]


def test_the_receipt_records_the_temperature_the_screen_used():
    got = run.effective_sampling("code", run.greedy(["q3-4b"]))
    assert got["code"]["temperature"] == 0.0


def test_the_receipt_key_is_unchanged():
    r = run.build_runner("q3-4b,temperature=0", "http://gw", None)
    assert r.candidate == "q3-4b" and r.sampling == {"temperature": 0.0}

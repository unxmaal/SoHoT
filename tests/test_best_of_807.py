"""best-of stops once a sample passes clean, samples after the first concurrently up to the base's
slots, and is priced at the calls it is expected to make. #807."""
import argparse
import threading
import time

import pytest

from evals.core import Case
from evals.runners.base import BaseRunner
from harness import completion, methods
from tests.test_projection_696 import _budget, _rows

GOOD = "def f():\n    return 1\n"
BROKEN = "def f(:\n"


def counting(replies, delay=0.0, peak=None):
    made, lock, live = [], threading.Lock(), [0]

    def ask(prompt, modality):
        with lock:
            made.append(modality)
            i = len(made) - 1
            live[0] += 1
            if peak is not None:
                peak[0] = max(peak[0], live[0])
        time.sleep(delay)
        with lock:
            live[0] -= 1
        return replies[min(i, len(replies) - 1)]
    return ask, made


def test_a_first_sample_that_passes_clean_is_the_only_call():
    ask, made = counting([GOOD, BROKEN, BROKEN])
    text, meta = methods.run("best-of:3:q3-4b", "code", "write f", ask, slots=3)
    assert text == GOOD and len(made) == 1
    assert meta["calls"] == 1 and meta["samples"] == 3 and meta["chosen"] == 1
    assert meta["wall_s"] >= 0


def test_one_slot_samples_in_turn_and_stops_at_the_first_clean_pass():
    ask, made = counting([BROKEN, GOOD, BROKEN, BROKEN])
    text, meta = methods.run("best-of:4:q3-4b", "code", "write f", ask, slots=1)
    assert text == GOOD and len(made) == 2 and meta["calls"] == 2 and meta["chosen"] == 2


def test_samples_after_the_first_go_concurrently_up_to_the_slots():
    peak = [0]
    ask, made = counting([BROKEN], 0.2, peak)
    _, meta = methods.run("best-of:4:q3-4b", "code", "write f", ask, slots=3)
    assert len(made) == 4 and meta["calls"] == 4
    assert peak == [3]   # the first alone, then three at once; a timing bound flaked on CI


def test_slots_are_asked_only_when_a_second_wave_is_needed(monkeypatch):
    asked = []
    monkeypatch.setattr(methods, "slots_of", lambda spec: asked.append(spec) or 2)
    methods.run("best-of:3:q3-4b", "code", "x", counting([GOOD])[0])
    assert asked == []
    _, meta = methods.run("best-of:3:q3-4b", "code", "x", counting([BROKEN])[0])
    assert asked == ["q3-4b"] and meta["calls"] == 3


class Slow(BaseRunner):
    candidate = "base"

    def __init__(self, answers, delay=0.0):
        self.answers, self.delay, self.made, self.lock = answers, delay, [], threading.Lock()

    def generate(self, case):
        with self.lock:
            self.made.append(1)
            i = len(self.made) - 1
        time.sleep(self.delay)
        return self.answers[min(i, len(self.answers) - 1)], 0

    def extra_metrics(self):
        return {"completion_tokens": 10}


def extract_case():
    return Case(id="e", modality="extract", prompt="what number?", assertions={"equals": "137"})


def test_the_runner_stops_at_a_first_sample_that_passes():
    from evals.runners.method import BestOfRunner
    base = Slow(["137", "12", "12"])
    r = BestOfRunner(base, 3, slots=3).run(extract_case())
    assert r.passed and len(base.made) == 1
    assert r.metrics["method_calls"] == 1 and r.metrics["method_samples"] == 3
    assert r.metrics["completion_tokens"] == 10


def test_the_runner_samples_concurrently_and_its_seconds_are_wall_time():
    from evals.runners.method import BestOfRunner
    delay = 0.3
    base = Slow(["12"], delay)
    r = BestOfRunner(base, 4, slots=3).run(extract_case())
    assert len(base.made) == 4 and r.metrics["method_calls"] == 4
    assert r.seconds < 3.5 * delay   # two delays concurrent, four in turn
    assert r.metrics["completion_tokens"] == 40


def test_expected_calls_follow_the_bases_per_case_pass_rates():
    assert methods.expected_calls("best-of:3:x") == 3
    assert methods.expected_calls("best-of:3:x", [1.0, 0.0]) == 2.0
    assert methods.expected_calls("best-of:3:x", [0.5]) == 1.75
    assert methods.expected_calls("best-of:3:x", [0.5], slots=3) == 1.5
    assert methods.expected_calls("plan:x", [1.0]) == 2
    assert methods.expected_calls("x", [0.5]) == 1


def _ns(**kw):
    return argparse.Namespace(**{"repeat": 1, "effect": 0.4, "power_budget_min": 10_000_000, **kw})


def test_measure_prices_best_of_at_its_bases_expected_calls_not_n(store_run):
    from harness.commands import measure as measure_cmd
    store_run("inc-1", "code", rows=_rows("code", "inc", 10.0), receipt=_budget("code"))
    _, plan = measure_cmd._plan(_ns(), "code", "inc", "best-of:3:inc")
    est = plan.as_dict()["estimate"]
    assert est["challenger_calls"] == 1.75    # every case passes half its draws
    assert plan.projected_s == pytest.approx(plan.cases_run * 10.0 * (1 + 1.75))


def test_a_failed_wave_still_raises_when_nothing_came_back():
    def dead(prompt, modality):
        raise completion.CompletionError("down")
    with pytest.raises(completion.CompletionError, match="down"):
        methods.run("best-of:3:q3-4b", "code", "x", dead, slots=3)

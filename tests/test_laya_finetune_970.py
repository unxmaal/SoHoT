"""Laya fine-tuned vs the embedding control: #311's folds, blinded test items, AUC, temperature and the paired verdict. #970."""
import hashlib
import json
import random

import pytest

from evals.analysis import laya_finetune as F


def _labels(tmp_path, n=60, held=10, seed=1):
    rng = random.Random(seed)
    rows = [{"id": 1000 + i, "text": f"exchange {i}", "label": "relevant" if i % 2 else "irrelevant",
             "held_out": i < held, "cascade_stage": rng.choice(["lexicon", "residue", "embed"])} for i in range(n)]
    path = tmp_path / "labels.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_the_folds_are_infovores_stratified_folds_over_the_items_not_held_out(tmp_path):
    items = F.load_labels(_labels(tmp_path))
    got = F.folds(items, 5)
    assert set(got) == {r["id"] for r in items if not r["held_out"]}
    for label in (True, False):
        ids = sorted((r["id"] for r in items if r["y"] is label and not r["held_out"]),
                     key=lambda e: hashlib.sha256(f"embed-cv-v1:{e}".encode()).digest())
        assert [got[e] for e in ids] == [i % 5 for i in range(len(ids))]


def test_every_trainable_item_is_tested_once_by_a_model_that_never_saw_it(tmp_path):
    items = F.load_labels(_labels(tmp_path))
    seen = []
    for name, train, test in F.splits(items, F.folds(items, 5), 5):
        assert not {r["id"] for r in train} & {r["id"] for r in test}
        assert not any(r["held_out"] for r in train)
        seen += [(name, r["id"]) for r in test]
    tested = [i for _, i in seen]
    assert sorted(tested) == sorted(r["id"] for r in items) and len(set(tested)) == len(tested)
    assert {i for n, i in seen if n == "held"} == {r["id"] for r in items if r["held_out"]}


def test_a_fitter_never_sees_a_test_label_and_a_finished_split_is_not_refit(tmp_path):
    items = F.load_labels(_labels(tmp_path))
    calls = []

    def fitter(train, test):
        assert all(set(r) == {"id", "text"} for r in test)
        calls.append(len(test))
        return [0.5] * len(test)
    dest = tmp_path / "s.jsonl"
    F.fit_arm(items, F.folds(items, 5), fitter, dest, 5)
    assert len(calls) == 6 and len(F.read_scores(dest)) == len(items)
    F.fit_arm(items, F.folds(items, 5), fitter, dest, 5)
    assert len(calls) == 6


def test_auc_ranks_ties_together():
    assert F.auc([False, False, True, True], [0.1, 0.2, 0.3, 0.4]) == 1.0
    assert F.auc([False, False, True, True], [0.4, 0.3, 0.2, 0.1]) == 0.0
    assert F.auc([False, True], [0.5, 0.5]) == 0.5
    assert F.auc([False, True, True, False], [0.1, 0.4, 0.35, 0.8]) == 0.5
    assert F.auc([True, True], [0.1, 0.2]) is None


def test_a_paired_bootstrap_of_one_arm_against_itself_is_a_tie_and_a_clear_gap_is_not():
    rng = random.Random(3)
    ys = [i % 2 == 1 for i in range(200)]
    good = [0.8 if y else 0.2 for y in ys]
    noise = [rng.random() for _ in ys]
    same = F.paired_auc(ys, noise, noise, resamples=300)
    assert same["verdict"] == "tie" and same["ci"] == (0.0, 0.0)
    assert F.paired_auc(ys, good, noise, resamples=300)["verdict"] == "a better"
    assert F.paired_auc(ys, noise, good, resamples=300)["verdict"] == "b better"


def test_the_fitted_temperature_recovers_the_one_that_made_the_data():
    rng = random.Random(5)
    zs = [rng.uniform(-6, 6) for _ in range(4000)]
    ys = [rng.random() < F._sigmoid(z / 2.0) for z in zs]
    assert F.fit_temperature(ys, [F._sigmoid(z) for z in zs]) == pytest.approx(2.0, rel=0.15)


def test_a_folds_temperature_is_fitted_on_the_other_folds_only():
    labels = {1: True, 2: False, 3: False, 4: True}
    scores = {1: ("fold0", 0.9), 2: ("fold0", 0.1), 3: ("fold1", 0.6), 4: ("fold1", 0.4)}
    got = F.calibrated(scores, labels)
    t0 = F.fit_temperature([False, True], [0.6, 0.4])
    assert t0 != F.fit_temperature([True, False, False, True], [0.9, 0.1, 0.6, 0.4])
    assert got[1] == pytest.approx(F._sigmoid(F._logit(0.9) / t0))
    t_held = F.fit_temperature([True, False, False, True], [0.9, 0.1, 0.6, 0.4])
    held = F.calibrated({**scores, 5: ("held", 0.7)}, {**labels, 5: True})
    assert held[5] == pytest.approx(F._sigmoid(F._logit(0.7) / t_held))


def test_gain_is_the_share_of_relevant_items_found_in_the_top_share():
    ys = [True, True, False, False, False, False, False, False, False, True]
    ps = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]
    assert F.gain(ys, ps, 0.10) == pytest.approx(1 / 3)
    assert F.gain(ys, ps, 0.50) == pytest.approx(2 / 3)


def test_ece_is_zero_for_scores_that_match_their_hit_rate():
    ys = [True] * 8 + [False] * 2 + [False] * 8 + [True] * 2
    assert F.ece(ys, [0.8] * 10 + [0.2] * 10) == pytest.approx(0.0)
    assert F.ece([True, False], [0.99, 0.99]) == pytest.approx(0.49, abs=1e-9)
    assert F.ece([False, True], [0.01, 0.01]) == pytest.approx(0.49, abs=1e-9)


def _fake_fit(labels, by_arm):
    def fit(arm, folds_path, dest):
        items = F.load_labels(labels)
        assigned = {int(k): v for k, v in json.loads(folds_path.read_text(encoding="utf-8")).items()}
        truth = {r["id"]: r["y"] for r in items}
        F.fit_arm(items, assigned, lambda train, test: [by_arm[arm](truth[r["id"]], r["id"]) for r in test], dest)
    return fit


def test_run_names_the_better_arm_only_when_the_paired_interval_excludes_zero(tmp_path):
    fake_labels = _labels(tmp_path, n=200, held=20)
    rng = random.Random(9)
    noise = {i: rng.random() for i in range(1000, 1200)}
    arms = {"embed": lambda y, i: noise[i], "laya-ft": lambda y, i: (0.7 if y else 0.3) + 0.01 * noise[i],
            "laya-zs": lambda y, i: noise[i]}
    text = F.run(fake_labels, tmp_path / "out", ["embed", "laya-ft", "laya-zs"], _fake_fit(fake_labels, arms), resamples=200)
    assert "200 (100 relevant), 20 held out" in text
    assert (tmp_path / "out" / "report.txt").read_text(encoding="utf-8") == text + "\n"
    assert "AUC(laya-ft) - AUC(embed), all n=200" in text and "-> laya-ft better" in text
    zs = next(line for line in text.splitlines() if "AUC(laya-zs) - AUC(embed), all" in line)
    assert zs.endswith("-> tie") and "+0.000 [+0.000, +0.000]" in zs
    row = next(line for line in text.splitlines() if line.startswith("| laya-ft | all |"))
    assert "| 200 (100) | 1.000 [1.000, 1.000] |" in row
    assert json.loads((tmp_path / "out" / "folds.json").read_text(encoding="utf-8")) == {
        str(k): v for k, v in F.folds(F.load_labels(fake_labels)).items()}


def test_the_fit_command_runs_isolated_in_the_named_python_with_every_knob():
    args = F.argparse.Namespace(python="/v/bin/python", labels="L", model="M", embed_model="E", device="mps",
                                epochs=3, micro_batch=4, grad_accum=2, seed=7, k=5)
    cmd = F._fit_command(args, "laya-ft", F.Path("f.json"), F.Path("d.jsonl"))
    assert cmd[:2] == ["/v/bin/python", "-I"] and cmd[3] == "fit"
    pairs = dict(zip(cmd[4::2], cmd[5::2]))
    assert pairs["--arm"] == "laya-ft" and pairs["--epochs"] == "3" and pairs["--grad-accum"] == "2"
    assert pairs["--seed"] == "7" and pairs["--embed-model"] == "E" and pairs["--folds"] == "f.json"

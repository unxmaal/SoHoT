"""`soh hear --suspect`: stt clips whose ears agree with each other against the reference (#94)."""
import json

import pytest

from harness import cli, clips, paths, runs
from harness import memory_store as ms


def case(root, cid, prompt):
    d = root / "stt"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cid}.yaml").write_text(f"id: {cid}\nmodality: stt\nprompt: {prompt}\naudio_file: /corpus/{cid}.flac\n",
                                   encoding="utf-8")


def heard(cid, cand, text):
    return {"case_id": cid, "candidate": cand, "passed": False, "output": text, "metrics": {"wer": 0.5}}


@pytest.fixture
def cases(tmp_path):
    root = tmp_path / "cases"
    case(root, "wrongref", "the influence with the timaeus has exercised")
    case(root, "hard", "the bat sat on the mat")
    case(root, "fewears", "a man entered the room")
    case(root, "spelling", "it happened to day")
    case(root, "rightref", "birds sing loudly")
    case(root, "split", "one dog growled")
    return root


@pytest.fixture
def store(cases):
    conn = ms.connect()
    try:
        rows = [heard("wrongref", c, "The influence which the Timaeus has exercised.") for c in "abc"]
        rows.append(heard("wrongref", "d", "the influence with the timaeus has exercised"))
        rows += [heard("hard", "a", "the cat sat on the mat"), heard("hard", "b", "a bat sat on a mat"),
                 heard("hard", "c", "the bat sat on that"), heard("hard", "d", "the hat sat on the mat")]
        rows += [heard("fewears", c, "the men entered the room") for c in "ab"]
        rows += [heard("spelling", c, "It happened today.") for c in "abc"]
        rows += [heard("rightref", c, "birds sing loudly") for c in "abc"]
        rows += [heard("split", c, "one dog barked") for c in "abc"]
        rows += [heard("split", c, f"one dog {w}") for c, w in zip("defg", ("ran", "sat", "slept", "ate"))]
        run = paths.runs() / "r-stt"
        run.mkdir(parents=True, exist_ok=True)
        runs.record(conn, run, {"receipt": {"modality": "stt"}, "environment": ms.this_machine(), "rows": rows})
    finally:
        conn.close()
    return ms.db_path()


def ids(got):
    return [c["case_id"] for c in got]


def test_ears_that_agree_against_the_reference_make_it_suspect(store, cases):
    got = clips.suspects(store=store, cases_dir=cases)
    assert ids(got) == ["wrongref"]
    top = got[0]
    assert (top["agree"], top["ears"], top["errors"]) == (3, 4, 1)
    assert top["candidates"] == ["a", "b", "c"]
    assert top["audio"] == "/corpus/wrongref.flac"


def test_ears_that_disagree_with_each_other_make_a_hard_clip_not_a_suspect(store, cases):
    assert "hard" not in ids(clips.suspects(store=store, cases_dir=cases))


def test_agreement_short_of_a_majority_of_the_ears_proves_nothing(store, cases):
    assert "split" not in ids(clips.suspects(store=store, cases_dir=cases))


def test_fewer_ears_than_the_minimum_prove_nothing(store, cases):
    assert "fewears" not in ids(clips.suspects(store=store, cases_dir=cases))
    assert "fewears" in ids(clips.suspects(store=store, cases_dir=cases, ears=2))


def test_a_difference_the_current_scorer_forgives_is_not_suspect(store, cases):
    assert "spelling" not in ids(clips.suspects(store=store, cases_dir=cases))


def test_the_command_lists_suspects_as_json(store, cases, capsys):
    assert cli.main(["hear", "--suspect", "--json", "--store", str(store), "--cases", str(cases)]) == 0
    got = json.loads(capsys.readouterr().out)
    assert ids(got["clips"]) == ["wrongref"]

"""`soh adopt --power --table`: each lane's holdout against the cases its effect needs. #603."""
import json
import math

from harness import adopt, cli, holdout, lanes, power


def _rows(capsys, *argv):
    assert cli.main(["adopt", "--json", "--power", *argv]) == 0
    return {r["lane"]: r for r in json.loads(capsys.readouterr().out)["lanes"]}


def test_the_table_prints_one_row_per_lane_with_holdout_and_cases_needed(capsys, monkeypatch):
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    assert cli.main(["adopt", "--power", "--table", "--lane", "svg"]) == 0
    out = capsys.readouterr().out.splitlines()
    head = next(i for i, line in enumerate(out) if line.split()[:1] == ["lane"])
    assert out[head].split() == ["lane", "cases", "holdout", "noise", "effect", "from", "rho", "rows", "power",
                                 "needed", "more_holdout", "more_cases", "status"]
    svg = out[head + 1].split()
    split = holdout.for_lane("svg")
    assert svg[:6] == ["svg", str(len(split.dev) + len(split.holdout)), str(len(split.holdout)),
                       f"{power.noise_for('svg'):.2f}", f"{power.effect_for('svg'):.2f}", "measured"]
    assert [line.split()[0] for line in out[head + 1:] if line.split()[0] in lanes.ALL] == ["svg"]


def test_more_cases_is_the_holdout_shortfall_over_the_holdout_fraction(capsys, monkeypatch):
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    row = _rows(capsys, "--lane", "web")["web"]
    assert row["more_holdout"] > 0
    assert row["more_cases"] == math.ceil(row["more_holdout"] / holdout.FRACTION)
    assert row["status"] == f"short {row['more_holdout']}"


def test_the_effect_names_where_it_came_from(capsys, monkeypatch):
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    assert "image" not in power.EFFECT
    assert _rows(capsys, "--lane", "svg")["svg"]["effect_from"] == "measured"
    assert _rows(capsys, "--lane", "image")["image"]["effect_from"] == "default"
    assert _rows(capsys, "--lane", "svg", "--effect", "0.3")["svg"]["effect_from"] == "given"


def test_a_lane_with_no_cases_here_gets_a_row_saying_so(capsys, monkeypatch):
    every = {k: v for k, v in holdout.splits().items() if k == "web"}
    monkeypatch.setattr(holdout, "splits", lambda root=None: every)
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    rows = _rows(capsys)
    assert set(rows) == set(lanes.ALL)
    stt = rows["stt"]
    assert stt["cases"] == 0 and stt["holdout"] == 0 and stt["status"] == "no cases here"
    assert rows["web"]["status"].startswith("short")


def test_a_lane_whose_holdout_reaches_its_need_is_enough(capsys, monkeypatch):
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    row = _rows(capsys, "--lane", "svg", "--effect", "1.0")["svg"]
    assert row["more_holdout"] == 0 and row["more_cases"] == 0 and row["status"] == "enough"

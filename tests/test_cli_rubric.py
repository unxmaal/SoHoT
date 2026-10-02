"""`lh rubric`. Issue #286."""
import json

import pytest
import yaml

from harness import cli, rubric_eval as rv

RUBRIC = {
    "name": "durable-fact", "version": 1, "instructions": "Fact?",
    "label": "verdict",
    "schema": {"type": "object", "required": ["verdict"],
               "properties": {"verdict": {"enum": ["fact", "no-fact"]}}},
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    root = tmp_path / "evalsets" / "demo"
    root.mkdir(parents=True)
    (root / "rubric.yaml").write_text(yaml.safe_dump(RUBRIC), encoding="utf-8")
    (root / "items.jsonl").write_text(
        json.dumps({"id": "a", "text": "J6 2-3"}) + "\n"
        + json.dumps({"id": "b", "text": "lol"}) + "\n", encoding="utf-8")
    return tmp_path, root


def test_status_resolves_a_bare_name_under_evalsets(home, capsys):
    _, root = home
    rv.record_label(root, "a", "fact")
    assert cli.main(["rubric", "status", "demo"]) == 0
    out = capsys.readouterr().out
    assert "1 of 2" in out


def test_run_writes_a_receipt_and_prints_floor_and_ceiling(home, capsys, monkeypatch):
    tmp, root = home
    rv.record_label(root, "a", "fact")
    rv.record_label(root, "b", "no-fact")
    monkeypatch.setattr(rv, "evaluate", lambda r, text, model, gw, post=None:
                        rv.Verdict(True, "fact", '{"verdict":"fact"}', "", 0.1))
    assert cli.main(["rubric", "run", "demo", "--candidates", "eval-4b"]) == 0
    out = capsys.readouterr().out
    assert "floor" in out and "ceiling" in out and "eval-4b" in out
    receipts = list((tmp / "runs").glob("rubric-*/results.json"))
    assert len(receipts) == 1
    body = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert body["candidates"]["eval-4b"]["agree"] == 1


def test_run_without_labels_fails_with_a_reason(home, capsys):
    assert cli.main(["rubric", "run", "demo", "--candidates", "m"]) != 0
    assert "label" in capsys.readouterr().err


def test_an_unknown_set_fails_with_a_reason(home, capsys):
    assert cli.main(["rubric", "status", "nope"]) != 0

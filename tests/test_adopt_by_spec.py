"""A hand adoption stores something the lane can run. #337."""
import json
from pathlib import Path

from harness import adopt, cli, engines, human, judge_server, screen
from harness import memory_store as ms

INCUMBENT = "acestep:acestep-v15-turbo,steps=8"
CHALLENGER = "acestep:ACE-Step/acestep-v15-xl-turbo,steps=8"


def _judged_run(tmp_path, monkeypatch, specs):
    names = [engines.resolve(s).name for s in (INCUMBENT, CHALLENGER)]
    run = tmp_path / "20261005-000000-music"
    run.mkdir()
    body = {"receipt": {"modality": "music"}, "summary": {}, "rows": []}
    if specs:
        body["specs"] = {engines.resolve(s).name: s
                         for s in (INCUMBENT, CHALLENGER)}
    (run / "results.json").write_text(json.dumps(body), encoding="utf-8")
    pairs = [{"case": "c", "a": names[0], "b": names[1]}]
    monkeypatch.setattr(human, "pairings", lambda receipt: pairs)
    monkeypatch.setattr(human, "decided", lambda *a: names[1])
    monkeypatch.setattr(human, "lane_verdict",
                        lambda lane, p: (names[1], "preferred 1-0"))
    monkeypatch.setattr(judge_server, "serve", lambda *a, **kw: None)
    monkeypatch.setattr(adopt, "default_for", lambda lane, fb, conn=None:
                        INCUMBENT)
    return run


def _adopted():
    conn = ms.connect()
    try:
        return adopt.adopted(conn).get("music")
    finally:
        conn.close()


def test_the_judge_records_the_spec_not_the_display_name(tmp_path,
                                                         monkeypatch):
    """The name drops the repo org. Stored, it could not be run."""
    run = _judged_run(tmp_path, monkeypatch, specs=True)
    assert cli.main(["judge", str(run), "--lane", "music", "--no-browser"]) == 0
    assert _adopted() == CHALLENGER


def test_a_receipt_without_specs_still_records_the_name(tmp_path, monkeypatch):
    """Negative control: older receipts carry no specs and behave as before."""
    run = _judged_run(tmp_path, monkeypatch, specs=False)
    assert cli.main(["judge", str(run), "--lane", "music", "--no-browser"]) == 0
    assert _adopted() == engines.resolve(CHALLENGER).name


def test_a_stored_display_name_runs_the_same_program(monkeypatch, tmp_path):
    """The row already in the store, `acestep/acestep-v15-turbo@steps=8`,
    must reach ACE-Step as `acestep-v15-turbo` with its steps."""
    monkeypatch.setenv(engines.ACESTEP_ROOT_ENV, str(tmp_path))
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    want = engines.resolve(INCUMBENT)
    got = engines.resolve(screen.candidate_for("music", want.name))
    out = Path("/tmp/o.wav")
    assert got.name == want.name
    assert got.argv("x", out, {}) == want.argv("x", out, {})


def test_a_run_writes_its_specs(tmp_path, monkeypatch):
    from evals import run as er
    src = Path(er.__file__).read_text(encoding="utf-8")
    assert '"specs": specs' in src and "specs[runner.candidate] = candidate" in src

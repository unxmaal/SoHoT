"""A hand adoption stores something the lane can run. #337."""
import json
from pathlib import Path

from harness import adopt, cli, engines, human, judge_server
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


def test_a_receipt_without_specs_records_nothing_it_cannot_run(tmp_path,
                                                                monkeypatch):
    """A display name is not a spec: with no map, nothing is adopted. #407."""
    run = _judged_run(tmp_path, monkeypatch, specs=False)
    assert cli.main(["judge", str(run), "--lane", "music", "--no-browser"]) == 0
    assert _adopted() is None


def test_a_receipt_without_specs_uses_the_stored_mapping(tmp_path,
                                                         monkeypatch):
    """The candidates table already knows the key, so the spec is recorded."""
    from harness import candidates
    run = _judged_run(tmp_path, monkeypatch, specs=False)
    conn = ms.connect()
    candidates.ensure(conn, CHALLENGER, lane="music")
    conn.close()
    assert cli.main(["judge", str(run), "--lane", "music", "--no-browser"]) == 0
    assert _adopted() == CHALLENGER


def test_a_run_writes_its_specs(tmp_path, monkeypatch):
    from evals import run as er
    src = Path(er.__file__).read_text(encoding="utf-8")
    assert '"specs": specs' in src and "specs[runner.candidate] = candidate" in src


def test_a_reference_model_is_never_adopted():
    """#374: preferring Opus on a judged lane must not make it the default."""
    conn = ms.connect()
    try:
        adopt.record(conn, adopt.Verdict("svg", "local-large",
                                         "claude-code:claude-opus-5-5", True,
                                         "preferred by hand: 3-0"))
        conn.commit()
        assert adopt.adopted(conn).get("svg") is None
    finally:
        conn.close()


def test_a_local_challenger_preferred_by_hand_is_still_adopted():
    """Negative control."""
    conn = ms.connect()
    try:
        adopt.record(conn, adopt.Verdict("svg", "local-large", "q3-30b", True,
                                         "preferred by hand: 3-0"))
        conn.commit()
        assert adopt.adopted(conn).get("svg") == "q3-30b"
    finally:
        conn.close()

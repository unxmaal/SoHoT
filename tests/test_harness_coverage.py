"""Issue #99: what discovery never saw.

Precision measures the quality of what is caught. Nothing measured reach, and
those are different numbers.
"""
import time

import pytest

from harness import coverage
from harness import memory_store as ms
from harness.memory_store import Seen


@pytest.fixture
def db(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    yield conn
    conn.close()


def seen(db, name, source="reddit-sd-week", at=None):
    ms.record(db, Seen(name=name, source=source, url=f"https://x/{name}",
                       resolved=name), at=at)


# --- what counts as a find -----------------------------------------------

def test_a_source_that_surfaced_something_we_run_is_credited(db, tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(coverage, "adopted",
                        lambda *a, **kw: {"org/thing": {"measured"}})
    seen(db, "org/thing", source="reddit-sd-week")
    got = coverage.report(db)
    assert [e["name"] for e in got["found"]] == ["org/thing"]
    assert got["by_source"] == {"reddit-sd-week": 1}


def test_a_thing_no_source_ever_produced_is_a_hole_with_a_name(db, tmp_path,
                                                               monkeypatch):
    monkeypatch.setattr(coverage, "adopted",
                        lambda *a, **kw: {"org/unseen": {"served"}})
    seen(db, "somebody/else")
    got = coverage.report(db)
    assert [h["name"] for h in got["holes"]] == ["org/unseen"]
    assert got["found"] == []


def test_our_own_tiers_are_not_credited_with_finding_anything(db, tmp_path,
                                                              monkeypatch):
    """`inspect` records what it read and `installed` is the seed list of what
    we already run. Crediting either with the find would be circular."""
    monkeypatch.setattr(coverage, "adopted",
                        lambda *a, **kw: {"org/thing": {"served"}})
    seen(db, "org/thing", source="inspect")
    got = coverage.report(db)
    assert got["found"] == []
    assert got["holes"][0]["why"].startswith("only recorded by a tier")


def test_a_source_that_agreed_afterwards_did_not_lead_us_to_it(db, store_run,
                                                               monkeypatch):
    """A thing found a month after it was already running did not lead us to
    it. That is the difference between a source that works and one that
    eventually agrees."""
    monkeypatch.setattr(coverage, "adopted",
                        lambda *a, **kw: {"org/thing": {"measured"}})
    store_run("r", "image", {"org/thing": {"pass_rate": 1.0}}, conn=db,
              specs={"org/thing": "org/thing"}, generated=time.strftime("%Y-%m-%dT%H:%M:%S",
                                      time.localtime(1_000_000.0)))
    seen(db, "org/thing", source="reddit-sd-week", at=2_000_000.0)
    got = coverage.report(db)
    assert got["found"] == []
    assert [e["name"] for e in got["late"]] == ["org/thing"]
    assert got["late"][0]["days_late"] > 10


# --- a thing is the proposal its candidates row names (#429) --------------

def _measured_run(db, store_run, key, spec, lane="stt"):
    store_run(f"r-{key.replace('/', '_')}", lane, {key: {"pass_rate": 1.0}},
              specs={key: spec}, conn=db)


def test_a_receipt_key_and_a_registry_id_are_one_thing_through_the_row(
        db, store_run):
    from harness import candidates
    seen(db, "mlx-community/parakeet-tdt-0.6b-v2", source="reddit-localllama-week",
         at=1.0)
    candidates.ensure(db, "stt:mlx-community/parakeet-tdt-0.6b-v2",
                      proposal="mlx-community/parakeet-tdt-0.6b-v2",
                      key="parakeet-tdt-0.6b-v2", lane="stt")
    _measured_run(db, store_run, "parakeet-tdt-0.6b-v2",
                  "stt:mlx-community/parakeet-tdt-0.6b-v2")
    assert "mlx-community/parakeet-tdt-0.6b-v2" in coverage.adopted(db)
    assert "mlx-community/parakeet-tdt-0.6b-v2" in \
        [e["name"] for e in coverage.report(db)["found"]]


def test_a_candidate_no_row_links_is_a_hole_not_a_spelling_match(
        db, store_run):
    """No segment rule: a shared tail does not make two names one thing."""
    seen(db, "mlx-community/parakeet-tdt-0.6b-v2", source="reddit-localllama-week",
         at=1.0)
    _measured_run(db, store_run, "parakeet-tdt-0.6b-v2", "parakeet-tdt-0.6b-v2")
    assert "parakeet-tdt-0.6b-v2" in coverage._measured(db, {})
    got = coverage.report(db)
    assert "parakeet-tdt-0.6b-v2" in [h["name"] for h in got["holes"]]
    assert "parakeet-tdt-0.6b-v2" not in [e["name"] for e in got["found"]]


def test_one_model_measured_across_voices_is_one_adopted_thing(db, store_run):
    from harness import candidates
    seen(db, "mlx-community/kokoro-82m-bf16")
    for voice in ("af_sky", "am_adam"):
        spec = f"tts:mlx-community/kokoro-82m-bf16,voice={voice}"
        candidates.ensure(db, spec, proposal="mlx-community/kokoro-82m-bf16",
                          key=f"kokoro-82m-bf16/{voice}", lane="tts")
        _measured_run(db, store_run, f"kokoro-82m-bf16/{voice}", spec, "tts")
    assert coverage._measured(db, {}).keys() == {"mlx-community/kokoro-82m-bf16"}


def test_a_run_option_variant_is_its_bare_specs_proposal(db):
    from harness import candidates
    seen(db, "org/x")
    candidates.ensure(db, "org/x", proposal="org/x", key="org/x")
    candidates.ensure(db, "org/x,temperature=0", key="org/x")
    assert candidates.get(db, "org/x,temperature=0")["proposal"] == "org/x"


def test_a_variant_stored_first_gets_the_proposal_when_its_base_does(db):
    from harness import candidates
    seen(db, "org/x")
    candidates.ensure(db, "org/x,temperature=0", key="org/x")
    assert candidates.get(db, "org/x,temperature=0")["proposal"] is None
    candidates.ensure(db, "org/x", proposal="org/x", key="org/x")
    assert candidates.get(db, "org/x,temperature=0")["proposal"] == "org/x"


def test_result_rows_with_no_candidate_are_counted_not_matched(db, store_run):
    seen(db, "org/thing", source="reddit-sd-week")
    store_run("r", "image", {"thing": {"pass_rate": 1.0}}, conn=db)
    got = coverage.report(db)
    assert set(got["unlinked"]) == {"thing"}
    assert "thing" not in coverage.adopted(db)


def test_a_publisher_is_not_a_model(db, tmp_path, monkeypatch):
    """Matching on an owner segment would call every model under one org the
    same model."""
    monkeypatch.setattr(coverage, "adopted",
                        lambda *a, **kw: {"mlx-community/some-model": {"served"}})
    for other in ("mlx-community/a", "mlx-community/b", "mlx-community/c"):
        seen(db, other)
    got = coverage.report(db)
    assert [h["name"] for h in got["holes"]] == ["mlx-community/some-model"]


def test_a_base_model_is_not_the_requantisation_we_run(db, tmp_path,
                                                       monkeypatch):
    """`Qwen/Qwen2.5-7B` and `mlx-community/Qwen2.5-7B-Instruct-4bit` are a
    base and a requant of it, which are not the same thing to download or to
    run. Calling that a find credits a source with a surface it did not."""
    monkeypatch.setattr(coverage, "adopted", lambda *a, **kw: {
        "mlx-community/qwen2.5-7b-instruct-4bit": {"served"}})
    seen(db, "Qwen/Qwen2.5-7B")
    assert coverage.report(db)["found"] == []


# --- the report has to distinguish two opposite problems -----------------

def test_a_source_producing_plenty_nobody_ran_is_not_a_source_producing_nothing(
        db, tmp_path, monkeypatch):
    """Those want opposite fixes: one needs a better source, the other needs
    the ladder below it to turn."""
    monkeypatch.setattr(coverage, "adopted",
                        lambda *a, **kw: {"org/unseen": {"served"}})
    for i in range(4):
        seen(db, f"someone/proposal-{i}", source="reddit-sd-recap")
    got = coverage.report(db)
    assert got["proposed"] == {"reddit-sd-recap": 4}
    assert got["by_source"] == {}

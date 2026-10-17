"""#918: the blame-audit sampler, its report statistics and the terminal_reason_coherent audit check."""
import json

import pytest

from evals import claims_report
from harness import blame_audit as ba, cli, intervals, live_audit
from harness import memory_store as ms
from harness.memory_store.transitions import RETEST, RETRACTION

#: (tier, outcome, reason, until, how many): a population with known strata.
STRATA = [("screen", "declined", "runtime", "version:mlx-lm>0.32.0", 7),
          ("screen", "broken", "candidate", "", 3),
          ("adopt", "declined", "candidate", "", 2),
          ("inspect", "declined", "machine", "ceiling_gb:>70", 60),
          ("inspect", "declined", "upstream", "", 8),
          ("fetch", "declined", "candidate", "", 30),
          ("fetch", "declined", "limit", "limit:fetch_gb>100", 2)]


def _seed(conn, name, lane="code"):
    ms.record(conn, ms.Seen(name=name, source="s", kind="candidate", registry=ms.HUGGINGFACE,
                            lane=lane, resolved=name))
    ms.decide(conn, name, "queued", tier="inspect", detail="fits")


def _store(strata=STRATA, prefix="org"):
    conn = ms.connect()
    for tier, outcome, reason, until, n in strata:
        for i in range(n):
            name = f"{prefix}/{tier}-{reason}-{i}"
            _seed(conn, name)
            ms.decide(conn, name, outcome, tier=tier, reason=reason, until=until)
    return conn


@pytest.fixture
def store():
    conn = _store()
    yield conn
    conn.close()


def _retracted(conn, n, tier="screen", then="screened", prefix="retracted"):
    for i in range(n):
        name = f"org/{prefix}-{tier}-{i}"
        _seed(conn, name)
        ms.decide(conn, name, "broken", tier=tier, reason="candidate")
        ms.decide(conn, name, "queued", tier=tier, reopen=RETRACTION, reopen_why="ours")
        if not then:
            ms.decide(conn, name, "queued", tier="inspect", detail="fits")
        elif then == "broken":
            ms.decide(conn, name, "broken", tier=tier, reason="candidate")
        else:
            ms.decide(conn, name, then, tier=tier, reason="candidate")


def _run(conn, cases=8, max_tokens=32768, path="r/adopt"):
    receipt = {"modality": "code", "case_ids": [f"c{i}#1" for i in range(cases)]}
    if max_tokens is not None:
        receipt["max_tokens"] = max_tokens
    return conn.execute("INSERT INTO runs (path, lane, receipt, recorded_at) VALUES (?, 'code', ?, 0)",
                        (path, json.dumps(receipt))).lastrowid


def _lost(conn, n, run=None, prefix="lost"):
    run = _run(conn) if run is None else run
    for i in range(n):
        name = f"org/{prefix}-{i}"
        _seed(conn, name)
        ms.decide(conn, name, "declined", tier="adopt", reason="candidate", run_id=run)
        ms.decide(conn, name, "queued", tier="adopt", reopen=RETEST, reopen_why="test")


def test_a_census_tier_is_labelled_whole_and_a_drawn_stratum_gets_its_floor(store):
    rows, sizes = ba.sample(store, 918)
    got = {}
    for r in rows:
        got[r["stratum"]] = got.get(r["stratum"], 0) + 1
    assert sizes == {"adopt/candidate": 2, "fetch/candidate": 30, "fetch/limit": 2, "inspect/machine": 60,
                     "inspect/upstream": 8, "screen/candidate": 3, "screen/runtime": 7}
    assert got["screen/runtime"] == 7 and got["screen/candidate"] == 3 and got["adopt/candidate"] == 2
    drawn = {s: n for s, n in got.items() if s.split("/")[0] in ("inspect", "fetch")}
    assert sum(drawn.values()) == ba.DRAW_TOTAL
    assert drawn == {"fetch/candidate": 12, "fetch/limit": 2, "inspect/machine": 20, "inspect/upstream": 6}


def test_allocation_floors_at_five_or_the_whole_stratum_and_spends_the_rest_by_size():
    assert ba.allocate({"a": 1, "b": 100, "c": 10}, total=20, minimum=5) == {"a": 1, "b": 14, "c": 5}
    assert ba.allocate({"a": 3, "b": 4}, total=40, minimum=5) == {"a": 3, "b": 4}


def test_the_same_seed_on_the_same_store_gives_the_same_queue_and_another_seed_does_not(store):
    _retracted(store, 4)
    one, two = ba.build(store, 918), ba.build(store, 918)
    assert one == two
    assert [r["verdict_id"] for r in ba.build(store, 919)["queue"]] != [r["verdict_id"] for r in one["queue"]]
    assert one["header"]["max_verdict_id"] == ba.max_verdict(store)


def test_plants_are_retracted_or_lost_rows_outside_the_sample_and_the_queue_does_not_mark_them(store):
    _retracted(store, 12)
    _lost(store, 6)
    got = ba.build(store, 918)
    plants = [k for k in got["key"] if k["role"] == "plant"]
    assert sum(k["plant"] == ba.HARNESS for k in plants) == ba.PLANT_HARNESS
    assert sum(k["plant"] == ba.MODEL for k in plants) == ba.PLANT_MODEL
    sampled = {k["verdict_id"] for k in got["key"] if k["role"] == "sample"}
    assert not sampled & {k["verdict_id"] for k in plants}
    assert set(got["queue"][0]) == {"verdict_id", "name"}
    assert {r["verdict_id"] for r in got["queue"]} == sampled | {k["verdict_id"] for k in plants}
    assert {r["verdict_id"] for r in got["second"]} <= sampled and len(got["second"]) == ba.SECOND_N


def test_kappa_is_one_on_agreement_zero_at_chance_and_counts_only_shared_rows():
    a = {1: "harness", 2: "model", 3: "harness", 4: "model"}
    assert ba.kappa(a, dict(a)) == (1.0, 4)
    assert ba.kappa(a, {1: "harness", 2: "harness", 3: "model", 4: "model"}) == (0.0, 4)
    assert ba.kappa(a, {1: "harness", 9: "model"}) == (1.0, 1)
    assert ba.kappa(a, {}) == (None, 0)


def test_the_wilson_helper_lives_in_one_place():
    assert claims_report.wilson is intervals.wilson
    assert intervals.wilson(0, 0) == (0.0, 1.0)
    assert intervals.wilson(5, 10) == (0.2366, 0.7634)


def test_a_census_stratum_adds_no_variance_and_a_sampled_one_does():
    assert intervals.stratified([(10, 10, 3), (5, 5, 0)]) == (0.2, 0.2, 0.2)
    share, lo, hi = intervals.stratified([(10, 10, 3), (100, 10, 0)])
    assert share == round(3 / 110, 4) and lo == 0.0 and hi > share
    _, lo_fpc, hi_fpc = intervals.stratified([(12, 10, 5)])
    _, lo_big, hi_big = intervals.stratified([(10_000, 10, 5)])
    assert hi_fpc - lo_fpc < hi_big - lo_big


def _label_all(path, key, label_of):
    with path.open("w", encoding="utf-8") as f:
        f.write("verdict_id,label,evidence\n")
        for k in key:
            f.write(f"{k['verdict_id']},{label_of(k)},sql\n")


def test_the_report_gives_per_stratum_shares_recall_and_kappa(store, tmp_path):
    _retracted(store, 12)
    _lost(store, 6)
    got = ba.build(store, 918)
    ba.write(got, tmp_path)
    harness_strata = {"screen/runtime"}

    def first(k):
        if k["plant"]:
            return k["plant"]
        return ba.HARNESS if k["stratum"] in harness_strata else ba.MODEL
    _label_all(tmp_path / "labels.csv", got["key"], first)
    _label_all(tmp_path / "labels-second.csv", [k for k in got["key"] if k["role"] == "sample"][:10],
               lambda k: ba.HARNESS)
    out = ba.report(tmp_path / "key.csv", tmp_path / "labels.csv", tmp_path / "labels-second.csv", store)
    by = {r["stratum"]: r for r in out["strata"]}
    assert by["screen/runtime"]["share"] == 1.0 and by["screen/runtime"]["N"] == 7
    assert by["inspect/machine"]["share"] == 0.0
    assert out["population"][0] == round(7 / 112, 4)
    assert out["recall"][ba.HARNESS] == {"hit": 10, "n": 10, "missed": []}
    assert out["recall"][ba.MODEL]["hit"] == 5
    assert out["kappa"]["n"] == 10
    assert out["floor"]["retracted"] == 12 and out["unlabelled"] == []
    assert "plant recall harness (first labeller): 10/10" in ba.report_text(out)
    assert out["floor"]["changed"] == 12 and out["recall_second"][ba.HARNESS]["n"] == 0


def test_a_label_outside_the_codebook_is_refused(store, tmp_path):
    got = ba.build(store, 918)
    ba.write(got, tmp_path)
    _label_all(tmp_path / "labels.csv", got["key"], lambda k: "ours")
    with pytest.raises(ValueError, match="unknown label"):
        ba.report(tmp_path / "key.csv", tmp_path / "labels.csv")


def test_soh_blame_samples_the_store_read_only_and_reports(store, tmp_path, capsys):
    store.close()
    out = tmp_path / "blame"
    assert cli.main(["blame", "sample", "--seed", "918", "--dir", str(out), "--json"]) == 0
    sampled = json.loads(capsys.readouterr().out)
    assert len(sampled["queue"]) == 52
    header, key = ba.read_csv(out / "key.csv")
    _label_all(out / "labels.csv", key, lambda k: ba.MODEL)
    assert cli.main(["blame", "report", "--dir", str(out), "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["population"][0] == 0.0 and got["recall"][ba.HARNESS]["n"] == 0
    assert cli.main(["blame", "codebook"]) == 0
    assert "machine-correct" in capsys.readouterr().out


def _coherent(strata, prefix="org"):
    conn = _store(strata, prefix)
    try:
        return live_audit._terminal_reason_coherent(conn, pinned=frozenset())[0]
    finally:
        conn.close()


def test_a_broken_row_with_a_limit_reason_fails_the_audit_check():
    bad = _coherent([("screen", "broken", "limit", "limit:max_tokens>4000", 1)])
    assert len(bad) == 1 and "broken with reason limit" in bad[0]


def test_a_terminal_harness_reason_fails_and_a_conditional_reason_with_nothing_to_reopen_fails():
    bad = _coherent([("fetch", "declined", "harness", "", 1), ("inspect", "declined", "machine", "", 1)])
    assert len(bad) == 2
    assert "harness fault" in bad[0] and "no until and no retest" in bad[1]


def test_a_clean_population_passes_and_a_scheduled_retest_counts_as_a_way_back():
    assert _coherent(STRATA) == []
    assert _coherent([("screen", "declined", "runtime", "", 1)], prefix="retest") == []


def test_a_retraction_is_a_harness_plant_only_when_the_re_ask_answered_differently(store):
    _retracted(store, 3, then="broken", prefix="same")
    _retracted(store, 3, then="", prefix="pending")
    assert ba.plants(store, 918, []) == []
    _retracted(store, 2, prefix="changed")
    got = ba.plants(store, 918, [])
    assert len(got) == 2 and all(r["plant"] == ba.HARNESS for r in got)
    assert ba.retraction_outcomes(store) == {"reproduced": 3, "changed": 2, "pending": 3}


def test_a_loss_is_a_model_plant_only_on_a_run_that_could_have_shown_a_win(store):
    _lost(store, 2, run=_run(store, max_tokens=4000, path="r/short"), prefix="short")
    _lost(store, 2, run=_run(store, max_tokens=None, path="r/legacy"), prefix="legacy")
    _lost(store, 2, run=_run(store, cases=3, path="r/few"), prefix="few")
    assert ba.plants(store, 918, []) == []
    _lost(store, 2, prefix="fair")
    assert {r["name"] for r in ba.plants(store, 918, [])} == {"org/fair-0", "org/fair-1"}


def test_a_machine_refusal_reopened_for_a_bigger_machine_is_not_a_harness_plant(store):
    name = "org/too-big"
    _seed(store, name)
    ms.decide(store, name, "declined", tier="inspect", reason="machine", until="ceiling_gb:>80")
    ms.decide(store, name, "queued", tier="inspect", reopen=RETRACTION, reopen_why="bigger machine")
    ms.decide(store, name, "declined", tier="inspect", reason="machine", until="ceiling_gb:>81")
    assert ba.plants(store, 918, []) == []


def test_the_pinned_incoherent_rows_only_warn_and_a_fifth_fails():
    conn = _store([("screen", "broken", "limit", "limit:max_tokens>4000", 5)], prefix="pinned")
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT state_verdict_id FROM proposals WHERE name LIKE 'pinned/%' ORDER BY state_verdict_id")]
        bad, known = live_audit._terminal_reason_coherent(conn, pinned=frozenset(ids[:4]))
        assert len(known) == 4 and len(bad) == 1 and f"verdict {ids[4]} " in bad[0]
        bad, known = live_audit._terminal_reason_coherent(conn, pinned=frozenset(ids))
        assert bad == [] and len(known) == 5
    finally:
        conn.close()


def test_the_pin_is_exactly_the_four_rows_the_check_started_with():
    assert live_audit.PINNED_INCOHERENT == {686, 687, 9143, 11513}

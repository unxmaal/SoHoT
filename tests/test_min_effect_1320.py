"""The gate powers for the larger of a lane's rerun noise and adopt_min_effect. #1320."""
import json
import time

import pytest

from harness import adopt, cli, cuts, effects, knobs, power, reasons
from harness import memory_store as ms
from harness import paths

FAKE_MACHINE = {"fingerprint": "test/rig", "hw_model": "", "os": "", "arch": "",
                "memory_gb": 0.0, "accelerator": "", "runtimes": "", "ceiling_gb": 0.0}
REAL_CONNECT = ms.connect


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", FAKE_MACHINE)
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    c = ms.connect()
    yield c
    c.close()


def _plan(effect, mde, enough=True):
    return power.Plan(repeat=1, power=0.9, cells=200, cases=200, effect=effect, alpha=0.05, target=power.TARGET,
                      cap=power.CAP, capped=False, stochastic=False, observed=200, why="", mde=mde)


def _null_on(lane, mde):
    got = adopt.Verdict(lane, "inc", "ch", False, "better on the metric, but 3 lost against 5 gained is p=0.73")
    return adopt._null(lane, "inc", "ch", got, _plan(power.effect_for(lane), mde))


def test_a_lane_whose_noise_effect_is_0_05_is_powered_at_the_floor(monkeypatch):
    monkeypatch.setattr(power, "EFFECT", {"decide": 0.05})
    assert power.MIN_EFFECT == 0.1
    assert power.noise_for("decide") == 0.05
    assert power.effect_for("decide") == power.MIN_EFFECT
    monkeypatch.setattr(power, "MIN_EFFECT", 0.15)
    assert power.effect_for("decide") == 0.15


def test_a_lane_whose_noise_effect_is_above_the_floor_keeps_its_noise_effect(monkeypatch):
    monkeypatch.setattr(power, "EFFECT", {"repo": 0.16, "decide": 0.05})
    assert power.effect_for("repo") == 0.16 == power.noise_for(" Repo ")
    assert power.effect_for("image") == power.DEFAULT_EFFECT == power.noise_for("image")


def test_the_min_effect_knob_is_a_share_from_0_05_to_0_20_defaulting_to_0_10():
    k = knobs.KNOBS["adopt_min_effect"]
    assert k.sites == ("harness/power.py:MIN_EFFECT",)
    assert k.unit == "share"
    assert min(k.values) == 0.05 and max(k.values) == 0.2
    assert k.default() == 0.1 == power.MIN_EFFECT


def test_the_power_table_prints_the_noise_effect_and_the_effect_used(capsys, monkeypatch):
    monkeypatch.setattr(power, "EFFECT", {**power.EFFECT, "decide": 0.05, "repo": 0.16})
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    assert cli.main(["adopt", "--power", "--table", "--lane", "decide"]) == 0
    out = capsys.readouterr().out.splitlines()
    head = next(i for i, line in enumerate(out) if line.split()[:1] == ["lane"])
    cols = out[head].split()
    row = dict(zip(cols, out[head + 1].split()))
    assert (row["noise"], row["effect"], row["from"]) == ("0.05", "0.10", "floor")
    assert cli.main(["adopt", "--json", "--power", "--lane", "repo"]) == 0
    repo = json.loads(capsys.readouterr().out)["lanes"][0]
    assert (repo["noise_effect"], repo["effect"], repo["effect_from"]) == (0.16, 0.16, "measured")


def test_a_null_that_only_the_floor_makes_a_loss_records_a_cut(conn, monkeypatch):
    monkeypatch.setattr(power, "EFFECT", {"decide": 0.05})
    floor = _null_on("decide", 0.08)
    assert floor.failure_class == "", floor.why
    assert adopt.outcome_of(floor) == ("declined", reasons.CANDIDATE)
    assert floor.why.endswith("; reruns could see +0.05, but a gain under adopt_min_effect +0.10 is not worth a switch")
    assert floor.evidence == {"min_effect": {"noise": 0.05, "effect": 0.1, "seen": 0.08}}
    for mde in (0.04, 0.05):
        seen = _null_on("decide", mde)
        assert seen.failure_class == "" and "+0.10" not in seen.why and not seen.evidence
    assert _null_on("decide", 0.12).failure_class == reasons.UNDERPOWERED
    cuts.flush(conn)
    assert conn.execute("SELECT COUNT(*) FROM limit_cuts").fetchone()[0] == 0, "deciding alone records nothing"

    plain = adopt.Verdict("decide", "inc", "q3-8b", False, "no gain", evidence={"power": {"effect": 0.1}})
    adopt.record(conn, plain)
    adopt.record(conn, adopt.Verdict("decide", "inc", "q3-30b", False, floor.why, evidence=floor.evidence))
    cuts.flush(conn)
    rows = conn.execute("SELECT knob, value, what, kept, dropped FROM limit_cuts").fetchall()
    assert [(r["knob"], r["value"], r["kept"], r["dropped"]) for r in rows] == [("adopt_min_effect", 0.1, 0, 1)]
    assert rows[0]["what"] == "decide: q3-30b declined on a null that could see +0.08, above the lane's +0.05 noise"
    stored = conn.execute("SELECT power FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert json.loads(stored)["min_effect"] == {"noise": 0.05, "effect": 0.1, "seen": 0.08}


def test_the_floor_evidence_rounds_seen_to_four_places_and_a_seen_at_the_noise_tolerance_is_a_plain_null(monkeypatch):
    monkeypatch.setattr(power, "EFFECT", {"decide": 0.05})
    assert _null_on("decide", 0.0812345).evidence["min_effect"]["seen"] == 0.0812
    edge = _null_on("decide", power.noise_for("decide") + 1e-9)
    assert edge.failure_class == "" and not edge.evidence and "+0.10" not in edge.why


def test_a_floor_cut_lands_in_the_store_the_verdict_is_recorded_in(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(power, "EFFECT", {"decide": 0.05})
    floor = _null_on("decide", 0.08)
    other = REAL_CONNECT(tmp_path / "other.db")
    try:
        adopt.record(other, adopt.Verdict("decide", "inc", "q3-30b", False, floor.why, evidence=floor.evidence))
        assert other.execute("SELECT knob FROM limit_cuts").fetchall()[0]["knob"] == "adopt_min_effect"
    finally:
        other.close()
    cuts.flush(conn)
    assert conn.execute("SELECT COUNT(*) FROM limit_cuts").fetchone()[0] == 0


def test_decide_carries_the_floor_evidence_from_its_null(monkeypatch):
    monkeypatch.setattr(power, "EFFECT", {"decide": 0.05})
    floor = adopt.Verdict("decide", "inc", "ch", False, "floored", evidence={"min_effect": {"seen": 0.08}})
    monkeypatch.setattr(adopt, "_null", lambda *a, **k: floor)
    monkeypatch.setattr(adopt, "_lane_too_small", lambda *a, **k: None)
    monkeypatch.setattr(adopt, "_worse", lambda *a, **k: "")
    monkeypatch.setattr(adopt, "_gates", lambda lane, i, c, *a, **k: adopt.Verdict(lane, i, c, False, "null"))
    rows = [{"candidate": "inc", "case_id": "a", "passed": True}, {"candidate": "ch", "case_id": "a", "passed": True}]
    got = adopt.decide("decide", {"candidate": "inc"}, {"candidate": "ch"}, rows, plan=_plan(0.1, 0.08))
    assert got.evidence["min_effect"] == {"seen": 0.08}
    assert got.evidence["power"]["effect"] == 0.1


def _verdict(c, lane, outcome, detail, plan, name):
    ms.record(c, ms.Seen(name=name, source="test", lane=lane))
    vid = ms.decide(c, name, outcome, tier=ms.ADOPT, detail=detail, reason=reasons.CANDIDATE)
    c.execute("UPDATE verdicts SET power = ? WHERE id = ?", (json.dumps(plan), vid))
    c.commit()
    return vid


def test_the_effects_replay_shows_the_class_under_the_noise_and_under_the_used_effect(conn, tmp_path, capsys):
    null = _verdict(conn, "decide", "declined", "decide: better on the metric, but 3 lost against 5 gained is p=0.73",
                    {"effect": 0.2, "mde": 0.08, "enough": True, "target": 0.8}, "org/a")
    wide = _verdict(conn, "decide", "declined", "decide: better on the metric, but 1 lost against 2 gained is p=0.9",
                    {"effect": 0.2, "mde": 0.15, "enough": True, "target": 0.8}, "org/b")
    got = {r["id"]: r for r in effects.replay(conn, {"decide": 0.05})}
    assert (got[null]["noise"], got[null]["effect"]) == (0.05, power.MIN_EFFECT)
    assert (got[null]["under_noise"], got[null]["replayed"]) == (reasons.UNDERPOWERED, "candidate")
    assert got[wide]["under_noise"] == got[wide]["replayed"] == reasons.UNDERPOWERED

    for i in range(2):
        rid = conn.execute("INSERT INTO runs (path, lane, tier, receipt, recorded_at) VALUES (?,?,?,?,?)",
                           (f"r{i}{time.monotonic_ns()}", "decide", "measure", "{}", time.time())).lastrowid
        conn.executemany("INSERT INTO results (run_id, seq, candidate, case_id, repeat_index, passed) "
                         "VALUES (?,?,'m',?,1,1)", [(rid, k, f"c{k}") for k in range(40)])
    conn.commit()
    copy = tmp_path / "copy.db"
    conn.execute(f"VACUUM INTO '{copy}'")
    assert cli.main(["knobs", "effects", "--json", "--store", str(copy)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "decide" not in out["drift"]
    assert out["min_effect"] == power.MIN_EFFECT
    floored = [r["id"] for r in out["replay"] if r["under_noise"] != r["replayed"]]
    assert floored == [null]

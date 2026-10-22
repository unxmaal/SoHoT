"""#1100, #1111: a family that keeps losing in a lane ranks lower; a family unmeasured there gets a reserved measure slot."""
import pytest

from harness import family, rank
from harness import memory_store as ms

DAY = 86400.0
NOW = 2_000_000_000.0
GIB = 1024 ** 3
INC = {"code": "llamacpp:Ornith-1.5-35B-Q4_K_M"}


@pytest.fixture(autouse=True)
def runnable_here(monkeypatch):
    monkeypatch.setattr(rank, "unrunnable", lambda row, machine=None: "")


@pytest.fixture
def conn(tmp_path):
    c = ms.connect(tmp_path / "s.db")
    yield c
    c.close()


def seen(conn, name, lane="code", parents=()):
    ms.record(conn, ms.Seen(name=name, source="t", lane=lane))
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    for p in parents:
        conn.execute("INSERT OR IGNORE INTO lineage (proposal_id, parent, kind) VALUES (?, ?, 'finetune')", (pid, p))
    conn.commit()


def paired(conn, name, outcome, at, lane="code", parents=("Qwen/Qwen3.6-27B",)):
    seen(conn, name, lane, parents)
    ms.decide(conn, name, outcome, tier=ms.ADOPT, at=at, reason="candidate",
              detail=f"{lane}: {'beats' if outcome == 'measured' else 'does not beat'} the incumbent")


def row(name, *, times=1, parents=(), lane="code"):
    return {"name": name, "lane": lane, "times": times, "description": "", "size_bytes": int(15 * GIB),
            "first_seen": NOW - 5 * DAY, "last_seen": NOW - DAY,
            "parents": [(p, "finetune") for p in parents]}


def order(conn, rows):
    got = rank.rank(rows, serving=(), measured_lanes={"code"}, ceiling_gib=66.0, incumbents_by_lane=INC,
                    bases_by_lane={}, now=NOW, standing=family.standing(conn), conn=None)
    return [r["name"] for r in got], {r["name"]: r["value_why"] for r in got}


SIBLING = row("someone/Qwen3.6-27B-Tuned-GGUF", times=4, parents=("Qwen/Qwen3.6-27B",))
OTHER = row("other/Gemma-4-27B-GGUF", times=2)


def test_after_n_losses_a_sibling_ranks_below_an_unrelated_candidate_it_used_to_outrank(conn):
    assert order(conn, [OTHER, SIBLING])[0] == [SIBLING["name"], OTHER["name"]]
    for i in range(family.LOSSES_TO_DEMOTE - 1):
        paired(conn, f"a{i}/Qwen3.6-27B-ft{i}", "declined", NOW - (10 - i) * DAY)
    assert order(conn, [OTHER, SIBLING])[0][0] == SIBLING["name"], "one loss short is no demotion"
    paired(conn, "last/Qwen3.6-27B-ft", "declined", NOW - DAY)
    names, why = order(conn, [OTHER, SIBLING])
    assert names == [OTHER["name"], SIBLING["name"]]
    assert f"{family.LOSSES_TO_DEMOTE} of the qwen3.6-27b family lost at the paired gate in code" in why[SIBLING["name"]]


def test_repeated_losses_by_one_member_count_once(conn):
    paired(conn, "a/Qwen3.6-27B-ft", "declined", NOW - 10 * DAY)
    pid = conn.execute("SELECT id FROM proposals WHERE name = 'a/Qwen3.6-27B-ft'").fetchone()[0]
    for i in range(family.LOSSES_TO_DEMOTE + 2):
        conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at, reason) "
                     "VALUES (?, 'declined', 'adopt', 'code: lost', ?, 'candidate')", (pid, NOW - (9 - i) * DAY))
    conn.commit()
    assert family.standing(conn).families[("code", "qwen3.6-27b")].verdicts == family.LOSSES_TO_DEMOTE + 3
    assert order(conn, [OTHER, SIBLING])[0][0] == SIBLING["name"]


def test_a_win_by_any_member_clears_the_demotion(conn):
    for i in range(family.LOSSES_TO_DEMOTE):
        paired(conn, f"a{i}/Qwen3.6-27B-ft{i}", "declined", NOW - (10 - i) * DAY)
    assert order(conn, [OTHER, SIBLING])[0][0] == OTHER["name"]
    paired(conn, "winner/Qwen3.6-27B-Best", "measured", NOW - DAY)
    assert order(conn, [OTHER, SIBLING])[0][0] == SIBLING["name"]
    paired(conn, "later/Qwen3.6-27B-ft", "declined", NOW)
    assert order(conn, [OTHER, SIBLING])[0][0] == SIBLING["name"], "losses before the win no longer count"


def test_a_lane_specific_card_is_exempt_and_the_exemption_is_recorded(conn):
    for i in range(family.LOSSES_TO_DEMOTE):
        paired(conn, f"a{i}/Qwen3.6-27B-ft{i}", "declined", NOW - (10 - i) * DAY)
    coder = row("someone/Qwen3.6-27B-Coder-GGUF", times=4, parents=("Qwen/Qwen3.6-27B",))
    names, why = order(conn, [OTHER, coder])
    assert names[0] == coder["name"]
    assert "exempt from the qwen3.6-27b family demotion in code" in why[coder["name"]]
    assert "(coder)" in why[coder["name"]]


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/family.py:LANE_TRAINING")
@pytest.mark.parametrize("name,lane", [("x/Qwen3.6-27B-Image-Tuned", "image"), ("x/Qwen3.6-27B-Coding-Tuned", "code"),
                                       ("x/Qwen3.6-27B-Coder", "web")])
def test_a_name_or_lane_the_training_table_does_not_list_is_not_exempt(name, lane):
    assert family.exempt(name, lane) == ""


def test_losses_in_another_lane_do_not_demote_here(conn):
    for i in range(family.LOSSES_TO_DEMOTE):
        paired(conn, f"a{i}/Qwen3.6-27B-ft{i}", "declined", NOW - (10 - i) * DAY, lane="web")
    assert order(conn, [OTHER, SIBLING])[0][0] == SIBLING["name"]


def test_a_method_crossing_is_not_a_family_member(conn):
    seen(conn, "Qwen/Qwen3.6-27B")
    for i in range(family.LOSSES_TO_DEMOTE):
        name = f"plan:Qwen/Qwen3.6-27B-v{i}"
        ms.record(conn, ms.Seen(name=name, source="t", lane="code"))
        ms.decide(conn, name, "declined", tier=ms.ADOPT, at=NOW - i, reason="candidate", detail="code: lost")
    assert not family.standing(conn).families


def test_the_root_is_the_end_of_the_lineage_chain_and_a_cross_size_parent_ends_it(conn):
    seen(conn, "Qwen/Qwen3.6-27B", parents=("Qwen/Qwen3.6-27B-Base",))
    seen(conn, "mid/Qwen3.6-27B-Instruct-ft", parents=("Qwen/Qwen3.6-27B",))
    seen(conn, "Hcompany/Holo-3.1-35B-A3B", parents=("Qwen/Qwen3.5-0.8B",))
    st = family.standing(conn)
    assert st.key_of({"name": "q/Qwen3.6-27B-Q4_K_M-GGUF", "parents": [("mid/Qwen3.6-27B-Instruct-ft", "")]}) \
        == "qwen3.6-27b"
    assert st.key_of({"name": "Hcompany/Holo-3.1-35B-A3B"}) == "holo-3.1-35b-a3b"
    assert family.root("a", {"a": ["b"], "b": ["a"]}) == "b", "a cycle stops"


def test_the_family_knobs_are_registered_with_ranges():
    from harness import knobs
    for name, attr in (("family_losses_to_demote", "LOSSES_TO_DEMOTE"), ("family_demotion", "DEMOTION"),
                       ("diversity_family_window_days", "WINDOW_DAYS"), ("diversity_slots", "SLOTS"),
                       ("family_size_ratio", "SIZE_RATIO")):
        k = knobs.KNOBS[name]
        assert k.default() == getattr(family, attr)
        assert len(k.values) >= 3 and getattr(family, attr) in k.values
    assert knobs.KNOBS["diversity_slots"].values == (0, 1, 2)


# --- #1111: the diversity slot -----------------------------------------------------------------------

def measured_queue(conn):
    for i in range(10):
        seen(conn, f"q{i}/Qwen3.6-27B-ft{i}", parents=("Qwen/Qwen3.6-27B",))
    paired(conn, "old/Qwen3.6-27B-ft", "declined", NOW - 2 * DAY)
    seen(conn, "new/Mistral-Small-24B", parents=("mistralai/Mistral-Small-24B-Base",))
    return [{"name": f"q{i}/Qwen3.6-27B-ft{i}", "lane": "code"} for i in range(10)] + \
        [{"name": "new/Mistral-Small-24B", "lane": "code"}]


def test_ten_same_family_rows_and_an_unmeasured_family_last_the_plan_includes_it(conn):
    rows = measured_queue(conn)
    st = family.standing(conn, losses_to_demote=99)
    got = [r["name"] for r in family.plan(rows, st, 3, now=NOW, slots=1)]
    assert got[0] == "new/Mistral-Small-24B"
    assert got[1:] == ["q0/Qwen3.6-27B-ft0", "q1/Qwen3.6-27B-ft1"]


def test_with_no_diversity_slots_the_plan_does_not_include_it(conn):
    rows = measured_queue(conn)
    st = family.standing(conn, losses_to_demote=99)
    got = [r["name"] for r in family.plan(rows, st, 3, now=NOW, slots=0)]
    assert "new/Mistral-Small-24B" not in got
    assert family.reserve(rows, st, now=NOW, slots=0)[2] == ["diversity: 0 slot(s) reserved, so none is held"]


def test_a_family_compared_before_the_window_qualifies_again(conn):
    rows = measured_queue(conn)
    st = family.standing(conn, losses_to_demote=99)
    _, picks, _ = family.reserve(rows, st, now=NOW + 60 * DAY, slots=1, window_days=30)
    assert picks[0]["name"] == "q0/Qwen3.6-27B-ft0"


def test_a_pick_that_does_not_fit_gives_its_slot_back_and_says_so(conn):
    rows = measured_queue(conn)
    st = family.standing(conn, losses_to_demote=99)
    queue, picks, lines = family.reserve(rows, st, now=NOW, slots=1,
                                         fits=lambda r: (False, "needs 80 GB, 40 free"))
    assert picks == [] and queue == rows
    assert any("new/Mistral-Small-24B (mistral-small-24b) does not fit: needs 80 GB, 40 free" in ln for ln in lines)
    assert any("1 reserved slot(s) return to the normal queue" in ln for ln in lines)


def test_a_demoted_family_never_takes_a_diversity_slot(conn):
    for i in range(family.LOSSES_TO_DEMOTE):
        paired(conn, f"a{i}/Qwen3.6-27B-ft{i}", "declined", NOW - 100 * DAY)
    st = family.standing(conn)
    rows = [{"name": "z/Qwen3.6-27B-ft", "lane": "code", "parents": [("Qwen/Qwen3.6-27B", "finetune")]}]
    assert family.reserve(rows, st, now=NOW - 99 * DAY, slots=1, window_days=30)[1] == [], "compared recently"
    _, picks, _ = family.reserve(rows, st, now=NOW, slots=1, window_days=30)
    assert picks == []


def test_the_measure_step_puts_a_demoted_family_last_and_the_pick_first(conn, monkeypatch):
    from harness import heartbeat
    from harness.commands import loop
    from harness.commands import measure as measure_cmd
    for i in range(family.LOSSES_TO_DEMOTE):
        paired(conn, f"a{i}/Gemma-4-27B-ft{i}", "declined", NOW - DAY, parents=("google/gemma-4-27b",))
    seen(conn, "b/Gemma-4-27B-ft", parents=("google/gemma-4-27b",))
    rows = measured_queue(conn)
    rows.insert(0, {"name": "b/Gemma-4-27B-ft", "lane": "code"})
    monkeypatch.setattr(measure_cmd, "measurable", lambda store, top, want="": list(rows))
    monkeypatch.setattr(family.time, "time", lambda: NOW)
    noted, said = {}, []
    monkeypatch.setattr(heartbeat, "note", lambda k, v: noted.__setitem__(k, v))
    got = loop.measure_queue(conn, "", 0, room=lambda r: (True, None, ""), say=said.append)
    names = [r["name"] for r in got]
    assert names[0] == "new/Mistral-Small-24B"
    assert names[-1] == "b/Gemma-4-27B-ft"
    assert noted[heartbeat.DIVERSITY]["picks"][0]["family"] == "mistral-small-24b"
    assert any("b/Gemma-4-27B-ft waits behind the rest" in s for s in said)


def test_morning_names_the_demotion_its_count_and_the_diversity_pick(conn):
    from harness import morning
    from harness.commands import morning as morning_cmd
    for i in range(family.LOSSES_TO_DEMOTE):
        paired(conn, f"a{i}/Qwen3.6-27B-ft{i}", "declined", NOW - DAY)
    fams = morning.families(conn)
    assert fams == [{"lane": "code", "family": "qwen3.6-27b", "losses": family.LOSSES_TO_DEMOTE,
                     "lost": [f"a{i}/Qwen3.6-27B-ft{i}" for i in range(family.LOSSES_TO_DEMOTE)]}]
    lines = morning_cmd.diversity_lines({"picks": [{"name": "new/Mistral-Small-24B", "lane": "code",
                                                    "family": "mistral-small-24b",
                                                    "why": "mistral-small-24b in code: never compared"}]})
    assert lines == ["diversity new/Mistral-Small-24B took a reserved slot: family mistral-small-24b in code: "
                     "never compared"]
    assert morning_cmd.diversity_lines({"picks": [], "lines": ["diversity: 1 reserved slot(s) return to the "
                                                               "normal queue: none fits"]}) \
        == ["diversity 1 reserved slot(s) return to the normal queue: none fits"]


def test_the_funnel_counts_a_demoted_familys_queued_members(conn):
    from harness import funnel
    for i in range(family.LOSSES_TO_DEMOTE):
        paired(conn, f"a{i}/Qwen3.6-27B-ft{i}", "declined", NOW - DAY)
    rows = [{"name": "z/Qwen3.6-27B-ft", "lane": "code", "state": "queued"},
            {"name": "z/Qwen3.6-27B-Coder", "lane": "code", "state": "queued"}]
    seen(conn, "z/Qwen3.6-27B-ft", parents=("Qwen/Qwen3.6-27B",))
    got = funnel.families(conn, rows)
    assert got[0]["family"] == "qwen3.6-27b" and got[0]["losses"] == family.LOSSES_TO_DEMOTE
    assert got[0]["demoted"] == ["z/Qwen3.6-27B-ft"]

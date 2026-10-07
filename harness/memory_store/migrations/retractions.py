"""Migration helpers that retract, requeue and relane verdicts an older schema got wrong."""
from __future__ import annotations

import re

from harness import store
from harness.memory_store.schema import MEASURE, SCREEN, TERMINAL, _DDL, _columns
from harness.memory_store.transitions import _migration_retraction


def _retract_screens_with_no_evidence(conn) -> None:
    """Reopen screen verdicts that are terminal on no evidence. #281."""
    # Only where it is still the state.
    for r in _stated(
            conn, "p.state = 'broken' AND v.run_path = '' "
            "AND v.detail LIKE 'it ran and passed nothing%' AND EXISTS "
            "(SELECT 1 FROM verdicts w WHERE w.proposal_id = p.id "
            " AND w.tier = ? AND w.outcome = 'broken' AND w.run_path = '' "
            " AND w.detail LIKE 'it ran and passed nothing%')", (SCREEN,)):
        _migration_retraction(conn, r["id"], r["name"], "queued", SCREEN,
                     "retracted: the screen stored no run_path, so the reason "
                     "it passed nothing is unrecoverable and the verdict "
                     "cannot be re-judged. Issue #281.")


def _stated(conn, where: str = "", args=()) -> list:
    """Each proposal beside the verdict holding its state. #409."""
    return conn.execute(
        "SELECT p.id, p.name, p.state AS outcome, v.tier, v.detail, v.run_path "
        "FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id"
        + (f" WHERE {where}" if where else ""), args).fetchall()


def _reopen_architecture_gaps(conn) -> None:
    """A runtime that could not build the architecture is not a verdict on the
    candidate: declined until a newer one is installed. #293."""
    from harness import reasons, screen
    until = screen.load_until()
    for r in _stated(conn, "p.state = 'broken' AND v.tier = ?", (SCREEN,)):
        if reasons.legacy_architecture_gap(r["detail"]):
            _migration_retraction(conn, r["id"], r["name"], "declined", SCREEN,
                         "the installed runtime could not load it: "
                         + str(r["detail"])[:500], until=until)


def _canonical_lanes(conn) -> None:
    """One name per lane. `text` IS `code`, and `all` was never a lane.

    discover.py wrote `text` and inspect.PIPELINE_LANES wrote `code` for the
    same models; rank.lane_of then discarded `text` as laneless, so half the
    lane never reached the queue. `all` is a SOURCE's coverage claim. #207.
    """
    from harness import lanes
    for old, new in lanes.ALIASES.items():
        conn.execute("UPDATE proposals SET lane=? WHERE lower(lane)=?",
                     (new, old))


def _backfill_lanes(conn) -> None:
    """Route rows the registry never classified, using their own prose.

    A proposal arrives with a one-line description of what it does and the
    lane was only ever read from a HuggingFace `pipeline_tag`, so a GitHub
    repo could never have one and 287 of 381 rows sat laneless while carrying
    the answer. Only rows with NO lane are touched: the registry's own label
    is the publisher's answer and outranks a guess at it. #207.
    """
    from harness import lanes
    rows = conn.execute(
        "SELECT p.id, p.name, s.why FROM proposals p "
        "JOIN sightings s ON s.proposal_id = p.id WHERE p.lane = ''"
    ).fetchall()
    # A proposal seen twice gets both descriptions, and they can disagree.
    # Disagreement is exactly the case from_prose refuses to break, so it is
    # fed all of them at once and falls silent rather than picking one.
    prose: dict = {}
    for row in rows:
        pid, name = row[0], row[1]
        prose.setdefault(pid, [name]).append(row[2] or "")
    for pid, parts in prose.items():
        lane = lanes.from_prose(" ".join(parts))
        if lane:
            conn.execute("UPDATE proposals SET lane=? WHERE id=?", (lane, pid))


#: "the screen exited 1" and nothing else: a refusal that discarded the
#: stderr saying whose fault it was.
_BARE_EXIT = re.compile(r"the screen exited \d+")


def _retract_harness_refusals(conn) -> None:
    """Re-queue anything settled for a reason that was about US, not about it.

    Every tier, not only the fetch: the screen recorded "no cases of a modality
    it can run" as `broken` for a candidate whose weights were on disk and
    whose lane has three cases.

    The fetch tier recorded "no measured size; inspect it first" as `declined`,
    which is TERMINAL, so 16 real candidates were suppressed from re-proposal
    forever because a size sat in a verdict row the reader did not look at.
    Among them was the only upgrade candidate the image lane had.

    A verdict is not deleted -- it is a record of what happened, and losing it
    would lose the evidence that this went wrong. A fresh `queued` row is
    appended saying why, and it moves the proposal's state. Issues #211, #206.
    """
    from harness import reasons
    for row in _stated(conn, "p.state IN ('declined', 'broken')"):
        pid, name = row["id"], row["name"]
        detail, tier = row["detail"] or "", row["tier"] or ""
        phrase = reasons.legacy_refused(detail)
        # A TERMINAL VERDICT WITH NO EVIDENCE CANNOT BE RE-JUDGED. The screen
        # stored only its own prose, so rows reading exactly "the screen
        # exited N" discarded the stderr that says whose fault the exit was.
        # Those are retracted too: an unjudgeable terminal verdict is settled
        # on nothing, and this project has settled sixteen real candidates
        # that way before. The screen now stores the evidence alongside.
        if not phrase and _BARE_EXIT.fullmatch((detail or "").strip()):
            phrase = "an exit code with no evidence recorded"
        if not phrase:
            continue
        _migration_retraction(conn, pid, name, "queued", tier,
                     f"retracted: {phrase!r} was a fact about this "
                     f"harness, not a verdict on {name}")


def _requeue_disk_floor_declines(conn) -> None:
    """A fetch that refused for a full disk settled the candidate; reopen each one. #528."""
    for row in conn.execute(
            "SELECT p.id, p.name FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
            "WHERE p.state = 'declined' AND v.tier = 'fetch' AND v.reason = 'machine' "
            "AND COALESCE(v.until, '') = '' AND v.detail LIKE '%floor%'").fetchall():
        _migration_retraction(conn, row["id"], row["name"], "queued", "fetch",
                              f"retracted: a disk below the floor was a fact about this machine, "
                              f"not a verdict on {row['name']}")


def _retract_verdicts_with_no_control(conn) -> None:
    """Undo an adoption verdict drawn from a run where the CONTROL scored zero.

    A doubled `/v1` in the gateway argument produced HTTP 404 for every
    request, so both the incumbent and the challenger passed 0 of 27, and the
    loop recorded `declined: does not beat the incumbent on the lane's metric`
    -- a statement about quality, from a run in which nothing ran.

    The receipts are on disk and say so, but re-deriving which runs were
    affected from them is guesswork after the fact. The one row this produced
    is named, because naming it is honest and a pattern match would catch
    legitimate declines too. Issue #223.
    """
    for row in _stated(
            conn, "v.tier = 'adopt' AND p.state = 'declined' "
            "AND v.detail LIKE '%does not beat the incumbent%' "
            "AND p.name = 'LiquidAI/LFM2.5-350M'"):
        _migration_retraction(conn, row["id"], row["name"], "queued", SCREEN,
                     "retracted: measured against a control that passed 0 of "
                     "27, so the verdict described a run in which nothing ran")


def _relane_from_the_card(conn) -> None:
    """Correct a lane the SOURCE supplied, using the candidate's own card.

    A feed declares the subject area it covers; that was recorded as every
    candidate's lane and never overwritten, so four video models sat in the
    image lane and a TTS model in the code lane. Each was screened against
    cases it could not pass and recorded `broken` -- terminal -- for a
    mismatch this harness created.

    Only rows whose card CONTRADICTS the recorded lane are touched. A lane
    with no card to check stays put: it may be right, and guessing again
    would be no better than the guess already there. #227.
    """
    from harness import inspect as ins
    from harness import lanes

    # The stored task column, which the schema 32 backfill fills first. #414.
    rows = conn.execute(
        "SELECT id, name, lane, hf_task FROM proposals "
        "WHERE hf_task <> ''").fetchall()
    moved = []
    for row in rows:
        card = ins.card_lane(row["hf_task"].lower())
        was = lanes.canonical(row["lane"])
        # A text task cannot say WHICH text lane: OmniSVG is image-text-to-text.
        if not card or was == card or (card == "code" and was in lanes.TEXT_SERVED):
            continue
        conn.execute("UPDATE proposals SET lane = ? WHERE id = ?",
                     (card, row["id"]))
        moved.append((row["id"], row["name"], row["lane"], card))
    _wrong_lane_requeues(conn, moved)


def _wrong_lane_requeues(conn, moved) -> None:
    """Re-queue a lane-tier terminal verdict on each (id, name, was, now) moved.

    A terminal verdict reached in the WRONG LANE says nothing about the
    candidate: the screen built its spec from the lane and handed it cases
    from a modality it does not serve. Re-queued, not deleted.
    """
    for pid, name, was, card in moved:
        last = _stated(conn, "p.id = ?", (pid,))
        # Only a tier that ran lane cases depends on the lane: "too big" and
        # "a LoRA" are true in any lane. #379.
        if not last or last[0]["outcome"] not in TERMINAL \
                or last[0]["tier"] not in (SCREEN, MEASURE):
            continue
        _migration_retraction(conn, pid, name, "queued", SCREEN,
                     f"retracted: settled in the {was or 'unknown'} lane, which "
                     f"came from the source rather than from {name}'s own card "
                     f"({card or 'no lane'})")


def _relane_the_settled_tasks(conn) -> None:
    """Move a row whose stored task #387 settled to the lane its card facts
    now name: a text-only lane cannot feed an input image, table or video,
    text-to-audio follows its tags, and an OCR card leaves code."""
    import json

    from harness import inspect as ins
    from harness import lanes
    marks = ",".join("?" * len(ins.SETTLED_TASKS))
    rows = conn.execute(
        "SELECT id, name, lane, hf_task, card_tags FROM proposals "
        f"WHERE lower(hf_task) IN ({marks}) "
        "OR (lower(hf_task) = 'image-text-to-text' AND card_tags LIKE '%ocr%')",
        ins.SETTLED_TASKS).fetchall()
    moved = []
    for row in rows:
        try:
            tags = json.loads(row["card_tags"] or "[]")
        except ValueError:
            tags = []
        lane, source = ins.lane_and_source(
            {"pipeline_tag": row["hf_task"], "tags": tags, "id": row["name"]})
        was = lanes.canonical(row["lane"])
        if lane == was or (lane == "code" and was in lanes.TEXT_SERVED):
            continue
        conn.execute("UPDATE proposals SET lane = ?, lane_source = ? "
                     "WHERE id = ?", (lane, source, row["id"]))
        moved.append((row["id"], row["name"], row["lane"], lane))
    _wrong_lane_requeues(conn, moved)


def _relane_the_laneless_from_the_card(conn) -> None:
    """Give a laneless row the lane its stored card now names. #423.

    text-classification and structured-prediction file under decide, so the
    Bespoke-Nimble adapters queued with no lane get one without a re-inspect.
    Only empty lanes are filled; a lane already there is _relane_from_the_card's.
    """
    import json

    from harness import inspect as ins
    rows = conn.execute(
        "SELECT id, hf_task, card_tags FROM proposals WHERE lane = '' "
        "AND (hf_task <> '' OR card_tags NOT IN ('', '[]'))").fetchall()
    for row in rows:
        try:
            tags = json.loads(row["card_tags"] or "[]")
        except ValueError:
            tags = []
        lane, source = ins.lane_and_source({"pipeline_tag": row["hf_task"],
                                            "tags": tags})
        if lane:
            conn.execute("UPDATE proposals SET lane = ?, lane_source = ? "
                         "WHERE id = ?", (lane, source, row["id"]))


def _requeue_broken_matching(conn, phrases: tuple = ("guidance_scale has to be",)) -> None:
    for r in _stated(conn, "p.state = 'broken'"):
        hit = next((p for p in phrases if p in (r["detail"] or "").lower()), "")
        if hit:
            _migration_retraction(conn, r["id"], r["name"], "queued", SCREEN,
                         f"retracted: {hit!r} was a setting this harness "
                         f"chose, not a verdict on {r['name']}")


def _requeue_screens_of_missing_weights(conn) -> None:
    """A screen that found no file in a snapshot holding no weights screened
    our missing download, not the candidate. #399."""
    from harness import fetching
    for r in _stated(conn, "p.state = 'broken'"):
        if "no such file or directory" in (r["detail"] or "").lower() \
                and not fetching.have(r["name"], conn):
            _migration_retraction(conn, r["id"], r["name"], "queued", SCREEN,
                         f"retracted: {r['name']}'s weights were never "
                         f"downloaded, so the screen ran on nothing")


def _requeue_diffusers_layout_gaps(conn) -> None:
    from harness import reasons
    for r in _stated(conn, "p.state = 'broken'"):
        if reasons.legacy_layout_gap(r["detail"]):
            _migration_retraction(conn, r["id"], r["name"], "queued", SCREEN,
                         f"retracted: the diffusers loader, not {r['name']}, "
                         f"failed to assemble the pipeline")


def _retract_verdicts_from_runs_that_never_ran(conn) -> None:
    """Undo a verdict whose challenger never reached a model.

    DERIVED FROM THE RECEIPTS, not from a list of names. The schema 8
    retraction named one row because I had verified it by hand, and missed the
    second member of the same class: mlx-community/Qwen3-8B-4bit sat
    `declined` from two runs that were pure HTTP 400 routing failures, 0 of 27
    at 11ms a case. Naming rows does not scale past the ones you happened to
    look at. #230.

    A receipt is only evidence against a verdict when EVERY row for that
    candidate is a refusal this harness produced. One row that reached a model
    means the candidate really was measured and its score is its own.
    """
    from harness import runs
    from harness.commands import measure as measure_cmd

    never_ran = set()
    for _, summary, rows in runs.summaries(conn, tier=""):
        for key, got in summary.items():
            if got.get("passed") or not got.get("total"):
                continue
            why = measure_cmd._all_refused(rows, key)
            if why and why != measure_cmd.NO_ROWS_FOR_CANDIDATE:
                never_ran.add((key, why))

    for key, why in sorted(never_ran):
        # The key's proposal comes from the candidates table, not the string. #407.
        for row in _stated(
                conn, "v.tier = 'adopt' AND p.state IN ('declined', 'broken') "
                "AND (p.name = ? OR p.id IN (SELECT proposal_id FROM candidates "
                "WHERE receipt_key = ?))", (key, key)):
            _migration_retraction(conn, row["id"], row["name"], "queued", SCREEN,
                         f"retracted: every case was refused before it reached "
                         f"a model ({why}), so the verdict described a run in "
                         f"which nothing ran")


def _verdicts_name_a_candidate(conn) -> None:
    """proposal_id becomes nullable and verdicts gain candidate_id. #407."""
    if store.backend() == store.POSTGRES:
        conn.execute("ALTER TABLE verdicts ALTER COLUMN proposal_id "
                     "DROP NOT NULL")
        if "candidate_id" not in _columns(conn, "verdicts"):
            conn.execute("ALTER TABLE verdicts ADD COLUMN candidate_id "
                         "INTEGER REFERENCES candidates(id)")
        return
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS verdicts \(.*?\n\);",
                    _DDL, re.S).group(0)
    have = [r["name"] for r in conn.execute("PRAGMA table_info(verdicts)")]
    conn.commit()
    # A rebuild drops the table `reopens` points at. #409.
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(ddl.replace("IF NOT EXISTS verdicts (", "verdicts_new ("))
    # Columns since retired ride along until drop_dead_columns keeps their data. #419.
    for r in conn.execute("PRAGMA table_info(verdicts)").fetchall():
        if r["name"] not in _columns(conn, "verdicts_new"):
            conn.execute(f"ALTER TABLE verdicts_new ADD COLUMN {r['name']} {r['type']}")
    cols = ", ".join(c for c in have)
    conn.execute(f"INSERT INTO verdicts_new ({cols}) SELECT {cols} FROM verdicts")
    conn.execute("DROP TABLE verdicts")
    conn.execute("ALTER TABLE verdicts_new RENAME TO verdicts")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_verdict_prop "
                 "ON verdicts(proposal_id)")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")

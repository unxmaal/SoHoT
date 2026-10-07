"""Migration helpers that lift facts out of prose into columns."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
import re

from harness.memory_store.cards import set_card
from harness.memory_store.machines import remember_machine
from harness.memory_store.revisit import _UNTIL_FROM_DETAIL, until_for
from harness.memory_store.schema import GIB, HUGGINGFACE, INSPECT, SCREEN, TERMINAL
from harness.memory_store.transitions import _migration_retraction


def _backfill_until(conn: sqlite3.Connection) -> None:
    for vid, detail in conn.execute(
            "SELECT id, detail FROM verdicts WHERE until = '' "
            "AND outcome IN ('declined', 'broken')").fetchall():
        until = until_for(detail)
        if until:
            conn.execute("UPDATE verdicts SET until = ? WHERE id = ?",
                         (until, vid))


#: `last commit 2.9 years ago`, the only spelling the tier has ever used.
_YEARS = re.compile(r"last commit ([\d.]+) years? ago")


#: The two sentences a tier writes when it refuses an attachment, and nothing
#: else. fetching says `lora in its own card: this attaches to...`; screen.plan
#: says `a lora: it attaches to...`. Anchored on the shared clause so a judge
#: merely USING the word "workflow" is not mistaken for a verdict about one.
_ATTACHES = re.compile(
    r"(?:^a (\w[\w-]*): it|^(\w[\w-]*) in its own card: this) "
    r"attaches to a model rather than being one", re.I | re.M)


def _let_a_revived_upstream_be_reconsidered(conn: sqlite3.Connection) -> None:
    """Give every `dead` verdict the commit that would reopen it.

    A repo idle for two years is refused, and that verdict is recorded
    `declined`, which is TERMINAL. So a candidate stays refused even if its
    upstream ships tomorrow -- and `mlx-community/Mistral-7B-Instruct-v0.3-4bit`
    is on that list, where a requantisation repo has no reason to receive
    commits at all.

    Every other machine-limited refusal got a condition in #266. This one was
    missed because its limit is not the machine: it waits on somebody else's
    repository, which is why until_met takes a plain dict of facts.

    The commit date is recovered from the age the tier recorded, so the
    condition inherits that approximation -- one decimal place of years, a
    36-day band. It is a floor on "newer than what we saw", and being
    conservative here re-asks slightly too early rather than never.
    """
    rows = conn.execute(
        "SELECT id, upstream_idle_days, decided_at FROM verdicts "
        "WHERE until = '' AND upstream_idle_days > 0").fetchall()
    for vid, idle, decided in rows:
        when = float(decided or 0) - float(idle) * 86400.0
        if when <= 0:
            continue
        iso = datetime.fromtimestamp(when, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        conn.execute("UPDATE verdicts SET until = ? WHERE id = ?",
                     (f"commit_after:{iso}", vid))


def _lift_kind_and_age_out_of_prose(conn: sqlite3.Connection) -> None:
    """Move the attachment kind and the source's staleness into columns.

    THE KIND IS RECOVERED FROM THE SENTENCE THE TIER WROTE, not recomputed.
    My first cut ran screen.is_attachment over the verdict's DETAIL, and the
    live code runs it over the candidate's DESCRIPTION -- so 78 judge verdicts
    whose prose happens to contain "workflow", "gui" or "embedding" were
    labelled attachments. They are not: "This is a composition of existing
    tools" is a judge explaining a score.

    A migration recovers what was DECIDED. Re-deciding invents verdicts that
    were never made, and here it would have taught the fetch tier to refuse
    57 real candidates as adapters.

    Both tiers that record one say `attaches to a model rather than being
    one`, with the kind as the first word, so that phrase is the marker.

    THE AGE IS RECOVERED APPROXIMATELY AND THAT IS RECORDED. The tier wrote
    one decimal place of YEARS, so `2.9 years ago` recovers 1058.5 days and
    the true value was somewhere in a 36-day band. Precision the prose threw
    away cannot be migrated back; what matters is that the column is now
    queryable and every row written from here is exact.
    """
    rows = conn.execute(
        "SELECT id, detail FROM verdicts "
        "WHERE attaches_to = '' AND upstream_idle_days = 0").fetchall()
    for vid, detail in rows:
        text = detail or ""
        kind = ""
        m = _ATTACHES.search(text)
        if m:
            kind = (m.group(1) or m.group(2) or "").strip()
        m = _YEARS.search(text)
        days = float(m.group(1)) * 365.0 if m else 0.0
        if kind or days:
            conn.execute(
                "UPDATE verdicts SET attaches_to = ?, "
                "upstream_idle_days = ? "
                "WHERE id = ?", (kind, days, vid))


def _lift_sizes_out_of_prose(conn: sqlite3.Connection) -> None:
    """Move measured sizes from `detail` into verdicts.size_bytes. Schema 13."""
    for vid, detail in conn.execute(
            "SELECT id, detail FROM verdicts WHERE size_bytes = 0 "
            "AND (detail LIKE '%bytes=%' OR detail LIKE '%GiB%')").fetchall():
        size = size_from_prose(detail)
        if size > 0:
            conn.execute("UPDATE verdicts SET size_bytes = ? WHERE id = ?",
                         (size, vid))


#: The two spellings inspect used for a size before it was a column. Backfill only. #211.
_PROSE_BYTES = re.compile(r"bytes=(\d+)")


_PROSE_GIB = re.compile(r"([\d.]+)\s*GiB")


#: The card total card_description() composes. Backfill only. #413.
_CARD_GIB = re.compile(r"([\d.]+) GiB of weights")


def size_from_prose(detail: str) -> int:
    """A size an old verdict wrote as a sentence: `bytes=N`, else the largest GiB figure."""
    detail = detail or ""
    m = _PROSE_BYTES.search(detail)
    if m:
        return int(m.group(1))
    found = [float(g) for g in _PROSE_GIB.findall(detail)]
    return int(max(found) * GIB) if found else 0


def size_from_card(description: str) -> int:
    """The `N GiB of weights` an old card description carries. Backfill only."""
    m = _CARD_GIB.search(description or "")
    return int(float(m.group(1)) * GIB) if m else 0


def size_sources(conn) -> dict[int, dict]:
    """Each proposal's size by source: inspect's column, inspect's prose, the card. #413."""
    out: dict[int, dict] = {}
    for r in conn.execute(
            "SELECT p.id, p.description, "
            "(SELECT v.size_bytes FROM verdicts v WHERE v.proposal_id = p.id "
            "  AND v.tier = ? AND v.size_bytes > 0 "
            "  ORDER BY v.id DESC LIMIT 1) AS col "
            "FROM proposals p", (INSPECT,)).fetchall():
        out[r["id"]] = {"column": int(r["col"] or 0), "prose": 0,
                        "card": size_from_card(r["description"])}
    for r in conn.execute(
            "SELECT proposal_id, detail FROM verdicts WHERE tier = ? "
            "AND (detail LIKE '%bytes=%' OR detail LIKE '%GiB%') "
            "ORDER BY id", (INSPECT,)).fetchall():
        size = size_from_prose(r["detail"])
        if size > 0 and r["proposal_id"] in out:
            out[r["proposal_id"]]["prose"] = size
    return out


def backfill_sizes(conn) -> int:
    """Fill proposals.size_bytes once: inspect's column, then its prose, then the card. #413."""
    n = 0
    for pid, src in size_sources(conn).items():
        size = src["column"] or src["prose"] or src["card"]
        if size > 0:
            n += conn.execute(
                "UPDATE proposals SET size_bytes = ? "
                "WHERE id = ? AND size_bytes = 0", (size, pid)).rowcount
    return n


def _attribute_old_verdicts(conn: sqlite3.Connection) -> None:
    """Point 1767 existing verdicts at the machine that wrote them, and give
    the machine-limited ones a condition.

    THIS IS AN INFERENCE AND IS RECORDED AS ONE. Only this Mac has ever
    written to this store -- 56 rows say `on arm64` and none say anything
    else -- so attributing every pre-existing row to the machine running the
    migration is correct HERE and would be wrong on a store that had been
    shared. The fingerprint carries the real identity either way, so a reader
    can see which machine was assumed rather than trusting that it was right.
    """
    mid = remember_machine(conn)
    conn.execute("UPDATE verdicts SET machine_id = ? WHERE machine_id IS NULL",
                 (mid,))
    for phrase, until in _UNTIL_FROM_DETAIL:
        conn.execute(
            "UPDATE verdicts SET until = ? "
            "WHERE until = '' AND lower(detail) LIKE ?",
            (until, f"%{phrase}%"))
    # THE 144 ROWS THE STUDIO IS FOR. `too-big` is measured against
    # MEMORY_CEILING, which describes ONE 32 GB machine, so every one of these
    # is a statement about the machine that measured it, not the model. The condition is
    # the size the weights actually need, read out of the tier's own sentence,
    # so a bigger machine matches exactly the rows it can now run rather than
    # all of them.
    for vid, detail in conn.execute(
            "SELECT id, detail FROM verdicts "
            "WHERE until = '' AND detail LIKE 'too-big:%'").fetchall():
        until = until_for(detail)
        if until:
            conn.execute("UPDATE verdicts SET until = ? WHERE id = ?",
                         (until, vid))


#: `needs-vllm on Mac14,12/macOS-.../arm64: ...`: machine_id already says where.
_MACHINE_IN_DETAIL = re.compile(r"^(needs-[\w.-]+) on [^:]+: ")


def strip_machine_from_fetch_details(conn) -> int:
    """Drop the machine string fetch wrote into detail; machine_id holds it. #415."""
    n = 0
    for v in conn.execute("SELECT id, detail FROM verdicts WHERE tier = 'fetch' "
                          "AND detail LIKE 'needs-% on %'").fetchall():
        new = _MACHINE_IN_DETAIL.sub(r"\1: ", v["detail"], count=1)
        if new != v["detail"]:
            conn.execute("UPDATE verdicts SET detail = ? WHERE id = ?",
                         (new, v["id"]))
            n += 1
    return n


def backfill_result_classes(conn) -> int:
    """A failure class for result rows stored before runners set one, read
    once from their detail. #408."""
    from harness import reasons
    n = 0
    for r in conn.execute(
            "SELECT r.id, r.detail, c.spec FROM results r LEFT JOIN candidates c "
            "ON c.id = r.candidate_id WHERE r.passed = 0 "
            "AND r.failure_class = ''").fetchall():
        cls = reasons.legacy_class(r["detail"] or "", r["spec"] or "")
        if cls:
            conn.execute("UPDATE results SET failure_class = ? WHERE id = ?",
                         (cls, r["id"]))
            n += 1
    conn.commit()
    return n


#: Old prose for the two limits whose predicate a migration can recover. #406.
_BUDGET = re.compile(r"(\d+)-token budget")


_CAP = re.compile(r"over the ([\d.]+) GiB cap")


def _reopen_terminal_harness_and_limit_facts(conn) -> list:
    """A terminal state held by a harness fact or a harness limit is not a
    verdict on the candidate. Only rows backfill_reasons labelled harness or
    limit; returns (name, what was done). #406, #408."""
    from harness import reasons
    done = []
    for r in conn.execute(
            "SELECT p.id, p.name, v.id AS vid, v.tier, v.detail, v.reason, "
            "v.until FROM proposals p JOIN verdicts v "
            "ON v.id = p.state_verdict_id WHERE p.state IN "
            f"({', '.join('?' * len(TERMINAL))}) AND v.reason IN (?, ?)",
            (*TERMINAL, reasons.HARNESS, reasons.LIMIT)).fetchall():
        detail = r["detail"] or ""
        budget, cap = _BUDGET.search(detail), _CAP.search(detail)
        if r["reason"] == reasons.HARNESS:
            cls = reasons.legacy_class(detail.split(":", 1)[-1]) or "harness"
            why = (f"retracted: {cls} was a fact about this harness, not a "
                   f"verdict on {r['name']}")
        elif "timed out after" in detail:
            why = ("retracted: screen now warms the model; the 180 s timeout "
                   "counted a cold load")
        elif budget or cap:
            until = (f"limit:max_tokens>{budget.group(1)}" if budget
                     else f"limit:download_gib>{float(cap.group(1)):g}")
            if not r["until"]:
                conn.execute("UPDATE verdicts SET until = ? WHERE id = ?",
                             (until, r["vid"]))
                done.append((r["name"], f"until {until}"))
            continue
        else:
            continue
        _migration_retraction(conn, r["id"], r["name"], "queued",
                              r["tier"] or SCREEN, why)
        done.append((r["name"], why))
    conn.commit()
    return done


def backfill_reasons(conn) -> int:
    """verdicts.reason for rows written before #408, read once from their
    prose. Classifies only: no outcome or state changes. RULE #292."""
    from harness import reasons
    n = 0
    for r in conn.execute(
            "SELECT id, outcome, tier, detail, reopen_kind FROM verdicts "
            "WHERE reason = ''").fetchall():
        why = reasons.legacy_reason(r["outcome"], r["tier"] or "",
                                    r["detail"] or "", r["reopen_kind"] or "")
        if why:
            conn.execute("UPDATE verdicts SET reason = ? WHERE id = ?",
                         (why, r["id"]))
            n += 1
    conn.commit()
    return n


def reason_audit(conn) -> dict:
    """The reason distribution, over every verdict and over held states. #408."""
    every = {r[0]: r[1] for r in conn.execute(
        "SELECT reason, COUNT(*) FROM verdicts GROUP BY reason")}
    held = {}
    for r in conn.execute(
            "SELECT p.state, v.reason, COUNT(*) AS n FROM proposals p "
            "JOIN verdicts v ON v.id = p.state_verdict_id "
            "GROUP BY p.state, v.reason"):
        held.setdefault(r["state"], {})[r["reason"]] = r["n"]
    ours = sum(n for state, by in held.items() if state in TERMINAL
               for why, n in by.items() if why in ("harness", "limit"))
    return {"verdicts": every, "held": held, "terminal_harness_or_limit": ours}


#: THE ONLY READER OF inspect.card_description()'s grammar, and only to
#: backfill the columns once. What the 300-character string lost is lost. #414.
_DESC_TASK = re.compile(r"(?:^|; )task ([a-z0-9-]+)")


_DESC_SERVED = re.compile(r"(?:^|; )served by (\w[\w.-]*)")


_DESC_TAGS = re.compile(r"(?:^|; )tagged ([^;]*)")


_DESC_LINEAGE = re.compile(r"(?:^|; )(built from|adapter of) ([^;]+)")


#: The pre-#414 runtime reading, over the whole string as rank ran it.
_DESC_NEEDS_CUDA = re.compile(
    r"\b(cuda|tensorrt|gemlite|nvfp4|modelopt|marlin|exllama|bitsandbytes)\b",
    re.I)


_DESC_CARD = re.compile(r"^(task |served by |tagged |built from |adapter of "
                        r"|[\d.]+ GiB of weights)")


def card_from_description(description: str, card_shaped: bool):
    """The card facts a stored description still holds, and what it lost.

    Attachment and runtime are read over the whole string, exactly as the
    readers this replaces did. Task, library, tags and lineage only from a
    string inspect composed from a card. Lost: tags past the first six
    non-decisive ones, parents past three, the kind of any `built from`
    parent, and anything cut at 300 characters.
    """
    from harness import inspect as ins
    from harness import screen
    text = description or ""
    card = ins.Card(attaches_to=screen.is_attachment(text))
    m = _DESC_NEEDS_CUDA.search(text)
    lost = []
    if card_shaped and _DESC_CARD.match(text):
        if (t := _DESC_TASK.search(text.lower())):
            card.task = t.group(1)
        if (s := _DESC_SERVED.search(text)):
            card.library = s.group(1)
        if (g := _DESC_TAGS.search(text)):
            card.tags = [x.strip() for x in g.group(1).split(",") if x.strip()]
        if (ln := _DESC_LINEAGE.search(text)):
            kind = "adapter" if ln.group(1) == "adapter of" else ""
            card.parents = [(p.strip(), kind) for p in ln.group(2).split(",")
                            if p.strip()]
            if not kind:
                lost.append("lineage kind")
        if len(text) >= 300:
            lost.append("truncated")
    if m:
        card.runtime_needed = "cuda"
    elif card.library:
        card.runtime_needed = ins.runtime_needed(card.library)
    return card, lost


def backfill_card_facts(conn) -> dict:
    """Fill the card columns and lineage from each stored description. #414.

    One pass, schema 32. Rows are marked card_read='description' so a reader
    can tell a recovered fact from one read off the card; the next inspect of
    the row overwrites it with the card's own fields.
    """
    from harness import inspect as ins
    from harness import lanes
    counts = {"rows": 0, "card_shaped": 0, "task": 0, "library": 0,
              "lineage_rows": 0, "parents": 0, "adapters": 0,
              "attaches_to": 0, "runtime_needed": 0, "lane_source_card": 0,
              "lost_lineage_kind": 0, "truncated": 0}
    rows = conn.execute(
        "SELECT id, name, registry, lane, description FROM proposals "
        "WHERE description <> '' AND card_read = ''").fetchall()
    for r in rows:
        shaped = r["registry"] in (HUGGINGFACE, "")
        card, lost = card_from_description(r["description"], shaped)
        counts["rows"] += 1
        counts["card_shaped"] += bool(card.task or card.library or card.tags
                                      or card.parents)
        counts["task"] += bool(card.task)
        counts["library"] += bool(card.library)
        counts["parents"] += bool(card.parents)
        counts["lineage_rows"] += len(card.parents)
        counts["adapters"] += any(k == "adapter" for _, k in card.parents)
        counts["attaches_to"] += bool(card.attaches_to)
        counts["runtime_needed"] += bool(card.runtime_needed)
        counts["lost_lineage_kind"] += "lineage kind" in lost
        counts["truncated"] += "truncated" in lost
        if card.task:
            card.lane = ins.card_lane(card.task)
            card.lane_source = "card"
            counts["lane_source_card"] += bool(card.lane) and \
                lanes.canonical(r["lane"]) == lanes.canonical(card.lane)
        set_card(conn, r["name"], card, read="description")
    conn.commit()
    return counts


#: The one prose shape the neighbors path wrote into edges.note. #416.
_EDGE_NOTE = re.compile(r"^\s*(\d+)/(\d+) at (-?[\d.]+(?:e-?\d+)?)\s*$")


def lift_edge_scores(conn) -> dict:
    """Move the neighbor score out of edges.note into columns, once. #416."""
    got = {"lifted": 0, "unparsed": []}
    for r in conn.execute("SELECT id, note FROM edges WHERE note != '' "
                          "AND score IS NULL").fetchall():
        m = _EDGE_NOTE.match(r["note"])
        if not m:
            got["unparsed"].append(r["note"])
            continue
        conn.execute("UPDATE edges SET shared = ?, crowd = ?, score = ?, "
                     "note = '' WHERE id = ?",
                     (int(m.group(1)), int(m.group(2)), float(m.group(3)),
                      r["id"]))
        got["lifted"] += 1
    return got

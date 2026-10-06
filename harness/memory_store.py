"""Durable memory for the discovery loop. Issue #52.

Without this a sweep prints and forgets, so nothing compounds: every run
re-proposes what was already declined, and the precision of the extractor cannot
be measured because there is no record of what became of anything.

Three tables. `proposals` is identity, `sightings` is the time axis, `verdicts`
is what happened. The graph is the foreign keys; traversal is a join.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
import time
from dataclasses import dataclass
from pathlib import Path

from harness import paths, store

SCHEMA_VERSION = 26

#: Outcomes a proposal can reach. TERMINAL ones suppress re-proposal.
VERDICTS = ("measured", "declined", "broken", "queued", "ignored", "screened")
TERMINAL = ("measured", "declined", "broken", "ignored")
#: Outcomes that are not answers. One never replaces a TERMINAL state. #409.
WAYPOINTS = ("queued", "screened")

#: Where a name can be resolved. A proposal is `org/name` in both registries
#: and the two namespaces overlap, so the string alone cannot say which one
#: holds it: `openai/whisper-small` is a model, `openai/openai-python` a repo.
#: Issue #167. Empty means nothing recorded it, which is not the same as
#: neither -- an old row is unknown, and asking the wrong registry about it is
#: how 227 of 235 candidates 404ed.
GITHUB, HUGGINGFACE = "github", "huggingface"
REGISTRIES = (GITHUB, HUGGINGFACE)

#: WHICH TIER ANSWERED. Named here because these strings are a vocabulary
#: shared by writers and readers in different modules: the CLI writes
#: tier='inspect', judgeable() reads it back, and fetching.queued() filters on
#: it. Spelled as literals in three files, a rename in one would leave the
#: others silently returning nothing -- the same class as a list forked into
#: two configs. VERDICTS already had this treatment; the tiers did not.
INSPECT, JUDGE, SCREEN, MEASURE = "inspect", "judge", "screen", "measure"
#: The closing tier. A lane reads its adopted winner from here and falls
#: back to the typed constant when nothing has been adopted. See
#: harness/adopt.py.
ADOPT = "adopt"
TIERS = (INSPECT, JUDGE, SCREEN, MEASURE, ADOPT)
FETCH = "fetch"
#: Ladder order: an earlier tier never replaces a later tier's state. #409.
LADDER = {INSPECT: 0, JUDGE: 1, FETCH: 2, SCREEN: 3, MEASURE: 4, ADOPT: 5}

_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS proposals (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL DEFAULT 'candidate',
    -- Which registry answers for this name. See REGISTRIES.
    registry    TEXT NOT NULL DEFAULT '',
    -- WHAT THE THING IS, as its registry describes it. A sighting's `why` is
    -- what one source said about it on one day; this is the card. The judge
    -- scores a description, and with only a name to read it floored six
    -- models with known opposite outcomes at the same number. Issue #175.
    description TEXT NOT NULL DEFAULT '',
    lane        TEXT NOT NULL DEFAULT '',
    resolved    TEXT NOT NULL DEFAULT '',
    -- What it consumes and produces, so valid compositions can be found
    -- without trying every pair. Empty means unknown.
    consumes    TEXT NOT NULL DEFAULT '',
    produces    TEXT NOT NULL DEFAULT '',
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    -- Written only by decide(); see transition_refused(). #409.
    state       TEXT NOT NULL DEFAULT '',
    state_verdict_id INTEGER,
    -- Retests spent on a screen/measure rejection and when the next is due;
    -- NULL beside a rejection means none is left. #431.
    retest_count INTEGER NOT NULL DEFAULT 0,
    next_retest_at REAL
);

CREATE TABLE IF NOT EXISTS sightings (
    id          INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    why         TEXT NOT NULL DEFAULT '',
    relevance   INTEGER NOT NULL DEFAULT 0,
    seen_at     REAL NOT NULL,
    UNIQUE (proposal_id, source, url)
);

-- Proposal <-> spec <-> receipt key, written once by whoever resolves it. #407.
CREATE TABLE IF NOT EXISTS candidates (
    id          INTEGER PRIMARY KEY,
    -- NULL for a typed default or a command-line candidate.
    proposal_id INTEGER REFERENCES proposals(id) ON DELETE SET NULL,
    spec        TEXT NOT NULL UNIQUE,
    receipt_key TEXT NOT NULL,
    lane        TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS verdicts (
    id          INTEGER PRIMARY KEY,
    -- NULL only for a verdict about a candidate no proposal names. #407.
    proposal_id INTEGER REFERENCES proposals(id) ON DELETE CASCADE,
    outcome     TEXT NOT NULL,
    tier        TEXT NOT NULL DEFAULT '',
    detail      TEXT NOT NULL DEFAULT '',
    issue       INTEGER,
    run_path    TEXT NOT NULL DEFAULT '',
    score       REAL,
    rubric      TEXT NOT NULL DEFAULT '',
    judge       TEXT NOT NULL DEFAULT '',
    decided_at  REAL NOT NULL,
    -- WHERE IT WAS DECIDED. The store is shared across three machines and a
    -- refusal is routinely a fact about ONE of them: `needs-cuda` is true
    -- here and false on the box with the card. This lived in the detail
    -- string as the word `arm64`, which is an architecture rather than a
    -- machine and cannot tell the 4070 under Linux from the same 4070 under
    -- Windows -- two rigs this project's own comparable() already refuses to
    -- pool. Issue #266.
    machine_id  INTEGER REFERENCES machines(id),
    -- THE MEASURED SIZE, WHICH CODE READS BACK. It lived in `detail` as
    -- `bytes=N`, then as `weights from 5.5 to 8.9 GiB` when the tier was
    -- reworded -- and fetching.size_of() parses BOTH with regexes because the
    -- rewording silently broke the numeric read. Every candidate came back
    -- unsized and was declined TERMINALLY for a size sitting in the row
    -- above (#211). A text column any code parses is a schema whose format
    -- nobody wrote down. 0 means not measured. Issue #266.
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    -- THE WORD THAT MADE THIS AN ATTACHMENT, not a sentence containing it.
    -- `lora`, `comfyui`, `browser`. "" means this is not an attachment, which
    -- is the answer for almost every row and must stay distinguishable from
    -- "nobody asked". Issue #268.
    attaches_to TEXT NOT NULL DEFAULT '',
    -- DAYS SINCE THE CANDIDATE'S UPSTREAM LAST COMMITTED, at decision time.
    -- Named `stale_days` first, which says nothing about WHOSE staleness and
    -- was read as the age of our own row -- this project is days old and the
    -- repos it refuses are years idle. The column exists to hold a number the
    -- tier only ever formatted: `last commit 2.9 years ago`. 0 means not
    -- measured. Issue #270.
    upstream_idle_days REAL NOT NULL DEFAULT 0,
    -- WHAT WOULD MAKE THIS WORTH ASKING AGAIN, in the machine's terms. A
    -- ceiling refusal expires when a bigger machine arrives, and until now
    -- nothing could find those rows: the reason was prose. Same shape as
    -- lanes.PARKED, which carries (why, until) for a lane and was the only
    -- place in the project that said out loud what it was waiting for.
    until       TEXT NOT NULL DEFAULT '',
    candidate_id INTEGER REFERENCES candidates(id),
    -- A named reopen: the state verdict it overrode, and which kind. #409.
    reopens     INTEGER REFERENCES verdicts(id),
    reopen_kind TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS machines (
    id           INTEGER PRIMARY KEY,
    -- Stable across runs and distinct between rigs. NOT the architecture and
    -- NOT the hostname: a hostname changes without the machine changing, and
    -- an architecture stays the same across two machines that measure
    -- differently.
    fingerprint  TEXT NOT NULL UNIQUE,
    hw_model     TEXT NOT NULL DEFAULT '',
    os           TEXT NOT NULL DEFAULT '',
    arch         TEXT NOT NULL DEFAULT '',
    memory_gb    REAL NOT NULL DEFAULT 0,
    accelerator  TEXT NOT NULL DEFAULT '',
    -- CAPABILITY AT DECISION TIME, which is the half that makes a verdict
    -- re-askable. A machine that gains a runtime is a different machine for
    -- this purpose, so these are recorded rather than probed when read.
    runtimes     TEXT NOT NULL DEFAULT '',
    ceiling_gb   REAL NOT NULL DEFAULT 0,
    first_seen   REAL NOT NULL,
    last_seen    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    id          INTEGER PRIMARY KEY,
    src         INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    dst         INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    relation    TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    UNIQUE (src, dst, relation)
);

-- Names pulled out of prose and REJECTED. Without these there is no
-- denominator: every proposal in the store resolved to something real, so
-- "100% resolved" was arithmetic, not precision. Issue #49.
CREATE TABLE IF NOT EXISTS extractions (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL,
    reason      TEXT NOT NULL,
    at          REAL NOT NULL,
    UNIQUE (name, source, reason)
);

-- One answer from a person on the judge page. #417.
CREATE TABLE IF NOT EXISTS human_votes (
    id              INTEGER PRIMARY KEY,
    lane            TEXT NOT NULL,
    run             TEXT NOT NULL DEFAULT '',
    case_id         TEXT NOT NULL,
    left_candidate  TEXT NOT NULL,
    right_candidate TEXT NOT NULL,
    winner          TEXT NOT NULL DEFAULT '',
    shown_first     TEXT NOT NULL DEFAULT '',
    voter           TEXT NOT NULL DEFAULT '',
    machine_id      INTEGER REFERENCES machines(id),
    at              REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_human_votes_pair
    ON human_votes(lane, case_id, left_candidate, right_candidate);
CREATE INDEX IF NOT EXISTS ix_sight_prop ON sightings(proposal_id);
CREATE INDEX IF NOT EXISTS ix_verdict_prop ON verdicts(proposal_id);
CREATE INDEX IF NOT EXISTS ix_cand_prop ON candidates(proposal_id);
CREATE INDEX IF NOT EXISTS ix_cand_key ON candidates(receipt_key);
CREATE INDEX IF NOT EXISTS ix_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS ix_edges_dst ON edges(dst);
"""


#: How long a writer waits for the lock before giving up. Generous because the
#: alternative is a failed sweep, and a discovery write is milliseconds: this
#: is a queue depth, not a latency budget.
BUSY_TIMEOUT_SECONDS = 30.0


def db_path() -> Path:
    return paths.home() / "discovery.db"


def connect(path: Path | None = None):
    """Open (creating if needed) and migrate to SCHEMA_VERSION.

    SQLite unless LOCALHARNESS_STORE says postgres, because `lh` on a laptop
    must keep working with no cluster at all -- a discovery engine that only
    runs in Kubernetes is a worse tool than the one that already exists.
    """
    if store.backend() == store.POSTGRES:
        conn = store.postgres_connect()
        conn.executescript(_DDL)
        _migrate(conn)
        return conn
    path = Path(path) if path is not None else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # SQLite does not corrupt under concurrent writers -- it SERIALISES them,
    # and an unprepared second writer gets `database is locked` at once. These
    # two lines are the difference between "waits its turn" and "fails", and
    # the discovery store is about to have several writers (#148).
    #
    # WAL also lets readers proceed during a write, which matters because the
    # sweep reads while the judge writes. The caveat is the filesystem: WAL
    # needs real shared memory and is unsafe over NFS-style mounts, so a
    # network-mounted store wants a single writer rather than this.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_SECONDS * 1000)}")
    conn.executescript(_DDL)
    _migrate(conn)
    return conn


def dangling_receipts(conn: sqlite3.Connection, exists=None) -> list:
    """Verdicts citing a run that is no longer on disk.

    A VERDICT WHOSE EVIDENCE IS GONE CANNOT BE RE-JUDGED. Schema 10 exists
    because verdicts were recorded from runs that never reached a model, and
    the fix required reading those runs back -- which is impossible once the
    directory is deleted. That migration ran once; nothing has checked since,
    and 7 of the 55 verdicts that name a run already point at nothing.

    A RELATIVE PATH IS RESOLVED BEFORE IT IS CALLED MISSING. Six of the seven
    rows this first reported as gone are `runs/cycle-screen` and friends,
    which are relative to paths.home() and exist. Reading them against the
    process's cwd made a healthy store look half-rotten -- the same class of
    error as every defect this function exists to find, committed by the
    finder. The column holds both spellings because nothing ever normalised
    it; resolving here is what makes the answer true rather than tidy.

    `exists` is injected so this is testable without staging a filesystem.
    """
    exists = exists if exists is not None else (lambda p: Path(p).exists())
    rows = conn.execute(
        "SELECT v.id, v.outcome, v.tier, v.run_path, p.name "
        "FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
        "WHERE v.run_path != ''").fetchall()
    out = []
    for r in rows:
        if any(exists(c) for c in resolved_run_paths(r["run_path"])):
            continue
        out.append(dict(r))
    return out


def resolved_run_paths(run_path: str) -> list[str]:
    """Every place `run_path` could mean, most likely first.

    The column mixes absolute paths with paths relative to the project home,
    because nothing ever normalised it and both spellings were written by
    code that was correct from where it stood.
    """
    from harness import paths

    raw = (run_path or "").strip()
    if not raw:
        return []
    if Path(raw).is_absolute():
        return [raw]
    return [raw, str(paths.home() / raw)]


def until_met(until: str, facts: dict | None = None) -> bool:
    """Whether `facts` satisfies the condition a verdict is waiting on.

    A PREDICATE, NOT A SENTENCE. The whole point of #266 is that a machine
    fact buried in prose cannot be queried, so writing the condition as prose
    would move the defect rather than fix it.

    Five forms, which is all the real rows need:
        runtime:<name>     the machine has that runtime
        version:<pkg>><v>  the installed <pkg> is newer than v (#293)
        memory_gb:><n>     the machine holds more than n GB
        ceiling_gb:><n>    the machine will load weights larger than n GiB
        commit_after:<iso> the candidate's upstream has committed since

    THE FIRST THREE ARE ABOUT THE MACHINE AND THE FOURTH IS NOT, which is why
    `facts` is a plain dict rather than a Machine: a verdict waits on whatever
    would change it, and `dead` waits on somebody else's repository.
    An unrecognised condition is NOT met, so a typo leaves the verdict
    standing rather than silently re-queueing everything.
    """
    if not until:
        return False
    facts = facts if facts is not None else this_machine()
    key, _, want = until.partition(":")
    if key == "runtime":
        have = (facts.get("runtimes") or "").split(",")
        return any(rt in have for rt in want.split("|"))
    if key in ("memory_gb", "ceiling_gb") and want.startswith(">"):
        try:
            return float(facts.get(key) or 0) > float(want[1:])
        except ValueError:
            return False
    if key == "version" and ">" in want:
        pkg, _, floor = want.partition(">")
        if "versions" in facts:
            have = (facts.get("versions") or {}).get(pkg)
        elif pkg == "llama.cpp":
            from harness import serving
            have = serving.llamacpp_build() or None
        else:
            # The same source load_until wrote the floor from: diffusers and
            # mflux live in their own venvs, which importlib cannot see. #389.
            from harness import feeds
            have = feeds.installed_version(pkg) or None
        a, b = _version_tuple(have), _version_tuple(floor)
        return a is not None and b is not None and a > b
    if key == "commit_after":
        seen = (facts.get("last_commit") or "").strip()
        # STRING COMPARISON IS CORRECT FOR ISO-8601 AND ONLY FOR IT, so both
        # sides are checked for the shape first. A length test was not enough
        # and the negative control caught it: "last Tuesday" is twelve
        # characters and sorts ABOVE any date beginning with a digit, so an
        # unparseable field reopened the verdict -- the opposite of the safe
        # direction this function is supposed to fail in.
        return bool(_ISO_DATE.match(seen) and _ISO_DATE.match(want)
                    and seen > want)
    return False


def _version_tuple(v) -> tuple | None:
    """`0.31.10` as (0, 31, 10), so it sorts after `0.31.9`. None if unparseable."""
    parts = str(v or "").split(".")
    return tuple(int(x) for x in parts) if all(x.isdigit() for x in parts) else None


def revisitable(conn: sqlite3.Connection, facts: dict | None = None) -> list:
    """Verdicts decided elsewhere whose condition THIS machine now satisfies.

    The read path the columns exist for. A candidate declined on a machine
    with no cuda is not declined on the box with the card, and until now
    nothing could find those rows: the reason was a sentence.

    Only the verdict holding the state counts, so a condition that was
    already retracted does not resurrect.
    """
    facts = facts if facts is not None else this_machine()
    rows = conn.execute("""
        SELECT p.name, p.lane, v.outcome, v.detail, v.until, v.tier,
               m.fingerprint AS decided_on
          FROM proposals p
          JOIN verdicts v ON v.id = p.state_verdict_id
          LEFT JOIN machines m ON m.id = v.machine_id
         WHERE v.until != ''
    """).fetchall()
    # Wherever it was decided: a refusal is written because its condition is
    # unmet, so meeting it later means the machine changed. #295.
    return [dict(r) for r in rows
            if r["outcome"] in TERMINAL and until_met(r["until"], facts)]


def requeue_revisitable(conn, facts: dict | None = None) -> list[str]:
    """Retract every revisitable verdict back to the inspect tier. #295."""
    names = []
    for r in revisitable(conn, facts):
        retract(conn, r["name"], f"{r['until']} is met here")
        names.append(r["name"])
    conn.commit()
    return names


_NONE_OF = re.compile(r"none of ([\w, ]+)$")
_TOO_BIG = re.compile(r"^too-big:.*?([\d.]+)\s*GiB")


def until_for(detail: str) -> str:
    """The predicate a refusal's own sentence implies, or '' if none."""
    detail = detail or ""
    m = _TOO_BIG.match(detail)
    if m:
        return f"ceiling_gb:>{float(m.group(1)):.1f}"
    for phrase, until in _UNTIL_FROM_DETAIL:
        if detail.lower().startswith(phrase):
            many = _NONE_OF.search(detail)
            if many:
                return "runtime:" + "|".join(
                    rt.strip() for rt in many.group(1).split(","))
            return until
    return ""


def _backfill_until(conn: sqlite3.Connection) -> None:
    for vid, detail in conn.execute(
            "SELECT id, detail FROM verdicts WHERE until = '' "
            "AND outcome IN ('declined', 'broken')").fetchall():
        until = until_for(detail)
        if until:
            conn.execute("UPDATE verdicts SET until = ? WHERE id = ?",
                         (until, vid))


#: What a pre-#266 refusal was waiting for, derived from the phrase the tier
#: wrote. Keyed on the runtime name because machine.refuses() builds these,
#: so the two stay in step without a second list to maintain.
_UNTIL_FROM_DETAIL = tuple(
    (f"needs-{rt}", f"runtime:{rt}")
    for rt in ("cuda", "rocm", "vllm", "mlx", "llamacpp"))


#: A date this can order by comparing strings. Anything else is not met.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")

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
    """Move 728 measured sizes from `detail` into a column.

    READ WITH THE SAME CODE THE TIER READS WITH. Writing a second parser here
    would give the migration its own idea of what the prose meant, and the
    whole defect is that the prose had two meanings already. fetching.size_of
    is the authority and knows about both spellings and which to prefer.
    """
    from harness import fetching

    for vid, detail in conn.execute(
            "SELECT id, detail FROM verdicts WHERE size_bytes = 0 "
            "AND (detail LIKE '%bytes=%' OR detail LIKE '%GiB%')").fetchall():
        size = fetching.size_of({"detail": detail or ""})
        if size > 0:
            conn.execute("UPDATE verdicts SET size_bytes = ? WHERE id = ?",
                         (size, vid))


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


def _migrate(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    have = int(row["value"]) if row else 0
    if have == SCHEMA_VERSION:
        return
    if have > SCHEMA_VERSION:
        raise RuntimeError(
            f"discovery.db is schema {have}, this code speaks {SCHEMA_VERSION}. "
            f"Refusing to touch a newer store.")
    # First, so every retraction below moves the state it reads. #409.
    _add_state(conn)
    _add_retest(conn)
    if have and have < 25:
        _backfill_state(conn)
    # The DDL above is CREATE IF NOT EXISTS, so v0 -> v1 and v1 -> v2 (which
    # only adds the extractions table) need nothing beyond the stamp. v3 adds
    # a column to a table that already exists, which CREATE IF NOT EXISTS
    # cannot do.
    if have < 3:
        if "registry" not in _columns(conn, "proposals"):
            conn.execute("ALTER TABLE proposals "
                         "ADD COLUMN registry TEXT NOT NULL DEFAULT ''")
        _backfill_registry(conn)
    if have and have < 4 and "description" not in _columns(conn, "proposals"):
        conn.execute("ALTER TABLE proposals "
                     "ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    if have and have < 5:
        _canonical_lanes(conn)
        _backfill_lanes(conn)
    if have and have < 7:
        _retract_harness_refusals(conn)
    if have and have < 8:
        _retract_verdicts_with_no_control(conn)
    if have and have < 9:
        _relane_from_the_card(conn)
    if have and have < 10:
        _retract_verdicts_from_runs_that_never_ran(conn)
    if have and have < 11:
        # The phrase list grew: a screen subprocess that resolved a PARENT
        # directory's virtualenv could not import our own eval package, and
        # four freshly fetched candidates were recorded BROKEN, which is
        # terminal, for something they never did. The retraction is DERIVED
        # from the current lists rather than naming rows, which is the lesson
        # of #230 -- naming rows by hand missed the second member of the same
        # class.
        _retract_harness_refusals(conn)
    if have and have < 12:
        for col, ddl in (("machine_id", "INTEGER REFERENCES machines(id)"),
                         ("until", "TEXT NOT NULL DEFAULT ''")):
            if col not in _columns(conn, "verdicts"):
                conn.execute(f"ALTER TABLE verdicts ADD COLUMN {col} {ddl}")
        _attribute_old_verdicts(conn)
    if have and have < 13:
        if "size_bytes" not in _columns(conn, "verdicts"):
            conn.execute("ALTER TABLE verdicts "
                         "ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")
        _lift_sizes_out_of_prose(conn)
    if have and have < 14:
        # UNDER THE NAME IT ENDS UP WITH. A store arriving from schema 13 has
        # never seen `stale_days`, so creating it just to rename it one block
        # later would make the old name real for the first time in a database
        # that exists AFTER it was retired. v15 below handles the stores that
        # genuinely have it.
        for col, ddl in (("attaches_to", "TEXT NOT NULL DEFAULT ''"),
                         ("upstream_idle_days", "REAL NOT NULL DEFAULT 0")):
            if col not in _columns(conn, "verdicts") and \
                    "stale_days" not in _columns(conn, "verdicts"):
                conn.execute(f"ALTER TABLE verdicts ADD COLUMN {col} {ddl}")
        if "stale_days" in _columns(conn, "verdicts"):
            conn.execute("ALTER TABLE verdicts "
                         "RENAME COLUMN stale_days TO upstream_idle_days")
        if "attaches_to" not in _columns(conn, "verdicts"):
            conn.execute("ALTER TABLE verdicts ADD COLUMN "
                         "attaches_to TEXT NOT NULL DEFAULT ''")
        _lift_kind_and_age_out_of_prose(conn)
    if have and have < 15:
        # SAY WHOSE FACT IT IS. `stale_days` reads as the age of the row; it
        # is days since the CANDIDATE's upstream last committed. It was read
        # the other way within a day of landing, which is the only test of a
        # name that matters.
        cols = _columns(conn, "verdicts")
        if "stale_days" in cols and "upstream_idle_days" not in cols:
            conn.execute("ALTER TABLE verdicts "
                         "RENAME COLUMN stale_days TO upstream_idle_days")
        elif "upstream_idle_days" not in cols:
            conn.execute("ALTER TABLE verdicts ADD COLUMN "
                         "upstream_idle_days REAL NOT NULL DEFAULT 0")
        _let_a_revived_upstream_be_reconsidered(conn)
    if have and have < 16:
        _retract_screens_with_no_evidence(conn)
    if have and have < 17:
        _reopen_architecture_gaps(conn)
    if have and have < 18:
        _backfill_until(conn)
    if have and have < 19:
        # Unlisted card tasks now file by what they produce, and a layout stock
        # diffusers cannot assemble is not the candidate's fault. #379, #381.
        _relane_from_the_card(conn)
        _requeue_diffusers_layout_gaps(conn)
    if have and have < 20:
        _requeue_screens_of_missing_weights(conn)
    if have and have < 21:
        # Only the new phrase: rerunning the whole list reopens what earlier
        # schemas deliberately left. #401.
        _requeue_broken_matching(conn)
    if have and have < 22:
        _requeue_broken_matching(conn, ("generation thread died",))
    if have < 23:
        import_human_verdicts_json(conn)
    if have and have < 24:
        _verdicts_name_a_candidate(conn)
        backfill_candidates(conn)
    if have and have < 26:
        backfill_retests(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_verdict_cand "
                 "ON verdicts(candidate_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_prop_state ON proposals(state)")
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)",
                 (str(SCHEMA_VERSION),))
    conn.commit()


def _add_state(conn) -> None:
    """The state columns, on a store older than the DDL. #409."""
    for table, col, ddl in (
            ("proposals", "state", "TEXT NOT NULL DEFAULT ''"),
            ("proposals", "state_verdict_id", "INTEGER"),
            ("verdicts", "reopens", "INTEGER REFERENCES verdicts(id)"),
            ("verdicts", "reopen_kind", "TEXT NOT NULL DEFAULT ''")):
        if col not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def _add_retest(conn) -> None:
    """The retest columns, on a store older than the DDL. #431."""
    for col, ddl in (("retest_count", "INTEGER NOT NULL DEFAULT 0"),
                     ("next_retest_at", "REAL")):
        if col not in _columns(conn, "proposals"):
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {col} {ddl}")


def backfill_retests(conn) -> int:
    """Schedule a first retest for each eligible rejection already held. #431."""
    n = 0
    for r in conn.execute(
            "SELECT p.id, p.state, v.tier, v.until, v.decided_at FROM proposals p "
            "JOIN verdicts v ON v.id = p.state_verdict_id "
            "WHERE p.next_retest_at IS NULL AND p.retest_count = 0").fetchall():
        if retest_eligible(r["state"], r["tier"], r["until"]):
            conn.execute("UPDATE proposals SET next_retest_at = ? WHERE id = ?",
                         (float(r["decided_at"]) + RETEST_AFTER_SECONDS, r["id"]))
            n += 1
    return n


def _backfill_state(conn) -> None:
    """Each proposal's state from its newest verdict, as every reader had it."""
    conn.execute(
        "UPDATE proposals SET state_verdict_id = (SELECT MAX(v.id) "
        "FROM verdicts v WHERE v.proposal_id = proposals.id)")
    conn.execute(
        "UPDATE proposals SET state = COALESCE((SELECT v.outcome FROM verdicts v "
        "WHERE v.id = proposals.state_verdict_id), '')")
    conn.commit()


def import_human_verdicts_json(conn, path: Path | None = None) -> int:
    """Backfill human_votes from the retired human-verdicts.json. Read-only."""
    path = Path(path) if path is not None else paths.home() / "human-verdicts.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        at = path.stat().st_mtime
    except (OSError, ValueError):
        return 0
    n = 0
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not r.get("lane") or not r.get("case"):
            continue
        lo, hi = sorted((r.get("left") or "", r.get("right") or ""))
        # The file kept no run, voter, machine or time; mtime bounds the time.
        conn.execute(
            "INSERT INTO human_votes (lane, run, case_id, left_candidate, "
            "right_candidate, winner, shown_first, voter, machine_id, at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r["lane"], "", r["case"], lo, hi, r.get("winner") or "",
             r.get("shown_first") or "", "", None, at))
        n += 1
    return n


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
    from harness import screen
    until = screen.load_until()
    for r in _stated(conn, "p.state = 'broken' AND v.tier = ?", (SCREEN,)):
        if screen.is_architecture_gap(r["detail"]):
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
    from harness import fetching, screen
    for row in _stated(conn, "p.state IN ('declined', 'broken')"):
        pid, name = row["id"], row["name"]
        detail, tier = row["detail"] or "", row["tier"] or ""
        phrase = (fetching.refused_by_harness(detail)
                  or screen.refused_by_harness(detail))
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


#: How the inspect tier spells the registry's own task inside a description.
_CARD_TASK = re.compile(r"task ([a-z0-9-]+)")


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

    rows = conn.execute(
        "SELECT id, name, lane, description FROM proposals "
        "WHERE description <> ''").fetchall()
    moved = []
    for row in rows:
        m = _CARD_TASK.search((row["description"] or "").lower())
        card = ins.card_lane(m.group(1)) if m else None
        was = lanes.canonical(row["lane"])
        # A text task cannot say WHICH text lane: OmniSVG is image-text-to-text.
        if not card or was == card or (card == "code" and was in lanes.TEXT_SERVED):
            continue
        conn.execute("UPDATE proposals SET lane = ? WHERE id = ?",
                     (card, row["id"]))
        moved.append((row["id"], row["name"], row["lane"], card))

    # A terminal verdict reached in the WRONG LANE says nothing about the
    # candidate: the screen built its spec from the lane and handed it cases
    # from a modality it does not serve. Re-queued, not deleted.
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
                     f"({card})")


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
                and not fetching.have(r["name"]):
            _migration_retraction(conn, r["id"], r["name"], "queued", SCREEN,
                         f"retracted: {r['name']}'s weights were never "
                         f"downloaded, so the screen ran on nothing")


def _requeue_diffusers_layout_gaps(conn) -> None:
    from harness import screen
    for r in _stated(conn, "p.state = 'broken'"):
        if any(g in (r["detail"] or "").lower()
               for g in screen.DIFFUSERS_LAYOUT_GAPS):
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
    import json

    from harness import cli, paths

    runs = paths.home() / "runs"
    if not runs.is_dir():
        return
    never_ran = set()
    for d in sorted(runs.iterdir()):
        f = d / "results.json"
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = data.get("rows") or []
        for key, got in (data.get("summary") or {}).items():
            if got.get("passed") or not got.get("total"):
                continue
            why = cli._all_refused(rows, key)
            if why and why != cli.NO_ROWS_FOR_CANDIDATE:
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
    cols = ", ".join(c for c in have)
    conn.execute(f"INSERT INTO verdicts_new ({cols}) SELECT {cols} FROM verdicts")
    conn.execute("DROP TABLE verdicts")
    conn.execute("ALTER TABLE verdicts_new RENAME TO verdicts")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_verdict_prop "
                 "ON verdicts(proposal_id)")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


#: The shape `lh judge` stored before receipts carried specs: Engine.name. #337.
_ACESTEP_LABEL = re.compile(r"^(?:acestep:)?acestep/([^@,]+)(?:@(.*))?$")


def _legacy_spec(label: str) -> str:
    """A spec for a label an old writer stored in place of one; else as given."""
    m = _ACESTEP_LABEL.match(label or "")
    if not m:
        return label
    return f"acestep:{m.group(1)}" + (f",{m.group(2)}" if m.group(2) else "")


def _adopted_by_name(conn) -> list:
    """Proposals adopt.record created from a spec or a receipt key."""
    return conn.execute(
        "SELECT p.id, p.name, p.lane FROM proposals p WHERE EXISTS "
        "(SELECT 1 FROM sightings s WHERE s.proposal_id = p.id) AND NOT EXISTS "
        "(SELECT 1 FROM sightings s WHERE s.proposal_id = p.id "
        " AND s.source != 'adopt')").fetchall()


def backfill_candidates(conn, runs=None) -> dict:
    """Fill `candidates` from what the store and receipts already hold. #407.

    Never decides anything: verdict outcomes are untouched, and a verdict moved
    off a spec-named proposal never becomes its new proposal's latest row.
    """
    import json
    from harness import candidates as C, gguf, screen
    from harness.serving import LLAMACPP_PREFIX

    counts = {"gguf": 0, "proposals": 0, "receipt_specs": 0,
              "receipt_keys": 0, "run_path_confirmed": 0, "fakes": 0,
              "fakes_to_proposal": 0, "fakes_unresolved": 0,
              "verdicts_linked": 0}
    fakes = {r["id"]: dict(r) for r in _adopted_by_name(conn)}
    lane_of = {r["name"]: r["lane"] for r in conn.execute(
        "SELECT name, lane FROM proposals")}
    for repo, filename in sorted(gguf._load().items()):
        if repo in lane_of and str(filename).endswith(".gguf"):
            if C.ensure(conn, f"{LLAMACPP_PREFIX}{filename[:-len('.gguf')]}",
                        proposal=repo, lane=lane_of[repo]):
                counts["gguf"] += 1
    own = {}
    rows = conn.execute(
        "SELECT DISTINCT p.id, p.name, p.lane, p.description FROM proposals p "
        "JOIN verdicts v ON v.proposal_id = p.id "
        "WHERE v.tier IN (?, ?, ?)", (SCREEN, MEASURE, ADOPT)).fetchall()
    for r in rows:
        if r["id"] in fakes or not r["lane"]:
            continue
        try:
            spec = screen.candidate_for(r["lane"], r["name"],
                                        r["description"] or "", adopt=False)
        except Exception:  # noqa: BLE001
            spec = ""
        cid = C.ensure(conn, spec, proposal=r["name"], lane=r["lane"]) \
            if spec else None
        if cid:
            own[r["id"]] = cid
            counts["proposals"] += 1
    root = runs or (paths.home() / "runs")
    for f in sorted(root.rglob("results.json")) if root.is_dir() else []:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        lane = str((data.get("receipt") or {}).get("modality") or "")
        specs = {k: _legacy_spec(v) for k, v in (data.get("specs") or {}).items()}
        for key, spec in specs.items():
            if C.key_of(spec) == key and C.ensure(conn, spec, key=key, lane=lane):
                counts["receipt_specs"] += 1
        for key in (data.get("summary") or {}):
            if key not in specs and ":" in key and C.key_of(key) == key \
                    and C.ensure(conn, key, lane=lane):
                counts["receipt_keys"] += 1
    for r in conn.execute(
            "SELECT DISTINCT v.proposal_id, v.run_path FROM verdicts v "
            "WHERE v.run_path != '' AND v.tier IN (?, ?)", (SCREEN, MEASURE)):
        cid = own.get(r["proposal_id"])
        f = Path(r["run_path"]) / "results.json"
        if not cid or not f.is_file():
            continue
        try:
            summary = json.loads(f.read_text(encoding="utf-8")).get("summary")
        except (OSError, ValueError):
            continue
        key = conn.execute("SELECT receipt_key FROM candidates WHERE id = ?",
                           (cid,)).fetchone()[0]
        if key in (summary or {}):
            counts["run_path_confirmed"] += 1
    for pid, fake in fakes.items():
        counts["fakes"] += 1
        label = _legacy_spec(fake["name"])
        got = C.get(conn, label)
        if got is None and ":" in label:
            C.ensure(conn, label, lane=fake["lane"])
            got = C.get(conn, label)
        if got is None:
            counts["fakes_unresolved"] += 1
            continue
        target = got["proposal_id"] if got["proposal_id"] != pid else None
        newest = conn.execute(
            "SELECT state_verdict_id FROM proposals WHERE id = ?",
            (target,)).fetchone()[0] if target else None
        moved = conn.execute("SELECT id FROM verdicts WHERE proposal_id = ?",
                             (pid,)).fetchall()
        for v in moved:
            keep = target if newest is not None and v["id"] < newest else None
            conn.execute("UPDATE verdicts SET proposal_id = ?, candidate_id = ? "
                         "WHERE id = ?", (keep, got["id"], v["id"]))
        if target:
            counts["fakes_to_proposal"] += 1
        conn.execute("UPDATE candidates SET proposal_id = NULL "
                     "WHERE proposal_id = ?", (pid,))
        conn.execute("DELETE FROM proposals WHERE id = ?", (pid,))
    for pid, cid in own.items():
        cur = conn.execute(
            "UPDATE verdicts SET candidate_id = ? WHERE proposal_id = ? "
            "AND candidate_id IS NULL AND tier IN (?, ?, ?)",
            (cid, pid, SCREEN, MEASURE, ADOPT))
        counts["verdicts_linked"] += cur.rowcount or 0
    conn.commit()
    return counts


def _columns(conn, table: str) -> set[str]:
    """Column names of one table, asked of whichever backend this is."""
    if store.backend() == store.POSTGRES:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?", (table,))
        return {r["column_name"] for r in rows}
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


#: Evidence a v2 store already holds about where a name came from, strongest
#: first. Each rule only fills rows still empty, so a URL beats a kind: the
#: inspect tier wrote kind='repo' for a GitHub repo while from_feeds wrote the
#: same kind for a HuggingFace one, and the URL it recorded alongside says
#: which is which.
_BACKFILL = (
    ("url", "https://huggingface.co/%", HUGGINGFACE),
    ("url", "https://github.com/%", GITHUB),
    ("kind", "weights", HUGGINGFACE),
    ("kind", "tool", GITHUB),
    ("kind", "repo", HUGGINGFACE),
)


def _backfill_registry(conn) -> int:
    """Fill `registry` from what the store already recorded. Returns the count.

    A row with no evidence keeps the empty string. Guessing one for it would
    turn "nobody knows" into a wrong answer that nothing ever revisits, which
    is the failure this column exists to end.
    """
    filled = 0
    for field, value, registry in _BACKFILL:
        if field == "url":
            cur = conn.execute(
                "UPDATE proposals SET registry = ? WHERE registry = '' "
                "AND id IN (SELECT proposal_id FROM sightings WHERE url LIKE ?)",
                (registry, value))
        else:
            cur = conn.execute(
                "UPDATE proposals SET registry = ? WHERE registry = '' "
                "AND kind = ?", (registry, value))
        filled += cur.rowcount or 0
    conn.commit()
    return filled


@dataclass
class Seen:
    """One proposal observed in one source at one time."""
    name: str
    source: str
    url: str = ""
    why: str = ""
    relevance: int = 0
    kind: str = "candidate"
    lane: str = ""
    resolved: str = ""
    #: One of REGISTRIES, or empty when the caller genuinely cannot say.
    registry: str = ""
    #: What the registry says this IS, as opposed to what one source said
    #: about it. Only filled by a tier that read the registry.
    description: str = ""


def record(conn: sqlite3.Connection, seen: Seen, at: float | None = None) -> int:
    """Upsert the proposal, add a sighting. Returns the proposal id.

    Seeing the same thing again is a SIGHTING, never a duplicate proposal:
    recurrence over time is the signal that separates a lasting thing from one
    that trended once.
    """
    now = time.time() if at is None else at
    cur = conn.execute("SELECT id FROM proposals WHERE name = ?", (seen.name,))
    row = cur.fetchone()
    if row:
        pid = row["id"]
        conn.execute(
            "UPDATE proposals SET last_seen = ?, "
            "  resolved = CASE WHEN ?<>'' THEN ? ELSE resolved END, "
            "  lane = CASE WHEN lane='' THEN ? ELSE lane END, "
            "  registry = CASE WHEN registry='' THEN ? ELSE registry END, "
            "  description = CASE WHEN ?<>'' THEN ? ELSE description END "
            "WHERE id = ?",
            (now, seen.resolved, seen.resolved, seen.lane, seen.registry,
             seen.description, seen.description, pid))
    else:
        pid = conn.execute(
            "INSERT INTO proposals (name, kind, registry, lane, resolved, "
            "description, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?)",
            (seen.name, seen.kind, seen.registry, seen.lane, seen.resolved,
             seen.description, now, now)).lastrowid
    conn.execute(
        "INSERT OR IGNORE INTO sightings (proposal_id, source, url, why, "
        "relevance, seen_at) VALUES (?,?,?,?,?,?)",
        (pid, seen.source, seen.url, seen.why, seen.relevance, now))
    conn.commit()
    return pid


def set_lane(conn, name: str, lane: str) -> bool:
    """Record a lane READ FROM THE REGISTRY, overwriting a guess.

    `record()` keeps the first non-empty lane, which is right for a value
    nothing can improve on. A lane is not that: the sweep can only guess from
    prose, and the inspect tier later reads the publisher's own task off the
    card. Without a way to correct it, the guess is permanent -- which is how
    four video models stayed in the image lane. #227.

    Returns whether anything changed, so a caller can say so.
    """
    from harness import lanes

    want = lanes.canonical(lane)
    if not want:
        return False
    row = conn.execute("SELECT id, lane FROM proposals WHERE name = ?",
                       (name,)).fetchone()
    if not row or lanes.canonical(row["lane"]) == want:
        return False
    conn.execute("UPDATE proposals SET lane = ? WHERE id = ?", (want, row["id"]))
    return True


#: The machine this process is running on, resolved once. The probes shell
#: out and the answer does not change while the process runs.
_THIS_MACHINE: dict | None = None


def this_machine() -> dict:
    """The identity facts a verdict needs to stay re-askable.

    IMPORTED LAZILY. evals.environment already computes exactly these for
    receipts and imports harness.memory, so a module-level import here would
    be a cycle -- and writing a second copy is how this repo collected four
    answers to "which engines exist" (RULE #237).

    The fingerprint is hw_model + os + arch rather than a hostname: a hostname
    changes without the machine changing, and an architecture stays the same
    across two rigs that measure differently. The 4070 under Linux and under
    Windows are different rigs by comparable()'s own definition -- different
    peak-memory instrument, different OCR grader -- and must not pool.
    """
    global _THIS_MACHINE
    if _THIS_MACHINE is not None:
        return _THIS_MACHINE
    try:
        from evals import environment
        from harness import inspect as _ins
        from harness import machine as _machine

        env = environment.capture()
        mach = _machine.detect()
        acc = env.get("accelerator") or {}
        got = {
            "hw_model": env.get("hw_model", ""),
            "os": env.get("os", ""),
            "arch": env.get("arch", ""),
            "memory_gb": float(env.get("memory_gb") or 0),
            "accelerator": f"{acc.get('kind', '')} "
                           f"{float(acc.get('total_gb') or 0):.0f}GB".strip(),
            "runtimes": ",".join(sorted(mach.runtimes)),
            "ceiling_gb": _ins.ceiling_bytes() / (1024 ** 3),
        }
    except Exception:  # noqa: BLE001
        # A store write must never fail because a probe did. An unknown
        # machine is recorded AS unknown rather than silently attributed to
        # whichever one wrote last, which would be worse than no column.
        got = {"hw_model": "", "os": "", "arch": "", "memory_gb": 0.0,
               "accelerator": "", "runtimes": "", "ceiling_gb": 0.0}
    got["fingerprint"] = "/".join(
        x for x in (got["hw_model"], got["os"], got["arch"]) if x) or "unknown"
    _THIS_MACHINE = got
    return got


def remember_machine(conn: sqlite3.Connection, facts: dict | None = None) -> int:
    """The id of the row for this machine, inserting or refreshing it."""
    facts = dict(facts or this_machine())
    now = time.time()
    # One statement: a SELECT-then-INSERT let two first writers collide. #422.
    conn.execute(
        "INSERT INTO machines (fingerprint, hw_model, os, arch, memory_gb, "
        "accelerator, runtimes, ceiling_gb, first_seen, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT (fingerprint) DO UPDATE SET "
        "last_seen = excluded.last_seen, runtimes = excluded.runtimes, "
        "ceiling_gb = excluded.ceiling_gb, memory_gb = excluded.memory_gb, "
        "accelerator = excluded.accelerator",
        (facts["fingerprint"], facts["hw_model"], facts["os"], facts["arch"],
         facts["memory_gb"], facts["accelerator"], facts["runtimes"],
         facts["ceiling_gb"], now, now))
    row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                       (facts["fingerprint"],)).fetchone()
    return int(row["id"])


class IllegalTransition(ValueError):
    """A write the state machine refuses. A named reopen is the way back. #409."""


#: Named reopens: kind -> the states it may reopen, None meaning any. Only
#: these move a terminal state back to a waypoint, and each records why.
RETRACTION = "retraction"
RETEST = "retest"
REOPENS: dict = {RETRACTION: None, RETEST: ("broken", "declined")}

#: A screen or measure rejection is asked again this often, this many times. #431.
RETEST_AFTER_SECONDS = 7 * 86400
RETESTS = 3
#: Tiers whose rejection can be the harness's fault; the measure step records
#: its verdict at adopt. Inspect and fetch decide facts.
RETEST_TIERS = (SCREEN, MEASURE, ADOPT)


def retest_eligible(state: str, tier: str, until: str = "") -> bool:
    """A rejection a retest may reopen; one waiting on `until` reopens through it."""
    return (state in REOPENS[RETEST] and tier in RETEST_TIERS
            and not (until or "").strip())


def _schedule_retest(conn, pid: int, row: dict, reopen: str) -> None:
    """Keep retest_count and next_retest_at in step with the state just written."""
    if reopen == RETEST:
        conn.execute("UPDATE proposals SET retest_count = retest_count + 1, "
                     "next_retest_at = NULL WHERE id = ?", (pid,))
        return
    due = None
    if retest_eligible(row["outcome"], row.get("tier", ""), row.get("until", "")):
        spent = conn.execute("SELECT retest_count FROM proposals WHERE id = ?",
                             (pid,)).fetchone()[0]
        if spent < RETESTS:
            due = float(row["decided_at"]) + RETEST_AFTER_SECONDS
    conn.execute("UPDATE proposals SET next_retest_at = ? WHERE id = ?",
                 (due, pid))


def due_retests(conn, now: float | None = None) -> list[dict]:
    """Rejections whose next retest has come due, oldest first. #431."""
    now = time.time() if now is None else now
    rows = conn.execute(
        "SELECT p.name, p.state, p.retest_count, p.next_retest_at, v.tier, "
        "v.until FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
        "WHERE p.next_retest_at IS NOT NULL AND p.next_retest_at <= ? "
        "AND p.retest_count < ? ORDER BY p.next_retest_at, p.id",
        (now, RETESTS)).fetchall()
    return [dict(r) for r in rows
            if retest_eligible(r["state"], r["tier"], r["until"])]


def reopen_due_retests(conn, now: float | None = None) -> list[str]:
    """Reopen each due retest to queued at inspect, naming the attempt. #431."""
    now = time.time() if now is None else now
    names = []
    for r in due_retests(conn, now):
        why = f"retest {r['retest_count'] + 1}/{RETESTS}: {r['state']} at {r['tier']}"
        if decide_or_skip(conn, r["name"], "queued", tier=INSPECT, at=now,
                          detail=why, reopen=RETEST, reason=why) is not None:
            names.append(r["name"])
    return names


def recovered_false_negatives(conn) -> list[dict]:
    """Candidates a screen or measure passed after a retest reopened them. #431."""
    return [dict(r) for r in conn.execute(
        "SELECT p.name, p.state, MAX(r.detail) AS attempt, "
        "MIN(w.decided_at) AS recovered_at FROM verdicts r "
        "JOIN proposals p ON p.id = r.proposal_id "
        "JOIN verdicts w ON w.proposal_id = r.proposal_id AND w.id > r.id "
        "AND w.outcome IN ('screened', 'measured') "
        "WHERE r.reopen_kind = ? GROUP BY p.id, p.name, p.state ORDER BY p.name",
        (RETEST,))]


def retest_counts(conn, now: float | None = None) -> dict:
    """Retests due now, scheduled later, spent for good, and recovered. #431."""
    now = time.time() if now is None else now
    pending = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE next_retest_at > ?",
        (now,)).fetchone()[0]
    final = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE retest_count >= ? "
        "AND next_retest_at IS NULL AND state IN (?, ?)",
        (RETESTS, *REOPENS[RETEST])).fetchone()[0]
    return {"due": len(due_retests(conn, now)), "pending": pending,
            "final": final, "recovered": len(recovered_false_negatives(conn))}


def transition_refused(state: str, held_tier: str, outcome: str,
                       tier: str, reopen: str = "") -> str:
    """Why `tier` may not move `state` to `outcome`, or '' if it may. #409."""
    if reopen:
        if reopen not in REOPENS:
            return f"{reopen!r} is not a reopen; known: {', '.join(REOPENS)}"
        allowed = REOPENS[reopen]
        if allowed is not None and state not in allowed:
            return f"a {reopen} cannot reopen {state or 'nothing'}"
        return ""
    if not state or state == "queued":
        return ""
    if state in TERMINAL and outcome in WAYPOINTS:
        return (f"{outcome} at {tier or '-'} would reopen {state} at "
                f"{held_tier or '-'}; only a named reopen does that")
    if LADDER.get(tier, 0) < LADDER.get(held_tier, 0):
        return (f"{tier or '-'} comes before {held_tier} on the ladder, so its "
                f"{outcome} cannot replace {state}")
    return ""


def fold(events) -> tuple[str, str]:
    """(state, tier) after (outcome, tier, reopen) events, refused ones skipped."""
    state, held = "", ""
    for outcome, tier, reopen in events:
        if not transition_refused(state, held, outcome, tier, reopen):
            state, held = outcome, tier
    return state, held


def _held(conn, pid: int):
    return conn.execute(
        "SELECT p.state, p.state_verdict_id AS id, v.tier, v.outcome, v.detail, "
        "v.score, v.run_path FROM proposals p LEFT JOIN verdicts v "
        "ON v.id = p.state_verdict_id WHERE p.id = ?", (pid,)).fetchone()


def _write(conn, pid: int, name: str, row: dict, reopen: str = "",
           reason: str = "") -> int:
    """Insert one verdict and move the proposal's state, or refuse. #409."""
    if reopen and not reason.strip():
        raise IllegalTransition(f"{name}: a {reopen} must say why")
    for _ in range(8):
        held = _held(conn, pid)
        # A deterministic tier restating its state is not a second fact (#184);
        # compared with the state row, so a retraction is never undone (#225).
        if (held["id"] and not reopen and row.get("score") is None
                and not row.get("run_path")
                and held["tier"] == row["tier"]
                and held["outcome"] == row["outcome"]
                and held["detail"] == row["detail"] and held["score"] is None
                and not held["run_path"]):
            return held["id"]
        why = transition_refused(held["state"], held["tier"] or "",
                                 row["outcome"], row["tier"], reopen)
        if why:
            raise IllegalTransition(f"{name}: {why}")
        cols = {**row, "proposal_id": pid}
        if reopen:
            cols.update(reopens=held["id"], reopen_kind=reopen)
        vid = conn.execute(
            f"INSERT INTO verdicts ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            tuple(cols.values())).lastrowid
        moved = conn.execute(
            "UPDATE proposals SET state = ?, state_verdict_id = ? "
            "WHERE id = ? AND COALESCE(state_verdict_id, 0) = ?",
            (row["outcome"], vid, pid, held["id"] or 0)).rowcount
        if moved == 1:
            _schedule_retest(conn, pid, row, reopen)
            return vid
        # Another writer moved the state first; re-check against theirs.
        conn.execute("DELETE FROM verdicts WHERE id = ?", (vid,))
    raise RuntimeError(f"{name}: the state kept moving under this write")


def _migration_retraction(conn, pid: int, name: str, outcome: str, tier: str,
                          detail: str, until: str = "") -> int:
    """A migration's retraction, in whatever columns this schema has yet."""
    row = {"outcome": outcome, "tier": tier, "detail": detail,
           "decided_at": time.time()}
    if "machine_id" in _columns(conn, "verdicts"):
        row["machine_id"] = remember_machine(conn)
    if until:
        row["until"] = until
    return _write(conn, pid, name, row, reopen=RETRACTION, reason=detail)


def retract(conn, name: str, why: str, *, outcome: str = "queued",
            tier: str = INSPECT, until: str = "") -> int:
    """Reopen or reclassify a decided name, saying why. #409."""
    detail = why if why.startswith("retracted:") else f"retracted: {why}"
    return decide(conn, name, outcome, tier=tier, until=until, detail=detail,
                  reopen=RETRACTION, reason=why)


def decide_or_skip(conn, name: str, outcome: str, **kw) -> int | None:
    """decide() for a tier loop: a refused move says so and returns None."""
    try:
        return decide(conn, name, outcome, **kw)
    except IllegalTransition as exc:
        print(f"  skipped {exc}", flush=True)
        return None


def state_audit(conn) -> dict:
    """Proposals whose history the transition table would fold differently,
    and those once terminal and now open, for a person to decide. #409."""
    events: dict = {}
    once_terminal = set()
    for r in conn.execute(
            "SELECT proposal_id, outcome, tier, reopen_kind, detail "
            "FROM verdicts WHERE proposal_id IS NOT NULL ORDER BY id"):
        # Before #409 a retraction was only its prose.
        kind = r["reopen_kind"] or (
            RETRACTION if str(r["detail"] or "").startswith("retracted:") else "")
        events.setdefault(r["proposal_id"], []).append(
            (r["outcome"], r["tier"] or "", kind))
        if r["outcome"] in TERMINAL:
            once_terminal.add(r["proposal_id"])
    differs, reopened = [], []
    for p in conn.execute("SELECT id, name, state FROM proposals ORDER BY id"):
        folded, _ = fold(events.get(p["id"], []))
        if folded != p["state"]:
            differs.append({"name": p["name"], "state": p["state"],
                            "folded": folded})
        if p["id"] in once_terminal and p["state"] not in TERMINAL:
            reopened.append({"name": p["name"], "state": p["state"]})
    return {"folds_differently": differs, "terminal_then_open": reopened}


def decide(conn: sqlite3.Connection, name: str, outcome: str, *, tier: str = "",
           detail: str = "", issue: int | None = None, run_path: str = "",
           score: float | None = None, rubric: str = "", judge: str = "",
           at: float | None = None, until: str = "",
           size_bytes: int = 0, attaches_to: str = "",
           upstream_idle_days: float = 0.0,
           candidate_id: int | None = None, reopen: str = "",
           reason: str = "") -> int:
    """Record what happened to a proposal, and move its state.

    The single write path for a verdict and for proposals.state. A move
    transition_refused() names raises IllegalTransition; a named `reopen`
    (a kind in REOPENS) with its `reason` is the only way back from a
    terminal state. #409.

    THE MACHINE IS RECORDED HERE AND NOWHERE ELSE. Issue #266.

    `until` is what would make this verdict worth asking again, as a
    PREDICATE rather than a sentence. See until_met().
    """
    if outcome not in VERDICTS:
        raise ValueError(f"unknown outcome {outcome!r}; "
                         f"known: {', '.join(VERDICTS)}")
    if not until and outcome in TERMINAL:
        until = until_for(detail)
    # A RUN PATH THAT IS NOT A PATH IS NOT EVIDENCE. #266.
    if run_path and not (Path(run_path).is_absolute() or "/" in run_path
                         or "\\" in run_path):
        raise ValueError(
            f"run_path {run_path!r} is not a path. It names the run whose "
            f"receipt backs this verdict, and a verdict whose evidence cannot "
            f"be found again cannot be re-judged.")
    row = conn.execute("SELECT id FROM proposals WHERE name = ?",
                       (name,)).fetchone()
    if not row and not (candidate_id and not name):
        raise KeyError(f"no proposal named {name!r}")
    pid = row["id"] if row else None
    if pid is None and score is None and not run_path:
        # A candidate no proposal names has no state to compare with. #184.
        same = conn.execute(
            "SELECT id, tier, outcome, detail, score, run_path FROM verdicts "
            "WHERE candidate_id = ? ORDER BY id DESC LIMIT 1",
            (candidate_id,)).fetchone()
        if (same and same["tier"] == tier and same["outcome"] == outcome
                and same["detail"] == detail and same["score"] is None
                and not same["run_path"]):
            return same["id"]
    fields = {"outcome": outcome, "tier": tier, "detail": detail,
              "issue": issue, "run_path": run_path, "score": score,
              "rubric": rubric, "judge": judge,
              "decided_at": time.time() if at is None else at,
              # Unknown is recorded as unknown, never omitted. #266.
              "machine_id": remember_machine(conn), "until": until,
              "size_bytes": int(size_bytes or 0), "attaches_to": attaches_to,
              "upstream_idle_days": float(upstream_idle_days or 0.0),
              "candidate_id": candidate_id}
    if pid is None:
        cols = {**fields, "proposal_id": None}
        vid = conn.execute(
            f"INSERT INTO verdicts ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            tuple(cols.values())).lastrowid
    else:
        vid = _write(conn, pid, name, fields, reopen=reopen, reason=reason)
    conn.commit()
    return vid


def link(conn: sqlite3.Connection, src: str, dst: str, relation: str,
         note: str = "") -> None:
    """An edge between two proposals. Both must already exist."""
    ids = {}
    for n in (src, dst):
        row = conn.execute("SELECT id FROM proposals WHERE name = ?",
                           (n,)).fetchone()
        if not row:
            raise KeyError(f"no proposal named {n!r}")
        ids[n] = row["id"]
    conn.execute("INSERT OR IGNORE INTO edges (src, dst, relation, note) "
                 "VALUES (?,?,?,?)", (ids[src], ids[dst], relation, note))
    conn.commit()


def settled(conn: sqlite3.Connection) -> set[str]:
    """Names in a terminal state, which must not be proposed again. #409."""
    q = (f"SELECT name FROM proposals WHERE state IN "
         f"({','.join('?' * len(TERMINAL))})")
    return {r["name"] for r in conn.execute(q, TERMINAL)}


def pending(conn, limit: int = 50, registry: str | None = None,
            screened: bool = True) -> list[str]:
    """Proposals nothing has answered yet, most-corroborated first.

    THE MISSING RUNG. The sweep writes proposals and every later tier read a
    different source -- inspect went to the crowd, so 233 swept proposals sat in
    the store with nothing consuming them. The ladder in #148 is sweep ->
    inspect -> judge -> screen -> measure, and without this the first arrow
    does not exist.

    Ordered by how many independent sightings a name has, because that is the
    project's own answer to a feed measuring popularity: a thing that keeps
    coming back is a different signal from a thing that trended once. Ties
    break on recency so a fresh proposal is not stuck behind an old one.

    A terminal verdict removes a name for good; `queued` and `screened` do not,
    because those are waypoints rather than answers.

    `registry` narrows to names one registry can answer for, and a caller that
    resolves names SHOULD pass it: the tier that clones from GitHub asked
    GitHub about HuggingFace model ids and 227 of 235 came back 404 (#167).

    None means every registry INCLUDING the unknown ones, which is right for a
    report and wrong for resolving. The EMPTY STRING asks for the unknown ones
    on their own -- names the store cannot route, which is work waiting on one
    question rather than work nobody can do.
    """
    where = "" if registry is None else "AND p.registry = ?"
    # Inspect must not re-answer a screened candidate: its `queued` sent it
    # back through the screen every loop. #393.
    stop = TERMINAL + (() if screened else ("screened",))
    args = (() if registry is None else (registry,)) + stop + (limit,)
    q = f"""
        SELECT p.name, COUNT(s.id) AS times, MAX(s.seen_at) AS last_seen
        FROM proposals p JOIN sightings s ON s.proposal_id = p.id
        WHERE p.resolved <> '' {where}
          AND p.state NOT IN ({','.join('?' * len(stop))})
        GROUP BY p.id
        ORDER BY times DESC, last_seen DESC
        LIMIT ?
    """
    return [r["name"] for r in conn.execute(q, args)]


def latest(conn, name: str) -> dict | None:
    """A name's state and the tier that set it, or None. #409."""
    row = conn.execute(
        "SELECT p.state AS outcome, v.tier FROM proposals p JOIN verdicts v "
        "ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone()
    return dict(row) if row else None


def set_registry(conn, name: str, registry: str) -> None:
    """Record which registry answered for a name, once something has asked.

    The migration fills what the store already proves and stops there, so a
    name that arrived as prose keeps an empty registry: the sweep resolved it
    against a registry and did not write down which one. This is how that
    answer gets back in -- found by asking, not by guessing from the shape of
    the string.
    """
    if registry not in REGISTRIES:
        raise ValueError(f"{registry!r} is not one of {', '.join(REGISTRIES)}")
    conn.execute("UPDATE proposals SET registry = ? WHERE name = ?",
                 (registry, name))
    conn.commit()


def survivors(conn, limit: int = 10) -> list[dict]:
    """Candidates whose LATEST verdict is a passed screen, newest first.

    The latest verdict, not any verdict: a candidate that screened green and
    was later measured and declined must not be handed to the measure tier
    again every time the loop runs.
    """
    rows = conn.execute("""
        SELECT p.name, p.lane, v.detail
        FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id
        WHERE p.state = 'screened' AND v.tier = ?
        ORDER BY v.id DESC LIMIT ?
    """, (SCREEN, limit)).fetchall()
    return [dict(r) for r in rows]


def by_registry(conn) -> dict[str, int]:
    """How many unanswered proposals each registry owns, "" being the ones
    nothing can resolve. Reported rather than hidden: a name with no registry
    is work nobody can do, and it should be visible as that rather than as a
    404 from whichever tier guessed."""
    out = {}
    for r in conn.execute(
            "SELECT p.registry AS registry, COUNT(*) AS n FROM proposals p "
            "WHERE p.resolved <> '' AND p.state NOT IN "
            f"({','.join('?' * len(TERMINAL))}) GROUP BY p.registry", TERMINAL):
        out[r["registry"]] = r["n"]
    return out


def judgeable(conn, limit: int = 50) -> list[dict]:
    """What the inspect tier queued and no judge has scored, best-corroborated
    first, with everything judge.describe() is shown.

    THE SAME MISSING RUNG ONE TIER ALONG. _judge_fits() scores the Fit objects
    sitting in memory from the inspect run that produced them, so a judge can
    only ever see candidates inspected in the same process. Everything the
    store already holds is unreachable, and after #167 that is a queue of real
    candidates with real verdicts that nothing ranks.

    A proposal already scored by a judge is not returned. Re-scoring it would
    cost a model call to learn what is already recorded, and the rubric and
    judge model are recorded beside the score, so a run under a NEW rubric is
    told apart by that rather than by scoring everything again.
    """
    q = f"""
        SELECT p.name, p.lane, p.registry, p.kind, p.description,
               COUNT(s.id) AS times, MAX(s.relevance) AS relevance,
               MAX(s.seen_at) AS last_seen,
               MIN(s.source) AS source, MIN(s.why) AS why,
               (SELECT v.detail FROM verdicts v
                 WHERE v.proposal_id = p.id AND v.tier = ?
                 ORDER BY v.id DESC LIMIT 1) AS inspected
        FROM proposals p JOIN sightings s ON s.proposal_id = p.id
        WHERE p.id IN (
            SELECT proposal_id FROM verdicts
            WHERE tier = ? AND outcome = 'queued'
        ) AND p.id NOT IN (
            SELECT proposal_id FROM verdicts WHERE tier = ?
        )
        -- AND NOBODY HAS ALREADY ANSWERED IT. A terminal verdict from ANY
        -- tier means the question is settled, and this looked only at the
        -- judge: a candidate screened `broken` came straight back round, and
        -- three of the four adopt verdicts in the real store are one model
        -- measured, declined, and measured again. #253.
        --
        -- The STATE decides, which a retraction reopens; a screened name is
        -- past the judge, which may not move it back. #409.
        AND p.state NOT IN ({','.join('?' * (len(TERMINAL) + 1))})
        GROUP BY p.id
        ORDER BY times DESC, last_seen DESC
        LIMIT ?
    """
    return [dict(r) for r in conn.execute(
        q, (INSPECT, INSPECT, JUDGE, *TERMINAL, "screened", limit))]


def judgeable_total(conn) -> int:
    """How many candidates are waiting, whatever one run's budget is. A tier
    that takes the top 25 of a backlog and says nothing about the rest reads as
    finished."""
    return len(judgeable(conn, limit=1_000_000))


def ranked(conn, limit: int = 50) -> list[dict]:
    """Everything a judge has scored, best first. What the tier is FOR."""
    q = """
        SELECT p.name, p.lane, v.score, v.rubric, v.judge, v.detail,
               v.decided_at
        FROM proposals p JOIN verdicts v ON v.proposal_id = p.id
        WHERE v.tier = ? AND v.score IS NOT NULL
        ORDER BY v.score DESC, v.id DESC
        LIMIT ?
    """
    return [dict(r) for r in conn.execute(q, (JUDGE, limit))]


def recurrence(conn: sqlite3.Connection, minimum: int = 2) -> list[dict]:
    """Proposals seen more than once, most-seen first.

    The answer to the README's own caveat that a feed measures popularity: a
    thing that keeps coming back over months is a different signal from a thing
    that trended once.
    """
    q = """
        SELECT p.name, p.kind, p.lane, p.resolved,
               COUNT(s.id) AS times, COUNT(DISTINCT s.source) AS sources,
               MIN(s.seen_at) AS first_seen, MAX(s.seen_at) AS last_seen
        FROM proposals p JOIN sightings s ON s.proposal_id = p.id
        -- COUNT repeated rather than `HAVING times >= ?`. SQLite lets HAVING
        -- see a select-list alias and standard SQL does not, so the alias
        -- version runs here and raises UndefinedColumn on Postgres. ORDER BY
        -- may use the alias in both, which is why it still does.
        GROUP BY p.id HAVING COUNT(s.id) >= ?
        ORDER BY times DESC, sources DESC, last_seen DESC
    """
    return [dict(r) for r in conn.execute(q, (minimum,))]


def precision(conn: sqlite3.Connection) -> dict:
    """How much of what the extractor proposes turns out to be worth anything.

    The number issue #49 asked for, as a query rather than a manual count.
    """
    total = conn.execute("SELECT COUNT(*) c FROM proposals").fetchone()["c"]
    resolved = conn.execute(
        "SELECT COUNT(*) c FROM proposals WHERE resolved <> ''").fetchone()["c"]
    counts = {o: 0 for o in VERDICTS}
    for r in conn.execute("SELECT outcome, COUNT(DISTINCT proposal_id) c "
                          "FROM verdicts GROUP BY outcome"):
        counts[r["outcome"]] = r["c"]
    judged = conn.execute("SELECT COUNT(DISTINCT proposal_id) c FROM verdicts "
                          "WHERE score IS NOT NULL").fetchone()["c"]
    return {"proposals": total, "resolved": resolved, "judged": judged,
            **{f"verdict_{k}": v for k, v in counts.items()}}


#: Why a name pulled out of prose did not become a proposal.
REJECTIONS = ("unresolvable", "not-a-repo", "duplicate", "already-measured",
              "below-relevance", "settled")


def reject(conn: sqlite3.Connection, name: str, source: str, reason: str,
           at: float | None = None) -> None:
    """Record a name that was extracted and thrown away.

    The thrown-away ones are the whole measurement. A store holding only what
    survived can report that 100% of proposals resolved, which is true and
    means nothing.
    """
    if reason not in REJECTIONS:
        raise ValueError(f"unknown rejection {reason!r}, known: "
                         f"{', '.join(REJECTIONS)}")
    conn.execute("INSERT OR IGNORE INTO extractions (name, source, reason, at) "
                 "VALUES (?,?,?,?)",
                 (name[:200], source, reason,
                  time.time() if at is None else at))
    conn.commit()


def extraction(conn: sqlite3.Connection) -> list[dict]:
    """Per source: how many extracted names survived, and why the rest did not.

    Issue #49 asked for extraction precision. This is the number.
    """
    kept = {r["source"]: r["n"] for r in conn.execute(
        "SELECT source, COUNT(DISTINCT proposal_id) n FROM sightings "
        "GROUP BY source")}
    out = []
    for source in sorted(set(kept) | {r["source"] for r in conn.execute(
            "SELECT DISTINCT source FROM extractions")}):
        reasons = {r["reason"]: r["n"] for r in conn.execute(
            "SELECT reason, COUNT(*) n FROM extractions WHERE source=? "
            "GROUP BY reason", (source,))}
        dropped = sum(reasons.values())
        k = kept.get(source, 0)
        out.append({"source": source, "kept": k, "dropped": dropped,
                    "extracted": k + dropped,
                    "precision": (k / (k + dropped)) if (k + dropped) else 0.0,
                    "reasons": reasons})
    return sorted(out, key=lambda r: -r["extracted"])


def parents(conn: sqlite3.Connection, name: str,
            relation: str = "needs") -> list[str]:
    """Proposals with an edge INTO `name`. Which repos named this weight."""
    return [r["name"] for r in conn.execute(
        "SELECT src.name FROM edges e JOIN proposals src ON src.id = e.src "
        "JOIN proposals dst ON dst.id = e.dst "
        "WHERE dst.name = ? AND e.relation = ?", (name, relation))]


def retire_unlisted(conn: sqlite3.Connection, name: str, keep,
                    relation: str = "needs", reason: str = "",
                    outcome: str = "ignored") -> list[str]:
    """Retire things `name` queued that it no longer ranks.

    A queue entry is a decision a ranking made at a point in time, and when the
    ranking changes every decision it made is suspect. Re-inspecting a repo used
    to only ADD, so the queue mixed picks from rules that no longer exist.

    A weight named by TWO repos is not this one's to retire: if any other parent
    still ranks it, it stays. Returns what was retired.
    """
    keep = set(keep)
    retired = []
    rows = conn.execute(
        "SELECT dst.name AS name FROM edges e JOIN proposals src ON src.id = e.src "
        "JOIN proposals dst ON dst.id = e.dst "
        "WHERE src.name = ? AND e.relation = ?", (name, relation)).fetchall()
    for row in rows:
        other = row["name"]
        if other in keep:
            continue
        cur = conn.execute("SELECT state FROM proposals WHERE name = ?",
                           (other,)).fetchone()
        if not cur or cur["state"] != "queued":
            continue
        if any(p != name for p in parents(conn, other, relation)):
            continue      # another repo still names it; not ours to retire
        # The state can move between the read above and this write.
        if decide_or_skip(conn, other, outcome, tier="inspect",
                          detail=reason[:200]) is not None:
            retired.append(other)
    return retired


def by_source(conn: sqlite3.Connection) -> list[dict]:
    """Per source: how many it proposed, how many resolved, how many settled.

    Issue #49 asked for extraction precision and it was impossible to answer
    without a store. It is a query now, and it compares sources against each
    other rather than reporting one number for all of them.
    """
    return [dict(r) for r in conn.execute("""
        SELECT s.source AS source,
               COUNT(DISTINCT s.proposal_id) AS proposals,
               COUNT(DISTINCT CASE WHEN p.resolved <> '' THEN p.id END) AS resolved,
               COUNT(DISTINCT CASE WHEN p.state IN ('measured','declined',
                     'broken','ignored') THEN p.id END) AS settled,
               COUNT(DISTINCT CASE WHEN v.outcome = 'measured' THEN p.id END)
                     AS measured
        FROM sightings s
        JOIN proposals p ON p.id = s.proposal_id
        LEFT JOIN verdicts v ON v.proposal_id = p.id
        GROUP BY s.source ORDER BY proposals DESC""")]


def traverse(conn: sqlite3.Connection, name: str, depth: int = 2,
             direction: str = "both") -> list[dict]:
    """Walk the edge graph from `name`, forwards, backwards, or both.

    Recursive CTE rather than a graph engine: at this scale the graph is joins,
    and a server would buy traversal performance nothing here needs.
    """
    if direction not in ("forward", "backward", "both"):
        raise ValueError("direction must be forward, backward or both")
    row = conn.execute("SELECT id FROM proposals WHERE name = ?",
                       (name,)).fetchone()
    if not row:
        raise KeyError(f"no proposal named {name!r}")
    step = {"forward": "e.src = w.id",
            "backward": "e.dst = w.id",
            "both": "(e.src = w.id OR e.dst = w.id)"}[direction]
    other = {"forward": "e.dst",
             "backward": "e.src",
             "both": "CASE WHEN e.src = w.id THEN e.dst ELSE e.src END"}[direction]
    q = f"""
        WITH RECURSIVE walk(id, depth, relation) AS (
            -- CAST is load-bearing, not decoration. Postgres infers the
            -- parameter's type from the non-recursive term, decides smallint,
            -- and then refuses the recursive term where the column is integer:
            -- "column 1 has type smallint in the non-recursive term but type
            -- integer overall". SQLite accepts the cast and ignores it.
            SELECT CAST(? AS INTEGER), 0, ''
            UNION
            SELECT {other}, w.depth + 1, e.relation
            FROM edges e JOIN walk w ON {step}
            WHERE w.depth < ?
        )
        SELECT p.name, p.kind, p.lane, w.depth, w.relation
        FROM walk w JOIN proposals p ON p.id = w.id
        WHERE w.depth > 0
        ORDER BY w.depth, p.name
    """
    return [dict(r) for r in conn.execute(q, (row["id"], depth))]


def composable(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Pairs whose types line up: a produces what b consumes.

    This is the pruning that makes pair search affordable. 47 proposals is 1,081
    blind pairs; most are nonsense on their face, because speech does not compose
    with an image upscaler.
    """
    q = """
        SELECT a.name AS a, b.name AS b
        FROM proposals a JOIN proposals b
          ON a.produces <> '' AND b.consumes <> ''
         AND a.produces = b.consumes AND a.id <> b.id
        ORDER BY a.name, b.name
    """
    return [(r["a"], r["b"]) for r in conn.execute(q)]


def types(conn: sqlite3.Connection, name: str, consumes: str = "",
          produces: str = "") -> None:
    """Declare what a proposal consumes and produces."""
    conn.execute("UPDATE proposals SET "
                 "consumes = CASE WHEN ?<>'' THEN ? ELSE consumes END, "
                 "produces = CASE WHEN ?<>'' THEN ? ELSE produces END "
                 "WHERE name = ?",
                 (consumes, consumes, produces, produces, name))
    conn.commit()


def export(conn: sqlite3.Connection) -> str:
    """The whole store as JSON, for a human or another tool."""
    out = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
           for t in ("proposals", "sightings", "verdicts", "edges",
                     "human_votes")}
    return json.dumps(out, indent=2)

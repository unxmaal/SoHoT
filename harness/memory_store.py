"""Durable memory for the discovery loop. Issue #52.

Without this a sweep prints and forgets, so nothing compounds: every run
re-proposes what was already declined, and the precision of the extractor cannot
be measured because there is no record of what became of anything.

Three tables. `proposals` is identity, `sightings` is the time axis, `verdicts`
is what happened. The graph is the foreign keys; traversal is a join.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
import time
from dataclasses import dataclass
from pathlib import Path

from harness import paths, store

SCHEMA_VERSION = 40

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
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    -- Written only by decide(); see transition_refused(). #409.
    state       TEXT NOT NULL DEFAULT '',
    state_verdict_id INTEGER,
    -- Retests spent on a screen/measure rejection and when the next is due;
    -- NULL beside a rejection means none is left. #431.
    retest_count INTEGER NOT NULL DEFAULT 0,
    next_retest_at REAL,
    -- Bytes a download of this candidate costs, as inspect measured it; 0 is unmeasured. #413.
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    -- Card facts, written by inspect from the registry's fields. #414.
    hf_task     TEXT NOT NULL DEFAULT '',
    library     TEXT NOT NULL DEFAULT '',
    card_tags   TEXT NOT NULL DEFAULT '[]',
    attaches_to TEXT NOT NULL DEFAULT '',
    runtime_needed TEXT NOT NULL DEFAULT '',
    -- card, tag or prose: what named the lane; '' is not recorded.
    lane_source TEXT NOT NULL DEFAULT '',
    -- 'card' read from the registry; 'description' recovered from the
    -- 300-character description by the schema 32 backfill; '' never read.
    card_read   TEXT NOT NULL DEFAULT ''
);

-- A card's base_model parents. The parent is rarely a proposal, so this is
-- not an edges row. kind: adapter, finetune, quantized, merge or ''. #414.
CREATE TABLE IF NOT EXISTS lineage (
    id          INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    parent      TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT '',
    UNIQUE (proposal_id, parent, kind)
);

CREATE TABLE IF NOT EXISTS sightings (
    id          INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    why         TEXT NOT NULL DEFAULT '',
    relevance   INTEGER NOT NULL DEFAULT 0,
    seen_at     REAL NOT NULL,
    -- The machine that recorded it, whose runtimes scored relevance; NULL is unknown. #450.
    machine_id  INTEGER REFERENCES machines(id),
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
    -- The size this verdict measured; proposals.size_bytes is what readers read. #266, #413.
    size_bytes  INTEGER NOT NULL DEFAULT 0,
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
    reopen_kind TEXT NOT NULL DEFAULT '',
    -- The stored run this verdict was read from. run_path is a download dir. #410.
    run_id      INTEGER REFERENCES runs(id),
    -- WHY, from reasons.REASONS, written by the tier that knows. #408.
    reason      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS machines (
    id           INTEGER PRIMARY KEY,
    -- hw_model/OS family/arch (machine.fingerprint): never the hostname, never
    -- the interpreter's platform string, which split one machine in two. #415.
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
    last_seen    REAL NOT NULL,
    -- json package -> installed version, from machine.versions(). #415.
    versions     TEXT NOT NULL DEFAULT '{}'
);

-- One `lh memory ramp` result; the headroom guard reads these. #299, #415.
CREATE TABLE IF NOT EXISTS memory_limits (
    id           INTEGER PRIMARY KEY,
    machine_id   INTEGER NOT NULL REFERENCES machines(id),
    measured_at  REAL NOT NULL,
    margin_gb    REAL,
    last_normal_gb REAL,
    stopped      TEXT NOT NULL DEFAULT '',
    report       TEXT NOT NULL DEFAULT '{}'
);

-- A machines row folded into another when their fingerprints became one. #415.
CREATE TABLE IF NOT EXISTS machine_merges (
    id               INTEGER PRIMARY KEY,
    from_id          INTEGER NOT NULL,
    from_fingerprint TEXT NOT NULL,
    into_id          INTEGER NOT NULL REFERENCES machines(id),
    repointed        TEXT NOT NULL DEFAULT '{}',
    merged_at        REAL NOT NULL
);

-- The work queue: one row per job any caller added. AUTOINCREMENT so a
-- cancelled id is never handed out again. #418.
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL DEFAULT '',
    -- command, image or video; MCP jobs name their artifact in output.
    kind         TEXT NOT NULL DEFAULT 'command',
    output       TEXT NOT NULL DEFAULT '',
    priority     INTEGER NOT NULL DEFAULT 0,
    argv         TEXT NOT NULL DEFAULT '[]',
    cwd          TEXT NOT NULL DEFAULT '',
    state        TEXT NOT NULL DEFAULT 'pending',
    created_at   REAL NOT NULL,
    started_at   REAL,
    finished_at  REAL,
    rc           INTEGER,
    log          TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT '',
    -- cli, mcp or migration.
    requested_by TEXT NOT NULL DEFAULT '',
    machine_id   INTEGER REFERENCES machines(id)
);

-- One eval run, written by evals.run; results.json is its export. #410.
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    -- Under the runs dir, relative to it; anywhere else, absolute.
    path         TEXT NOT NULL UNIQUE,
    lane         TEXT NOT NULL DEFAULT '',
    tier         TEXT NOT NULL DEFAULT 'measure',
    machine_id   INTEGER REFERENCES machines(id),
    -- When the receipt says it ran; NULL if it did not say. Never mtime.
    generated_at REAL,
    repeat_count INTEGER NOT NULL DEFAULT 1,
    cases_digest TEXT NOT NULL DEFAULT '',
    receipt      TEXT NOT NULL DEFAULT '{}',
    environment  TEXT NOT NULL DEFAULT '{}',
    specs        TEXT NOT NULL DEFAULT '{}',
    recorded_at  REAL NOT NULL,
    -- The queued job that ran evals.run, if one did. #418.
    job_id       INTEGER REFERENCES jobs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS results (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    candidate_id INTEGER REFERENCES candidates(id),
    -- The receipt key the runner wrote.
    candidate    TEXT NOT NULL,
    case_id      TEXT NOT NULL,
    repeat_index INTEGER NOT NULL DEFAULT 1,
    passed       INTEGER NOT NULL,
    seconds      REAL NOT NULL DEFAULT 0,
    peak_kb      INTEGER NOT NULL DEFAULT 0,
    detail       TEXT NOT NULL DEFAULT '',
    metrics      TEXT NOT NULL DEFAULT '{}',
    warnings     TEXT NOT NULL DEFAULT '[]',
    artifact     TEXT,
    -- Why it failed, set by the runner where it failed (reasons.py). #408.
    failure_class TEXT NOT NULL DEFAULT '',
    -- The harness limit it hit, as a `limit:` predicate body. #406.
    hit_limit    TEXT NOT NULL DEFAULT ''
);

-- What a lane serves from now: one row per adoption, never parsed from detail. #412.
CREATE TABLE IF NOT EXISTS adoptions (
    id           INTEGER PRIMARY KEY,
    lane         TEXT NOT NULL,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id),
    incumbent_id INTEGER REFERENCES candidates(id),
    run_id       INTEGER REFERENCES runs(id),
    verdict_id   INTEGER UNIQUE REFERENCES verdicts(id),
    -- Where it was decided; a measured adoption serves only there. #412.
    machine_id   INTEGER REFERENCES machines(id),
    -- 'measured' by the paired gates, or 'by-hand' from a person's verdicts.
    how          TEXT NOT NULL,
    adopted_at   REAL NOT NULL
);

-- Weights on disk, one row per fetched or found path on one machine. #411.
CREATE TABLE IF NOT EXISTS downloads (
    id           INTEGER PRIMARY KEY,
    proposal_id  INTEGER REFERENCES proposals(id) ON DELETE SET NULL,
    repo         TEXT NOT NULL DEFAULT '',
    -- hub: the models-- dir; gguf: the file in llama-server's models dir.
    kind         TEXT NOT NULL,
    path         TEXT NOT NULL,
    file         TEXT NOT NULL DEFAULT '',
    -- fetch, script, hub-link, scan, backfill, partial.
    origin       TEXT NOT NULL DEFAULT '',
    -- For a hub-link GGUF, the hub file it points at.
    source       TEXT NOT NULL DEFAULT '',
    bytes        INTEGER NOT NULL DEFAULT 0,
    files        INTEGER NOT NULL DEFAULT 0,
    -- Config or weights present when measured; a card alone is 0. #399.
    complete     INTEGER NOT NULL DEFAULT 0,
    -- Repos its own config names, as JSON. #196.
    requires     TEXT NOT NULL DEFAULT '[]',
    started_at   REAL,
    finished_at  REAL,
    removed_at   REAL,
    removed_by   TEXT NOT NULL DEFAULT '',
    removal_verdict_id INTEGER REFERENCES verdicts(id),
    machine_id   INTEGER REFERENCES machines(id)
);

CREATE TABLE IF NOT EXISTS edges (
    id          INTEGER PRIMARY KEY,
    src         INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    dst         INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    relation    TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    -- A crowd edge's neighbor score, as neighbors computed it; NULL elsewhere. #416.
    shared      INTEGER,
    crowd       INTEGER,
    score       REAL,
    UNIQUE (src, dst, relation)
);

-- One discovery source and when it was last read, written by feeds.read. #416.
CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    kind            TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    enabled         INTEGER NOT NULL DEFAULT 1,
    -- Last successful read; NULL is never read.
    last_read_at    REAL,
    last_attempt_at REAL,
    -- 'ok' or 'failed', of the last attempt.
    last_status     TEXT NOT NULL DEFAULT '',
    last_error      TEXT NOT NULL DEFAULT '',
    -- Consecutive failed attempts since the last success.
    failures        INTEGER NOT NULL DEFAULT 0
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
CREATE INDEX IF NOT EXISTS ix_runs_lane ON runs(lane, generated_at);
CREATE INDEX IF NOT EXISTS ix_results_run ON results(run_id);
CREATE INDEX IF NOT EXISTS ix_results_cand ON results(candidate_id);
CREATE INDEX IF NOT EXISTS ix_adoptions_lane ON adoptions(lane, adopted_at);
CREATE INDEX IF NOT EXISTS ix_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS ix_downloads_repo ON downloads(repo);
CREATE INDEX IF NOT EXISTS ix_downloads_path ON downloads(path);
CREATE INDEX IF NOT EXISTS ix_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS ix_jobs_state ON jobs(state, priority);
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
    if not path.exists():
        _guard_live(path, lambda: 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    try:
        _guard_live(path, lambda: _stored_schema(conn))
    except Exception:
        conn.close()
        raise
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


class LiveStoreRefused(RuntimeError):
    """The live store is behind this code and this code is not the deploy. #455."""


def _stored_schema(conn) -> int:
    if not conn.execute("SELECT 1 FROM sqlite_master "
                        "WHERE type='table' AND name='meta'").fetchone():
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    return int(row["value"]) if row else 0


def _guard_live(path: Path, schema) -> None:
    """Only the deploy checkout moves the live store's schema; else services refuse it."""
    if not paths.is_live(path) or os.environ.get(paths.ALLOW_MIGRATE_ENV) == "1":
        return
    have = schema()
    if have >= SCHEMA_VERSION:
        return
    deploy = paths.runs_elsewhere()
    if deploy is None:
        return
    raise LiveStoreRefused(
        f"{path} is the live store at schema {have}; this checkout "
        f"({paths.REPO}) speaks {SCHEMA_VERSION} and is not the deploy checkout "
        f"({deploy}). Migrating it would leave the deployed "
        f"services refusing a newer store. Merge to main and run "
        f"./scripts/launchd.sh install to deploy, or for a scratch run set "
        f"{paths.ENV_VAR}=<scratch dir>. {paths.ALLOW_MIGRATE_ENV}=1 overrides.")


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
        "WHERE v.run_path != '' AND v.run_id IS NULL").fetchall()
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
        # The recorded versions, the same probe load_until wrote from. #389, #415.
        have = (facts.get("versions") or {}).get(pkg)
        a, b = _version_tuple(have), _version_tuple(floor)
        return a is not None and b is not None and a > b
    if key == "limit" and ">" in want:
        # A limit this harness chose; met once the harness chooses more. #406.
        name, _, floor = want.partition(">")
        if "limits" in facts:
            have = (facts.get("limits") or {}).get(name)
        else:
            from harness import reasons
            have = reasons.limits().get(name)
        try:
            return have is not None and float(have) > float(floor)
        except ValueError:
            return False
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
    if facts is None:
        # What this machine recorded, versions included, not a second probe. #415.
        facts = recorded_facts(conn, remember_machine(conn)) or this_machine()
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

GIB = 1024 ** 3


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
    _add_reasons(conn)
    if "size_bytes" not in _columns(conn, "proposals"):
        conn.execute("ALTER TABLE proposals "
                     "ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")
    _add_card_facts(conn)
    _add_machine_versions(conn)
    _add_sighting_machine(conn)
    if "job_id" not in _columns(conn, "runs"):
        conn.execute("ALTER TABLE runs ADD COLUMN job_id "
                     "INTEGER REFERENCES jobs(id) ON DELETE SET NULL")
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
    if have < 27:
        # Before the older steps, so they read stored runs, not the dir. #410.
        if "run_id" not in _columns(conn, "verdicts"):
            conn.execute("ALTER TABLE verdicts ADD COLUMN run_id "
                         "INTEGER REFERENCES runs(id)")
        from harness import runs
        runs.backfill(conn)
    if have and have < 31:
        # Before the older steps, so have() reads rows, not the hub. #411.
        from harness import downloads
        downloads.backfill(conn)
    if have and have < 4 and "description" not in _columns(conn, "proposals"):
        conn.execute("ALTER TABLE proposals "
                     "ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    if have and have < 32:
        # Before the relane steps, which read hf_task. #414.
        backfill_card_facts(conn)
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
    if have and have < 28:
        backfill_adoptions(conn)
    if have and have < 29:
        backfill_result_classes(conn)
        backfill_reasons(conn)
        _reopen_terminal_harness_and_limit_facts(conn)
    if have and have < 30:
        backfill_sizes(conn)
    if have and have < 33:
        # After #411's backfill, so its downloads rows are repointed too.
        merge_duplicate_machines(conn)
        import_memory_limits_json(conn)
        strip_machine_from_fetch_details(conn)
    if have < 34:
        _add_edge_scores(conn)
        lift_edge_scores(conn)
        import_discovery_state_json(conn)
        import_size_cache_lanes(conn)
    if have < 35:
        # After the runs backfill, so an old job's log can name its run. #418.
        from harness import workqueue
        workqueue.import_json(conn)
    if have and have < 36:
        drop_dead_columns(conn)
    if have and have < 37:
        resolve_identity_leftovers(conn)
    if have and have < 38:
        attribute_sightings(conn)
    if have and have < 39:
        # text-classification and structured-prediction file under decide;
        # a code row whose card says so moves too. #423.
        _relane_the_laneless_from_the_card(conn)
        _relane_from_the_card(conn)
    if have and have < 40:
        _relane_the_settled_tasks(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_verdict_cand "
                 "ON verdicts(candidate_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_prop_state ON proposals(state)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_runs_job ON runs(job_id)")
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)",
                 (str(SCHEMA_VERSION),))
    conn.commit()


#: Columns nothing reads: (table, column). #419.
DEAD_COLUMNS = (("proposals", "consumes"), ("proposals", "produces"),
                ("verdicts", "issue"), ("verdicts", "attaches_to"))


def drop_dead_columns(conn) -> dict:
    """Keep what the dead columns held, then drop them. #419.

    verdicts.issue folds into detail; verdicts.attaches_to fills an empty
    proposals.attaches_to. A store whose SQLite cannot drop a column keeps it.
    """
    got = {"issue_folded": 0, "attaches_lifted": 0, "dropped": [], "kept": []}
    if "issue" in _columns(conn, "verdicts"):
        for r in conn.execute("SELECT id, detail, issue FROM verdicts "
                              "WHERE issue IS NOT NULL").fetchall():
            tag = f"#{r['issue']}"
            if tag not in (r["detail"] or ""):
                detail = f"{r['detail']} ({tag})" if r["detail"] else tag
                conn.execute("UPDATE verdicts SET detail = ? WHERE id = ?",
                             (detail, r["id"]))
            got["issue_folded"] += 1
    if "attaches_to" in _columns(conn, "verdicts"):
        got["attaches_lifted"] = conn.execute(
            "UPDATE proposals SET attaches_to = (SELECT v.attaches_to FROM "
            "verdicts v WHERE v.proposal_id = proposals.id AND v.attaches_to <> '' "
            "ORDER BY v.id DESC LIMIT 1) WHERE attaches_to = '' AND id IN "
            "(SELECT proposal_id FROM verdicts WHERE attaches_to <> '')").rowcount
    sqlite_ok = (store.backend() == store.POSTGRES
                 or sqlite3.sqlite_version_info >= (3, 35, 0))
    for table, col in DEAD_COLUMNS:
        if col not in _columns(conn, table):
            continue
        if not sqlite_ok:
            got["kept"].append(f"{table}.{col}")
            continue
        conn.execute("SAVEPOINT drop_dead")
        try:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
        except Exception:  # noqa: BLE001 - an older SQLite that cannot: keep it
            conn.execute("ROLLBACK TO drop_dead")
            got["kept"].append(f"{table}.{col}")
        else:
            got["dropped"].append(f"{table}.{col}")
        conn.execute("RELEASE drop_dead")
    return got


def _add_sighting_machine(conn) -> None:
    if "machine_id" not in _columns(conn, "sightings"):
        conn.execute("ALTER TABLE sightings ADD COLUMN machine_id "
                     "INTEGER REFERENCES machines(id)")


def attribute_sightings(conn) -> dict:
    """Schema 38: give a legacy sighting the one machine the store shows could
    have recorded it, else leave it unknown. #450.

    Evidence of a machine is a run its receipt names or its machines row; a
    machine whose earliest evidence is later than the sighting did not sweep
    it. Runs with no machine name nobody and count for nobody.
    """
    first: dict[int, float] = {}
    for sql in ("SELECT machine_id AS m, MIN(generated_at) AS t FROM runs "
                "WHERE machine_id IS NOT NULL AND generated_at IS NOT NULL "
                "GROUP BY machine_id",
                "SELECT id AS m, first_seen AS t FROM machines"):
        for r in conn.execute(sql).fetchall():
            if r["t"] is not None:
                first[r["m"]] = min(first.get(r["m"], r["t"]), r["t"])
    counts = {"assigned": 0, "unknown": 0, "by_machine": {}}
    for s in conn.execute("SELECT id, seen_at FROM sightings "
                          "WHERE machine_id IS NULL").fetchall():
        could = [m for m, t in first.items() if t <= s["seen_at"]]
        if len(could) != 1:
            counts["unknown"] += 1
            continue
        conn.execute("UPDATE sightings SET machine_id = ? WHERE id = ?",
                     (could[0], s["id"]))
        counts["assigned"] += 1
        counts["by_machine"][could[0]] = counts["by_machine"].get(could[0], 0) + 1
    conn.commit()
    return counts


def _add_machine_versions(conn) -> None:
    if "versions" not in _columns(conn, "machines"):
        conn.execute("ALTER TABLE machines "
                     "ADD COLUMN versions TEXT NOT NULL DEFAULT '{}'")


def _machine_fk_tables(conn) -> list[str]:
    """Every table with a machine_id column, so a merge misses none. #415."""
    if store.backend() == store.POSTGRES:
        names = [r["table_name"] for r in conn.execute(
            "SELECT DISTINCT table_name FROM information_schema.columns "
            "WHERE column_name = 'machine_id'")]
    else:
        names = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]
        names = [n for n in names if "machine_id" in _columns(conn, n)]
    return sorted(names)


def merge_duplicate_machines(conn) -> dict:
    """Fold machines rows whose fingerprint is now one into the oldest. #415.

    Every machine_id is repointed and each fold is a machine_merges row.
    Returns {"merged": n, "repointed": {table: rows}}.
    """
    from harness import machine as _machine
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM machines ORDER BY id").fetchall()]
    groups: dict[str, list[dict]] = {}
    for r in rows:
        fp = _machine.fingerprint(r["hw_model"], r["os"], r["arch"]) \
            if (r["hw_model"] or r["os"] or r["arch"]) else r["fingerprint"]
        groups.setdefault(fp, []).append(r)
    # A receipt that named no OS: the one machine with that board, if only one.
    for fp in [f for f, m in groups.items()
               if m[0]["hw_model"] and not _machine.os_family(m[0]["os"])]:
        hw, arch = groups[fp][0]["hw_model"], groups[fp][0]["arch"]
        homes = [f for f, m in groups.items() if f != fp
                 and m[0]["hw_model"] == hw and m[0]["arch"] == arch]
        if len(homes) == 1:
            groups[homes[0]] = sorted(groups[homes[0]] + groups.pop(fp),
                                      key=lambda r: r["id"])
    tables = _machine_fk_tables(conn)
    out: dict = {"merged": 0, "repointed": dict.fromkeys(tables, 0)}
    now = time.time()
    for fp, members in groups.items():
        keep, rest = members[0], members[1:]
        for r in rest:
            moved = {}
            for t in tables:
                n = conn.execute(f"UPDATE {t} SET machine_id = ? "
                                 f"WHERE machine_id = ?",
                                 (keep["id"], r["id"])).rowcount
                moved[t] = n
                out["repointed"][t] += n
            conn.execute(
                "INSERT INTO machine_merges (from_id, from_fingerprint, "
                "into_id, repointed, merged_at) VALUES (?,?,?,?,?)",
                (r["id"], r["fingerprint"], keep["id"],
                 json.dumps(moved, sort_keys=True), now))
            conn.execute("DELETE FROM machines WHERE id = ?", (r["id"],))
            out["merged"] += 1
        if keep["fingerprint"] != fp or rest:
            # The newest probe that said anything describes the machine now.
            recent = sorted(members, key=lambda r: (-r["last_seen"], -r["id"]))

            def latest(col, recent=recent):
                return next((r[col] for r in recent if r[col]), recent[0][col])
            conn.execute(
                "UPDATE machines SET fingerprint = ?, os = ?, first_seen = ?, "
                "last_seen = ?, memory_gb = ?, accelerator = ?, runtimes = ?, "
                "ceiling_gb = ?, versions = ? WHERE id = ?",
                (fp, latest("os"), min(r["first_seen"] for r in members),
                 recent[0]["last_seen"], latest("memory_gb"),
                 latest("accelerator"), latest("runtimes"), latest("ceiling_gb"),
                 next((r["versions"] for r in recent
                       if r.get("versions") not in (None, "", "{}")), "{}"),
                 keep["id"]))
    return out


def import_memory_limits_json(conn, path: Path | None = None) -> int:
    """memory-limits.json's ramp runs as memory_limits rows; the file is then dead. #415."""
    from harness import machine as _machine, ramp
    path = Path(path) if path is not None else paths.home() / "memory-limits.json"
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for old_fp, reports in (got.items() if isinstance(got, dict) else ()):
        parts = str(old_fp).split("/")
        fp = (_machine.fingerprint(*parts) if len(parts) == 3 else str(old_fp))
        row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                           (fp,)).fetchone()
        if row:
            mid = row["id"]
        else:
            hw, os_, arch = (parts + ["", "", ""])[:3] if len(parts) == 3 \
                else ("", "", "")
            mid = remember_machine(conn, {
                "fingerprint": fp, "hw_model": hw, "os": os_, "arch": arch})
        for report in (reports if isinstance(reports, list) else [reports]):
            if isinstance(report, dict):
                ramp.save(conn, report, mid)
                n += 1
    return n


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


def _add_reasons(conn) -> None:
    """verdicts.reason and the results' failure class, on an older store. #408."""
    for table, col in (("verdicts", "reason"), ("results", "failure_class"),
                       ("results", "hit_limit")):
        if col not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} "
                         f"TEXT NOT NULL DEFAULT ''")


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


#: The card-fact columns, on a store older than the DDL. #414.
CARD_COLUMNS = ("hf_task", "library", "card_tags", "attaches_to",
                "runtime_needed", "lane_source", "card_read")


def _add_card_facts(conn) -> None:
    for col in CARD_COLUMNS:
        if col not in _columns(conn, "proposals"):
            default = "'[]'" if col == "card_tags" else "''"
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {col} "
                         f"TEXT NOT NULL DEFAULT {default}")


def set_card(conn, name: str, card, read: str = "card") -> bool:
    """Write a card's facts and its lineage rows; False if no such proposal.

    The writer is the inspect tier, from the registry's own fields. Lineage is
    replaced, not merged: a card that dropped a parent no longer has it. #414.
    """
    from harness import lanes
    row = conn.execute("SELECT id, lane FROM proposals WHERE name = ?",
                       (name,)).fetchone()
    if not row:
        return False
    same = bool(card.lane) and lanes.canonical(row["lane"]) == \
        lanes.canonical(card.lane)
    conn.execute(
        "UPDATE proposals SET hf_task = ?, library = ?, card_tags = ?, "
        "attaches_to = ?, runtime_needed = ?, card_read = ?, "
        "lane_source = CASE WHEN ? THEN ? ELSE lane_source END WHERE id = ?",
        (card.task, card.library, json.dumps(list(card.tags)),
         card.attaches_to, card.runtime_needed, read,
         1 if same else 0, card.lane_source, row["id"]))
    conn.execute("DELETE FROM lineage WHERE proposal_id = ?", (row["id"],))
    for parent, kind in card.parents:
        conn.execute("INSERT OR IGNORE INTO lineage (proposal_id, parent, kind) "
                     "VALUES (?,?,?)", (row["id"], parent, kind))
    conn.commit()
    return True


def parents_of(conn, names) -> dict[str, list[tuple[str, str]]]:
    """name -> [(parent, kind)] from the lineage table. #414."""
    names = list(dict.fromkeys(names))
    out: dict = {n: [] for n in names}
    for i in range(0, len(names), 500):
        chunk = names[i:i + 500]
        for r in conn.execute(
                "SELECT p.name, l.parent, l.kind FROM lineage l "
                "JOIN proposals p ON p.id = l.proposal_id "
                f"WHERE p.name IN ({','.join('?' * len(chunk))}) "
                "ORDER BY l.id", chunk):
            out[r["name"]].append((r["parent"], r["kind"]))
    return out


def with_lineage(conn, rows: list[dict]) -> list[dict]:
    """Each row with `parents`: its [(parent, kind)] lineage. #414."""
    got = parents_of(conn, [r["name"] for r in rows])
    for r in rows:
        r["parents"] = got.get(r["name"], [])
    return rows


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


def backfill_adoptions(conn) -> int:
    """One adoptions row per adopt-tier `measured` verdict. #412.

    The lane is read from the detail prefix here, once; nothing reads it there
    again.
    """
    from harness import adopt, lanes
    n = 0
    for r in conn.execute(
            "SELECT v.id, v.detail, v.run_id, v.machine_id, v.decided_at, "
            "COALESCE(v.candidate_id, (SELECT MAX(c.id) FROM candidates c "
            "WHERE c.proposal_id = v.proposal_id)) AS cid FROM verdicts v "
            "WHERE v.tier = ? AND v.outcome = 'measured' AND v.id NOT IN "
            "(SELECT verdict_id FROM adoptions WHERE verdict_id IS NOT NULL) "
            "ORDER BY v.id", (ADOPT,)).fetchall():
        lane = lanes.canonical(str(r["detail"]).partition(":")[0])
        spec = conn.execute("SELECT spec FROM candidates WHERE id = ?",
                            (r["cid"],)).fetchone() if r["cid"] else None
        if not lane or not spec or adopt.is_reference(spec["spec"]):
            continue
        how = (adopt.BY_HAND if "preferred by hand" in str(r["detail"])
               else adopt.MEASURED)
        conn.execute(
            "INSERT INTO adoptions (lane, candidate_id, run_id, verdict_id, "
            "machine_id, how, adopted_at) VALUES (?,?,?,?,?,?,?)",
            (lane, r["cid"], r["run_id"], r["id"], r["machine_id"], how,
             float(r["decided_at"])))
        n += 1
    return n


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


def _add_edge_scores(conn) -> None:
    """edges.shared/crowd/score, on a store older than the DDL. #416."""
    for col, ddl in (("shared", "INTEGER"), ("crowd", "INTEGER"),
                     ("score", "REAL")):
        if col not in _columns(conn, "edges"):
            conn.execute(f"ALTER TABLE edges ADD COLUMN {col} {ddl}")


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


def record_source(conn, name: str, *, kind: str = "", url: str = "",
                  enabled: bool = True, ok: bool = True, error: str = "",
                  at: float | None = None) -> None:
    """One read of a discovery source, successful or not. #416."""
    at = time.time() if at is None else float(at)
    conn.execute(
        "INSERT INTO sources (name, kind, url, enabled) VALUES (?,?,?,?) "
        "ON CONFLICT (name) DO UPDATE SET kind = excluded.kind, "
        "url = excluded.url, enabled = excluded.enabled",
        (name, kind, url, int(bool(enabled))))
    if ok:
        conn.execute("UPDATE sources SET last_read_at = ?, last_attempt_at = ?, "
                     "last_status = 'ok', last_error = '', failures = 0 "
                     "WHERE name = ?", (at, at, name))
    else:
        conn.execute("UPDATE sources SET last_attempt_at = ?, "
                     "last_status = 'failed', last_error = ?, "
                     "failures = failures + 1 WHERE name = ?",
                     (at, error[:500], name))
    conn.commit()


def source_row(conn, name: str) -> dict | None:
    row = conn.execute("SELECT * FROM sources WHERE name = ?",
                       (name,)).fetchone()
    return dict(row) if row else None


def import_discovery_state_json(conn, path: Path | None = None) -> int:
    """Backfill sources from the retired discovery-state.json. Read-only. #416."""
    from harness import feeds
    path = (Path(path) if path is not None
            else paths.home() / "discovery-state.json")
    try:
        fetched = json.loads(path.read_text(encoding="utf-8")).get("fetched")
    except (OSError, ValueError, AttributeError):
        return 0
    known = {s.name: s for s in feeds.DEFAULT_SOURCES}
    n = 0
    for name, when in (fetched or {}).items():
        if not isinstance(when, (int, float)) or isinstance(when, bool):
            continue
        s = known.get(name)
        conn.execute(
            "INSERT INTO sources (name, kind, url, enabled) VALUES (?,?,?,?) "
            "ON CONFLICT (name) DO NOTHING",
            (name, s.kind if s else "", s.url if s else "",
             int(s.enabled) if s else 1))
        cur = conn.execute(
            "UPDATE sources SET last_read_at = ?, last_attempt_at = "
            "COALESCE(last_attempt_at, ?), last_status = CASE WHEN "
            "last_status = '' THEN 'ok' ELSE last_status END WHERE name = ? "
            "AND (last_read_at IS NULL OR last_read_at < ?)",
            (float(when), float(when), name, float(when)))
        n += cur.rowcount or 0
    return n


def import_size_cache_lanes(conn, path: Path | None = None) -> int:
    """Lanes the HF size cache carried, onto proposals that have none. #416."""
    from harness import lanes
    path = (Path(path) if path is not None
            else paths.home() / "cache" / "github" / "hf-sizes.json")
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for name, hit in (cache.items() if isinstance(cache, dict) else ()):
        lane = lanes.canonical(hit.get("lane") or "") if isinstance(hit, dict) else ""
        if lane:
            cur = conn.execute("UPDATE proposals SET lane = ? WHERE name = ? "
                               "AND lane = ''", (lane, name))
            n += cur.rowcount or 0
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
    from harness import cli, runs

    never_ran = set()
    for _, summary, rows in runs.summaries(conn, tier=""):
        for key, got in summary.items():
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
    from harness import candidates as C, screen
    from harness.serving import LLAMACPP_PREFIX

    counts = {"gguf": 0, "proposals": 0, "receipt_specs": 0,
              "receipt_keys": 0, "run_path_confirmed": 0, "fakes": 0,
              "fakes_to_proposal": 0, "fakes_unresolved": 0,
              "verdicts_linked": 0}
    fakes = {r["id"]: dict(r) for r in _adopted_by_name(conn)}
    lane_of = {r["name"]: r["lane"] for r in conn.execute(
        "SELECT name, lane FROM proposals")}
    for d in conn.execute(
            "SELECT DISTINCT repo, file FROM downloads "
            "WHERE kind = 'gguf' AND file != '' ORDER BY repo").fetchall():
        repo, filename = d["repo"], d["file"]
        if repo in lane_of and str(filename).endswith(".gguf"):
            if C.ensure(conn, f"{LLAMACPP_PREFIX}{filename[:-len('.gguf')]}",
                        proposal=repo, lane=lane_of[repo]):
                counts["gguf"] += 1
    own = {}
    rows = conn.execute(
        "SELECT DISTINCT p.id, p.name, p.lane, p.attaches_to FROM proposals p "
        "JOIN verdicts v ON v.proposal_id = p.id "
        "WHERE v.tier IN (?, ?, ?)", (SCREEN, MEASURE, ADOPT)).fetchall()
    for r in rows:
        if r["id"] in fakes or not r["lane"]:
            continue
        try:
            spec = screen.candidate_for(r["lane"], r["name"],
                                        r["attaches_to"] or "", conn=conn)
        except Exception:  # noqa: BLE001
            spec = ""
        cid = C.ensure(conn, spec, proposal=r["name"], lane=r["lane"]) \
            if spec else None
        if cid:
            own[r["id"]] = cid
            counts["proposals"] += 1
    from harness import runs as R
    if runs is not None:
        R.backfill(conn, runs)
    for run in R.find(conn):
        specs = {k: _legacy_spec(v)
                 for k, v in json.loads(run["specs"] or "{}").items()}
        for key, spec in specs.items():
            if C.key_of(spec) == key and C.ensure(conn, spec, key=key,
                                                  lane=run["lane"]):
                counts["receipt_specs"] += 1
        for key in R.keys_in(conn, run["id"]):
            if key not in specs and ":" in key and C.key_of(key) == key \
                    and C.ensure(conn, key, lane=run["lane"]):
                counts["receipt_keys"] += 1
    for r in conn.execute(
            "SELECT DISTINCT v.proposal_id, v.run_path FROM verdicts v "
            "WHERE v.run_path != '' AND v.tier IN (?, ?)", (SCREEN, MEASURE)):
        cid = own.get(r["proposal_id"])
        run = next((R.at(conn, p) for p in resolved_run_paths(r["run_path"])
                    if R.at(conn, p)), None)
        if not cid or not run:
            continue
        key = conn.execute("SELECT receipt_key FROM candidates WHERE id = ?",
                           (cid,)).fetchone()[0]
        if key in R.keys_in(conn, run["id"]):
            counts["run_path_confirmed"] += 1
    _resolve_fakes(conn, fakes, counts)
    for pid, cid in own.items():
        cur = conn.execute(
            "UPDATE verdicts SET candidate_id = ? WHERE proposal_id = ? "
            "AND candidate_id IS NULL AND tier IN (?, ?, ?)",
            (cid, pid, SCREEN, MEASURE, ADOPT))
        counts["verdicts_linked"] += cur.rowcount or 0
    conn.commit()
    return counts


def _by_download(conn, label: str, lane: str) -> str:
    """The one spec, built from a downloaded repo, whose runner writes `label`. #429."""
    from harness import candidates as C, screen
    found = set()
    for r in conn.execute("SELECT DISTINCT repo FROM downloads "
                          "WHERE repo != ''").fetchall():
        try:
            spec = screen.candidate_for(lane, r["repo"], conn=conn)
        except Exception:  # noqa: BLE001
            spec = ""
        if spec and C.key_of(spec) == label:
            found.add(spec)
    return found.pop() if len(found) == 1 else ""


def _resolve_fakes(conn, fakes: dict, counts: dict) -> None:
    """Fold each spec-named proposal into the candidate it names. #407, #429."""
    from harness import candidates as C
    for pid, fake in fakes.items():
        counts["fakes"] += 1
        label = _legacy_spec(fake["name"])
        got = C.get(conn, label)
        if got is None and ":" in label:
            C.ensure(conn, label, lane=fake["lane"])
            got = C.get(conn, label)
        if got is None and fake["lane"]:
            spec = _by_download(conn, label, fake["lane"])
            if spec and C.ensure(conn, spec, key=label, lane=fake["lane"]):
                got = C.get(conn, spec)
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


def resolve_identity_leftovers(conn) -> dict:
    """Schema 37: variants get their proposal, spec-named proposals fold. #429."""
    from harness import candidates as C
    counts = {"fakes": 0, "fakes_to_proposal": 0, "fakes_unresolved": 0}
    _resolve_fakes(conn, {r["id"]: dict(r) for r in _adopted_by_name(conn)},
                   counts)
    counts["variants_linked"] = C.link_variants(conn)
    counts["downloads_linked"] = conn.execute(
        "UPDATE downloads SET proposal_id = (SELECT MIN(p.id) FROM proposals p "
        "WHERE lower(p.name) = lower(downloads.repo)) WHERE proposal_id IS NULL "
        "AND repo != '' AND EXISTS (SELECT 1 FROM proposals p "
        "WHERE lower(p.name) = lower(downloads.repo))").rowcount or 0
    counts["unlinked_results"] = conn.execute(
        "SELECT COUNT(*) AS n FROM results WHERE candidate_id IS NULL"
    ).fetchone()["n"]
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
    #: about it. Only filled by a tier that read the registry. Prose for the
    #: judge; the facts in it are columns written by set_card(). #414.
    description: str = ""
    #: What named `lane`: card, tag or prose. #414.
    lane_source: str = ""


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
            "  lane_source = CASE WHEN lane='' AND ?<>'' THEN ? "
            "                ELSE lane_source END, "
            "  lane = CASE WHEN lane='' THEN ? ELSE lane END, "
            "  registry = CASE WHEN registry='' THEN ? ELSE registry END, "
            "  description = CASE WHEN ?<>'' THEN ? ELSE description END "
            "WHERE id = ?",
            (now, seen.resolved, seen.resolved, seen.lane, seen.lane_source,
             seen.lane, seen.registry,
             seen.description, seen.description, pid))
    else:
        pid = conn.execute(
            "INSERT INTO proposals (name, kind, registry, lane, resolved, "
            "description, lane_source, first_seen, last_seen) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (seen.name, seen.kind, seen.registry, seen.lane, seen.resolved,
             seen.description, seen.lane_source if seen.lane else "",
             now, now)).lastrowid
        # Weights downloaded before this proposal existed are now its. #429.
        conn.execute("UPDATE downloads SET proposal_id = ? WHERE "
                     "proposal_id IS NULL AND lower(repo) = ?",
                     (pid, seen.name.lower()))
    conn.execute(
        "INSERT OR IGNORE INTO sightings (proposal_id, source, url, why, "
        "relevance, seen_at, machine_id) VALUES (?,?,?,?,?,?,?)",
        (pid, seen.source, seen.url, seen.why, seen.relevance, now,
         remember_machine(conn)))
    conn.commit()
    return pid


def set_lane(conn, name: str, lane: str, source: str = "") -> bool:
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
    conn.execute("UPDATE proposals SET lane = ?, lane_source = ? WHERE id = ?",
                 (want, source, row["id"]))
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

    The fingerprint is machine.fingerprint: hw_model + OS family + arch. Not a
    hostname, which changes without the machine changing, and not the
    interpreter's platform string, which differs between two venvs on one
    machine (#415). The 4070 under Linux and under Windows are different rigs
    by comparable()'s own definition and keep different fingerprints.
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
            "versions": dict(env.get("versions") or {}),
        }
    except Exception:  # noqa: BLE001
        # A store write must never fail because a probe did. An unknown
        # machine is recorded AS unknown rather than silently attributed to
        # whichever one wrote last, which would be worse than no column.
        got = {"hw_model": "", "os": "", "arch": "", "memory_gb": 0.0,
               "accelerator": "", "runtimes": "", "ceiling_gb": 0.0,
               "versions": {}}
    from harness import machine as _machine
    got["fingerprint"] = _machine.fingerprint(got["hw_model"], got["os"],
                                              got["arch"])
    _THIS_MACHINE = got
    return got


def remember_machine(conn: sqlite3.Connection, facts: dict | None = None) -> int:
    """The id of the row for this machine, inserting or refreshing it."""
    facts = dict(facts or this_machine())
    if not facts.get("fingerprint"):
        from harness import machine as _machine
        facts["fingerprint"] = _machine.fingerprint(
            facts.get("hw_model", ""), facts.get("os", ""), facts.get("arch", ""))
    versions = {k: v for k, v in (facts.get("versions") or {}).items() if v}
    now = time.time()
    # One statement: a SELECT-then-INSERT let two first writers collide. #422.
    conn.execute(
        "INSERT INTO machines (fingerprint, hw_model, os, arch, memory_gb, "
        "accelerator, runtimes, ceiling_gb, first_seen, last_seen, versions) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (fingerprint) DO UPDATE SET "
        "last_seen = excluded.last_seen, runtimes = excluded.runtimes, "
        "ceiling_gb = excluded.ceiling_gb, memory_gb = excluded.memory_gb, "
        "accelerator = excluded.accelerator, os = excluded.os, "
        "versions = excluded.versions",
        (facts["fingerprint"], facts.get("hw_model", ""), facts.get("os", ""),
         facts.get("arch", ""), facts.get("memory_gb", 0.0),
         facts.get("accelerator", ""), facts.get("runtimes", ""),
         facts.get("ceiling_gb", 0.0), now, now,
         json.dumps(versions, sort_keys=True)))
    row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                       (facts["fingerprint"],)).fetchone()
    return int(row["id"])


def machine_row(conn, fingerprint: str | None = None) -> int | None:
    """The id stored for a fingerprint (this machine's by default), or None."""
    fp = fingerprint if fingerprint is not None else this_machine()["fingerprint"]
    row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                       (fp,)).fetchone()
    return int(row["id"]) if row else None


def recorded_facts(conn, machine_id: int) -> dict:
    """A machines row as until_met's facts, versions decoded. #415."""
    row = conn.execute("SELECT * FROM machines WHERE id = ?",
                       (machine_id,)).fetchone()
    if not row:
        return {}
    got = dict(row)
    try:
        got["versions"] = json.loads(got.get("versions") or "{}")
    except ValueError:
        got["versions"] = {}
    return got


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
                          detail=why, reopen=RETEST, reopen_why=why) is not None:
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
        "v.score, v.run_path, v.run_id FROM proposals p LEFT JOIN verdicts v "
        "ON v.id = p.state_verdict_id WHERE p.id = ?", (pid,)).fetchone()


def _write(conn, pid: int, name: str, row: dict, reopen: str = "",
           why: str = "") -> int:
    """Insert one verdict and move the proposal's state, or refuse. #409."""
    if reopen and not why.strip():
        raise IllegalTransition(f"{name}: a {reopen} must say why")
    for _ in range(8):
        held = _held(conn, pid)
        # A deterministic tier restating its state is not a second fact (#184);
        # compared with the state row, so a retraction is never undone (#225).
        if (held["id"] and not reopen and row.get("score") is None
                and not row.get("run_path") and not row.get("run_id")
                and held["tier"] == row["tier"]
                and held["outcome"] == row["outcome"]
                and held["detail"] == row["detail"] and held["score"] is None
                and not held["run_path"] and not held["run_id"]):
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
    if "reason" in _columns(conn, "verdicts"):
        row["reason"] = "reopened"
    return _write(conn, pid, name, row, reopen=RETRACTION, why=detail)


def retract(conn, name: str, why: str, *, outcome: str = "queued",
            tier: str = INSPECT, until: str = "") -> int:
    """Reopen or reclassify a decided name, saying why. #409."""
    detail = why if why.startswith("retracted:") else f"retracted: {why}"
    return decide(conn, name, outcome, tier=tier, until=until, detail=detail,
                  reopen=RETRACTION, reopen_why=why)


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
           detail: str = "", run_path: str = "",
           score: float | None = None, rubric: str = "", judge: str = "",
           at: float | None = None, until: str = "",
           size_bytes: int = 0, upstream_idle_days: float = 0.0,
           candidate_id: int | None = None, reopen: str = "",
           reopen_why: str = "", reason: str = "",
           run_id: int | None = None) -> int:
    """Record what happened to a proposal, and move its state.

    The single write path for a verdict and for proposals.state. A move
    transition_refused() names raises IllegalTransition; a named `reopen`
    (a kind in REOPENS) with its `reason` is the only way back from a
    terminal state. #409.

    THE MACHINE IS RECORDED HERE AND NOWHERE ELSE. Issue #266.

    `until` is what would make this verdict worth asking again, as a
    PREDICATE rather than a sentence, written by the caller. See until_met().
    `reason` is why, from reasons.REASONS; a named reopen is `reopened`. #408.
    """
    from harness import reasons
    if outcome not in VERDICTS:
        raise ValueError(f"unknown outcome {outcome!r}; "
                         f"known: {', '.join(VERDICTS)}")
    if reopen:
        reason = reasons.REOPENED
    if reason and reason not in reasons.REASONS:
        raise ValueError(f"unknown reason {reason!r}; "
                         f"known: {', '.join(reasons.REASONS)}")
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
    if pid is None and score is None and not run_path and not run_id:
        # A candidate no proposal names has no state to compare with. #184.
        same = conn.execute(
            "SELECT id, tier, outcome, detail, score, run_path, run_id "
            "FROM verdicts WHERE candidate_id = ? ORDER BY id DESC LIMIT 1",
            (candidate_id,)).fetchone()
        if (same and same["tier"] == tier and same["outcome"] == outcome
                and same["detail"] == detail and same["score"] is None
                and not same["run_path"] and not same["run_id"]):
            return same["id"]
    fields = {"outcome": outcome, "tier": tier, "detail": detail,
              "run_path": run_path, "score": score,
              "rubric": rubric, "judge": judge,
              "decided_at": time.time() if at is None else at,
              # Unknown is recorded as unknown, never omitted. #266.
              "machine_id": remember_machine(conn), "until": until,
              "size_bytes": int(size_bytes or 0),
              "upstream_idle_days": float(upstream_idle_days or 0.0),
              "candidate_id": candidate_id, "run_id": run_id,
              "reason": reason}
    if pid is None:
        cols = {**fields, "proposal_id": None}
        vid = conn.execute(
            f"INSERT INTO verdicts ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            tuple(cols.values())).lastrowid
    else:
        vid = _write(conn, pid, name, fields, reopen=reopen, why=reopen_why)
    conn.commit()
    return vid


def set_size(conn: sqlite3.Connection, name: str, size_bytes: int) -> bool:
    """Record what inspect measured a candidate's weights at. 0 leaves a known size alone. #413."""
    if not size_bytes or int(size_bytes) <= 0:
        return False
    cur = conn.execute("UPDATE proposals SET size_bytes = ? WHERE name = ?",
                       (int(size_bytes), name))
    conn.commit()
    return cur.rowcount > 0


def link(conn: sqlite3.Connection, src: str, dst: str, relation: str,
         note: str = "", *, shared: int | None = None,
         crowd: int | None = None, score: float | None = None) -> None:
    """An edge between two proposals. Both must already exist.

    A neighbor score is columns, refreshed on every link; never prose. #416.
    """
    ids = {}
    for n in (src, dst):
        row = conn.execute("SELECT id FROM proposals WHERE name = ?",
                           (n,)).fetchone()
        if not row:
            raise KeyError(f"no proposal named {n!r}")
        ids[n] = row["id"]
    if score is None:
        conn.execute("INSERT OR IGNORE INTO edges (src, dst, relation, note) "
                     "VALUES (?,?,?,?)", (ids[src], ids[dst], relation, note))
    else:
        conn.execute(
            "INSERT INTO edges (src, dst, relation, note, shared, crowd, score) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT (src, dst, relation) DO UPDATE "
            "SET shared = excluded.shared, crowd = excluded.crowd, "
            "score = excluded.score",
            (ids[src], ids[dst], relation, note, shared, crowd, float(score)))
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
        SELECT p.name, p.lane, p.attaches_to, v.detail
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
               p.size_bytes,
               p.hf_task, p.library, p.attaches_to, p.runtime_needed,
               COUNT(s.id) AS times,
               MAX(CASE WHEN s.machine_id = ? THEN s.relevance END) AS relevance,
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
    return with_lineage(conn, [dict(r) for r in conn.execute(
        q, (machine_row(conn), INSPECT, INSPECT, JUDGE, *TERMINAL,
            "screened", limit))])


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
                    relation: str = "needs", why: str = "",
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
                          detail=why[:200], reason="candidate") is not None:
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


def export(conn: sqlite3.Connection) -> str:
    """The whole store as JSON, for a human or another tool."""
    out = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
           for t in ("proposals", "sightings", "verdicts", "edges",
                     "human_votes")}
    return json.dumps(out, indent=2)

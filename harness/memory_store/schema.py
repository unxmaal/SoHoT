"""The store's shape: SCHEMA_VERSION, the vocabularies writers and readers share, the DDL."""
from __future__ import annotations

from harness import store


SCHEMA_VERSION = 51


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
    reason      TEXT NOT NULL DEFAULT '',
    -- reasons.UNDERPOWERED when the adopt gate could not have seen the effect. #479.
    failure_class TEXT NOT NULL DEFAULT '',
    -- The holdout assignment version and the power plan an adopt verdict used. #479.
    split_version TEXT NOT NULL DEFAULT '',
    power       TEXT NOT NULL DEFAULT '{}'
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
    job_id       INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    -- Which side of the holdout split ran (all, dev, holdout), and its version. #479.
    split        TEXT NOT NULL DEFAULT '',
    split_version TEXT NOT NULL DEFAULT ''
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
    -- The text a text runner returned; NULL when the runner made a file. #463.
    output       TEXT,
    -- The file written for the row under artifact_name; NULL if none. #463.
    artifact_path TEXT,
    -- Why it failed, set by the runner where it failed (reasons.py). #408.
    failure_class TEXT NOT NULL DEFAULT '',
    -- The harness limit it hit, as a `limit:` predicate body. #406.
    hit_limit    TEXT NOT NULL DEFAULT '',
    -- Request to first content / reasoning token; NULL where not streamed. #468.
    ttft_s       REAL,
    first_reasoning_s REAL,
    -- llama-server's own prompt processing time. #468.
    prefill_s    REAL,
    -- 1 for the first request after a load (no warm-up); NULL if the runner cannot say.
    cold         INTEGER
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
    adopted_at   REAL NOT NULL,
    -- 1 when adopted with --all-machines; otherwise it serves machine_id only. #485.
    all_machines INTEGER NOT NULL DEFAULT 0,
    -- The person's answers a by-hand adoption rests on; NULL for measured. #485.
    votes        INTEGER,
    agreement    REAL,
    forced       INTEGER NOT NULL DEFAULT 0,
    -- json median_s/peak_gb against the incumbent's, on machine_id. #485.
    cost         TEXT NOT NULL DEFAULT '{}'
);

-- Each time the gateway's sohot-<lane> alias moved to a new adoption. #483.
CREATE TABLE IF NOT EXISTS gateway_switches (
    id           INTEGER PRIMARY KEY,
    lane         TEXT NOT NULL,
    old_spec     TEXT NOT NULL,
    new_spec     TEXT NOT NULL,
    -- 'idle' after a quiet window, or 'forced' at the max wait.
    how          TEXT NOT NULL,
    requested_at REAL NOT NULL,
    switched_at  REAL NOT NULL,
    -- Requests in flight at the restart; NULL when the gateway would not say.
    in_flight    INTEGER,
    -- 'switched' once the gateway serves the new alias, else 'failed' with its reason. #522.
    outcome      TEXT NOT NULL DEFAULT 'switched',
    reason       TEXT NOT NULL DEFAULT ''
);

-- One request through the gateway, with no prompt or completion text. #481.
CREATE TABLE IF NOT EXISTS gateway_requests (
    id                INTEGER PRIMARY KEY,
    at                REAL NOT NULL,
    -- The alias asked for, and the lane when it is sohot-<lane>.
    alias             TEXT NOT NULL DEFAULT '',
    lane              TEXT NOT NULL DEFAULT '',
    -- The upstream model LiteLLM called, and the adoption the alias served.
    served            TEXT NOT NULL DEFAULT '',
    spec              TEXT NOT NULL DEFAULT '',
    -- The key alias, else the user agent's first product token.
    client            TEXT NOT NULL DEFAULT '',
    call_type         TEXT NOT NULL DEFAULT '',
    stream            INTEGER NOT NULL DEFAULT 0,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    -- Streamed requests only; NULL is not measured.
    ttft_s            REAL,
    total_s           REAL,
    tool_calls        INTEGER NOT NULL DEFAULT 0,
    -- Calls whose arguments parse to an object and that name an offered tool.
    tool_calls_valid  INTEGER NOT NULL DEFAULT 0,
    finish_reason     TEXT NOT NULL DEFAULT '',
    -- '' on success.
    error_class       TEXT NOT NULL DEFAULT '',
    error_code        TEXT NOT NULL DEFAULT ''
);

-- Text of a request, only while the usage_text setting is on, newest kept. #481.
CREATE TABLE IF NOT EXISTS gateway_samples (
    request_id  INTEGER PRIMARY KEY REFERENCES gateway_requests(id) ON DELETE CASCADE,
    prompt      TEXT NOT NULL DEFAULT '',
    completion  TEXT NOT NULL DEFAULT ''
);

-- One queued re-run of a lane's served model and what it found; never swaps a model. #480.
CREATE TABLE IF NOT EXISTS reverifications (
    id              INTEGER PRIMARY KEY,
    lane            TEXT NOT NULL,
    candidate_id    INTEGER REFERENCES candidates(id),
    spec            TEXT NOT NULL,
    -- The incumbent re-run beside it, '' when there is none.
    incumbent       TEXT NOT NULL DEFAULT '',
    -- JSON [[kind, why], ...]: versions, age or usage.
    triggers        TEXT NOT NULL DEFAULT '[]',
    job_id          INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    -- The last passing run it is compared against; NULL when it never passed here.
    baseline_run_id INTEGER REFERENCES runs(id),
    run_id          INTEGER REFERENCES runs(id),
    machine_id      INTEGER REFERENCES machines(id),
    queued_at       REAL NOT NULL,
    settled_at      REAL,
    -- '' until settled, then passed, failed, regressed or cancelled.
    outcome         TEXT NOT NULL DEFAULT '',
    -- From reasons.REASONS and reasons.CLASSES. #408.
    reason          TEXT NOT NULL DEFAULT '',
    failure_class   TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT ''
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
    machine_id   INTEGER REFERENCES machines(id),
    -- A gguf row's served context per slot; 0 is refused or not computed. #498.
    ctx          INTEGER NOT NULL DEFAULT 0,
    ctx_trained  INTEGER NOT NULL DEFAULT 0,
    kv_bytes_token INTEGER NOT NULL DEFAULT 0,
    ctx_slots    INTEGER NOT NULL DEFAULT 0,
    ctx_why      TEXT NOT NULL DEFAULT '',
    ctx_at       REAL,
    -- The KV cap and the co-resident MLX model the choice was made under. #498.
    kv_cap_bytes INTEGER NOT NULL DEFAULT 0,
    coresident_bytes INTEGER NOT NULL DEFAULT 0
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

-- One benchmark a sweep found, with the facts that decide whether to use it. #491.
CREATE TABLE IF NOT EXISTS benchmarks (
    id          INTEGER PRIMARY KEY,
    -- hf:<org/name> or gh:<org/name>.
    name        TEXT NOT NULL,
    lane        TEXT NOT NULL,
    registry    TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    license     TEXT NOT NULL DEFAULT '',
    -- '' open; 'auto' or 'manual' when the registry gates it.
    gated       TEXT NOT NULL DEFAULT '',
    created     TEXT NOT NULL DEFAULT '',
    updated     TEXT NOT NULL DEFAULT '',
    size        TEXT NOT NULL DEFAULT '',
    rows        INTEGER NOT NULL DEFAULT 0,
    task_format TEXT NOT NULL DEFAULT '',
    revision    TEXT NOT NULL DEFAULT '',
    likes       INTEGER NOT NULL DEFAULT 0,
    downloads   INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    UNIQUE (name, lane)
);

-- A candidate's training cutoff and the datasets its card says it trained on. #470.
CREATE TABLE IF NOT EXISTS candidate_training (
    id            INTEGER PRIMARY KEY,
    -- The registry repo the facts were read from.
    candidate     TEXT NOT NULL UNIQUE,
    -- The receipt key or gateway alias results carry for it.
    alias         TEXT NOT NULL DEFAULT '',
    -- The lane it is a candidate in; '' dates every lane.
    lane          TEXT NOT NULL DEFAULT '',
    -- YYYY-MM or YYYY-MM-DD; '' is unknown.
    cutoff        TEXT NOT NULL DEFAULT '',
    -- 'card' stated on the card, 'release' the registry's creation date.
    cutoff_source TEXT NOT NULL DEFAULT '',
    datasets      TEXT NOT NULL DEFAULT '[]',
    read_at       REAL NOT NULL
);

-- One prefix-completion probe of one case against one model. A miss is not absence. #470.
CREATE TABLE IF NOT EXISTS contamination_probes (
    id          INTEGER PRIMARY KEY,
    model       TEXT NOT NULL,
    lane        TEXT NOT NULL DEFAULT '',
    case_id     TEXT NOT NULL,
    family      TEXT NOT NULL DEFAULT '',
    -- 'hit', 'miss', 'skipped' or 'error'.
    outcome     TEXT NOT NULL,
    overlap     REAL,
    detail      TEXT NOT NULL DEFAULT '',
    at          REAL NOT NULL
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
CREATE INDEX IF NOT EXISTS ix_probes_model ON contamination_probes(model, lane);
"""


GIB = 1024 ** 3


def _columns(conn, table: str) -> set[str]:
    """Column names of one table, asked of whichever backend this is."""
    if store.backend() == store.POSTGRES:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?", (table,))
        return {r["column_name"] for r in rows}
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}

BEGIN TRANSACTION;
CREATE TABLE adoptions (
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
INSERT INTO "adoptions" VALUES(1,'code',1,2,1,14,1,'measured',1789039200.0);
INSERT INTO "adoptions" VALUES(2,'svg',7,NULL,NULL,21,2,'by-hand',1789824000.0);
CREATE TABLE candidates (
    id          INTEGER PRIMARY KEY,
    -- NULL for a typed default or a command-line candidate.
    proposal_id INTEGER REFERENCES proposals(id) ON DELETE SET NULL,
    spec        TEXT NOT NULL UNIQUE,
    receipt_key TEXT NOT NULL,
    lane        TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL
);
INSERT INTO "candidates" VALUES(1,1,'llamacpp:coder-7b-Q4_K_M','coder-7b','code',1788960000.0);
INSERT INTO "candidates" VALUES(2,NULL,'local-mid','local-mid','code',1788960000.0);
INSERT INTO "candidates" VALUES(3,13,'mflux:org-m/image-gen','image-gen','image',1788960000.0);
INSERT INTO "candidates" VALUES(4,6,'diffusers:org-f/screen-broke','screen-broke','image',1788960000.0);
INSERT INTO "candidates" VALUES(5,8,'mlx:org-h/tts-model','tts-model','tts',1788960000.0);
INSERT INTO "candidates" VALUES(6,NULL,'kokoro','kokoro','tts',1788960000.0);
INSERT INTO "candidates" VALUES(7,12,'mlx:org-l/svg-thing','svg-thing','svg',1788960000.0);
INSERT INTO "candidates" VALUES(8,NULL,'local-large','local-large','svg',1788960000.0);
CREATE TABLE downloads (
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
INSERT INTO "downloads" VALUES(1,1,'org-a/coder-7b-GGUF','hub','/HF/hub/models--org-a--coder-7b-GGUF/snapshots/0a1b2c3d','','backfill','',1073741824,4,1,'[]',1788643200.0,1788643200.0,NULL,'',NULL,1);
INSERT INTO "downloads" VALUES(2,8,'org-h/tts-model','hub','/HF/hub/models--org-h--tts-model/snapshots/0a1b2c3d','','backfill','',1073741824,4,1,'[]',1788643200.0,1788643200.0,NULL,'',NULL,1);
INSERT INTO "downloads" VALUES(3,7,'org-g/gguf-llama','gguf','/GGUF/gguf-llama-Q4_K_M.gguf','gguf-llama-Q4_K_M.gguf','backfill','',0,0,0,'[]',1789500000.0,1789500000.0,1789500000.0,'absent at backfill',NULL,1);
INSERT INTO "downloads" VALUES(4,6,'org-f/screen-broke','hub','/HF/hub/models--org-f--screen-broke/snapshots/0a1b2c3d','','backfill','',3221225472,0,0,'[]',NULL,NULL,1789320000.0,'lh disk',NULL,1);
CREATE TABLE edges (
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
INSERT INTO "edges" VALUES(1,1,8,'crowd','',3,12,0.25);
CREATE TABLE extractions (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL,
    reason      TEXT NOT NULL,
    at          REAL NOT NULL,
    UNIQUE (name, source, reason)
);
INSERT INTO "extractions" VALUES(1,'not-a-model','hf-trending','not-a-repo',1788618000.0);
CREATE TABLE human_votes (
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
INSERT INTO "human_votes" VALUES(1,'svg','','icon-1','local-large','svg-thing','svg-thing','left','',NULL,1789788000.0);
INSERT INTO "human_votes" VALUES(2,'svg','','icon-1','local-large','svg-thing','svg-thing','left','',NULL,1789788000.0);
INSERT INTO "human_votes" VALUES(3,'image','','cat','image-gen','screen-broke','image-gen','right','',NULL,1789788000.0);
INSERT INTO "human_votes" VALUES(4,'image','20260912-090000-0002-image','dog','image-gen','screen-broke','image-gen','left','judge-page',1,1789896000.0);
CREATE TABLE jobs (
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
INSERT INTO "jobs" VALUES(1,'soh discover','command','',0,'["soh", "discover"]','/REPO','done',1789788000.0,NULL,NULL,0,'/LOGS/0001.log','','migration',1);
INSERT INTO "jobs" VALUES(2,'tts measure','command','',5,'["uv", "run", "python", "-m", "evals.run"]','/REPO','failed',1789788000.0,NULL,NULL,1,'/LOGS/0002.log','one case failed','migration',1);
CREATE TABLE lineage (
    id          INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    parent      TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT '',
    UNIQUE (proposal_id, parent, kind)
);
INSERT INTO "lineage" VALUES(1,4,'org-z/base-xl','adapter');
CREATE TABLE machine_merges (
    id               INTEGER PRIMARY KEY,
    from_id          INTEGER NOT NULL,
    from_fingerprint TEXT NOT NULL,
    into_id          INTEGER NOT NULL REFERENCES machines(id),
    repointed        TEXT NOT NULL DEFAULT '{}',
    merged_at        REAL NOT NULL
);
INSERT INTO "machine_merges" VALUES(1,90,'Mac14,12/macOS-26.0-arm64-arm-64bit-Mach-O/arm64',1,'{"runs": 1}',1789680000.0);
INSERT INTO "machine_merges" VALUES(2,91,'Mac14,12//arm64',1,'{"runs": 1}',1789680000.0);
CREATE TABLE machines (
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
INSERT INTO "machines" VALUES(1,'Mac14,12/macOS/arm64','Mac14,12','macOS-26.0-arm64-arm-64bit','arm64',32.0,'metal 32GB','llamacpp,mlx',23.0,1788600000.0,1790040000.0,'{"mlx": "0.29.0"}');
INSERT INTO "machines" VALUES(2,'Mac17,15/macOS/arm64','Mac17,15','macOS-27.0.1-arm64-arm-64bit','arm64',64.0,'metal 32GB','llamacpp,mlx',23.0,1788610800.0,1790050800.0,'{"mlx": "0.29.0"}');
INSERT INTO "machines" VALUES(3,'B650M/Linux/x86_64','B650M','Linux-6.8.0-45-generic-x86_64-with-glibc2.39','x86_64',64.0,'cuda 12GB','cuda,llamacpp,vllm',23.0,1788614400.0,1790054400.0,'{}');
INSERT INTO "machines" VALUES(4,'B650M/Windows/AMD64','B650M','Windows-11-SP0','AMD64',64.0,'cuda 12GB','cuda,llamacpp,vllm',23.0,1788618000.0,1790058000.0,'{}');
CREATE TABLE memory_limits (
    id           INTEGER PRIMARY KEY,
    machine_id   INTEGER NOT NULL REFERENCES machines(id),
    measured_at  REAL NOT NULL,
    margin_gb    REAL,
    last_normal_gb REAL,
    stopped      TEXT NOT NULL DEFAULT '',
    report       TEXT NOT NULL DEFAULT '{}'
);
INSERT INTO "memory_limits" VALUES(1,1,1789788000.0,6.5,25.5,'floor','{"last_normal_gb": 25.5, "margin_gb": 6.5, "measured_at": "2026-09-20T10:00:00", "stopped": "floor"}');
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO "meta" VALUES('schema','41');
CREATE TABLE proposals (
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
INSERT INTO "proposals" VALUES(1,'org-a/coder-7b-GGUF','candidate','huggingface','task text-generation; served by llamacpp; tagged gguf, code','code','',1788600000.0,1789320000.0,'measured',14,0,NULL,0,'text-generation','gguf','["gguf"]','','','card','card');
INSERT INTO "proposals" VALUES(2,'org-b/huge-70b','candidate','huggingface','task text-generation','code','',1788603600.0,1789323600.0,'declined',4,0,NULL,0,'text-generation','transformers','[]','','','card','card');
INSERT INTO "proposals" VALUES(3,'org-c/old-repo','candidate','github','A training script for a vision model','','',1788607200.0,1789327200.0,'declined',5,0,NULL,0,'','','[]','','','','');
INSERT INTO "proposals" VALUES(4,'org-d/lora-x','candidate','huggingface','task text-to-image; adapter of org-z/base-xl','image','',1788610800.0,1789330800.0,'ignored',6,0,NULL,0,'text-to-image','diffusers','[]','lora','','card','card');
INSERT INTO "proposals" VALUES(5,'org-e/vllm-only','candidate','huggingface','task text-generation; served by vllm','code','',1788614400.0,1789334400.0,'declined',8,0,NULL,0,'text-generation','vllm','[]','','','card','card');
INSERT INTO "proposals" VALUES(6,'org-f/screen-broke','candidate','huggingface','task text-to-image','image','',1788618000.0,1789338000.0,'broken',16,0,NULL,0,'text-to-image','diffusers','[]','','','card','card');
INSERT INTO "proposals" VALUES(7,'org-g/gguf-llama','candidate','huggingface','task text-generation; tagged gguf','code','',1788621600.0,1789341600.0,'declined',9,0,NULL,0,'text-generation','gguf','["gguf"]','','','card','card');
INSERT INTO "proposals" VALUES(8,'org-h/tts-model','candidate','huggingface','task text-to-speech','tts','',1788625200.0,1789345200.0,'declined',20,0,1790400000.0,0,'text-to-speech','mlx','[]','','','card','card');
INSERT INTO "proposals" VALUES(9,'org-i/queued-only','candidate','huggingface','a small model','code','',1788628800.0,1789348800.0,'queued',12,0,NULL,0,'','','[]','','','','');
INSERT INTO "proposals" VALUES(10,'org-j/never-judged','candidate','github','','','',1788632400.0,1789352400.0,'',NULL,0,NULL,0,'','','[]','','','','');
INSERT INTO "proposals" VALUES(11,'org-k/harness-broke','candidate','huggingface','task text-generation','code','',1788636000.0,1789356000.0,'queued',18,0,NULL,0,'text-generation','mlx','[]','','','card','card');
INSERT INTO "proposals" VALUES(12,'org-l/svg-thing','candidate','huggingface','task text-generation; tagged svg','svg','',1788639600.0,1789359600.0,'measured',21,0,NULL,0,'text-generation','mlx','[]','','','card','card');
INSERT INTO "proposals" VALUES(13,'org-m/image-gen','candidate','huggingface','task text-to-image','image','',1788643200.0,1789363200.0,'screened',15,0,NULL,0,'text-to-image','mflux','[]','','','card','card');
CREATE TABLE results (
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
    hit_limit    TEXT NOT NULL DEFAULT ''
);
INSERT INTO "results" VALUES(1,1,0,1,'coder-7b','add',1,1,2.5,524288,'','{}','[]','def add(a, b):
    return a + b
',NULL,'','');
INSERT INTO "results" VALUES(2,1,1,1,'coder-7b','sort',1,1,2.5,524288,'','{}','[]','def add(a, b):
    return a + b
',NULL,'','');
INSERT INTO "results" VALUES(3,1,2,1,'coder-7b','parse',1,0,2.5,524288,'failed: wrong answer','{}','[]',NULL,NULL,'content_failed','');
INSERT INTO "results" VALUES(4,1,3,2,'local-mid','add',1,1,2.5,524288,'','{}','[]','def add(a, b):
    return a + b
',NULL,'','');
INSERT INTO "results" VALUES(5,1,4,2,'local-mid','sort',1,0,2.5,524288,'failed: wrong answer','{}','[]','def add(a, b):
    return a + b
',NULL,'content_failed','');
INSERT INTO "results" VALUES(6,1,5,2,'local-mid','parse',1,0,2.5,524288,'failed: wrong answer','{}','[]',NULL,NULL,'content_failed','');
INSERT INTO "results" VALUES(7,2,0,3,'image-gen','cat',1,1,2.5,524288,'','{}','[]',NULL,'/RUNS/0002-image/image-gen-cat.png','','');
INSERT INTO "results" VALUES(8,2,1,3,'image-gen','dog',1,1,2.5,524288,'','{}','[]',NULL,'/RUNS/0002-image/image-gen-dog.png','','');
INSERT INTO "results" VALUES(9,2,2,4,'screen-broke','cat',1,0,2.5,524288,'failed: wrong answer','{}','[]',NULL,NULL,'content_failed','');
INSERT INTO "results" VALUES(10,2,3,4,'screen-broke','dog',1,0,2.5,524288,'failed: wrong answer','{}','[]',NULL,NULL,'content_failed','');
INSERT INTO "results" VALUES(11,3,0,5,'tts-model','hello#1',1,1,2.5,524288,'','{}','[]',NULL,'/RUNS/0003-tts/tts-model-hello.wav','','');
INSERT INTO "results" VALUES(12,3,1,5,'tts-model','hello#2',2,0,2.5,524288,'failed: wrong answer','{}','[]',NULL,'/RUNS/0003-tts/tts-model-hello-2.wav','content_failed','');
INSERT INTO "results" VALUES(13,3,2,6,'kokoro','hello#1',1,1,2.5,524288,'','{}','[]',NULL,'/RUNS/0003-tts/kokoro-hello.wav','','');
INSERT INTO "results" VALUES(14,3,3,6,'kokoro','hello#2',2,1,2.5,524288,'','{}','[]',NULL,'/RUNS/0003-tts/kokoro-hello-2.wav','','');
CREATE TABLE runs (
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
INSERT INTO "runs" VALUES(1,'20260910-120000-0001-code','code','screen',1,1789032000.0,1,'digest-0','{"modality": "code", "tier": "screen", "cases_digest": "digest-0"}','{"hw_model": "Mac14,12", "os": "macOS-26.0-arm64-arm-64bit", "arch": "arm64"}','{"coder-7b": "llamacpp:coder-7b-Q4_K_M", "local-mid": "local-mid"}',1789032000.0,NULL);
INSERT INTO "runs" VALUES(2,'20260912-090000-0002-image','image','screen',1,1789140000.0,1,'digest-1','{"modality": "image", "tier": "screen", "cases_digest": "digest-1"}','{"hw_model": "Mac14,12", "os": "", "arch": "arm64"}','{"image-gen": "mflux:org-m/image-gen", "screen-broke": "diffusers:org-f/screen-broke"}',1789140000.0,NULL);
INSERT INTO "runs" VALUES(3,'20260920-100000-0003-tts','tts','measure',2,1789788000.0,1,'digest-2','{"modality": "tts", "tier": "measure", "cases_digest": "digest-2"}','{"hw_model": "Mac17,15", "os": "macOS-27.0.1-arm64-arm-64bit", "arch": "arm64"}','{"tts-model": "mlx:org-h/tts-model", "kokoro": "kokoro"}',1789788000.0,2);
CREATE TABLE sightings (
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
INSERT INTO "sightings" VALUES(1,1,'hf-trending','https://example.org/org-a/coder-7b-GGUF','trending this week',2,1788600000.0,1);
INSERT INTO "sightings" VALUES(2,2,'hf-trending','https://example.org/org-b/huge-70b','trending this week',2,1788603600.0,1);
INSERT INTO "sightings" VALUES(3,3,'github-search','https://example.org/org-c/old-repo','trending this week',2,1788607200.0,1);
INSERT INTO "sightings" VALUES(4,4,'hf-trending','https://example.org/org-d/lora-x','trending this week',2,1788610800.0,1);
INSERT INTO "sightings" VALUES(5,5,'hf-trending','https://example.org/org-e/vllm-only','trending this week',2,1788614400.0,1);
INSERT INTO "sightings" VALUES(6,6,'hf-trending','https://example.org/org-f/screen-broke','trending this week',2,1788618000.0,1);
INSERT INTO "sightings" VALUES(7,7,'hf-trending','https://example.org/org-g/gguf-llama','trending this week',2,1788621600.0,1);
INSERT INTO "sightings" VALUES(8,8,'hf-trending','https://example.org/org-h/tts-model','trending this week',2,1788625200.0,1);
INSERT INTO "sightings" VALUES(9,9,'hf-trending','https://example.org/org-i/queued-only','trending this week',2,1788628800.0,1);
INSERT INTO "sightings" VALUES(10,10,'github-search','https://example.org/org-j/never-judged','trending this week',2,1788632400.0,1);
INSERT INTO "sightings" VALUES(11,11,'hf-trending','https://example.org/org-k/harness-broke','trending this week',2,1788636000.0,1);
INSERT INTO "sightings" VALUES(12,12,'hf-trending','https://example.org/org-l/svg-thing','trending this week',2,1788639600.0,1);
INSERT INTO "sightings" VALUES(13,13,'hf-trending','https://example.org/org-m/image-gen','trending this week',2,1788643200.0,1);
CREATE TABLE sources (
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
INSERT INTO "sources" VALUES(1,'hf-trending','','',1,1790004000.0,1790004000.0,'ok','',0);
INSERT INTO "sources" VALUES(2,'github-search','','',1,1790007600.0,1790007600.0,'ok','',0);
CREATE TABLE verdicts (
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
INSERT INTO "verdicts" VALUES(1,1,'queued','inspect','fits: 4.4 GiB of weights under the 23.0 GiB ceiling','',NULL,'','',1788636000.0,1,4724464025,0.0,'',NULL,NULL,'',NULL,'candidate');
INSERT INTO "verdicts" VALUES(2,1,'queued','judge','judged relevant','',0.81,'relevance','local-mid',1788639600.0,1,0,0.0,'',NULL,NULL,'',NULL,'candidate');
INSERT INTO "verdicts" VALUES(3,1,'queued','fetch','downloaded','',NULL,'','',1788643200.0,1,0,0.0,'',NULL,NULL,'',NULL,'candidate');
INSERT INTO "verdicts" VALUES(4,2,'declined','inspect','too-big: 39.5 GiB of weights over the 23.0 GiB ceiling','',NULL,'','',1788646800.0,1,42412802048,0.0,'ceiling_gb:>39.5',NULL,NULL,'',NULL,'machine');
INSERT INTO "verdicts" VALUES(5,3,'declined','inspect','dead: last commit 2.9 years ago','',NULL,'','',1788650400.0,1,0,1059.0,'',NULL,NULL,'',NULL,'upstream');
INSERT INTO "verdicts" VALUES(6,4,'ignored','inspect','attaches to a model: lora in its own card','',NULL,'','',1788654000.0,1,0,0.0,'',NULL,NULL,'',NULL,'candidate');
INSERT INTO "verdicts" VALUES(7,5,'queued','inspect','fits: 14.0 GiB of weights under the 23.0 GiB ceiling','',NULL,'','',1788657600.0,1,0,0.0,'',NULL,NULL,'',NULL,'candidate');
INSERT INTO "verdicts" VALUES(8,5,'declined','fetch','needs-vllm: no vllm on this machine','',NULL,'','',1788661200.0,1,0,0.0,'runtime:vllm',NULL,NULL,'',NULL,'machine');
INSERT INTO "verdicts" VALUES(9,7,'declined','inspect','needs-llamacpp','',NULL,'','',1788664800.0,1,0,0.0,'runtime:llamacpp',NULL,NULL,'',NULL,'machine');
INSERT INTO "verdicts" VALUES(10,8,'queued','inspect','fits: 0.3 GiB of weights under the 23.0 GiB ceiling','',NULL,'','',1788668400.0,1,0,0.0,'',NULL,NULL,'',NULL,'candidate');
INSERT INTO "verdicts" VALUES(11,8,'queued','fetch','downloaded','',NULL,'','',1788672000.0,1,0,0.0,'',NULL,NULL,'',NULL,'candidate');
INSERT INTO "verdicts" VALUES(12,9,'queued','inspect','fits: 2.0 GiB of weights under the 23.0 GiB ceiling','',NULL,'','',1788675600.0,1,0,0.0,'',NULL,NULL,'',NULL,'candidate');
INSERT INTO "verdicts" VALUES(13,1,'screened','screen','passed 2/3','runs/20260910-120000-0001-code',0.67,'','',1789035600.0,1,0,0.0,'',1,NULL,'',1,'candidate');
INSERT INTO "verdicts" VALUES(14,1,'measured','adopt','code: adopted over local-mid at 0.67 vs 0.33','runs/20260910-120000-0001-code',0.67,'','',1789039200.0,1,0,0.0,'',1,NULL,'',1,'candidate');
INSERT INTO "verdicts" VALUES(15,13,'screened','screen','passed 2/2','runs/20260912-090000-0002-image',1.0,'','',1789143600.0,1,0,0.0,'',3,NULL,'',2,'candidate');
INSERT INTO "verdicts" VALUES(16,6,'broken','screen','it ran and passed nothing: 0/2','runs/20260912-090000-0002-image',0.0,'','',1789147200.0,1,0,0.0,'',4,NULL,'',2,'candidate');
INSERT INTO "verdicts" VALUES(17,11,'broken','screen','the screen exited 1: generation thread died','',NULL,'','',1789176000.0,1,0,0.0,'',NULL,NULL,'',NULL,'harness');
INSERT INTO "verdicts" VALUES(18,11,'queued','inspect','retracted: generation thread died is this harness','',NULL,'','',1789179600.0,1,0,0.0,'',NULL,17,'retraction',NULL,'reopened');
INSERT INTO "verdicts" VALUES(19,8,'screened','screen','passed 1/2','runs/20260920-100000-0003-tts',0.5,'','',1789791600.0,2,0,0.0,'',5,NULL,'',3,'candidate');
INSERT INTO "verdicts" VALUES(20,8,'declined','measure','lost to the incumbent: 0.50 vs 1.00','runs/20260920-100000-0003-tts',0.5,'','',1789795200.0,2,0,0.0,'',5,NULL,'',3,'candidate');
INSERT INTO "verdicts" VALUES(21,12,'measured','adopt','svg: preferred by hand over local-large','',NULL,'','',1789824000.0,2,0,0.0,'',7,NULL,'',NULL,'candidate');
CREATE INDEX ix_human_votes_pair
    ON human_votes(lane, case_id, left_candidate, right_candidate);
CREATE INDEX ix_sight_prop ON sightings(proposal_id);
CREATE INDEX ix_verdict_prop ON verdicts(proposal_id);
CREATE INDEX ix_cand_prop ON candidates(proposal_id);
CREATE INDEX ix_cand_key ON candidates(receipt_key);
CREATE INDEX ix_runs_lane ON runs(lane, generated_at);
CREATE INDEX ix_results_run ON results(run_id);
CREATE INDEX ix_results_cand ON results(candidate_id);
CREATE INDEX ix_adoptions_lane ON adoptions(lane, adopted_at);
CREATE INDEX ix_edges_src ON edges(src);
CREATE INDEX ix_downloads_repo ON downloads(repo);
CREATE INDEX ix_downloads_path ON downloads(path);
CREATE INDEX ix_edges_dst ON edges(dst);
CREATE INDEX ix_jobs_state ON jobs(state, priority);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('jobs',2);
COMMIT;

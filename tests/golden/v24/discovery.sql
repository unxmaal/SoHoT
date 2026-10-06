BEGIN TRANSACTION;
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
CREATE TABLE disk_removals (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL,
    repo        TEXT NOT NULL DEFAULT '',
    grp         TEXT NOT NULL,
    bytes       INTEGER NOT NULL DEFAULT 0,
    verdict_id  INTEGER,
    source      TEXT NOT NULL DEFAULT '',
    removed_at  REAL NOT NULL
);
INSERT INTO "disk_removals" VALUES(1,'/HF/hub/models--org-f--screen-broke/snapshots/0a1b2c3d','org-f/screen-broke','rejected',3221225472,NULL,'lh disk',1789320000.0);
CREATE TABLE edges (
    id          INTEGER PRIMARY KEY,
    src         INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    dst         INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    relation    TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    UNIQUE (src, dst, relation)
);
INSERT INTO "edges" VALUES(1,1,8,'crowd','3/12 at 0.25');
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
CREATE TABLE machines (
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
INSERT INTO "machines" VALUES(1,'Mac14,12/macOS-26.0-arm64-arm-64bit/arm64','Mac14,12','macOS-26.0-arm64-arm-64bit','arm64',32.0,'metal 32GB','llamacpp,mlx',23.0,1788600000.0,1790040000.0);
INSERT INTO "machines" VALUES(2,'Mac14,12/macOS-26.0-arm64-arm-64bit-Mach-O/arm64','Mac14,12','macOS-26.0-arm64-arm-64bit-Mach-O','arm64',32.0,'metal 32GB','llamacpp,mlx',23.0,1788603600.0,1790043600.0);
INSERT INTO "machines" VALUES(3,'Mac14,12//arm64','Mac14,12','','arm64',32.0,'metal 32GB','llamacpp,mlx',23.0,1788607200.0,1790047200.0);
INSERT INTO "machines" VALUES(4,'Mac17,15/macOS-27.0.1-arm64-arm-64bit/arm64','Mac17,15','macOS-27.0.1-arm64-arm-64bit','arm64',64.0,'metal 32GB','llamacpp,mlx',23.0,1788610800.0,1790050800.0);
INSERT INTO "machines" VALUES(5,'B650M/Linux-6.8.0-45-generic-x86_64-with-glibc2.39/x86_64','B650M','Linux-6.8.0-45-generic-x86_64-with-glibc2.39','x86_64',64.0,'cuda 12GB','cuda,llamacpp,vllm',23.0,1788614400.0,1790054400.0);
INSERT INTO "machines" VALUES(6,'B650M/Windows-11-SP0/AMD64','B650M','Windows-11-SP0','AMD64',64.0,'cuda 12GB','cuda,llamacpp,vllm',23.0,1788618000.0,1790058000.0);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO "meta" VALUES('schema','24');
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
    -- What it consumes and produces, so valid compositions can be found
    -- without trying every pair. Empty means unknown.
    consumes    TEXT NOT NULL DEFAULT '',
    produces    TEXT NOT NULL DEFAULT '',
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL
);
INSERT INTO "proposals" VALUES(1,'org-a/coder-7b-GGUF','candidate','huggingface','task text-generation; served by llamacpp; tagged gguf, code','code','','','',1788600000.0,1789320000.0);
INSERT INTO "proposals" VALUES(2,'org-b/huge-70b','candidate','huggingface','task text-generation','code','','','',1788603600.0,1789323600.0);
INSERT INTO "proposals" VALUES(3,'org-c/old-repo','candidate','github','A training script for a vision model','','','','',1788607200.0,1789327200.0);
INSERT INTO "proposals" VALUES(4,'org-d/lora-x','candidate','huggingface','task text-to-image; adapter of org-z/base-xl','image','','','',1788610800.0,1789330800.0);
INSERT INTO "proposals" VALUES(5,'org-e/vllm-only','candidate','huggingface','task text-generation; served by vllm','code','','','',1788614400.0,1789334400.0);
INSERT INTO "proposals" VALUES(6,'org-f/screen-broke','candidate','huggingface','task text-to-image','image','','','',1788618000.0,1789338000.0);
INSERT INTO "proposals" VALUES(7,'org-g/gguf-llama','candidate','huggingface','task text-generation; tagged gguf','code','','','',1788621600.0,1789341600.0);
INSERT INTO "proposals" VALUES(8,'org-h/tts-model','candidate','huggingface','task text-to-speech','tts','','','',1788625200.0,1789345200.0);
INSERT INTO "proposals" VALUES(9,'org-i/queued-only','candidate','huggingface','a small model','','','','',1788628800.0,1789348800.0);
INSERT INTO "proposals" VALUES(10,'org-j/never-judged','candidate','github','','','','','',1788632400.0,1789352400.0);
INSERT INTO "proposals" VALUES(11,'org-k/harness-broke','candidate','huggingface','task text-generation','code','','','',1788636000.0,1789356000.0);
INSERT INTO "proposals" VALUES(12,'org-l/svg-thing','candidate','huggingface','task text-generation; tagged svg','svg','','','',1788639600.0,1789359600.0);
INSERT INTO "proposals" VALUES(13,'org-m/image-gen','candidate','huggingface','task text-to-image','image','','','',1788643200.0,1789363200.0);
CREATE TABLE sightings (
    id          INTEGER PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    why         TEXT NOT NULL DEFAULT '',
    relevance   INTEGER NOT NULL DEFAULT 0,
    seen_at     REAL NOT NULL,
    UNIQUE (proposal_id, source, url)
);
INSERT INTO "sightings" VALUES(1,1,'hf-trending','https://example.org/org-a/coder-7b-GGUF','trending this week',2,1788600000.0);
INSERT INTO "sightings" VALUES(2,2,'hf-trending','https://example.org/org-b/huge-70b','trending this week',2,1788603600.0);
INSERT INTO "sightings" VALUES(3,3,'github-search','https://example.org/org-c/old-repo','trending this week',2,1788607200.0);
INSERT INTO "sightings" VALUES(4,4,'hf-trending','https://example.org/org-d/lora-x','trending this week',2,1788610800.0);
INSERT INTO "sightings" VALUES(5,5,'hf-trending','https://example.org/org-e/vllm-only','trending this week',2,1788614400.0);
INSERT INTO "sightings" VALUES(6,6,'hf-trending','https://example.org/org-f/screen-broke','trending this week',2,1788618000.0);
INSERT INTO "sightings" VALUES(7,7,'hf-trending','https://example.org/org-g/gguf-llama','trending this week',2,1788621600.0);
INSERT INTO "sightings" VALUES(8,8,'hf-trending','https://example.org/org-h/tts-model','trending this week',2,1788625200.0);
INSERT INTO "sightings" VALUES(9,9,'hf-trending','https://example.org/org-i/queued-only','trending this week',2,1788628800.0);
INSERT INTO "sightings" VALUES(10,10,'github-search','https://example.org/org-j/never-judged','trending this week',2,1788632400.0);
INSERT INTO "sightings" VALUES(11,11,'hf-trending','https://example.org/org-k/harness-broke','trending this week',2,1788636000.0);
INSERT INTO "sightings" VALUES(12,12,'hf-trending','https://example.org/org-l/svg-thing','trending this week',2,1788639600.0);
INSERT INTO "sightings" VALUES(13,13,'hf-trending','https://example.org/org-m/image-gen','trending this week',2,1788643200.0);
CREATE TABLE verdicts (
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
    candidate_id INTEGER REFERENCES candidates(id)
);
INSERT INTO "verdicts" VALUES(1,1,'queued','inspect','fits: 4.4 GiB of weights under the 23.0 GiB ceiling',NULL,'',NULL,'','',1788636000.0,1,4724464025,'',0.0,'',NULL);
INSERT INTO "verdicts" VALUES(2,1,'queued','judge','judged relevant',NULL,'',0.81,'relevance','local-mid',1788639600.0,1,0,'',0.0,'',NULL);
INSERT INTO "verdicts" VALUES(3,1,'queued','fetch','downloaded',NULL,'/HF/hub/models--org-a--coder-7b-GGUF/snapshots/0a1b2c3d',NULL,'','',1788643200.0,1,0,'',0.0,'',NULL);
INSERT INTO "verdicts" VALUES(4,2,'declined','inspect','too-big: 39.5 GiB of weights over the 23.0 GiB ceiling',NULL,'',NULL,'','',1788646800.0,1,42412802048,'',0.0,'ceiling_gb:>39.5',NULL);
INSERT INTO "verdicts" VALUES(5,3,'declined','inspect','dead: last commit 2.9 years ago',NULL,'',NULL,'','',1788650400.0,1,0,'',1059.0,'',NULL);
INSERT INTO "verdicts" VALUES(6,4,'ignored','inspect','attaches to a model: lora in its own card',NULL,'',NULL,'','',1788654000.0,1,0,'lora',0.0,'',NULL);
INSERT INTO "verdicts" VALUES(7,5,'queued','inspect','fits: 14.0 GiB of weights under the 23.0 GiB ceiling',NULL,'',NULL,'','',1788657600.0,1,0,'',0.0,'',NULL);
INSERT INTO "verdicts" VALUES(8,5,'declined','fetch','needs-vllm on Mac14,12/macOS-26.0-arm64-arm-64bit/arm64: no vllm on this machine',NULL,'',NULL,'','',1788661200.0,1,0,'',0.0,'runtime:vllm',NULL);
INSERT INTO "verdicts" VALUES(9,7,'declined','inspect','needs-llamacpp',NULL,'',NULL,'','',1788664800.0,1,0,'',0.0,'runtime:llamacpp',NULL);
INSERT INTO "verdicts" VALUES(10,8,'queued','inspect','fits: 0.3 GiB of weights under the 23.0 GiB ceiling',NULL,'',NULL,'','',1788668400.0,1,0,'',0.0,'',NULL);
INSERT INTO "verdicts" VALUES(11,8,'queued','fetch','downloaded',NULL,'/HF/hub/models--org-h--tts-model/snapshots/0a1b2c3d',NULL,'','',1788672000.0,1,0,'',0.0,'',NULL);
INSERT INTO "verdicts" VALUES(12,9,'queued','inspect','fits: 2.0 GiB of weights under the 23.0 GiB ceiling',NULL,'',NULL,'','',1788675600.0,1,0,'',0.0,'',NULL);
INSERT INTO "verdicts" VALUES(13,1,'screened','screen','passed 2/3',NULL,'runs/20260910-120000-0001-code',0.67,'','',1789035600.0,1,0,'',0.0,'',1);
INSERT INTO "verdicts" VALUES(14,1,'measured','adopt','code: adopted over local-mid at 0.67 vs 0.33',NULL,'runs/20260910-120000-0001-code',0.67,'','',1789039200.0,1,0,'',0.0,'',1);
INSERT INTO "verdicts" VALUES(15,13,'screened','screen','passed 2/2',NULL,'runs/20260912-090000-0002-image',1.0,'','',1789143600.0,1,0,'',0.0,'',3);
INSERT INTO "verdicts" VALUES(16,6,'broken','screen','it ran and passed nothing: 0/2',NULL,'runs/20260912-090000-0002-image',0.0,'','',1789147200.0,1,0,'',0.0,'',4);
INSERT INTO "verdicts" VALUES(17,11,'broken','screen','the screen exited 1: generation thread died',NULL,'',NULL,'','',1789176000.0,1,0,'',0.0,'',NULL);
INSERT INTO "verdicts" VALUES(18,11,'queued','inspect','retracted: generation thread died is this harness',NULL,'',NULL,'','',1789179600.0,1,0,'',0.0,'',NULL);
INSERT INTO "verdicts" VALUES(19,8,'screened','screen','passed 1/2',NULL,'runs/20260920-100000-0003-tts',0.5,'','',1789791600.0,4,0,'',0.0,'',5);
INSERT INTO "verdicts" VALUES(20,8,'declined','measure','lost to the incumbent: 0.50 vs 1.00',NULL,'runs/20260920-100000-0003-tts',0.5,'','',1789795200.0,4,0,'',0.0,'',5);
INSERT INTO "verdicts" VALUES(21,12,'measured','adopt','svg: preferred by hand over local-large',NULL,'',NULL,'','',1789824000.0,4,0,'',0.0,'',7);
CREATE INDEX ix_human_votes_pair
    ON human_votes(lane, case_id, left_candidate, right_candidate);
CREATE INDEX ix_sight_prop ON sightings(proposal_id);
CREATE INDEX ix_verdict_prop ON verdicts(proposal_id);
CREATE INDEX ix_cand_prop ON candidates(proposal_id);
CREATE INDEX ix_cand_key ON candidates(receipt_key);
CREATE INDEX ix_edges_src ON edges(src);
CREATE INDEX ix_edges_dst ON edges(dst);
COMMIT;

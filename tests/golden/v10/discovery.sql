BEGIN TRANSACTION;
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
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO "meta" VALUES('schema','10');
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
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    outcome     TEXT NOT NULL,
    tier        TEXT NOT NULL DEFAULT '',
    detail      TEXT NOT NULL DEFAULT '',
    issue       INTEGER,
    run_path    TEXT NOT NULL DEFAULT '',
    score       REAL,
    rubric      TEXT NOT NULL DEFAULT '',
    judge       TEXT NOT NULL DEFAULT '',
    decided_at  REAL NOT NULL
);
INSERT INTO "verdicts" VALUES(1,1,'queued','inspect','fits: 4.4 GiB of weights under the 23.0 GiB ceiling',NULL,'',NULL,'','',1788636000.0);
INSERT INTO "verdicts" VALUES(2,1,'queued','judge','judged relevant',NULL,'',0.81,'relevance','local-mid',1788639600.0);
INSERT INTO "verdicts" VALUES(3,1,'queued','fetch','downloaded',NULL,'/HF/hub/models--org-a--coder-7b-GGUF/snapshots/0a1b2c3d',NULL,'','',1788643200.0);
INSERT INTO "verdicts" VALUES(4,2,'declined','inspect','too-big: 39.5 GiB of weights over the 23.0 GiB ceiling',NULL,'',NULL,'','',1788646800.0);
INSERT INTO "verdicts" VALUES(5,3,'declined','inspect','dead: last commit 2.9 years ago',NULL,'',NULL,'','',1788650400.0);
INSERT INTO "verdicts" VALUES(6,4,'ignored','inspect','attaches to a model: lora in its own card',NULL,'',NULL,'','',1788654000.0);
INSERT INTO "verdicts" VALUES(7,5,'queued','inspect','fits: 14.0 GiB of weights under the 23.0 GiB ceiling',NULL,'',NULL,'','',1788657600.0);
INSERT INTO "verdicts" VALUES(8,5,'declined','fetch','needs-vllm on Mac14,12/macOS-26.0-arm64-arm-64bit/arm64: no vllm on this machine',NULL,'',NULL,'','',1788661200.0);
INSERT INTO "verdicts" VALUES(9,7,'declined','inspect','needs-llamacpp',NULL,'',NULL,'','',1788664800.0);
INSERT INTO "verdicts" VALUES(10,8,'queued','inspect','fits: 0.3 GiB of weights under the 23.0 GiB ceiling',NULL,'',NULL,'','',1788668400.0);
INSERT INTO "verdicts" VALUES(11,8,'queued','fetch','downloaded',NULL,'/HF/hub/models--org-h--tts-model/snapshots/0a1b2c3d',NULL,'','',1788672000.0);
INSERT INTO "verdicts" VALUES(12,9,'queued','inspect','fits: 2.0 GiB of weights under the 23.0 GiB ceiling',NULL,'',NULL,'','',1788675600.0);
INSERT INTO "verdicts" VALUES(13,1,'screened','screen','passed 2/3',NULL,'runs/20260910-120000-0001-code',0.67,'','',1789035600.0);
INSERT INTO "verdicts" VALUES(14,1,'measured','adopt','code: adopted over local-mid at 0.67 vs 0.33',NULL,'runs/20260910-120000-0001-code',0.67,'','',1789039200.0);
INSERT INTO "verdicts" VALUES(15,13,'screened','screen','passed 2/2',NULL,'runs/20260912-090000-0002-image',1.0,'','',1789143600.0);
INSERT INTO "verdicts" VALUES(16,6,'broken','screen','it ran and passed nothing',NULL,'',NULL,'','',1789147200.0);
INSERT INTO "verdicts" VALUES(17,6,'broken','screen','it ran and passed nothing',NULL,'',NULL,'','',1789150800.0);
INSERT INTO "verdicts" VALUES(18,11,'broken','screen','the screen exited 1: generation thread died',NULL,'',NULL,'','',1789176000.0);
INSERT INTO "verdicts" VALUES(19,8,'screened','screen','passed 1/2',NULL,'runs/20260920-100000-0003-tts',0.5,'','',1789791600.0);
INSERT INTO "verdicts" VALUES(20,8,'declined','measure','lost to the incumbent: 0.50 vs 1.00',NULL,'runs/20260920-100000-0003-tts',0.5,'','',1789795200.0);
INSERT INTO "verdicts" VALUES(21,12,'measured','adopt','svg: preferred by hand over local-large',NULL,'',NULL,'','',1789824000.0);
CREATE INDEX ix_sight_prop ON sightings(proposal_id);
CREATE INDEX ix_verdict_prop ON verdicts(proposal_id);
CREATE INDEX ix_edges_src ON edges(src);
CREATE INDEX ix_edges_dst ON edges(dst);
COMMIT;

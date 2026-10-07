"""A verdict is a fact about the machine that made it. Issue #266.

The store is shared across three machines and recorded only WHAT was decided.
A refusal is routinely a fact about one of them -- `needs-cuda` is true on an
mlx-only machine and false on one with the card, `too-big` is measured against a ceiling that
describes one 32 GB machine -- so a verdict made elsewhere read as a fact
about the model, and could not be found again when the machine changed.

56 rows in the real store carried the machine as prose inside `detail`, and
the only identifier in it was `arm64`.
"""
import re

import pytest

from harness import memory_store as ms

MAC = {"fingerprint": "Mac14,12/macOS-26.5.1/arm64", "runtimes": "cpu,mlx",
       "memory_gb": 32.0, "ceiling_gb": 22.0, "hw_model": "Mac14,12",
       "os": "macOS-26.5.1", "arch": "arm64", "accelerator": "unified 32GB"}
BOX = {"fingerprint": "MS-7D25/Linux-6.8/x86_64", "runtimes": "cpu,cuda",
       "memory_gb": 61.0, "ceiling_gb": 11.0, "hw_model": "MS-7D25",
       "os": "Linux-6.8", "arch": "x86_64", "accelerator": "discrete 12GB"}
#: The SAME box under the other operating system. `arch` cannot tell these
#: apart and comparable() already refuses to pool them: different peak-memory
#: instrument, different OCR grader.
BOX_WINDOWS = {**BOX, "os": "Windows-11", "arch": "x86_64",
               "fingerprint": "MS-7D25/Windows-11/x86_64"}


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    conn.execute("INSERT INTO proposals (name, kind, lane, resolved, "
                 "first_seen, last_seen, registry) "
                 "VALUES ('org/c','candidate','code','org/c',0,0,'huggingface')")
    yield conn
    conn.close()


def _decide_as(conn, facts, outcome, detail, until="", retract=""):
    """A verdict written as if `facts` were the machine, through the state."""
    mid = ms.remember_machine(conn, facts)
    ms._write(conn, 1, "org/c", {"outcome": outcome, "tier": "fetch",
                                 "detail": detail, "decided_at": 0,
                                 "machine_id": mid, "until": until},
              reopen=ms.RETRACTION if retract else "", why=retract)
    conn.commit()


# --- identity -------------------------------------------------------------

def test_two_operating_systems_on_one_box_are_two_machines(store):
    """`arch` was the only identifier in the old prose and says x86_64 for
    both. They measure peak memory with different instruments, so pooling
    their verdicts pools two different exams."""
    a = ms.remember_machine(store, BOX)
    b = ms.remember_machine(store, BOX_WINDOWS)
    assert a != b, "one row for two rigs the receipt layer already separates"


def test_the_same_machine_twice_is_one_row(store):
    """Or every sweep invents a machine and the table becomes a log."""
    assert ms.remember_machine(store, MAC) == ms.remember_machine(store, MAC)


def test_an_unidentifiable_machine_is_recorded_as_unknown(store, monkeypatch):
    """NOT omitted. A NULL would read as "some machine" and be pooled with
    rows that do know which one."""
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(ms, "this_machine",
                        lambda: {**MAC, "fingerprint": "unknown"})
    mid = ms.remember_machine(store)
    got = store.execute("SELECT fingerprint FROM machines WHERE id = ?",
                        (mid,)).fetchone()
    assert got["fingerprint"] == "unknown"


def test_every_verdict_records_its_machine(store):
    """decide() is the single write path, so no caller has to remember --
    and the 56 prose rows are what asking callers to remember produced."""
    ms.decide(store, "org/c", "declined", tier="fetch", detail="needs-cuda")
    row = store.execute("SELECT machine_id FROM verdicts").fetchone()
    assert row["machine_id"] is not None


# --- the condition --------------------------------------------------------

def test_a_condition_is_a_predicate_not_a_sentence():
    """The first draft stored "a machine with cuda" and re-created the exact
    defect being fixed, one level up: a machine fact only a human can read."""
    assert ms.until_met("runtime:cuda", BOX)
    assert not ms.until_met("runtime:cuda", MAC)
    assert ms.until_met("ceiling_gb:>15", MAC)
    assert not ms.until_met("ceiling_gb:>30", MAC)


def test_an_unreadable_condition_leaves_the_verdict_standing():
    """A typo must not silently re-queue everything. Not-met is the safe
    direction: the verdict stays until somebody looks."""
    assert not ms.until_met("runtimes:cuda", BOX)     # plural, wrong key
    assert not ms.until_met("ceiling_gb:<9", MAC)     # unsupported operator
    assert not ms.until_met("", MAC)


# --- the read path the columns exist for ----------------------------------

def test_a_refusal_elsewhere_reopens_where_its_reason_does_not_apply(store):
    """34 rows in the real store were declined on an mlx-only machine for wanting cuda,
    and the box with the card could not find them."""
    _decide_as(store, MAC, "declined", "needs-cuda: no runtime here",
               until="runtime:cuda")
    assert ms.revisitable(store, BOX), "the box with the card sees nothing"
    assert not ms.revisitable(store, MAC), (
        "a machine must not be told to revisit its own refusal")


def test_a_bigger_machine_reopens_only_what_it_can_hold(store):
    """144 rows are `too-big` against a ceiling describing one 32 GB machine.
    The condition carries the size the weights actually need, so a Studio
    matches the rows it can now run rather than all of them."""
    studio = {**MAC, "fingerprint": "Mac16,9/macOS/arm64", "memory_gb": 96.0,
              "ceiling_gb": 80.0}
    _decide_as(store, MAC, "declined", "too-big: 52.7 GiB",
               until="ceiling_gb:>52.7")
    assert ms.revisitable(store, studio)
    assert not ms.revisitable(store, {**studio, "ceiling_gb": 40.0}), (
        "a machine that still cannot hold these weights was told to try")


def test_only_the_latest_verdict_can_be_revisited(store):
    """A condition already retracted must not resurrect. Schema 7 exists so a
    verdict can be undone by appending, and this read has to honour that."""
    _decide_as(store, MAC, "declined", "needs-cuda", until="runtime:cuda")
    _decide_as(store, MAC, "queued", "retracted: worth another look",
               retract="worth another look")
    assert not ms.revisitable(store, BOX)


# --- the migration --------------------------------------------------------

SCHEMA_11 = """
    CREATE TABLE proposals (id INTEGER PRIMARY KEY, name TEXT,
        kind TEXT DEFAULT '', lane TEXT DEFAULT '',
        resolved TEXT DEFAULT '', consumes TEXT DEFAULT '',
        produces TEXT DEFAULT '', first_seen REAL DEFAULT 0,
        last_seen REAL DEFAULT 0, registry TEXT DEFAULT '',
        description TEXT DEFAULT '');
    CREATE TABLE verdicts (id INTEGER PRIMARY KEY, proposal_id INTEGER,
        outcome TEXT, tier TEXT DEFAULT '', detail TEXT DEFAULT '',
        issue INTEGER, run_path TEXT DEFAULT '', score REAL,
        rubric TEXT DEFAULT '', judge TEXT DEFAULT '', decided_at REAL);
"""


def test_an_old_store_is_attributed_and_says_it_was_inferred(old_store):
    """1767 rows predate the column. Only this Mac has ever written to the
    real store, so attributing them to the migrating machine is right HERE
    and would be wrong on a store that had genuinely been shared -- the
    fingerprint is recorded so a reader can see what was assumed."""
    path = old_store(11, """
        INSERT INTO proposals (id,name) VALUES (1,'org/a'),(2,'org/b');
        INSERT INTO verdicts (proposal_id,outcome,detail,decided_at)
          VALUES (1,'declined','needs-cuda on arm64: no runtime',0),
                 (2,'declined','too-big: smallest weight it names is 52.7 GiB,
                                over the 22 GiB ceiling',0);
    """, ddl=SCHEMA_11)
    conn = ms.connect(path)
    try:
        rows = {r["detail"][:8]: r["until"] for r in
                conn.execute("SELECT detail, until FROM verdicts")}
        assert rows["needs-cu"] == "runtime:cuda"
        assert rows["too-big:"] == "ceiling_gb:>52.7", rows
        unattributed = conn.execute(
            "SELECT COUNT(*) c FROM verdicts WHERE machine_id IS NULL"
        ).fetchone()["c"]
        assert unattributed == 0
    finally:
        conn.close()


# --- evidence -------------------------------------------------------------

def test_a_verdict_whose_run_is_gone_is_reported(store):
    ms.decide(store, "org/c", "measured", tier="measure",
              run_path="/nowhere/runs/gone")
    got = ms.dangling_receipts(store, exists=lambda p: False)
    assert [r["run_path"] for r in got] == ["/nowhere/runs/gone"]


def test_a_relative_run_path_is_resolved_before_it_is_called_missing(store):
    """THE FINDER'S OWN VERSION OF THE DEFECT IT FINDS. This first reported 7
    of 55 receipts gone; six were `runs/cycle-screen` and friends, relative to
    paths.home() and present. Reading them against the process cwd made a
    healthy store look half-rotten."""
    from harness import paths

    ms.decide(store, "org/c", "screened", tier="screen",
              run_path="runs/cycle-screen")
    home = str(paths.home() / "runs/cycle-screen")
    assert not ms.dangling_receipts(store, exists=lambda p: p == home), (
        "a receipt that exists under the project home was called missing")
    assert ms.dangling_receipts(store, exists=lambda p: False)


def test_a_run_path_that_is_not_a_path_is_refused(store):
    """One row in the real store holds `ok`, because a snapshot stand-in
    returned that string and the column took it. A verdict claiming evidence
    it cannot produce is worse than one claiming none."""
    with pytest.raises(ValueError, match="is not a path"):
        ms.decide(store, "org/c", "queued", tier="fetch", run_path="ok")
    ms.decide(store, "org/c", "queued", tier="fetch", run_path="runs/a")
    ms.decide(store, "org/c", "queued", tier="fetch", run_path="/abs/b")


# --- the attachment kind and the source's age -----------------------------

def test_the_attachment_kind_is_the_proposals_card_fact_not_a_verdict_column(store):
    """#268 put the word on the verdict; #414 made it a card fact inspect writes,
    and nothing read the verdict's copy. #419 dropped it."""
    assert "attaches_to" not in ms._columns(store, "verdicts")
    with pytest.raises(TypeError):
        ms.decide(store, "org/c", "declined", tier="fetch", attaches_to="lora")


def test_the_upstream_idle_time_is_a_number_not_one_decimal_of_years(store):
    """`last commit 2.9 years ago` is a number a reader acts on and no query
    can reach.

    THE NAME SAYS WHOSE. It was `stale_days` for a day and was read as the age
    of our own row -- this project is days old and the repos it refuses this
    way are years idle. A column named for a fact without its subject is the
    same defect as machine_id() answering `arm64`."""
    ms.decide(store, "org/c", "declined", tier="inspect",
              upstream_idle_days=1058.5,
              detail="dead: last commit 2.9 years ago")
    row = store.execute("SELECT upstream_idle_days FROM verdicts "
                        "ORDER BY id DESC LIMIT 1").fetchone()
    assert row["upstream_idle_days"] == pytest.approx(1058.5)


def test_a_judge_using_the_word_workflow_is_not_a_verdict_about_one(old_store):
    """THE MIGRATION'S OWN NEAR-MISS, and the reason it recovers rather than
    recomputes.

    The first cut ran screen.is_attachment over the verdict's DETAIL. The live
    code runs it over the candidate's DESCRIPTION, so 78 judge verdicts whose
    prose happens to contain "workflow", "gui" or "embedding" came back
    labelled attachments -- and "This is a composition of existing tools" is a
    judge explaining a score, not a declaration that a candidate is an adapter.
    Shipping it would have taught the fetch tier to refuse 57 real candidates.
    """
    path = old_store(13, """
        INSERT INTO proposals (id,name) VALUES (1,'org/judged'),(2,'org/lora'),
                                               (3,'org/old');
        INSERT INTO verdicts (proposal_id,outcome,tier,detail,decided_at)
          VALUES (1,'queued','judge',
                  'This is a composition of existing tools with a clean gui and a reusable workflow for embedding extraction',0),
                 (2,'declined','fetch',
                  'lora in its own card: this attaches to a model rather than being one, and no lane can run it alone',0),
                 (3,'declined','inspect','dead: last commit 2.9 years ago',0);
    """)
    conn = ms.connect(path)
    try:
        # The kind lands on the proposal when #419 drops the verdict column.
        got = {r["proposal_id"]: (r["attaches_to"], r["upstream_idle_days"])
               for r in conn.execute(
                   "SELECT v.proposal_id, p.attaches_to, v.upstream_idle_days "
                   "FROM verdicts v JOIN proposals p ON p.id = v.proposal_id")}
        assert got[1] == ("", 0.0), (
            f"a judge's prose was read as a verdict about an attachment: "
            f"{got[1]}")
        assert got[2][0] == "lora"
        assert got[3][1] == pytest.approx(2.9 * 365.0)
    finally:
        conn.close()


# --- a refusal that waits on somebody else's repository -------------------

def test_a_dead_upstream_can_be_reconsidered_when_it_commits(store):
    """A repo idle two years is refused, and that verdict is `declined`,
    which is TERMINAL. So the candidate stayed refused even after its upstream
    shipped -- and `mlx-community/Mistral-7B-Instruct-v0.3-4bit` is on that
    list, where a requantisation repo has no reason to receive commits at all.

    Every other machine-limited refusal got a condition in #266. This one was
    missed because its limit is not the machine."""
    ms.decide(store, "org/c", "declined", tier="inspect",
              upstream_idle_days=1058.5,
              until="commit_after:2023-10-22T03:10:14Z",
              detail="dead: last commit 2.9 years ago")
    fresh = {"fingerprint": "elsewhere", "last_commit": "2026-09-01T00:00:00Z"}
    assert ms.revisitable(store, fresh), "a revived upstream stays refused"
    stale = {"fingerprint": "elsewhere", "last_commit": "2023-01-01T00:00:00Z"}
    assert not ms.revisitable(store, stale), (
        "an upstream that has NOT moved was offered for reconsideration")


def test_an_unparseable_commit_date_does_not_reopen_everything():
    """Not-met is the safe direction: a registry field that is not ISO-8601
    must leave the verdict standing rather than re-queueing the corpus."""
    assert not ms.until_met("commit_after:2023-10-22T03:10:14Z",
                            {"last_commit": "last Tuesday"})
    assert not ms.until_met("commit_after:2023-10-22T03:10:14Z",
                            {"last_commit": ""})
    assert not ms.until_met("commit_after:2023-10-22T03:10:14Z", {})


def test_the_machine_conditions_still_ignore_an_upstream_fact():
    """The negative control for mixing two kinds of condition in one column.
    A machine with cuda must not satisfy a verdict waiting on a commit."""
    assert not ms.until_met("commit_after:2023-01-01T00:00:00Z",
                            {"runtimes": "cpu,cuda", "memory_gb": 61.0})
    assert not ms.until_met("runtime:cuda",
                            {"last_commit": "2026-09-01T00:00:00Z"})


def test_a_runtime_version_predicate_compares_numerically():
    from harness import memory_store as ms
    f = lambda v: {"versions": {"mlx-lm": v}}
    assert ms.until_met("version:mlx-lm>0.31.3", f("0.31.4"))
    assert not ms.until_met("version:mlx-lm>0.31.3", f("0.31.3"))
    assert ms.until_met("version:mlx-lm>0.31.9", f("0.31.10")), (
        "string comparison would call 0.31.10 older than 0.31.9")
    assert not ms.until_met("version:mlx-lm>0.31.3", f("unknown"))
    assert not ms.until_met("version:mlx-lm>0.31.3", {"versions": {}})


# --- #295: a runtime this machine gains reopens its own refusals ----------

def test_a_runtime_installed_here_reopens_this_machines_refusal(store):
    _decide_as(store, MAC, "declined", "needs-llamacpp: GGUF only",
               until="runtime:llamacpp")
    later = {**MAC, "runtimes": "cpu,llamacpp,mlx"}
    assert [r["name"] for r in ms.revisitable(store, later)] == ["org/c"]
    assert not ms.revisitable(store, MAC)


def test_a_queued_row_is_not_revisitable(store):
    """The headroom guard queues with memory_gb:> the memory free at the time,
    which total memory always meets. A queued row is already in the queue."""
    _decide_as(store, MAC, "queued", "not enough headroom",
               until="memory_gb:>6.8")
    assert not ms.revisitable(store, MAC)


def test_any_of_several_runtimes_meets_the_condition():
    assert ms.until_met("runtime:cuda|mlx", MAC)
    assert not ms.until_met("runtime:cuda|rocm", MAC)


@pytest.mark.parametrize("detail,until", [
    ("needs-llamacpp: depends on GGUF weights, and this machine has no "
     "llamacpp", "runtime:llamacpp"),
    ("needs-cuda: depends on torch, and this machine has none of cuda, rocm",
     "runtime:cuda|rocm"),
    ("too-big: smallest weight it names is 59.9 GiB, over the 22 GiB ceiling",
     "ceiling_gb:>59.9"),
    ("too-big: source tree is 259 MB, which is weights in git, not a source "
     "repo", ""),
    ("fits: weights from 5.5 to 8.9 GiB", ""),
])
def test_the_condition_is_read_from_the_refusal(detail, until):
    assert ms.until_for(detail) == until


def test_the_inspect_tier_writes_the_condition_its_refusal_names():
    """#333: the writer supplies the predicate. #408: from the Fit, not its
    sentence."""
    from harness import inspect as ins
    fit = ins.Fit(repo="org/g", verdict="needs-llamacpp", offered=["llamacpp"])
    assert ins.until_of(fit) == "runtime:llamacpp"
    assert ins.reason_of(fit) == "machine"
    big = ins.Fit(repo="org/b", verdict="too-big", smallest=int(59.9 * 1024 ** 3))
    assert ins.until_of(big) == "ceiling_gb:>59.9"
    dead = ins.Fit(repo="org/d", verdict="dead", last_commit="2023-01-01")
    assert (ins.until_of(dead), ins.reason_of(dead)) == (
        "commit_after:2023-01-01", "upstream")


def test_decide_no_longer_reads_a_condition_out_of_the_detail(store):
    """Negative control for #408: the sentence is prose, never parsed live."""
    ms.record(store, ms.Seen(name="org/g", source="t", kind="weights",
                             lane="code", why="seeded"))
    ms.decide(store, "org/g", "declined", tier=ms.INSPECT, reason="machine",
              detail="needs-llamacpp: depends on GGUF weights")
    got = store.execute("SELECT until, reason FROM verdicts ORDER BY id DESC "
                        "LIMIT 1").fetchone()
    assert tuple(got) == ("", "machine")


def test_schema_18_backfills_refusals_written_after_266(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    ms.record(conn, ms.Seen(name="org/g", source="t", kind="weights",
                            lane="code", why="seeded"))
    conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, "
                 "decided_at) SELECT id, 'declined', 'inspect', "
                 "'needs-llamacpp: GGUF', 0 FROM proposals")
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', '17')")
    conn.commit()
    conn.close()
    again = ms.connect(tmp_path / "s.db")
    try:
        assert again.execute("SELECT until FROM verdicts").fetchone()[0] == (
            "runtime:llamacpp")
    finally:
        again.close()


def _at_schema_18(tmp_path, name, lane, description, outcome, detail):
    conn = ms.connect(tmp_path / "s.db")
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights",
                            lane=lane, why="seeded"))
    conn.execute("UPDATE proposals SET description = ?", (description,))
    conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, "
                 "decided_at) SELECT id, ?, 'screen', ?, 0 FROM proposals",
                 (outcome, detail))
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', '18')")
    conn.commit()
    conn.close()
    return ms.connect(tmp_path / "s.db")


def test_schema_19_refiles_a_vlm_judge_out_of_the_image_lane(tmp_path):
    """#379: Qwen-Image-Bench, image-text-to-text, sat in the image lane."""
    again = _at_schema_18(tmp_path, "Qwen/Qwen-Image-Bench", "image",
                          "task image-text-to-text; tagged text-to-image",
                          "broken", "it ran and passed nothing")
    try:
        assert again.execute("SELECT lane FROM proposals").fetchone()[0] == "code"
        assert again.execute("SELECT outcome FROM verdicts ORDER BY id DESC"
                             ).fetchone()[0] == "queued"
    finally:
        again.close()


def test_schema_19_requeues_a_layout_diffusers_could_not_assemble(tmp_path):
    """#381."""
    again = _at_schema_18(tmp_path, "tokenaii/Horus-Lens-1.0", "image", "",
                          "broken", "it ran and passed nothing: ValueError: "
                          "expected ['vae'], but only set() were passed.")
    try:
        assert again.execute("SELECT outcome FROM verdicts ORDER BY id DESC"
                             ).fetchone()[0] == "queued"
    finally:
        again.close()


def test_schema_19_leaves_a_model_that_genuinely_failed(tmp_path):
    """Negative control."""
    again = _at_schema_18(tmp_path, "org/bad", "image", "task text-to-image",
                          "broken", "it ran and passed nothing: no fox")
    try:
        assert again.execute("SELECT outcome FROM verdicts ORDER BY id DESC"
                             ).fetchone()[0] == "broken"
    finally:
        again.close()


def test_schema_19_does_not_reopen_a_verdict_the_lane_never_touched(tmp_path):
    """#379: relaning reopened inspect's too-big verdicts on 1.4 TB models."""
    conn = ms.connect(tmp_path / "s.db")
    ms.record(conn, ms.Seen(name="moonshotai/Kimi-K3", source="t",
                            kind="weights", lane="", why="seeded"))
    conn.execute("UPDATE proposals SET description = 'task image-text-to-text'")
    conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, "
                 "decided_at) SELECT id, 'declined', 'inspect', "
                 "'too-big: 1453.8 GiB', 0 FROM proposals")
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', '18')")
    conn.commit()
    conn.close()
    again = ms.connect(tmp_path / "s.db")
    try:
        assert again.execute("SELECT lane FROM proposals").fetchone()[0] == "code"
        assert again.execute("SELECT outcome FROM verdicts ORDER BY id DESC"
                             ).fetchone()[0] == "declined"
    finally:
        again.close()


def test_schema_19_keeps_an_svg_model_in_the_svg_lane(tmp_path):
    """OmniSVG is image-text-to-text: a text task, not a reason to leave svg."""
    again = _at_schema_18(tmp_path, "OmniSVG/OmniSVG1.1_8B", "svg",
                          "task image-text-to-text; tagged svg",
                          "screened", "1 case(s) passed a screen")
    try:
        assert again.execute("SELECT lane FROM proposals").fetchone()[0] == "svg"
    finally:
        again.close()


def _at_schema_39(tmp_path, name, lane, task, tags, verdicts):
    import json
    conn = ms.connect(tmp_path / "s.db")
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights",
                            lane=lane, why="seeded"))
    conn.execute("UPDATE proposals SET hf_task = ?, card_tags = ?, "
                 "lane_source = 'card'", (task, json.dumps(tags)))
    for tier, outcome, detail in verdicts:
        conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, "
                     "detail, decided_at) SELECT id, ?, ?, ?, 0 FROM proposals",
                     (outcome, tier, detail))
    ms._backfill_state(conn)
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', '39')")
    conn.commit()
    conn.close()
    return ms.connect(tmp_path / "s.db")


def _lane_and_last(conn):
    lane = conn.execute("SELECT lane FROM proposals").fetchone()[0]
    last = conn.execute("SELECT outcome FROM verdicts ORDER BY id DESC"
                        ).fetchone()[0]
    return lane, last


@pytest.mark.parametrize("name,lane,task,tags,want", [
    ("m-a-p/YuE2-3B", "tts", "text-to-audio", ["music-generation"], "music"),
    ("OpenMOSS-Team/MOSS-SoundEffect-v2.0", "tts", "text-to-audio",
     ["sound-effects"], ""),
    # Emptied by schema 40 (#387), then filed under ocr by schema 53 (#562).
    ("PaddlePaddle/PaddleOCR-VL-1.6", "code", "image-text-to-text",
     ["PaddleOCR", "ocr"], "ocr"),
    ("JustANormalTinkerer/hayai-ocr-v2", "code", "image-to-text", ["ocr"], "ocr"),
    ("Boogu/Boogu-Image-0.1-Edit", "image", "image-to-image",
     ["image-to-image"], ""),
    ("oumoumad/ltx-2.3-dearchive-lora", "video", "video-to-video", [], ""),
])
def test_schema_40_moves_a_settled_task_and_reopens_its_screen(
        tmp_path, name, lane, task, tags, want):
    """#387: a screen in a lane whose cases the task cannot take is no verdict."""
    again = _at_schema_39(tmp_path, name, lane, task, tags,
                          [("screen", "broken", "it ran and passed nothing")])
    try:
        assert _lane_and_last(again) == (want, "queued")
    finally:
        again.close()


@pytest.mark.parametrize("name,lane,task,tags", [
    ("Marvis-AI/marvis-tts-250m-v0.2-MLX-8bit", "tts", "text-to-audio",
     ["mlx-audio"]),
    ("black-forest-labs/FLUX.2-klein-9B", "image", "image-to-image",
     ["image-editing", "image-generation"]),
    ("Qwen/Qwen3.5-4B", "code", "image-text-to-text", ["vision-language"]),
    ("OmniSVG/OmniSVG1.1_8B", "svg", "image-text-to-text", ["svg", "process-ocr"]),
    ("a/text-to-image", "image", "text-to-image", ["ocr"]),
])
def test_schema_40_leaves_a_row_its_card_agrees_with(tmp_path, name, lane, task, tags):
    """Negative control for #387."""
    again = _at_schema_39(tmp_path, name, lane, task, tags,
                          [("screen", "broken", "it ran and passed nothing")])
    try:
        assert _lane_and_last(again) == (lane, "broken")
    finally:
        again.close()


@pytest.mark.parametrize("tier,detail", [
    ("inspect", "too-big: weights 129.5 GiB over the 22 GiB ceiling"),
    ("fetch", "lora in its own card: this attaches to a model rather than "
              "being one")])
def test_schema_40_keeps_a_verdict_no_lane_reached(tmp_path, tier, detail):
    """#387 under #383's scope: moved, and a lane-free verdict stays."""
    again = _at_schema_39(tmp_path, "drbaph/Viggle-Animate-ComfyUI", "video",
                          "video-to-video", ["video-generation"],
                          [("screen", "broken", "it ran and passed nothing"),
                           (tier, "declined", detail)])
    try:
        assert _lane_and_last(again) == ("", "declined")
    finally:
        again.close()


def _at_schema_51(tmp_path, rows):
    """rows: (name, lane, task, tags, parents, verdict outcome)."""
    import json
    conn = ms.connect(tmp_path / "s.db")
    for name, lane, task, tags, parents, outcome in rows:
        ms.record(conn, ms.Seen(name=name, source="t", kind="weights",
                                lane=lane, why="seeded"))
        conn.execute("UPDATE proposals SET hf_task = ?, card_tags = ? "
                     "WHERE name = ?", (task, json.dumps(tags), name))
        for parent in parents:
            conn.execute("INSERT INTO lineage (proposal_id, parent, kind) "
                         "SELECT id, ?, 'quantized' FROM proposals WHERE name = ?",
                         (parent, name))
        conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, "
                     "decided_at) SELECT id, ?, 'inspect', 'seeded', 0 "
                     "FROM proposals WHERE name = ?", (outcome, name))
    ms._backfill_state(conn)
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', '51')")
    conn.commit()
    conn.close()
    return ms.connect(tmp_path / "s.db")


_557_ROWS = [
    ("huytd189/Qwen3.6-27B-pure-GGUF", "", "", ["gguf"], ["Qwen/Qwen3.6-27B"], "queued"),
    ("google/gemma-4-12B-it", "", "any-to-any", ["image-text-to-text"], [], "declined"),
    ("google/magenta-realtime-2", "", "text-to-audio", ["realtime-music"], [], "queued"),
    ("OpenMOSS-Team/MOSS-SoundEffect-v2.0", "", "text-to-audio",
     ["sound-effects"], [], "queued"),
    ("org/filed-in-image", "image", "", [], ["Qwen/Qwen3-8B"], "broken"),
]


def test_schema_52_fills_an_empty_lane_from_lineage_and_narrower_tasks(tmp_path):
    """#557: only empty lanes are filled; no verdict is written or moved."""
    again = _at_schema_51(tmp_path, _557_ROWS)
    try:
        got = {r["name"]: (r["lane"], r["lane_source"], r["state"]) for r in again.execute(
            "SELECT name, lane, lane_source, state FROM proposals")}
        assert got == {
            "huytd189/Qwen3.6-27B-pure-GGUF": ("code", "lineage", "queued"),
            "google/gemma-4-12B-it": ("code", "tag", "declined"),
            "google/magenta-realtime-2": ("music", "tag", "queued"),
            "OpenMOSS-Team/MOSS-SoundEffect-v2.0": ("", "", "queued"),
            "org/filed-in-image": ("image", "", "broken"),
        }
        assert again.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == len(_557_ROWS)
    finally:
        again.close()


# --- #383 class 4: a retraction keyed on one fact leaves the others alone ---

RETRACTIONS = sorted(n for n in dir(ms)
                     if re.match(r"_(retract|relane|reopen|requeue)_", n))

#: Older rows a retraction looks for, under a latest verdict no lane can change.
_BAIT = [("screen", "broken", "it ran and passed nothing: ValueError: "
          "expected ['vae'], but only set() were passed."),
         ("screen", "broken", "the screen exited 1"),
         ("screen", "broken", "it ran and passed nothing: gateway returned "
          "HTTP 404: Model type gpt_x not supported."),
         ("adopt", "declined", "does not beat the incumbent")]
LANE_FREE = [("inspect", "too-big: weights 1453.8 GiB over the 22 GiB ceiling"),
             ("fetch", "lora in its own card: this attaches to a model "
                       "rather than being one")]


def test_the_retraction_census_is_not_empty():
    assert {"_relane_from_the_card", "_requeue_diffusers_layout_gaps",
            "_retract_harness_refusals"} <= set(RETRACTIONS)


@pytest.mark.parametrize("tier,detail", LANE_FREE)
@pytest.mark.parametrize("fn", RETRACTIONS)
def test_a_lane_independent_verdict_survives_every_retraction(tmp_path, fn, tier, detail):
    conn = ms.connect(tmp_path / "s.db")
    try:
        # A card that contradicts the lane, so a relane moves the row.
        ms.record(conn, ms.Seen(name="LiquidAI/LFM2.5-350M", source="t",
                                kind="weights", lane="image", why="seeded"))
        conn.execute("UPDATE proposals SET description = 'task text-to-video'")
        for t, outcome, d in _BAIT + [(tier, "declined", detail)]:
            conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, "
                         "detail, decided_at) SELECT id, ?, ?, ?, 0 "
                         "FROM proposals", (outcome, t, d))
        # Old rows, so the state is the newest one, as the backfill sets it.
        ms._backfill_state(conn)
        getattr(ms, fn)(conn)
        last = conn.execute("SELECT outcome, tier FROM verdicts "
                            "ORDER BY id DESC LIMIT 1").fetchone()
        assert tuple(last) == ("declined", tier), fn
    finally:
        conn.close()


def test_a_version_predicate_reads_the_recorded_versions():
    """#389, #415: the floor and the check read one probe, machines.versions."""
    facts = {"versions": {"diffusers": "0.41.0"}}
    assert ms.until_met("version:diffusers>0.40.0", facts)
    assert not ms.until_met("version:diffusers>0.41.0", facts)
    assert not ms.until_met("version:ace-step>1.0", facts)
    assert not ms.until_met("version:diffusers>0.40.0", {})


def _hub(conn, name, files):
    from harness import downloads
    snap = downloads.hub_dir(name) / "snapshots" / "abc"
    snap.mkdir(parents=True)
    for f in files:
        (snap / f).write_text("x", encoding="utf-8")
    return downloads.record(conn, name, downloads.HUB, snap.parent.parent)


def test_a_snapshot_with_only_a_card_is_not_downloaded(tmp_path):
    """#399: Marlin-2B had LICENSE and README and was screened as present.
    The row records it incomplete, and have() reads the row. #411."""
    from harness import fetching
    conn = ms.connect(tmp_path / "d.db")
    assert _hub(conn, "org/card", ["LICENSE", "README.md"])["complete"] == 0
    assert _hub(conn, "org/real", ["config.json", "model.safetensors"])["complete"] == 1
    assert not fetching.have("org/card", conn)
    assert fetching.have("org/real", conn)
    conn.close()


def test_schema_20_requeues_a_screen_of_weights_never_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.fetching.have", lambda m, conn=None: m == "org/here")
    for name, want in (("org/gone", "queued"), ("org/here", "broken")):
        again = _at_schema_18(tmp_path / name.replace("/", "_"), name, "code", "",
                              "broken", "it ran and passed nothing: [Errno 2] "
                              "No such file or directory: 'x/config.json'")
        try:
            assert again.execute("SELECT outcome FROM verdicts ORDER BY id DESC"
                                 ).fetchone()[0] == want, name
        finally:
            again.close()


def test_schema_21_requeues_a_sampling_setting_the_pipeline_refused(tmp_path):
    """#401."""
    again = _at_schema_18(tmp_path, "Photoroom/prxpixel-t2i", "image", "",
                          "broken", "it ran and passed nothing: fox-snow: exit 1: "
                          "ValueError: guidance_scale has to be >= 1.0 but is 0.0")
    try:
        assert again.execute("SELECT outcome FROM verdicts ORDER BY id DESC"
                             ).fetchone()[0] == "queued"
    finally:
        again.close()


def test_schema_22_requeues_screens_of_a_dead_server(tmp_path):
    """#404: six candidates were recorded broken against a crashed mlx_lm.server."""
    again = _at_schema_18(tmp_path, "Qwen/Qwen3-0.6B", "code", "", "broken",
                          'it ran and passed nothing: chunk-bytes: gateway returned '
                          'HTTP 404: {"error": "generation thread died"}')
    try:
        assert again.execute("SELECT outcome FROM verdicts ORDER BY id DESC"
                             ).fetchone()[0] == "queued"
    finally:
        again.close()

"""Planted candidates with known verdicts, through the real fetch, screen, measure and adopt of loop._loop_spend. #919."""
import re
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fakes  # noqa: E402
import test_loop_circuit as circuit  # noqa: E402
from test_loop_circuit import world  # noqa: E402,F401

from harness import adopt, ceiling, cli, downloads, memory, reasons  # noqa: E402
from harness import memory_store as ms  # noqa: E402
from harness.commands import loop as loop_cmd  # noqa: E402

pytestmark = pytest.mark.long

BETTER = WORSE = circuit.CHALLENGER
GGUF = "Ninnix96/Qwengram-0.8B"
LEFTOVER = "org/leftover-needs-more-memory-notreal"
#: The top level of the live Qwengram-0.8B snapshot (KB RULE #792): GGUF quants, an auxiliary safetensors, no config.json.
GGUF_TOP = ("QwenGram-0.8B-BF16.gguf", "QwenGram-0.8B-Q4_K_M.gguf", "QwenGram-0.8B-Q6_K.gguf",
            "QwenGram-0.8B-Q8_0.gguf", "reader.safetensors", "arbiter.pt", "tokenizer.json",
            "tokenizer_config.json", "README.md")
#: The loop steps a plant must reach for real; none of them may be replaced in this module or its world.
STEPS = ("_loop_spend", "_spend_and_settle", "_reopen_retests", "_reverify", "_sweeps",
         "screenable_backlog", "cmd_fetch", "cmd_discover", "_report_screen", "measurable",
         "resume_first", "_measure_and_adopt", "decide", "record", "run", "plan")


def spend(top=1):
    """One sweep's spend: the loop after its sweep and inspect, as `soh discover --loop --run` runs it."""
    a = cli.build_parser().parse_args([
        "discover", "--loop", "--run", "--lane", "code", "--top", str(top), "--budget-gib", "12",
        "--repeat", "4", "--power-budget-min", "1e9", "--ceiling-h", "1e9"])
    return loop_cmd._spend_and_settle(a, 0, [], ceiling.Sweep(1e9 * 3600))


def plant(name, gib=0.7, card=True):
    """`name` queued by inspect with a size, as a sweep and inspect leave a candidate."""
    conn = ms.connect()
    try:
        fakes.seeded_store(conn, [(name, "code", gib, 2)])
        if card:
            fakes.carded(conn, name, fakes.card(name))
    finally:
        conn.close()


def verdicts(name):
    conn = ms.connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT v.id, v.outcome, v.tier, v.reason, v.detail FROM verdicts v "
            "JOIN proposals p ON p.id = v.proposal_id WHERE p.name = ? ORDER BY v.id", (name,))]
    finally:
        conn.close()


def last(name, tier=None):
    rows = [v for v in verdicts(name) if tier is None or v["tier"] == tier]
    return rows[-1] if rows else None


def never_blamed_for_the_harness(name):
    bad = [v for v in verdicts(name) if v["outcome"] in ms.TERMINAL and v["reason"] == reasons.CANDIDATE
           and v["tier"] in (ms.FETCH, ms.SCREEN)]
    assert bad == [], bad


def evals_of(world, name):
    return [e for e in world.evals if any(name in str(x) for x in e)]


def test_no_loop_step_is_replaced_here():
    """The plants are only worth their verdicts while every step between them is the real one."""
    for source in (Path(__file__), Path(circuit.__file__)):
        text = source.read_text(encoding="utf-8")
        hits = [m.group(0) for m in re.finditer(
            r"monkeypatch\.setattr\(\s*(\w+)\s*,\s*[\"'](\w+)[\"']", text)
            if m.group(1).endswith("_cmd") and m.group(2) in STEPS]
        hits += re.findall(rf"monkeypatch\.setattr\(\s*[\"']harness\.commands\.\w+\.(?:{'|'.join(STEPS)})[\"']", text)
        assert hits == [], f"{source.name} replaces a loop step: {hits}"


def test_a_known_better_challenger_is_adopted_and_served(world):
    plant(BETTER)
    spend()
    v = last(BETTER)
    assert (v["outcome"], v["tier"]) == ("measured", "adopt"), v
    conn = ms.connect()
    try:
        assert adopt.default_for("code", circuit.INCUMBENT_UPSTREAM, conn=conn) == BETTER
    finally:
        conn.close()


@pytest.fixture
def planted(world):
    """The circuit's world, answering each model from its own set of passing cases."""
    from evals.run import screen_cases
    from harness import holdout
    split = holdout.for_lane("code")
    world.screen = {c.id for c in screen_cases(circuit._cases("code"))}
    world.all = set(world.prompts)
    world.passes = {}
    world.split = split

    def answer(payload):
        user = payload["messages"][-1]["content"]
        if "Reply with the word ok." in user:
            return "ok", []
        good = world.passes.get(payload["model"], world.all)
        for case_id, prompt in world.prompts.items():
            if prompt in user:
                return (circuit._reference(case_id) if case_id in good else ""), []
        return "", []
    world._answer = answer
    return world


def test_a_known_worse_challenger_is_declined_for_good(planted):
    planted.passes[WORSE] = set(planted.screen)
    plant(WORSE)
    spend()
    v = last(WORSE)
    assert (v["outcome"], v["tier"], v["reason"]) == ("declined", "adopt", reasons.CANDIDATE), v
    asked = len(evals_of(planted, WORSE))
    spend()
    assert last(WORSE)["id"] == v["id"] and len(evals_of(planted, WORSE)) == asked, last(WORSE)


def gguf_first(world, tmp_path, monkeypatch):
    """Qwengram-0.8B as the hub left it, and a gateway whose mlx-lm opens the snapshot's config.json."""
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(tmp_path / "gguf"))
    (tmp_path / "gguf").mkdir()
    snapshot, post = world.snapshot, world.post

    def snap(repo_id, **kw):
        if repo_id != GGUF:
            return snapshot(repo_id, **kw)
        where = downloads.hub_dir(repo_id) / "snapshots" / "9efeb01d"
        (where / "safetensors").mkdir(parents=True, exist_ok=True)
        for i, name in enumerate(GGUF_TOP):
            (where / name).write_bytes(b"GGUF" + bytes(64 * (i + 1)))
        (where / "safetensors" / "config.json").write_text("{}", encoding="utf-8")
        (where / "safetensors" / "model.safetensors").write_bytes(b"x" * 64)
        fakes.hub_ref(where)
        return str(where)

    def gateway(base, payload, timeout):
        if payload["model"] == GGUF:
            config = downloads.hub_dir(GGUF) / "snapshots" / "9efeb01d" / "config.json"
            return httpx.Response(404, json={"error": f"[Errno 2] No such file or directory: '{config}'"},
                                  request=httpx.Request("POST", f"{base}/v1/chat/completions"))
        return post(base, payload, timeout)
    def hub_file(repo_id, filename, local_dir, **kw):
        assert repo_id == GGUF, repo_id
        out = Path(local_dir) / filename
        out.write_bytes(b"GGUF" + bytes(64))
        return str(out)
    world.snapshot, world.post = snap, gateway
    monkeypatch.setattr("huggingface_hub.snapshot_download", snap)
    monkeypatch.setattr("huggingface_hub.hf_hub_download", hub_file)
    monkeypatch.setattr("harness.completion._post", gateway)


def test_a_gguf_first_snapshot_is_screened_on_llama_server(planted, tmp_path, monkeypatch):
    gguf_first(planted, tmp_path, monkeypatch)
    plant(GGUF)
    spend()
    never_blamed_for_the_harness(GGUF)
    v = last(GGUF, ms.SCREEN)
    assert v and v["outcome"] == "screened", verdicts(GGUF)
    assert any("llamacpp:" in str(x) for e in evals_of(planted, "QwenGram-0.8B") for x in e), planted.evals


@pytest.mark.parametrize("fault", ["dead", "refused"])
def test_a_dead_or_refusing_server_is_the_harnesss_fault(planted, monkeypatch, fault):
    post = planted.post

    def gateway(base, payload, timeout):
        if fault == "refused":
            raise httpx.ConnectError("[Errno 61] Connection refused",
                                     request=httpx.Request("POST", f"{base}/v1/chat/completions"))
        planted.server = "dead"
        return post(base, payload, timeout)
    monkeypatch.setattr("harness.completion._post", gateway)
    plant(BETTER)
    spend()
    v = last(BETTER)
    assert v["tier"] == ms.SCREEN and v["reason"] == reasons.HARNESS, verdicts(BETTER)
    circuit.assert_a_harness_fact({**v, "until": last_until(BETTER)})
    assert adopted() == {}


def last_until(name):
    conn = ms.connect()
    try:
        row = conn.execute("SELECT v.until FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
                           "WHERE p.name = ? ORDER BY v.id DESC LIMIT 1", (name,)).fetchone()
        return row["until"] if row else None
    finally:
        conn.close()


def adopted():
    return circuit.adopted()


def test_a_leftover_waiting_for_memory_does_not_hold_back_a_ranked_candidate(planted, monkeypatch):
    plant(LEFTOVER, card=False)
    snap = Path(planted.snapshot(LEFTOVER))
    need = "needs 40.0 GB but only 20.0 GB is safely available"
    conn = ms.connect()
    try:
        downloads.record(conn, LEFTOVER, downloads.HUB, snap.parent.parent)
        ms.decide(conn, LEFTOVER, "queued", tier=ms.SCREEN, detail=f"not screened: {need}",
                  reason=reasons.MEMORY)
        conn.commit()
    finally:
        conn.close()
    asked = []

    def check_model(name, *a, **k):
        # It fits when the fetch reads memory and not when the screen re-checks it (KB FINDING #524).
        asked.append(name)
        return (False, need) if name == LEFTOVER and asked.count(LEFTOVER) > 1 else (True, "")
    monkeypatch.setattr(memory, "check_model", check_model)
    plant(BETTER)
    spend()
    v = last(BETTER, ms.SCREEN)
    assert v and v["outcome"] == "screened", verdicts(BETTER)
    assert last(LEFTOVER)["outcome"] not in ms.TERMINAL, verdicts(LEFTOVER)

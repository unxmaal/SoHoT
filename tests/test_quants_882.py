"""#882: a base too big or unloadable here is followed to a quantized repo that fits."""
from __future__ import annotations

import json

import pytest

from harness import feeds, quants
from harness import inspect as ins
from harness import memory_store as ms

GIB = 1024 ** 3
BASE = "Qwen/Qwen3.6-35B-A3B"
GGUF = "unsloth/Qwen3.6-35B-A3B-GGUF"
MLX8 = "lmstudio-community/Qwen3.6-35B-A3B-MLX-8bit"
MLX4 = "lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit"


def sib(name, gib):
    return {"rfilename": name, "size": int(gib * GIB)}


CARDS = {
    BASE: {"pipeline_tag": "image-text-to-text", "library_name": "transformers",
           "tags": ["transformers", "safetensors", "text-generation"],
           "siblings": [sib("model-00001.safetensors", 33.5), sib("model-00002.safetensors", 33.5)]},
    GGUF: {"pipeline_tag": "image-text-to-text", "tags": ["gguf", f"base_model:quantized:{BASE}"],
           "siblings": [sib("Qwen3.6-35B-A3B-Q4_K_M.gguf", 20), sib("Qwen3.6-35B-A3B-Q8_0.gguf", 35),
                        sib("Qwen3.6-35B-A3B-BF16.gguf", 67)]},
    MLX8: {"pipeline_tag": "text-generation", "library_name": "mlx",
           "tags": ["mlx", f"base_model:quantized:{BASE}"],
           "siblings": [sib("model.safetensors", 36)]},
    MLX4: {"pipeline_tag": "text-generation", "library_name": "mlx",
           "tags": ["mlx", f"base_model:quantized:{BASE}"],
           "siblings": [sib("model.safetensors", 19)]},
}

LISTING = [
    {"id": "nvidia/Qwen3.6-35B-A3B-NVFP4", "downloads": 4_500_000, "library_name": "Model Optimizer",
     "tags": [f"base_model:quantized:{BASE}"]},
    {"id": "HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive", "downloads": 890_000,
     "tags": ["gguf", f"base_model:quantized:{BASE}"]},
    {"id": MLX8, "downloads": 245_000, "library_name": "mlx", "tags": ["mlx"]},
    {"id": "someone/Qwen3.6-35B-A3B-GGUF", "downloads": 2_000_000, "tags": ["gguf"]},
    {"id": GGUF, "downloads": 1_200_000, "tags": ["gguf"]},
    {"id": MLX4, "downloads": 263_000, "library_name": "mlx", "tags": ["mlx"]},
]


def _machine(*runtimes, gb=32.0):
    from harness.machine import Machine
    from harness.memory import Accelerator
    return Machine(runtimes=frozenset(runtimes), accelerator=Accelerator("unified", "test", gb, gb))


def _registry(listing=LISTING, cards=CARDS, extra=None, asked=None):
    def get(url):
        if asked is not None:
            asked.append(url)
        for prefix, body in (extra or {}).items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return body if isinstance(body, str) else json.dumps(body)
        if url.startswith(quants.LISTING.format(base=BASE)):
            return json.dumps(listing)
        if "/api/models?" in url:
            return "[]"
        for model_id, card in cards.items():
            if url == ins.MODEL_URL.format(model_id=model_id):
                return json.dumps(card)
        raise feeds.FeedError(f"{url}: HTTP 404")
    return get


def test_a_67_gib_base_proposes_its_20_gib_q4_k_m_quant():
    fit = quants.best(BASE, get=_registry(), ceiling=22 * GIB, machine=_machine("llamacpp", "mlx"))
    assert fit is not None and fit.repo == GGUF
    assert fit.largest == 20 * GIB


def test_known_quantizers_come_first_and_finetunes_and_cuda_formats_never():
    got = quants.ranked(BASE, LISTING, _machine("llamacpp", "mlx"))
    assert got == [GGUF, MLX4, MLX8, "someone/Qwen3.6-35B-A3B-GGUF"]


def test_a_runtime_the_machine_lacks_is_never_proposed():
    fit = quants.best(BASE, get=_registry(), ceiling=22 * GIB, machine=_machine("mlx"))
    assert fit is not None and fit.repo == MLX4


def test_nothing_fitting_proposes_nothing():
    assert quants.best(BASE, get=_registry(), ceiling=10 * GIB,
                       machine=_machine("llamacpp", "mlx")) is None


def test_an_empty_listing_falls_back_to_the_known_quantizers():
    asked = []
    by_author = quants.BY_AUTHOR.format(author="unsloth", name="Qwen3.6-35B-A3B")
    get = _registry(listing=[], extra={by_author: [{"id": GGUF, "tags": ["gguf"]}]}, asked=asked)
    fit = quants.best(BASE, get=get, ceiling=22 * GIB, machine=_machine("llamacpp"))
    assert fit is not None and fit.repo == GGUF
    assert by_author in asked


def _pin(monkeypatch, ceiling=22 * GIB, runtimes=("llamacpp", "mlx", "cpu")):
    from harness import machine
    monkeypatch.setattr(ins, "ceiling_bytes", lambda acc=None: ceiling)
    monkeypatch.setattr(machine, "detect", lambda *a, **k: _machine(*runtimes))


def _edges(conn, src):
    return [r["name"] for r in conn.execute(
        "SELECT d.name FROM edges e JOIN proposals s ON s.id = e.src JOIN proposals d ON d.id = e.dst "
        "WHERE s.name = ? AND e.relation = ?", (src, quants.RELATION))]


def test_the_inspect_tier_follows_a_too_big_base_to_its_quant(monkeypatch, capsys):
    from harness.commands import discover as discover_cmd
    _pin(monkeypatch)
    monkeypatch.setattr(ins, "hf_get", _registry())
    conn = ms.connect()
    ms.record(conn, ms.Seen(name=BASE, source="t", registry=ms.HUGGINGFACE, resolved=BASE, lane="code"))
    conn.close()
    args = type("A", (), {"repos": [], "from_store": True, "top": 10, "budget": 10,
                          "shard": "", "judge": False, "json": False})()
    assert discover_cmd._report_inspect(args) == 0
    assert f"proposed {GGUF}" in capsys.readouterr().out
    conn = ms.connect()
    try:
        assert conn.execute("SELECT state FROM proposals WHERE name = ?", (BASE,)).fetchone()[0] == "declined"
        row = conn.execute("SELECT state, size_bytes, lane FROM proposals WHERE name = ?", (GGUF,)).fetchone()
        assert (row["state"], row["size_bytes"]) == ("queued", 20 * GIB)
        assert row["lane"] == "code"
        assert _edges(conn, BASE) == [GGUF]
        assert quants.follow(conn, BASE, get=_registry()).endswith(f"already followed to {GGUF}")
    finally:
        conn.close()


def test_a_settled_quant_is_passed_over_for_the_next_one():
    conn = ms.connect()
    try:
        ms.record(conn, ms.Seen(name=BASE, source="t", registry=ms.HUGGINGFACE, lane="code"))
        ms.record(conn, ms.Seen(name=GGUF, source="t", registry=ms.HUGGINGFACE, lane="code"))
        ms.decide(conn, GGUF, "declined", tier=ms.INSPECT, detail="too-big: stale size")
        line = quants.follow(conn, BASE, get=_registry(), ceiling=22 * GIB,
                             machine=_machine("llamacpp", "mlx"))
        assert f"proposed {MLX4}" in line
    finally:
        conn.close()


def test_a_derivative_that_failed_to_load_is_followed_through_its_quantized_parent():
    conn = ms.connect()
    try:
        name = "EschaLabs/Qwen3.6-35B-A3B-Escha-W2"
        ms.record(conn, ms.Seen(name=name, source="t", registry=ms.HUGGINGFACE, lane="code"))
        ms.set_card(conn, name, ins.card_facts({"tags": [f"base_model:quantized:{BASE}"]}))
        from harness import reasons
        ms.decide(conn, name, "declined", tier=ms.SCREEN, reason=reasons.RUNTIME,
                  detail="the installed runtime could not load it")
        ms.record(conn, ms.Seen(name="org/Huge", source="t", registry=ms.HUGGINGFACE, lane="code"))
        ms.decide(conn, "org/Huge", "declined", tier=ms.INSPECT, reason=reasons.MACHINE,
                  detail="too-big: smallest weight it names is 67.0 GiB", until="ceiling_gb:>67.0")
        ms.record(conn, ms.Seen(name="org/Dead", source="t", registry=ms.HUGGINGFACE, lane="code"))
        ms.decide(conn, "org/Dead", "declined", tier=ms.INSPECT, reason=reasons.UPSTREAM,
                  detail="dead: last commit 3 years ago", until="commit_after:2023-01-01T00:00:00Z")
        assert quants.unrunnable(conn) == [BASE, "org/Huge"]
    finally:
        conn.close()


ORNITH = "ornith-ai/Ornith-1.5-35B-A3B"
README = """
outperforms its similar-sized peer Qwen 3.6-35B across all coding benchmarks
<table><tr><th style="x">Benchmark</th><th>Ornith-1.5-35B-A3B</th>
<th style="color:#FD8E5B">Qwen3.6-35B-A3B</th><th>Gemma-4-31B <sub></sub></th>
<th>SWE-bench Verified</th><th>BFCL-v3</th></tr></table>

| Model | Terminal-Bench 2.1 | Qwen3.5-397B |
|---|---|---|
| a | 1 | 2 |
"""


def test_a_cards_comparison_table_names_the_models_it_is_measured_against():
    assert quants.compared(README, "Ornith-1.5-35B-A3B") == [
        "Qwen3.6-35B-A3B", "Gemma-4-31B", "Qwen3.5-397B"]


def test_a_compared_name_resolves_to_the_original_not_a_quant():
    search = quants.SEARCH.format(name="Qwen3.5-397B")
    get = _registry(extra={search: [
        {"id": "Qwen/Qwen3.5-397B-A17B-FP8", "downloads": 9, "tags": ["base_model:quantized:Qwen/Qwen3.5-397B-A17B"]},
        {"id": "Qwen/Qwen3.5-397B-A17B", "downloads": 5, "tags": []},
        {"id": "someone/NotQwen3.5-397B", "downloads": 99, "tags": []}]})
    assert quants.resolve("Qwen3.5-397B", get) == "Qwen/Qwen3.5-397B-A17B"


def test_an_incumbent_without_lineage_tags_is_built_from_its_name_less_the_format():
    assert quants.family("ornith-ai/Ornith-1.5-35B-A3B-GGUF", {"tags": ["gguf"]}) == [ORNITH]
    assert quants.family(GGUF, {"tags": [f"base_model:quantized:{BASE}"]}) == [BASE]


def test_the_sweep_follows_an_incumbents_compared_peer(monkeypatch):
    conn = ms.connect()
    try:
        monkeypatch.setattr(quants, "incumbents", lambda c: ["ornith-ai/Ornith-1.5-35B-A3B-GGUF"])
        get = _registry(extra={
            ins.MODEL_URL.format(model_id="ornith-ai/Ornith-1.5-35B-A3B-GGUF"): {"tags": ["gguf"]},
            quants.README.format(model_id=ORNITH): README,
            quants.README.format(model_id="ornith-ai/Ornith-1.5-35B-A3B-GGUF"): README,
            quants.SEARCH.format(name="Qwen3.6-35B-A3B"): [{"id": BASE, "tags": []}],
            ins.MODEL_URL.format(model_id=ORNITH): feeds.FeedError("HTTP 404"),
        })
        assert quants.seeds(conn, get) == [ORNITH, BASE]
        lines = quants.sweep(conn, get=get, ceiling=22 * GIB, machine=_machine("llamacpp", "mlx"))
        assert any(f"{BASE}: proposed {GGUF}" in line for line in lines), lines
        assert conn.execute("SELECT state FROM proposals WHERE name = ?", (BASE,)).fetchone()[0] == "declined"
        assert _edges(conn, BASE) == [GGUF]
        assert ms.source_row(conn, quants.SOURCE)["last_status"] == "ok"
        assert quants.sweep(conn, get=get, ceiling=22 * GIB, machine=_machine("llamacpp")) == []
    finally:
        conn.close()


def test_a_rate_limited_listing_defers_the_sweep():
    conn = ms.connect()
    try:
        ms.record(conn, ms.Seen(name=BASE, source="t", registry=ms.HUGGINGFACE, lane="code"))
        ms.decide(conn, BASE, "declined", tier=ms.INSPECT, detail="too-big: 67 GiB")
        get = _registry(extra={quants.LISTING.format(base=BASE): feeds.RateLimitedFeed("429")})
        lines = quants.sweep(conn, get=get, ceiling=22 * GIB, machine=_machine("llamacpp"))
        assert "rate-limited" in lines[-1]
        assert ms.source_row(conn, quants.SOURCE)["last_status"] == ms.DEFERRED
    finally:
        conn.close()


@pytest.mark.parametrize("name", ["org/Qwen3.6-35B-A3B-abliterated-GGUF", "org/Other-35B-GGUF"])
def test_a_repo_that_is_not_the_base_itself_is_not_its_quant(name):
    assert quants.ranked(BASE, [{"id": name, "tags": ["gguf"]}], _machine("llamacpp")) == []


def test_a_descendant_in_a_runtime_the_machine_lacks_costs_no_registry_call():
    asked = []
    quants.best(BASE, get=_registry(asked=asked), ceiling=22 * GIB, machine=_machine("mlx"))
    assert ins.MODEL_URL.format(model_id=GGUF) not in asked

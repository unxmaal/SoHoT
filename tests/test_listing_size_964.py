"""hf_facts, card_description and the inspect verdict report one size for a listing: the variant inspect runs. #964."""
import json
import re
import types

import fakes
from harness import inspect as ins

GIB = 1024 ** 3
CEILING = 66 * GIB
MIXED = "OBLITERATUS/Qwen3.8-27B-OBLITERATED"


def _machine(*runtimes):
    have = set(runtimes) | {"always"}
    return types.SimpleNamespace(runtimes=frozenset(have),
                                 refuses=lambda rt: None if rt in have else f"needs-{rt}")


MAC = _machine("mlx", "llamacpp")


def _described_gib(text) -> float:
    return float(re.search(r"([\d.]+) GiB of weights", text).group(1))


def test_a_mixed_mlx_and_gguf_listing_has_one_size_everywhere():
    card = fakes.card(MIXED)
    total = sum(s.get("size") or 0 for s in card["siblings"])
    fit = ins.inspect_model(MIXED, data=card, ceiling=CEILING, machine=MAC)
    facts = ins.hf_facts(MIXED, fetch=lambda url: json.dumps(card), ceiling=CEILING, machine=MAC)
    assert 0 < fit.smallest < total / 4
    assert facts["size"] == fit.smallest
    assert _described_gib(fit.description) == round(fit.smallest / GIB, 1)


def test_card_description_alone_sizes_as_inspect_does():
    card = fakes.card(MIXED)
    for machine, ceiling in ((MAC, CEILING), (MAC, 16 * GIB), (_machine("mlx"), CEILING)):
        fit = ins.inspect_model(MIXED, data=card, ceiling=ceiling, machine=machine)
        assert ins.card_description(card, ceiling=ceiling, machine=machine) == fit.description


def test_a_listing_with_no_weight_file_is_sized_by_its_files():
    assert ins.hf_facts("org/x", fetch=lambda url: '{"siblings": [{"size": 100}, {"size": 250}]}',
                        ceiling=CEILING, machine=MAC)["size"] == 350


def test_a_cached_repo_total_is_refetched_not_trusted():
    card = fakes.card(MIXED)
    total = sum(s.get("size") or 0 for s in card["siblings"])
    cache = {MIXED: {"size": total, "pipeline_tag": card.get("pipeline_tag", ""), "tags": []}}
    calls = []

    def fetch(url):
        calls.append(url)
        return json.dumps(card)

    got = ins.hf_facts(MIXED, fetch=fetch, cache=cache, ceiling=CEILING, machine=MAC)
    assert calls and got["size"] < total
    assert cache[MIXED] == {**cache[MIXED], "size": got["size"], "ceiling": CEILING}
    again = ins.hf_facts(MIXED, fetch=fetch, cache=cache, ceiling=CEILING, machine=MAC)
    assert again["size"] == got["size"] and len(calls) == 1
    ins.hf_facts(MIXED, fetch=fetch, cache=cache, ceiling=CEILING // 2, machine=MAC)
    assert len(calls) == 2, "a size picked under another ceiling is not this one"


def test_a_repo_sizes_the_weights_it_names_against_its_own_ceiling_and_machine(tmp_path):
    asked = []

    def run(argv, cwd=None, timeout=180.0):
        d = tmp_path / "a__b"
        d.mkdir(exist_ok=True)
        (d / "m.py").write_text(f'load("{MIXED}")', encoding="utf-8")
        return "2026-01-01T00:00:00+00:00"

    def facts(model_id, cache=None, ceiling=None, machine=None):
        asked.append((model_id, ceiling, machine))
        return {"size": 5 * GIB, "lane": "code"}

    ins.inspect("a/b", tmp_path, meta={"size": 10}, run=run, facts=facts, ceiling=CEILING, machine=MAC)
    assert asked == [(MIXED, CEILING, MAC)]

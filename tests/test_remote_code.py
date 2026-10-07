"""A repo that needs trust_remote_code is a runner gap before its download, not after. #567."""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fakes  # noqa: E402
from harness import engines, fetching, rank, screen  # noqa: E402
from harness import inspect as ins  # noqa: E402
from harness import memory_store as ms  # noqa: E402
from harness import remote_code  # noqa: E402
from harness.remote_code import code_evidence, remote_code_gap  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NATIVE = frozenset({"paddleocr_vl", "trocr"})
PIN = "transformers==5.17.0"
REFUSED = ("baidu/Unlimited-OCR", "JustANormalTinkerer/hayai-ocr-v2")


@pytest.mark.parametrize("auto_map,files,evidence", [
    (False, ["configuration_hayai.py", "modeling_hayai.py"], ""),
    (True, ["configuration_hayai.py", "modeling_hayai.py", "config.json"],
     "configuration_hayai.py, modeling_hayai.py"),
    (True, ["README.md", "config.json"], "auto_map"),
    (True, ["sub/modeling_x.py", "inference.py"], "modeling_x.py"),
    (True, [f"modeling_{c}.py" for c in "edcba"],
     "modeling_a.py, modeling_b.py, modeling_c.py"),
])
def test_the_evidence_is_the_auto_map_and_the_code_files_it_names(auto_map, files, evidence):
    config = {"auto_map": {"AutoModel": "m.M"}} if auto_map else {}
    assert code_evidence(config, files) == evidence


@pytest.mark.parametrize("model_type,evidence,want", [
    ("hayai", "", ""),
    ("", "auto_map", ""),
    ("paddleocr_vl", "modeling_paddleocr_vl.py", ""),
    ("hayai", "configuration_hayai.py, modeling_hayai.py",
     "ships its own modelling code (configuration_hayai.py, modeling_hayai.py) for model "
     "type 'hayai', which transformers==5.17.0 does not ship"),
])
def test_only_code_for_a_model_type_transformers_lacks_is_a_gap(model_type, evidence, want):
    assert remote_code_gap(model_type, evidence, NATIVE, PIN) == want


@pytest.mark.parametrize("repo,model_type,ships", [
    ("baidu/Unlimited-OCR", "unlimited-ocr", "modeling_unlimitedocr.py"),
    ("JustANormalTinkerer/hayai-ocr-v2", "hayai", "modeling_hayai.py"),
    ("PaddlePaddle/PaddleOCR-VL-1.6", "paddleocr_vl", "modeling_paddleocr_vl.py"),
    ("openai/privacy-filter", "openai_privacy_filter", ""),
    ("cross-encoder/ettin-reranker-1b-v1", "modernbert", ""),
])
def test_inspect_reads_the_model_type_and_the_code_from_a_recorded_card(repo, model_type, ships):
    card = ins.card_facts(fakes.card(repo))
    assert card.model_type == model_type
    assert (ships in card.remote_code) if ships else card.remote_code == ""


def test_a_card_with_no_config_claims_nothing():
    card = ins.card_facts(fakes.card("bespokelabs/Bespoke-Nimble-9B"))
    assert (card.model_type, card.remote_code) == ("", "")


def _row(repo):
    card = ins.card_facts(fakes.card(repo))
    return {"name": repo, "lane": "ocr", "hf_task": card.task, "library": card.library,
            "card_tags": card.tags, "model_type": card.model_type,
            "remote_code": card.remote_code}


@pytest.mark.parametrize("repo", REFUSED)
def test_an_ocr_model_needing_its_own_code_is_a_runner_gap(repo):
    gap = screen.runner_gap("ocr", repo, card=_row(repo))
    assert gap.startswith("needs its own runner: ships its own modelling code")
    planned = screen.plan([_row(repo)], missing=lambda n: [])[0]
    assert planned["state"] == screen.NO_RUNNER


def test_code_for_a_model_type_transformers_ships_is_not_a_gap():
    repo = "PaddlePaddle/PaddleOCR-VL-1.6"
    assert screen.runner_gap("ocr", repo, card=_row(repo)) == ""


def test_the_gap_belongs_to_the_transformers_engines_only():
    card = _row("baidu/Unlimited-OCR")
    assert engines.card_gap("osocr:auto", card) == ""
    for head in sorted(engines.HF_TASK_ENGINES):
        assert engines.card_gap(f"{head}:baidu/Unlimited-OCR", card)


def test_runners_wanted_lists_them_and_not_the_native_one():
    rows = [_row(r) for r in (*REFUSED, "PaddlePaddle/PaddleOCR-VL-1.6")]
    assert sorted(r["name"] for r in rank.runnerless(rows)) == sorted(REFUSED)


def test_the_store_keeps_both_facts_and_card_of_returns_them(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        repo = "baidu/Unlimited-OCR"
        ms.record(conn, ms.Seen(name=repo, source="t", lane="ocr",
                                registry=ms.HUGGINGFACE, resolved=repo))
        fakes.carded(conn, repo, fakes.card(repo))
        got = ms.card_of(conn, repo)
        assert got["model_type"] == "unlimited-ocr"
        assert "modeling_unlimitedocr.py" in got["remote_code"]
    finally:
        conn.close()


def test_the_fetch_tier_queues_it_before_any_download(tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    conn = ms.connect(tmp_path / "s.db")
    try:
        repo = "baidu/Unlimited-OCR"
        ms.record(conn, ms.Seen(name=repo, source="t", lane="ocr",
                                registry=ms.HUGGINGFACE, resolved=repo))
        ms.set_size(conn, repo, 7 * fetching.GIB)
        fakes.carded(conn, repo, fakes.card(repo))
        ms.decide(conn, repo, "queued", tier="inspect", detail="fits")
        got = fetching.run(conn, {repo: 7 * fetching.GIB}, limit=1, free=500 * fetching.GIB,
                           snapshot=lambda *a, **k: pytest.fail("downloaded remote code"))
        assert got and not got[0]["ok"]
        assert "ships its own modelling code" in got[0]["why"]
        row = conn.execute("SELECT state FROM proposals WHERE name = ?", (repo,)).fetchone()
        assert row["state"] == "queued"
    finally:
        conn.close()


def test_the_snapshot_is_of_the_transformers_the_hf_task_venv_pins():
    text = (ROOT / "scripts" / "versions.sh").read_text(encoding="utf-8")
    pin = re.search(r'^TRANSFORMERS_PIN="([^"]+)"', text, re.M).group(1)
    got_pin, native = remote_code.native_types()
    assert got_pin == pin
    assert {"paddleocr_vl", "trocr", "openai_privacy_filter", "modernbert"} <= native
    assert not {"unlimited-ocr", "hayai"} & native

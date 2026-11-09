"""A slot-plan GGUF refused for its weights says so and names what holds the room, not a KV shortfall. #1651."""
import pytest

from harness import context, interactive, reasons
from tests.test_context import ORNITH, write_gguf

GIB = 1024 ** 3
URL = "http://127.0.0.1:18083"


@pytest.fixture
def pinned():
    interactive.write({"url": URL, "budget_bytes": 35 * GIB, "bytes": 33 * GIB,
                       "lanes": {"code": {"stem": context.ORNITH_STEM, "bytes": 21 * GIB}}, "skipped": {}})


def _plan(tmp_path, monkeypatch, weights, coresident=16 * GIB):
    path = tmp_path / f"{context.ORNITH_STEM}.gguf"
    write_gguf(path, ORNITH)
    monkeypatch.setattr(context, "router_rows", lambda conn: [{"path": str(path), "id": 1}])
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: coresident)
    monkeypatch.setattr(context, "_weights", lambda p: weights)
    return context.plan(None, budget=int(59.8 * GIB), kv_cap=64 * GIB, record=False)[0]


def test_an_ornith_whose_weights_exceed_what_the_pinned_set_and_mlx_leave_is_refused_for_its_weights(
        pinned, tmp_path, monkeypatch):
    got = _plan(tmp_path, monkeypatch, int(20.2 * GIB))
    why = got["why"]
    assert got["ctx"] == 0
    assert why.startswith("refused: 20.2 GiB of weights over the 10.8 GiB budget"), why
    assert "33.0 GiB of the machine held by the interactive server's pinned models" in why
    assert "16.0 GiB by the co-resident MLX model" in why
    assert "GiB of KV" not in why and "slots of" not in why
    cls = reasons.classify(f"llamacpp:{context.ORNITH_STEM} is not served: {why}",
                           candidate=f"llamacpp:{context.ORNITH_STEM}")
    assert cls == reasons.PLAN_REFUSED and reasons.CLASSES[cls] == ("declined", reasons.LIMIT)


def test_an_ornith_whose_weights_fit_but_whose_slots_do_not_keeps_the_kv_refusal(pinned, tmp_path, monkeypatch):
    why = _plan(tmp_path, monkeypatch, 8 * GIB)["why"]
    assert why == "refused: 4 slots of 262144 tokens need 20.0 GiB of KV, 2.8 GiB fits", why


def test_choose_slots_names_the_weights_without_a_pinned_set_or_mlx():
    why = context.choose_slots(ORNITH, 12 * GIB, 10 * GIB, 4, 262144).why
    assert why.startswith("refused: 12.0 GiB of weights over the 10.0 GiB budget"), why
    assert "pinned" not in why and "MLX" not in why

"""KV is priced by layer type: sliding layers hold their window, linear-attention layers no cache. #2033."""
import json

from harness import memory, serving

CTX = serving.MLX_REQUEST_CTX
GEMMA4_31B = {"num_hidden_layers": 60, "num_attention_heads": 32, "num_key_value_heads": 16, "head_dim": 256,
              "sliding_window": 1024, "num_global_key_value_heads": 4, "global_head_dim": 512,
              "layer_types": (["sliding_attention"] * 5 + ["full_attention"]) * 10}
QWEN36_27B = {"num_hidden_layers": 64, "num_attention_heads": 24, "num_key_value_heads": 4, "head_dim": 256,
              "full_attention_interval": 4, "layer_types": (["linear_attention"] * 3 + ["full_attention"]) * 16}


def _repo(tmp_path, cfg, wrap=False):
    (tmp_path / "config.json").write_text(json.dumps({"text_config": cfg} if wrap else cfg), encoding="utf-8")
    return str(tmp_path)


def test_a_dense_config_costs_what_it_always_did(tmp_path):
    cfg = {"num_hidden_layers": 28, "num_attention_heads": 28, "num_key_value_heads": 4, "hidden_size": 3584}
    assert memory.mlx_kv_bytes_per_token("", path=_repo(tmp_path, cfg)) == 2 * 28 * 4 * 128 * 2


def test_sliding_layers_hold_their_window_and_full_layers_their_global_heads(tmp_path):
    got = memory.mlx_kv_bytes_per_token("", path=_repo(tmp_path, GEMMA4_31B, wrap=True)) * CTX
    want = 50 * 2 * 16 * 256 * 2 * 1024 + 10 * 2 * 4 * 512 * 2 * CTX
    assert abs(got - want) < CTX
    assert got / 1024 ** 3 < 4 < 2 * 60 * 16 * 256 * 2 * CTX / 1024 ** 3


def test_linear_attention_layers_hold_no_cache(tmp_path):
    want = 16 * 2 * 4 * 256 * 2
    assert memory.mlx_kv_bytes_per_token("", path=_repo(tmp_path, QWEN36_27B)) == want
    bare = {k: v for k, v in QWEN36_27B.items() if k != "layer_types"}
    assert memory.mlx_kv_bytes_per_token("", path=_repo(tmp_path, bare)) == want


def test_a_short_context_pays_a_sliding_layer_only_for_what_it_holds(tmp_path):
    path = _repo(tmp_path, GEMMA4_31B)
    short = memory.mlx_kv_bytes_per_token("", path=path, ctx=512)
    assert short == 50 * 2 * 16 * 256 * 2 + 10 * 2 * 4 * 512 * 2
    assert short > memory.mlx_kv_bytes_per_token("", path=path)


def test_a_31b_sliding_model_is_priced_under_the_room_a_screen_has(tmp_path, monkeypatch):
    path = _repo(tmp_path, GEMMA4_31B)
    monkeypatch.setattr(memory, "cache_path", lambda repo: path)
    monkeypatch.setattr(memory, "size_gb", lambda p: 21.7)
    need = memory.need_gb("google/gemma-4-31B-it-qat-w4a16-ct", parallel=1)
    assert need < 26.0

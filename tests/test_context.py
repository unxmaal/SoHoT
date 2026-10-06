"""Per-model context from GGUF metadata and the memory ceiling. #498."""
import struct

import pytest

from harness import context

_TYPES = {int: 4, float: 6, bool: 7, str: 8}


def _s(text: str) -> bytes:
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw


def _value(v) -> tuple[int, bytes]:
    if isinstance(v, bool):
        return 7, struct.pack("<?", v)
    if isinstance(v, int):
        return (10, struct.pack("<Q", v)) if v > 0xFFFFFFFF else (4, struct.pack("<I", v))
    if isinstance(v, float):
        return 6, struct.pack("<f", v)
    if isinstance(v, str):
        return 8, _s(v)
    if isinstance(v, list):
        inner = [_value(x) for x in v]
        kind = inner[0][0] if inner else 4
        return 9, struct.pack("<IQ", kind, len(v)) + b"".join(b for _, b in inner)
    raise TypeError(v)


def write_gguf(path, meta: dict) -> None:
    """A GGUF v3 header with these key/values and no tensors."""
    body = b""
    for key, v in meta.items():
        kind, raw = _value(v)
        body += _s(key) + struct.pack("<I", kind) + raw
    path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, len(meta)) + body)


LLAMA = {"general.architecture": "llama", "llama.context_length": 131072,
         "llama.block_count": 32, "llama.embedding_length": 4096,
         "llama.attention.head_count": 32, "llama.attention.head_count_kv": 8,
         "tokenizer.ggml.tokens": ["a", "b", "c"]}


def test_reads_the_metadata_a_gguf_header_carries(tmp_path):
    f = tmp_path / "m.gguf"
    write_gguf(f, {**LLAMA, "big": 2 ** 40, "ratio": 0.5, "ok": True})
    meta = context.read_meta(f)
    assert meta["general.architecture"] == "llama"
    assert meta["llama.context_length"] == 131072
    assert meta["big"] == 2 ** 40 and meta["ok"] is True
    assert meta["ratio"] == pytest.approx(0.5)


def test_a_file_that_is_not_gguf_is_refused(tmp_path):
    f = tmp_path / "m.gguf"
    f.write_bytes(b"NOPE" + b"\0" * 32)
    with pytest.raises(ValueError, match="not a GGUF"):
        context.read_meta(f)


QWEN3_4B = {"general.architecture": "qwen3", "qwen3.context_length": 262144,
            "qwen3.block_count": 36, "qwen3.embedding_length": 2560,
            "qwen3.attention.head_count": 32, "qwen3.attention.head_count_kv": 8,
            "qwen3.attention.key_length": 128, "qwen3.attention.value_length": 128}
ORNITH = {"general.architecture": "qwen35moe", "qwen35moe.context_length": 262144,
          "qwen35moe.block_count": 41, "qwen35moe.nextn_predict_layers": 1,
          "qwen35moe.embedding_length": 2048, "qwen35moe.attention.head_count": 16,
          "qwen35moe.attention.head_count_kv": 2,
          "qwen35moe.attention.key_length": 256,
          "qwen35moe.attention.value_length": 256,
          "qwen35moe.full_attention_interval": 4}
MIB = 1024 ** 2
GIB = 1024 ** 3


def test_kv_per_token_matches_what_llama_server_allocated_for_a_dense_model():
    # llama-server 11146: 2304.00 MiB for 16384 cells, 36 layers, f16.
    assert context.kv_bytes_per_token(QWEN3_4B) * 16384 == 2304 * MIB


def test_kv_per_token_counts_only_the_attention_layers_of_a_hybrid():
    # llama-server 11146 for Ornith: 320.00 MiB for 16384 cells, 10 layers.
    assert context.kv_bytes_per_token(ORNITH) * 16384 == 320 * MIB


def test_head_dims_default_to_embedding_over_heads():
    assert context.kv_bytes_per_token(LLAMA) == 32 * 8 * (128 + 128) * 2


def test_per_layer_kv_heads_skip_recurrent_layers():
    meta = {**LLAMA, "llama.block_count": 4,
            "llama.attention.head_count_kv": [0, 8, 0, 8]}
    assert context.kv_bytes_per_token(meta) == 2 * 8 * 256 * 2


def test_sliding_window_layers_are_costed_as_full_attention():
    meta = {**LLAMA, "llama.attention.sliding_window": 1024,
            "llama.attention.sliding_window_pattern": [True, False] * 16}
    assert context.kv_bytes_per_token(meta) == context.kv_bytes_per_token(LLAMA)


def test_a_quantised_cache_costs_less_per_token():
    assert context.kv_bytes_per_token(LLAMA, "q8_0") == 32 * 8 * 256 * 34 // 32


def test_trained_context_comes_from_the_architecture_key():
    assert context.trained(ORNITH) == 262144
    assert context.trained({"general.architecture": "x"}) == 0


def test_context_is_the_trained_length_when_memory_allows():
    got = context.choose(ORNITH, weights=20 * GIB, budget=60 * GIB)
    assert got.ctx == 262144 and got.trained == 262144
    assert got.kv_per_token == 20480 and "trained" in got.why


def test_context_is_capped_by_the_kv_room_left_after_the_weights():
    room = 16 * GIB - 10 * GIB
    got = context.choose(QWEN3_4B, weights=10 * GIB, budget=16 * GIB)
    assert got.ctx == room // 147456 // 1024 * 1024
    assert got.ctx % 1024 == 0 and got.ctx < 262144 and "memory" in got.why


def test_parallel_slots_split_the_room():
    one = context.choose(QWEN3_4B, weights=10 * GIB, budget=16 * GIB)
    two = context.choose(QWEN3_4B, weights=10 * GIB, budget=16 * GIB, slots=2)
    assert two.ctx == one.ctx // 2 // 1024 * 1024


def test_below_the_floor_is_refused_with_a_reason():
    got = context.choose(QWEN3_4B, weights=15 * GIB, budget=16 * GIB)
    assert got.ctx == 0
    assert "8192" in got.why and "refused" in got.why


def test_a_model_trained_short_is_refused_too():
    got = context.choose({**QWEN3_4B, "qwen3.context_length": 4096},
                         weights=GIB, budget=60 * GIB)
    assert got.ctx == 0 and "4096" in got.why


def test_metadata_without_the_attention_shape_is_refused():
    got = context.choose({"general.architecture": "mystery",
                          "mystery.context_length": 32768},
                         weights=GIB, budget=60 * GIB)
    assert got.ctx == 0 and "KV" in got.why

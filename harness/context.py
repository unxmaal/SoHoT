"""The context each GGUF is served at: trained length, capped by what its KV cache leaves room for. #498."""
from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import NamedTuple

_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f",
           7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_STRING, _ARRAY = 8, 9
#: Arrays longer than this (tokenizer vocabularies) are skipped, not kept.
_KEEP_ARRAY = 4096


def _read(fh, fmt: str):
    size = struct.calcsize(fmt)
    raw = fh.read(size)
    if len(raw) != size:
        raise ValueError("truncated GGUF header")
    return struct.unpack(fmt, raw)[0]


def _string(fh) -> str:
    n = _read(fh, "<Q")
    return fh.read(n).decode("utf-8", "replace")


def _value(fh, kind: int):
    if kind in _SCALAR:
        return _read(fh, _SCALAR[kind])
    if kind == _STRING:
        return _string(fh)
    if kind == _ARRAY:
        inner, count = _read(fh, "<I"), _read(fh, "<Q")
        if count > _KEEP_ARRAY:
            if inner in _SCALAR:
                fh.seek(count * struct.calcsize(_SCALAR[inner]), 1)
            else:
                for _ in range(count):
                    _value(fh, inner)
            return None
        return [_value(fh, inner) for _ in range(count)]
    raise ValueError(f"unknown GGUF value type {kind}")


#: Below this a served model fails ordinary agent work; refuse rather than serve it.
FLOOR = 8192
STEP = 1024


def _stepped(tokens: int) -> int:
    return tokens // STEP * STEP
#: Default ceiling on one model's KV cache, which llama-server allocates whole at load; set on a 32 GB machine.
KV_MAX_GIB = 8
#: The unified memory KV_MAX_GIB was set on; other machines scale it by their RAM, as inspect.MEMORY_CEILING does. #692.
KV_MAX_RAM_GB = 32
#: Tokens llama-server keeps per sliding-window layer beyond the window: one ubatch. #692.
SWA_UBATCH = 512
#: arch -> period of its hard-coded sliding-window pattern (n-1 local layers, then one global), where the header has none.
SWA_PERIOD = {"gemma2": 2, "gemma3": 6, "cohere2": 4, "gpt-oss": 2}
#: Bytes per cached element for each llama-server cache type, as (numerator, denominator).
CACHE_BYTES = {"f32": (4, 1), "f16": (2, 1), "bf16": (2, 1), "q8_0": (34, 32),
               "q5_1": (24, 32), "q5_0": (22, 32), "q4_1": (20, 32),
               "q4_0": (18, 32), "iq4_nl": (18, 32)}


#: Qwen2.5-7B-Instruct-Q4_K_M (once eval-7b) serves infovore's bulk claims run in parallel: slots, and the context each slot is sized for. #665.
EVAL_7B_STEM = "Qwen2.5-7B-Instruct-Q4_K_M"
EVAL_7B_SLOTS = 8
EVAL_7B_SLOT_CTX = 4096
#: A claims request is a 6000-character window and a 400-token reply; no slot is sized under it. #665.
MIN_SLOT_CTX = 3072

#: Ornith-1.5-35B-Q4_K_M serves the code lane, the agent lane and local_complete: slots, each at its full trained context. #682.
ORNITH_STEM = "Ornith-1.5-35B-Q4_K_M"
ORNITH_SLOTS = 4
ORNITH_SLOT_CTX = 262144
#: The agent lane and the 65536 budget-ladder rung need one slot to hold more than this. #682.
MIN_LONG_SLOT_CTX = 131072

#: Slots every other GGUF is served with, the measured knee of the code model (#682); fewer when the room does not hold them. #699.
LLAMACPP_SLOTS = 4

#: stem -> (slots constant, slot context constant, floor constant, what the floor is for), read at call time.
SLOT_PLANS = {EVAL_7B_STEM: ("EVAL_7B_SLOTS", "EVAL_7B_SLOT_CTX", "MIN_SLOT_CTX", "a claims request"),
              ORNITH_STEM: ("ORNITH_SLOTS", "ORNITH_SLOT_CTX", "MIN_LONG_SLOT_CTX",
                            "the agent lane and the 64k ladder rung")}


def slot_plan(stem: str) -> tuple[int, int] | None:
    """(slots, context per slot) a stem is served at by name, else None for the memory plan."""
    names = SLOT_PLANS.get(stem)
    if names is None:
        return None
    here = globals()
    slots, slot_ctx, floor = (int(here[n]) for n in names[:3])
    if slot_ctx < floor:
        raise ValueError(f"{stem}: {slot_ctx} tokens per slot is under the "
                         f"{floor}-token floor {names[3]} needs")
    return max(slots, 1), slot_ctx


def choose_slots(meta: dict, weights: int, budget: int, slots: int, slot_ctx: int,
                 cache_type: str = "f16", kv_cap: int | None = None) -> "Choice":
    """A pool of slots * slot_ctx shared by the slots, when it fits beside the weights and one slot fits kv_cap."""
    full = trained(meta)
    per = kv_bytes_per_token(meta, cache_type)
    pool = slots * slot_ctx
    room = max(budget - weights - swa_bytes(meta, cache_type) * slots, 0)
    if not per or not full or slot_ctx > full:
        return Choice(0, full, per, f"refused: {slots} slots of {slot_ctx} tokens, "
                      f"trained for {full}, {per} B/token")
    # The cap bounds what one request's context may cost; the budget bounds the pool. #682.
    if kv_cap is not None and slot_ctx * per > kv_cap:
        return Choice(0, full, per, f"refused: one slot of {slot_ctx} tokens needs "
                      f"{slot_ctx * per / 1024 ** 3:.1f} GiB of KV, over the "
                      f"{kv_cap / 1024 ** 3:.1f} GiB cap")
    if pool * per > room:
        return Choice(0, full, per, f"refused: {slots} slots of {slot_ctx} tokens need "
                      f"{pool * per / 1024 ** 3:.1f} GiB of KV, {room / 1024 ** 3:.1f} GiB fits")
    return Choice(pool, full, per, f"slots: {slots} x {slot_ctx} tokens, "
                  f"{pool * per / 1024 ** 3:.1f} GiB of KV (#665)")


def fitting_slots(meta: dict, weights: int, budget: int, slots: int, slot_ctx: int,
                  cache_type: str = "f16", kv_cap: int | None = None) -> tuple[int, "Choice"]:
    """The most slots up to `slots` whose pool fits, so a knob set for a bigger machine serves fewer, not none. #682."""
    first = choose_slots(meta, weights, budget, slots, slot_ctx, cache_type, kv_cap)
    if first.ctx:
        return slots, first
    for n in range(slots - 1, 0, -1):
        got = choose_slots(meta, weights, budget, n, slot_ctx, cache_type, kv_cap)
        if got.ctx:
            return n, got._replace(why=f"{got.why}; {slots} asked, {n} fit")
    return slots, first


def shared_pool(meta: dict, weights: int, budget: int, slots: int, slot_ctx: int,
                cache_type: str = "f16", kv_cap: int | None = None) -> "Choice":
    """slots x slot_ctx when it fits, else one unified pool of the room that still holds one slot_ctx request. #748."""
    got = choose_slots(meta, weights, budget, slots, slot_ctx, cache_type, kv_cap)
    if got.ctx or not got.kv_per_token or got.why.startswith("refused: one slot"):
        return got
    per = got.kv_per_token
    pool = min(slots * slot_ctx, _stepped(max(budget - weights, 0) // per))
    if pool < slot_ctx or slot_ctx > got.trained:
        return got
    return Choice(pool, got.trained, per, f"shared pool: {slots} slots over {pool} tokens, "
                  f"{pool * per / 1024 ** 3:.1f} GiB of KV; one request up to {slot_ctx}, "
                  f"concurrent long ones can fill it (#748)", pool // slots)


class Choice(NamedTuple):
    #: llama-server's c: the pool every slot shares.
    ctx: int
    trained: int
    kv_per_token: int
    why: str
    #: What each slot is sized for when all of them are busy. #699.
    slot_ctx: int = 0


def _arch(meta: dict, key: str, default=None):
    return meta.get(f"{meta.get('general.architecture', '')}.{key}", default)


def trained(meta: dict) -> int:
    """The context the model was trained for, 0 when the header does not say."""
    return int(_arch(meta, "context_length") or 0)


def _layer_heads(meta: dict) -> list[int]:
    """KV heads per layer, 0 for a recurrent layer; a hybrid's layers are its attention layers only."""
    blocks = int(_arch(meta, "block_count") or 0)
    heads = _arch(meta, "attention.head_count_kv", _arch(meta, "attention.head_count"))
    if isinstance(heads, list):
        return [int(h or 0) for h in heads]
    if not heads or not blocks:
        return []
    layers = blocks - int(_arch(meta, "nextn_predict_layers") or 0)
    interval = int(_arch(meta, "full_attention_interval") or 0)
    if interval > 1:
        layers //= interval
    return [int(heads)] * layers


def _kv_heads(meta: dict) -> list[int]:
    """KV heads per KV-bearing layer; recurrent layers are left out."""
    return [h for h in _layer_heads(meta) if h]


def _swa_layers(meta: dict, n: int) -> list[bool]:
    """Which of n layers use a sliding window: the header's pattern, else the arch's known period. #692."""
    if not _arch(meta, "attention.sliding_window"):
        return [False] * n
    pattern = _arch(meta, "attention.sliding_window_pattern")
    if isinstance(pattern, list) and pattern:
        return [bool(pattern[i % len(pattern)]) for i in range(n)]
    period = SWA_PERIOD.get(str(meta.get("general.architecture", "")), 0)
    return [period > 1 and i % period < period - 1 for i in range(n)]


def _per_layer_bytes(meta: dict, swa: bool) -> int:
    q_heads = _arch(meta, "attention.head_count")
    q_heads = max(q_heads) if isinstance(q_heads, list) else q_heads
    embd = _arch(meta, "embedding_length")
    per_head = embd // q_heads if embd and q_heads else 0
    k = int(_arch(meta, "attention.key_length") or per_head)
    v = int(_arch(meta, "attention.value_length") or per_head)
    if swa:
        k = int(_arch(meta, "attention.key_length_swa") or k)
        v = int(_arch(meta, "attention.value_length_swa") or v)
    return k + v


def _split(meta: dict, cache_type: str) -> tuple[int, int]:
    """(bytes per token of the layers that grow with the context, bytes per token of the sliding-window layers)."""
    heads = _layer_heads(meta)
    swa = _swa_layers(meta, len(heads))
    num, den = CACHE_BYTES[cache_type]
    full = sum(h * _per_layer_bytes(meta, False) for h, w in zip(heads, swa) if h and not w)
    local = sum(h * _per_layer_bytes(meta, True) for h, w in zip(heads, swa) if h and w)
    return full * num // den, local * num // den


def kv_bytes_per_token(meta: dict, cache_type: str = "f16") -> int:
    """KV bytes one more token of context costs; sliding-window layers are not, they hold their window. 0 if unknown."""
    return _split(meta, cache_type)[0]


def swa_bytes(meta: dict, cache_type: str = "f16") -> int:
    """KV bytes one slot's sliding-window layers hold whatever the context: the window plus one ubatch. #692."""
    local = _split(meta, cache_type)[1]
    return local * (int(_arch(meta, "attention.sliding_window") or 0) + SWA_UBATCH) if local else 0


def _too_big_why(weights: int, budget: int) -> str:
    """Why a model whose weights alone exceed the budget is not served. #779.

    SAY THE TERM THAT ACTUALLY REFUSED IT. This used to fall through to the KV
    arithmetic, which then reported "0.0 GiB of KV room holds 0 tokens", and
    that reads as a context problem fixable by asking for less context. It is
    not. The weights do not fit, and no context would make them.

    Where the platform has a commit limit, the host side is named too, because
    that is the wall a partly offloaded model actually hits. An 18.48 GiB model
    on a 12 GiB card served at 2.1 tok/s with 0.58 GiB of commit headroom left,
    which is half a gigabyte from allocations failing across the whole machine.
    Reporting only the VRAM shortfall would invite someone to offload the
    remainder and meet that wall without warning.
    """
    from harness import memory
    why = (f"refused: {weights / 1024 ** 3:.1f} GiB of weights over the "
           f"{budget / 1024 ** 3:.1f} GiB budget")
    head = memory.commit_headroom_gb()
    if head is None:
        # No commit limit to read, so no claim about the host side. macOS grows
        # swap until the disk is gone; inventing a number here would be worse
        # than the silence.
        return why
    # NOT "over by N GiB", WHICH INVITES THE WRONG SUM. The shortfall is not
    # the host cost: partly offloading an 18.48 GiB file committed 20.23 GiB of
    # private host memory, the whole model plus overhead, not the 8.5 GiB that
    # did not fit on the card. A reader given the shortfall and the headroom
    # would compare 8.5 against 13.0, conclude it fits, and meet the commit
    # limit instead.
    return (f"{why}; offloading the rest commits the whole file in host "
            f"memory, not the shortfall, against {head:.1f} GiB of commit "
            f"headroom")


def choose(meta: dict, weights: int, budget: int, slots: int = 1,
           cache_type: str = "f16", floor: int = FLOOR,
           kv_cap: int | None = None) -> Choice:
    """A pool of slots x min(trained, each slot's share of the room under kv_cap), in steps of 1024; 0 when a slot is below `floor`."""
    full = trained(meta)
    per = kv_bytes_per_token(meta, cache_type)
    if not full or not per:
        return Choice(0, full, per, "refused: the GGUF header gives no trained context "
                      "or KV shape to size a cache from")
    if weights >= budget:
        return Choice(0, full, per, _too_big_why(weights, budget))
    room = max(budget - weights, 0)
    room = min(room, kv_cap) if kv_cap is not None else room
    slots = max(slots, 1)
    room = max(room - swa_bytes(meta, cache_type) * slots, 0)
    fits = _stepped(room // per // slots)
    ctx = min(_stepped(full) or full, fits)
    if ctx < floor:
        limit = (f"trained for {full}" if full < floor else
                 f"{room / 1024 ** 3:.1f} GiB of KV room "
                 f"holds {fits} tokens at {per} B/token")
        return Choice(0, full, per, f"refused: {limit}, under the {floor}-token floor")
    shape = f"{slots} x " if slots > 1 else ""
    if ctx < full:
        return Choice(ctx * slots, full, per, f"memory: {shape}{fits} tokens fit in "
                      f"{room / 1024 ** 3:.1f} GiB of KV at {per} B/token "
                      f"(trained {full})", ctx)
    return Choice(ctx * slots, full, per, f"trained: {shape}{full} tokens, "
                  f"{per * ctx * slots / 1024 ** 3:.1f} GiB of KV fits", ctx)


def read_meta(path) -> dict:
    """The key/value metadata of a GGUF file; long arrays come back as None."""
    with open(path, "rb") as fh:
        if fh.read(4) != b"GGUF":
            raise ValueError(f"{Path(path).name}: not a GGUF file")
        version = _read(fh, "<I")
        if version < 2:
            raise ValueError(f"{Path(path).name}: GGUF v{version} is not read")
        _read(fh, "<Q")
        count = _read(fh, "<Q")
        meta = {}
        for _ in range(count):
            key = _string(fh)
            meta[key] = _value(fh, _read(fh, "<I"))
            if meta[key] is None and not key.startswith("tokenizer."):
                from harness import cuts
                cuts.cut("gguf_keep_array", f"GGUF array {key} skipped unread")
        return meta


def _weights(path) -> int:
    return Path(path).stat().st_size


def budget_bytes(conn=None) -> int:
    """The machine's ceiling less its measured reserve (#415): what weights plus KV may take."""
    from harness import memory
    return int((memory.ceiling_gb() - memory.measured_reserve_gb(conn)) * 1024 ** 3)


def kv_cap_bytes() -> int:
    """The most KV cache one model may allocate: LLAMACPP_KV_MAX_GIB, else KV_MAX_GIB scaled by this machine's RAM. #692."""
    import os
    if os.environ.get("LLAMACPP_KV_MAX_GIB"):
        return int(float(os.environ["LLAMACPP_KV_MAX_GIB"]) * 1024 ** 3)
    from harness import memory
    return int(KV_MAX_GIB * memory.total_gb() / KV_MAX_RAM_GB * 1024 ** 3)


def coresident_bytes(conn, defaults=None, config=None, size_of=None) -> int:
    """The largest text model this machine serves on mlx_lm.server, which stays resident beside the router."""
    from harness import downloads, gateway, lanes, memory, serving
    if defaults is None:
        from harness import adopt
        defaults = adopt.lane_defaults(conn)
    if size_of is None:
        def size_of(repo):
            path = downloads.path_of(repo, conn, kind=downloads.HUB)
            got = memory.size_gb(str(path)) if path else None
            return int(got * 1024 ** 3) if got else 0
    text = set(lanes.TEXT_SERVED) | set(gateway.TEXT_LANES)
    entries = {str(e.get("model_name", "")).lower(): e
               for e in gateway.load(config).get("model_list") or []}
    best = 0
    for lane, spec in defaults.items():
        name = (spec or "").partition(",")[0].strip()
        if lane not in text or not name or ":" in name:
            continue
        entry = entries.get(name.lower())
        # A model served by another machine is not resident in this one's memory.
        if entry and not serving.loopback(serving.api_base(entry) or serving.MLX_URL):
            continue
        if serving.engine_for(name, config=config) == serving.LLAMACPP:
            continue
        repo = (gateway.strip_provider(str((entry.get("litellm_params") or {}).get("model", "")))
                if entry else name)
        if "/" in repo:
            best = max(best, int(size_of(repo) or 0))
    return best


def _ram_models_max() -> int:
    """LLAMACPP_MAX_MODELS, else what scripts/router-max-models.sh allows for this machine's RAM. #644."""
    got = (os.environ.get("LLAMACPP_MAX_MODELS") or "").strip()
    if got.isdigit() and int(got) > 0:
        return int(got)
    from harness import memory
    return 2 if memory.total_gb() >= 64 else 1


def router_rows(conn) -> list[dict]:
    """Live GGUF rows whose file is in the dir the router reads, the only stems it can load. #780."""
    from harness import downloads, gguf
    where = gguf.models_dir().resolve()
    return [r for r in downloads.live(conn, kind=downloads.GGUF)
            if Path(r["path"]).exists() and Path(r["path"]).parent.resolve() == where]


def router_bytes(conn) -> int:
    """Weights plus planned KV of the heaviest router models that may be resident at once on this machine. #699."""
    held = []
    for row in router_rows(conn):
        path = Path(row["path"])
        if row.get("ctx_at") and row.get("ctx"):
            held.append(_weights(path) + int(row["ctx"]) * int(row.get("kv_bytes_token") or 0))
    return sum(sorted(held, reverse=True)[:recorded_models_max()])


def recorded_models_max() -> int:
    """The most residents any router preset on this machine was planned for, at most _ram_models_max(). #699."""
    from harness import paths
    cap = _ram_models_max()
    got = []
    for f in paths.home().glob("llamacpp-preset-*.ini.models-max"):
        text = f.read_text(encoding="utf-8").strip()
        if text.isdigit() and int(text) > 0:
            got.append(int(text))
    return min(max(got), cap) if got else cap


def models_max_path(preset) -> Path:
    """Where main() writes the models-max the plan was sized for, beside the preset. #699."""
    return Path(f"{preset}.models-max")


def _sized(meta: dict, weights: int, alone: int, room: int, fixed, n: int, cache_type: str,
           kv_cap: int | None) -> tuple[int, Choice]:
    """(slots, choice) for one GGUF: its own slot plan when it has one, else the most slots up to `n` that fit."""
    if fixed:
        # The slots it serves alone, sharing whatever pool the k-resident room holds. #748.
        n, got = fitting_slots(meta, weights, alone, *fixed, cache_type, kv_cap)
        pooled = shared_pool(meta, weights, room, n, fixed[1], cache_type, kv_cap) if got.ctx else got
        return n, (got if pooled.ctx == got.ctx else pooled)
    got = choose(meta, weights, room, n, cache_type, kv_cap=kv_cap)
    while not got.ctx and n > 1:
        n -= 1
        got = choose(meta, weights, room, n, cache_type, kv_cap=kv_cap)
    return n, got


def _bound(meta: dict, weights: int, alone: int, room: int, fixed, n: int, cache_type: str, kv_cap: int | None,
           got: Choice) -> str:
    """The limit that made this plan smaller than the room allows: cap, floor, plan, pool, slots; "" for none."""
    if _sized(meta, weights, alone, room, fixed, n, cache_type, None)[1].ctx > got.ctx:
        return "cap"
    if not got.ctx:
        if fixed:
            return "plan" if choose(meta, weights, room, 1, cache_type).ctx else ""
        return "floor" if got.why.endswith("-token floor") else ""
    if fixed and n > 1 and got.ctx < n * fixed[1]:
        return "pool"
    if not fixed and n > 1 and choose(meta, weights, room, 1, cache_type, kv_cap=kv_cap).slot_ctx > got.slot_ctx:
        return "slots"
    return ""


def _cuts(conn, bound: dict, slots: int) -> None:
    """One limit_cuts row per limit that shrank or refused a planned GGUF context."""
    from harness import cuts
    if bound.get("floor"):
        cuts.cut("harness/context.py:FLOOR", f"GGUFs refused under the context floor: {', '.join(bound['floor'])}",
                 kept=0, dropped=len(bound["floor"]), conn=conn)
    if bound.get("cap"):
        cuts.cut("kv_cap", f"GGUF contexts the KV cap shrank or refused: {', '.join(bound['cap'])}",
                 dropped=len(bound["cap"]), conn=conn)
    for stem in bound.get("plan", ()):
        slot_knob = "eval7b_slot_ctx" if stem == EVAL_7B_STEM else "ornith_slot_ctx"
        cuts.cut(slot_knob, f"{stem}: its slot plan does not fit, though a smaller context would", kept=0, dropped=1,
                 conn=conn)
    for stem in bound.get("pool", ()):
        slots_knob = "eval7b_slots" if stem == EVAL_7B_STEM else "ornith_slots"
        cuts.cut(slots_knob, f"{stem}: its slots share a pool smaller than each one's context, so busy slots can run "
                 "out of room", conn=conn)
    if bound.get("slots"):
        cuts.cut("llamacpp_slots", f"GGUFs whose slots split the context one request may use: "
                 f"{', '.join(bound['slots'])}", value=slots, conn=conn)


def plan(conn, budget: int | None = None, slots: int = 1,
         cache_type: str = "f16", kv_cap: int | None = None,
         models_max: int = 1, record: bool = True) -> list[dict]:
    """Choose and record the context of every live GGUF row on this machine, so any
    `models_max` of them resident at once fit the budget together. #699."""
    import time

    budget = budget_bytes(conn) if budget is None else budget
    kv_cap = kv_cap_bytes() if kv_cap is None else kv_cap
    from harness import serving
    try:
        beside = coresident_bytes(conn)
    except serving.UnknownEngine:
        raise
    except Exception:  # noqa: BLE001
        beside = 0
    rows = router_rows(conn)
    sizes = [_weights(r["path"]) for r in rows]
    k = max(min(models_max, len(sizes)), 1)
    heaviest = sum(sorted(sizes, reverse=True)[:k])
    out = []
    bound: dict[str, list[str]] = {}
    for row in rows:
        path = Path(row["path"])
        stem = path.name[:-len(".gguf")]
        fixed = slot_plan(stem)
        n = fixed[0] if fixed else max(slots, 1)
        try:
            meta, weights = read_meta(path), _weights(path)
            # With k resident, each gets an equal share of what the k heaviest weights leave. #699.
            room = budget - beside if k == 1 else weights + max(budget - beside - heaviest, 0) // k
            asked = n
            n, got = _sized(meta, weights, budget - beside, room, fixed, n, cache_type, kv_cap)
            if record:
                bound.setdefault(_bound(meta, weights, budget - beside, room, fixed, asked, cache_type, kv_cap, got),
                                 []).append(stem)
        except (OSError, ValueError, KeyError, struct.error) as exc:
            got = Choice(0, 0, 0, f"refused: unreadable GGUF header ({exc})")
        if k > 1 and got.ctx:
            got = got._replace(why=f"{got.why}; {k} resident share {budget - beside - heaviest >> 20} MiB of KV")
        out.append({"stem": stem, "path": str(path), "ctx": got.ctx, "slots": n,
                    "why": got.why})
        if not record:
            continue
        conn.execute("UPDATE downloads SET ctx = ?, ctx_trained = ?, kv_bytes_token = ?, "
                     "ctx_slots = ?, ctx_why = ?, ctx_at = ?, kv_cap_bytes = ?, "
                     "coresident_bytes = ? WHERE id = ?",
                     (got.ctx, got.trained, got.kv_per_token, n, got.why,
                      time.time(), kv_cap, beside, row["id"]))
    if record:
        _cuts(conn, bound, slots)
        conn.commit()
    return out


def plan_router(conn, slots: int, cache_type: str = "f16") -> tuple[list[dict], int]:
    """The most resident models up to _ram_models_max() that serve every stem one alone would, and the plan recorded for it. #699."""
    cap = _ram_models_max()
    alone = {p["stem"] for p in plan(conn, slots=slots, cache_type=cache_type, record=False) if p["ctx"]}
    chosen = 1
    for k in range(cap, 1, -1):
        got = plan(conn, slots=slots, cache_type=cache_type, models_max=k, record=False)
        if alone <= {p["stem"] for p in got if p["ctx"]}:
            chosen = k
            break
    return plan(conn, slots=slots, cache_type=cache_type, models_max=chosen), chosen


def served(conn, stem: str) -> dict | None:
    """The recorded context row for a router stem on this machine, or None."""
    from harness import downloads
    for row in downloads.live(conn, kind=downloads.GGUF):
        if Path(row["path"]).name == f"{stem}.gguf" and row.get("ctx_at"):
            return row
    return None


def _get_json(url: str, key: str = "") -> dict:
    import json
    import urllib.request
    from harness import cuts
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"} if key else {})
    with cuts.timeout("harness/context.py:_get_json->urllib.request.urlopen(timeout)", f"{url}: no answer in time"):
        with urllib.request.urlopen(req, timeout=5.0) as r:
            return json.loads(r.read() or b"{}")


def _entry_for(spec: str, config=None) -> dict | None:
    from harness import gateway
    name = (spec or "").partition(",")[0].strip()
    served = gateway.served_path(config)
    for entry in gateway.load(served if served.exists() else config).get("model_list") or []:
        if str(entry.get("model_name", "")).lower() == name.lower():
            return entry
    return None


def _key(spec: str, config=None) -> str:
    """The key a gateway entry sends upstream, read from the environment it names; "" for none. #684."""
    raw = str(((_entry_for(spec, config) or {}).get("litellm_params") or {}).get("api_key") or "")
    if raw.startswith("os.environ/"):
        return os.environ.get(raw[len("os.environ/"):], "").strip()
    return "" if raw in ("", "not-needed") else raw


def _upstream(spec: str, config=None) -> tuple[str, str] | None:
    """(router base URL, stem) a text spec reaches llama-server through, else None."""
    from harness import gateway, router
    from harness.serving import LLAMACPP_PREFIX
    name = (spec or "").partition(",")[0].strip()
    if name.startswith(LLAMACPP_PREFIX):
        return router.url(), name[len(LLAMACPP_PREFIX):].strip()
    if not name or ":" in name:
        return None
    entry = _entry_for(name, config)
    if entry is None:
        return None
    params = entry.get("litellm_params") or {}
    base = str(params.get("api_base", "")).rstrip("/").removesuffix("/v1")
    return (base, gateway.strip_provider(str(params.get("model", "")))) if base else None


def _props(base: str, key: str, get=None) -> dict:
    """A single-model llama-server's /props: {"ctx": per-slot context, "slots"}; {} when it does not say. #684."""
    try:
        got = get(base + "/props") if get else _get_json(base + "/props", key)
    except Exception:  # noqa: BLE001 - not llama-server, or not answering
        return {}
    ctx = (got.get("default_generation_settings") or {}).get("n_ctx")
    return {k: int(v) for k, v in (("ctx", ctx), ("slots", got.get("total_slots"))) if v}


def served_ctx(spec: str, config=None, get=None, conn=None) -> int | None:
    """The per-slot context llama-server serves this spec at: the router's own launch args,
    else the stored choice; None when neither says (another engine, or unknown)."""
    from harness import ds4
    if (spec or "").startswith(ds4.PREFIX):
        return ds4.served_ctx(spec)
    where = _upstream(spec, config)
    if where is None:
        return None
    base, stem = where
    key = _key(spec, config)
    try:
        for m in (get(base + "/models") if get else _get_json(base + "/models", key)
                  ).get("data") or []:
            args = (m.get("status") or {}).get("args") or [] if isinstance(m, dict) else []
            if m.get("id") == stem and "--ctx-size" in args:
                return _per_slot(stem, args, conn)
    except Exception:  # noqa: BLE001
        pass
    from harness import serving
    # The stored choice was planned for this machine; a remote server says itself or is unknown. #722.
    if not serving.loopback(base):
        return _props(base, key, get).get("ctx")
    from harness import downloads
    try:
        with downloads.store(conn) as c:
            row = served(c, stem)
    except Exception:  # noqa: BLE001
        return None
    if not row or not row["ctx"]:
        return None
    # A sized pool is unified, so one request reaches up to the trained length. #682.
    ctx, slots, full = int(row["ctx"]), int(row["ctx_slots"] or 1), int(row["ctx_trained"] or 0)
    return ctx if slots <= 1 else (min(ctx, full) if full else ctx // slots)


def _trained_of(stem: str, conn=None) -> int:
    """The trained context recorded for a router stem, 0 when none is."""
    from harness import downloads
    try:
        with downloads.store(conn) as c:
            row = served(c, stem)
    except Exception:  # noqa: BLE001
        return 0
    return int(row["ctx_trained"] or 0) if row else 0


def _per_slot(stem: str, args: list, conn=None) -> int:
    """What one request can reach: its share of a split pool, or a unified pool up to the trained length. #682."""
    ctx = int(args[args.index("--ctx-size") + 1])
    slots = int(args[args.index("--parallel") + 1]) if "--parallel" in args else 1
    if slots <= 1:
        return ctx
    full = _trained_of(stem, conn) if "--kv-unified" in args else 0
    return min(ctx, full) if full else ctx // slots


def served_slots(spec: str, config=None, get=None) -> int | None:
    """The slots llama-server serves this spec with, from the router's launch args; None if unknown. #697."""
    where = _upstream(spec, config)
    if where is None:
        return None
    base, stem = where
    key = _key(spec, config)
    try:
        for m in (get(base + "/models") if get else _get_json(base + "/models", key)
                  ).get("data") or []:
            args = (m.get("status") or {}).get("args") or [] if isinstance(m, dict) else []
            for flag in ("--parallel", "-np"):
                if m.get("id") == stem and flag in args:
                    return int(args[args.index(flag) + 1])
    except Exception:  # noqa: BLE001 - an unreachable router serves an unknown shape
        return None
    from harness import serving
    return None if serving.loopback(base) else _props(base, key, get).get("slots")


#: llama-server's /props sampler names, as the request keys they default. #921.
PROPS_SAMPLER = {"temperature": "temperature", "top_p": "top_p", "top_k": "top_k", "min_p": "min_p",
                 "presence_penalty": "presence_penalty", "repeat_penalty": "repetition_penalty"}


def served_sampler(spec: str, config=None, get=None) -> dict:
    """The sampler llama-server applies where a request names no value, from its /props; {} when it does not say. #921."""
    where = _upstream(spec, config)
    if where is None:
        return {}
    base, stem = where
    try:
        url = f"{base}/props?model={stem}"
        got = (get(url) if get else _get_json(url, _key(spec, config))).get("default_generation_settings") or {}
    except Exception:  # noqa: BLE001 - not llama-server, or not answering
        return {}
    params = got.get("params") if isinstance(got.get("params"), dict) else got
    return {ours: params[theirs] for theirs, ours in PROPS_SAMPLER.items()
            if isinstance(params.get(theirs), (int, float))}


def refusal(stem: str, conn=None) -> str:
    """Why this stem is not served, or "" when it is or nothing is recorded."""
    from harness import downloads
    try:
        with downloads.store(conn) as c:
            row = served(c, stem)
    except Exception:  # noqa: BLE001
        return ""
    return row["ctx_why"] if row and not row["ctx"] else ""


def planned(stem: str, conn=None) -> bool:
    """Whether the recorded llama-server plan serves this stem with a context. #1047."""
    from harness import downloads
    try:
        with downloads.store(conn) as c:
            row = served(c, stem)
    except Exception:  # noqa: BLE001 - an unreadable store serves nothing
        return False
    return bool(row and row["ctx"])


def preset_text(plans: list[dict], default_ctx: int, slots: int, cache_type: str = "f16") -> str:
    """llama-server's --models-preset INI: [*] for unrecorded files, one section per servable stem."""
    def args(ctx: int, n: int) -> list[str]:
        # The KV type the plan priced, so the server allocates what was budgeted. #521.
        out = [f"c = {ctx}", f"parallel = {n}", f"cache-type-k = {cache_type}",
               f"cache-type-v = {cache_type}"]
        return out + ["kv-unified = true"] if n > 1 else out
    lines = ["version = 1", "", "[*]", *args(default_ctx, slots), ""]
    for p in sorted(plans, key=lambda p: p["stem"]):
        if p["ctx"]:
            lines += [f"; {p['why']}", f"[{p['stem']}]", *args(p["ctx"], p.get("slots", slots)), ""]
        else:
            lines += [f"; {p['stem']} {p['why']}", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    """`python -m harness.context OUT.ini`: plan, record and write the router preset."""
    import os
    import sys

    from harness import memory_store as ms
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m harness.context PRESET.ini", file=sys.stderr)
        return 2
    slots = max(int(os.environ.get("LLAMACPP_PARALLEL") or LLAMACPP_SLOTS), 1)
    cache = os.environ.get("LLAMACPP_CACHE_TYPE") or "f16"
    default = int(os.environ.get("LLAMACPP_CTX") or 16384)
    conn = ms.connect()
    try:
        plans, models_max = plan_router(conn, slots, cache)
    finally:
        conn.close()
    for p in plans:
        print(f"context: {p['stem']}: {p['ctx'] or 'refused'} ({p['why']})", file=sys.stderr)
    Path(argv[0]).write_text(preset_text(plans, default, slots, cache), encoding="utf-8")
    models_max_path(argv[0]).write_text(f"{models_max}\n", encoding="utf-8")
    print(argv[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

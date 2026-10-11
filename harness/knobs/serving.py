"""Knobs of slots and context of served models, and what a server listens on (#751)."""
from harness.knobs.base import MACHINE, TEXT_LANES, _k

KNOBS = [
    _k("eval7b_slot_ctx", ["harness/context.py:EVAL_7B_SLOT_CTX"], [3072, 4096, 8192],
       note="context each Qwen2.5-7B-Instruct-Q4_K_M slot is sized for; never under context.MIN_SLOT_CTX (#665)"),
    _k("eval7b_slots", ["harness/context.py:EVAL_7B_SLOTS"], [1, 4, 8, 16, 32],
       note="llama-server slots Qwen2.5-7B-Instruct-Q4_K_M batches across; sets claims throughput, not a grade (#665)"),
    _k("ornith_slot_ctx", ["harness/context.py:ORNITH_SLOT_CTX"], [131072, 262144],
       note="context each Ornith-1.5-35B-Q4_K_M slot is sized for; never under context.MIN_LONG_SLOT_CTX (#682)"),
    _k("ornith_slots", ["harness/context.py:ORNITH_SLOTS"], [1, 2, 4, 8],
       note="llama-server slots Ornith-1.5-35B-Q4_K_M batches across; sets code and agent lane throughput, not a grade (#682)"),
    _k("served_ctx", ["harness/context.py:KV_MAX_GIB", "harness/context.py:KV_MAX_RAM_GB", "harness/ds4.py:DEFAULT_CTX",
                      "harness/vllm.py:METAL_MAX_MODEL_LEN", "harness/context.py:environ(LLAMACPP_CTX)",
                      "scripts/serve-llamacpp.sh:LLAMACPP_CTX", "scripts/serve-llamacpp.sh:LLAMACPP_CTX#2"],
       [4, 8, 16, 24, 32], lanes=TEXT_LANES, limit="served_ctx", predicate=MACHINE,
       note="the context a model is served at: KV GiB per model on 32 GB (scaled by RAM), ds4 --ctx, vllm-metal "
            "--max-model-len, llama-server's unplanned default; the receipt records it as served ctx (#692)"),
]

NOT_GATING = {
    "harness/mcp_server.py:MAX_INLINE_BYTES": "how a result is returned, inline or as a path; never what it is",
    "harness/context.py:MIN_SLOT_CTX": "the floor the eval7b_slot_ctx range is held to; a preset under it is refused (#665)",
    "harness/context.py:MIN_LONG_SLOT_CTX": "the floor the ornith_slot_ctx range is held to; a preset under it is refused (#682)",
    "harness/audio_server.py:environ(AUDIO_PORT)": "where the audio server listens; never what it answers (#706)",
    **{f"harness/nodes.py:{n}": "a node's default, set per node in nodes.yaml; it decides which machine "
       "answers, which the receipt records, never whether a request is answered (#684)"
       for n in ("CONNECT_TIMEOUT_S", "TIMEOUT_S", "COOLDOWN_S", "_to_node->params.update(max_retries)")},
    "harness/nodes.py:keychain->subprocess.run(timeout)": "how long the Keychain may take to hand over a key (#684)",
    "harness/live_audit.py:FALLBACK_WINDOW_S": "how far back the audit lists node fallbacks; reported, never a check (#739)",
    "scripts/lan-probe.sh:LAN_PROBE_WAIT_EXTRA_S": "how long the deploy waits for a launchd probe to write; never a lane's outcome (#739)",
    **{f"harness/context.py:SWA_PERIOD[{a}]": "llama.cpp's hard-coded sliding-window period of an architecture, a fact of "
       "the model (#692)" for a in ("gemma2", "gemma3", "cohere2")},
    **{f"harness/context.py:CACHE_BYTES[{t}]": "bytes per KV element of a cache type, a fact of the format (#706)"
       for t in ("f32", "f16", "bf16", "q8_0", "q5_1", "q5_0", "q4_1", "q4_0", "iq4_nl")},
    "harness/mcp_server.py:JobInfo.seconds": "how long a job took, as reported (#706)",
    **{site: "where a server listens; never what it answers (#706)" for site in (
        "scripts/serve-audio-cuda.sh:AUDIO_PORT",
        "scripts/serve-ds4.sh:DS4_PORT",
        "scripts/serve-eval.sh:LLAMACPP_PORT",
        "scripts/serve-gateway.sh:GATEWAY_PORT",
        "scripts/serve-llamacpp.sh:LLAMACPP_PORT",
        "scripts/serve-llamacpp.sh:LLAMACPP_PORT#2",
        "scripts/serve-llamacpp.sh:LLAMACPP_PORT#3",
        "scripts/serve-mcp.sh:MCP_PORT",
        "scripts/serve-mlx.sh:MLX_PORT",
        "scripts/serve-tts.sh:TTS_PORT",
        "scripts/services.sh:GATEWAY_PORT",
        "scripts/services.sh:LLAMACPP_PORT",
        "scripts/services.sh:LLAMACPP_PORT#2",
        "scripts/services.sh:LLAMACPP_PORT#3",
        "scripts/services.sh:AUDIO_PORT",
        "scripts/services.sh:DS4_PORT",
        "scripts/slots-sweep.sh:SWEEP_PORT",
        "scripts/smoke.sh:GATEWAY_PORT",
        "scripts/smoke.sh:MLX_PORT",
        "scripts/smoke.sh:TTS_PORT",
    )},
    "scripts/env.sh:HF_HUB_OFFLINE": "a switch, offline or not; never a threshold (#706)",
    "scripts/h3-weights-status.sh:BYTES": "the fallback of a measured size when none was measured (#706)",
    "scripts/router-max-models.sh:bytes": "the fallback of a measured RAM size when none was measured (#706)",
    "scripts/router-sleep-idle.sh:bytes": "the fallback of a measured RAM size when none was measured (#694)",
    **{site: "a ceiling held above the slowest load_timeout plus the longest reply_budget by a test, so the "
       "server or gateway never ends a request before the eval's own limit does (#694)" for site in (
        "scripts/serve-llamacpp.sh:LLAMACPP_TIMEOUT",
        "gateway/config.yaml:litellm_settings.request_timeout",
        "gateway/config.cuda.yaml:litellm_settings.request_timeout",
    )},
    **{f"gateway/{name}:litellm_settings.num_retries": "pinned at 0 by a test, so no retry hides a failed "
       "upstream or folds two attempts into one timing (#694)" for name in ("config.yaml", "config.cuda.yaml")},
}

"""Knobs of slots and context of served models, and what a server listens on (#751)."""
from harness.knobs.base import MACHINE, TEXT_LANES, _k

KNOBS = [
    _k("cloud_evals", ["harness/exclusive.py:CLOUD_SLOTS"], [1, 2, 3, 4],
       note="cloud-only evals at once, outside the GPU lock; job 0137 (repo, claude-code Opus) peaked at 0.19 "
            "cpu_active_ratio on the 30-core Studio, mean 0.08, GPU 0.05 (power.jsonl, 2026-10-22) (#1135)"),
    _k("context_step", ["harness/context.py:STEP"], [256, 1024, 4096],
       note="tokens a served context and its KV pool are rounded down to (#498)"),
    _k("eval7b_slot_ctx", ["harness/context.py:EVAL_7B_SLOT_CTX"], [3072, 4096, 8192],
       note="context each Qwen2.5-7B-Instruct-Q4_K_M slot is sized for; never under context.MIN_SLOT_CTX (#665)"),
    _k("eval7b_slots", ["harness/context.py:EVAL_7B_SLOTS"], [1, 4, 8, 16, 32],
       note="llama-server slots Qwen2.5-7B-Instruct-Q4_K_M batches across; sets claims throughput, not a grade (#665)"),
    _k("gateway_down_wait", ["evals/run.py:GATEWAY_DOWN_WAIT_S"], [30.0, 120.0, 300.0],
       note="seconds a warm-up asks again while nothing listens at the gateway before every case is refused_by_gateway; "
            "jobs 0141/0142 met a router restart that bound :8082 within 5 s (0143 warmed at 21:07:32), and a "
            "restart is given gguf.READY_TIMEOUT_S 120 s to answer (#1012, #1181)"),
    _k("gguf_keep_array", ["harness/context.py:_KEEP_ARRAY"], [1024, 4096, 65536],
       note="GGUF metadata arrays longer than this are skipped unread: tokenizer vocabularies, never a per-layer array (#498)"),
    _k("gpu_fraction", ["harness/memory.py:GPU_FRACTION"], [0.65, 0.75, 0.85],
       note="share of RAM Metal hands out when sysctl iogpu.wired_limit_mb is unset; measured on 32 GB (#699)"),
    _k("kv_cap", ["harness/context.py:KV_MAX_GIB", "harness/context.py:KV_MAX_RAM_GB"], [4, 8, 16, 24, 32],
       note="GiB of KV one llama-server model may allocate on a 32 GB machine, scaled by RAM; it sets the planned "
            "served context, which binds as served_ctx (#692)"),
    _k("llamacpp_slots", ["harness/context.py:LLAMACPP_SLOTS"], [1, 2, 4, 8],
       note="llama-server slots every GGUF without its own slot plan batches across; throughput, not a grade (#699)"),
    _k("mlx_max_parallel", ["harness/serving.py:MLX_MAX_PARALLEL"], [4, 8, 16, 32],
       note="most requests the gateway lets mlx_lm.server hold; fewer when their KV does not fit (#542, #699)"),
    _k("mlx_prompt_cache_bytes", ["harness/mlx_server.py:PROMPT_CACHE_BYTES"], ["4GB", "8GB", "16GB"],
       note="bytes of KV cache mlx_lm.server keeps; mlx-lm leaves it unbounded (#912)"),
    _k("mlx_prompt_cache_size", ["harness/mlx_server.py:PROMPT_CACHE_SIZE"], [2, 4, 8, 10],
       note="distinct KV caches mlx_lm.server keeps; at mlx-lm's 10 Metal's 499000-buffer limit killed its "
            "generation thread (#912)"),
    _k("mlx_request_ctx", ["harness/serving.py:MLX_REQUEST_CTX"], [8192, 16384, 32768, 65536],
       note="context one MLX request's KV is priced at when the parallel cap is sized (#699)"),
    _k("mlx_swap_timeout", ["harness/mlx_server.py:SWAP_TIMEOUT_S"], [30.0, 120.0, 300.0],
       note="seconds a swap of the mlx server back to its boot model may take before the idle model is kept (#1082)"),
    _k("ornith_slot_ctx", ["harness/context.py:ORNITH_SLOT_CTX"], [131072, 262144],
       note="context each Ornith-1.5-35B-Q4_K_M slot is sized for; never under context.MIN_LONG_SLOT_CTX (#682)"),
    _k("ornith_slots", ["harness/context.py:ORNITH_SLOTS"], [1, 2, 4, 8],
       note="llama-server slots Ornith-1.5-35B-Q4_K_M batches across; sets code and agent lane throughput, not a grade (#682)"),
    _k("serve_idle_unload_day_s", ["harness/watchdog.py:IDLE_UNLOAD_DAY_S"], [300.0, 600.0, 900.0, 1800.0],
       note="seconds a Mac's watchdog leaves a loaded model with no request in the day hours before it gives it back; "
            "14 days of gateway requests: 600 s costs Ornith 0.8 cold loads a day (median 8.9 s, p90 80 s each) "
            "against 0.17 idle-but-loaded h, where never unloading held it all day (soh load-log --idle) (#1157)"),
    _k("serve_idle_unload_node_s", ["scripts/router-sleep-idle.sh:LLAMACPP_SLEEP_IDLE"], [60, 300, 900],
       note="llama-server's own idle sleep off a Mac, where no watchdog gives models back; on the 4070 VRAM read "
            "2473 MiB again fifteen seconds after a request (#694)"),
    _k("serve_idle_unload_s", ["scripts/router-sleep-idle.sh:SERVE_IDLE_UNLOAD_S"], [3600, 5400, 7200],
       note="llama-server's own idle sleep on a Mac and its watchdog's night limit; it outlasts the longest request "
            "a paired turn leaves the other model idle through, completion.timeout_for(65536) = 2621 s, and the "
            "longest stored local case, 1599 s (#694, #1157)"),
    _k("served_ctx", ["harness/context.py:environ(LLAMACPP_CTX)", "harness/ds4.py:DEFAULT_CTX",
                      "harness/vllm.py:METAL_MAX_MODEL_LEN",
                      "scripts/serve-llamacpp.sh:LLAMACPP_CTX", "scripts/serve-llamacpp.sh:LLAMACPP_CTX#2"],
       [8192, 16384, 32768, 65536, 131072], lanes=TEXT_LANES, limit="served_ctx", unit="tokens", predicate=MACHINE,
       note="tokens a model is served at: llama-server's unplanned default, ds4 --ctx, vllm-metal --max-model-len; "
            "a planned llama-server context is set by kv_cap; the receipt records it as served ctx (#692)"),
    _k("slot_probe_busy_wait", ["harness/slot_probe.py:BUSY_WAIT_S"], [1.0, 5.0, 10.0],
       note="seconds the smoke slot probe waits, its stream open, to see the slot busy before it closes the stream; "
            "the first poll usually sees it, so the bound only matters on a loaded machine (#1168)"),
    _k("slot_probe_max_tokens", ["harness/slot_probe.py:MAX_TOKENS"], [2048, 4096, 8192],
       note="tokens the smoke slot probe asks for; at the fastest stored llama-server decode (LFM2.5-350M, 310 tok/s "
            "on 2026-10-22) 4096 runs 13 s, past slot_probe_settle, so a natural finish cannot pass for a freed slot (#1127)"),
    _k("slot_probe_settle", ["harness/slot_probe.py:SETTLE_S"], [2.0, 5.0, 10.0],
       note="seconds a slot has to go idle after the probe closes its stream; llama-server checks the connection "
            "per token, a few ms at the stored decode rates, so 5 s is room for a busy machine (#1127)"),
]

NOT_GATING = {
    "harness/ds4.py:GIB": "bytes in a gibibyte (#611)",
    "evals/run.py:GATEWAY_DOWN_POLL_S": "how often a warm-up asks a refusing gateway again; gateway_down_wait bounds the wait (#1181)",
    "harness/idle_unload.py:WINDOW_DAYS": "how far back soh load-log --idle reads requests; evidence for a knob, never a limit (#1157)",
    "harness/slot_probe.py:POLL_S": "how often the slot probe asks /slots while it waits; slot_probe_settle bounds the wait (#1127)",
    "harness/commands/loop.py:LEASE_S": "how long a discover loop's store lease outlives a holder that died; "
                                        "it picks which machine sweeps, never a result (#703)",
    "harness/batch.py:TTL_S": "how long a batch lease outlives its last request; it picks which batch loads a "
                              "serving machine, never a result (#769)",
    "harness/batch.py:BUSY_WAIT_S": "how long a request waits out another batch; past it the request is "
                                    "refused_by_gateway, charged to the harness, never to the model (#769)",
    "harness/batch.py:BUSY_POLL_S": "how often a request refused as busy asks again; never a result (#769)",
    "harness/gguf.py:READY_TIMEOUT_S": "how long a fetch waits for a restarted router before saying so; a screen "
                                       "after it is refused_by_gateway, charged to the harness, never the model (#1012)",
    "harness/gguf.py:READY_POLL_S": "how often a restarted router is asked whether it answers yet; never a result (#1012)",
    "harness/exclusive.py:_renewing->t.join(timeout)": "how long a batch lease renewer may take to stop (#769)",
    "harness/gateway_switch.py:IDLE_S": "the quiet window a switch restarts in; it never cuts a request (#703)",
    "harness/gateway_switch.py:MAX_WAIT_S": "how long a switch waits for a quiet window before draining; the bound "
                                            "on a request in flight is DRAIN_S, derived from completion.timeout_for "
                                            "over every LADDER rung (#703)",
    "harness/mcp_server.py:MAX_INLINE_BYTES": "how a result is returned, inline or as a path; never what it is",
    "harness/mcp_server.py:SHUTDOWN_GRACE_S": "how long a stopping MCP server waits on open clients; never what a tool answers (#1155)",
    "harness/context.py:MIN_SLOT_CTX": "the floor the eval7b_slot_ctx range is held to; a preset under it is refused (#665)",
    "harness/context.py:MIN_LONG_SLOT_CTX": "the floor the ornith_slot_ctx range is held to; a preset under it is refused (#682)",
    "harness/context.py:Choice.slot_ctx": "a planned result's value before it is planned (#699)",
    "harness/context.py:plan(models_max)": "how many residents a plan is sized for; plan_router derives it from the plan (#699)",
    "harness/memory.py:_wired_limit_gb->subprocess.run(timeout)": "how long sysctl may take to answer (#699)",
    "harness/audio_server.py:environ(AUDIO_PORT)": "where the audio server listens; never what it answers (#706)",
    **{f"harness/nodes.py:{n}": "a node's default, set per node in nodes.yaml; it decides which machine "
       "answers, which the receipt records, never whether a request is answered (#684)"
       for n in ("CONNECT_TIMEOUT_S", "TIMEOUT_S", "COOLDOWN_S", "_to_node->params.update(max_retries)")},
    "harness/nodes.py:keychain->subprocess.run(timeout)": "how long the Keychain may take to hand over a key (#684)",
    "harness/machine.py:RETRY_S": "how soon a failed identity probe is asked again; never which machine answers (#747)",
    "harness/live_audit.py:FALLBACK_WINDOW_S": "how far back the audit lists node fallbacks; reported, never a check (#739)",
    "scripts/lan-probe.sh:LAN_PROBE_WAIT_EXTRA_S": "how long the deploy waits for a launchd probe to write; never a lane's outcome (#739)",
    "scripts/logs.sh:LOG_KEEP": "generations of a service log kept across restarts; how much history is readable, never what a lane measures (#786)",
    "scripts/logs.sh:LOG_MAX_BYTES": "size past which a kept log is dropped rather than given a generation slot; retention, never a lane's outcome (#786)",
    "scripts/launchd.sh:PREFLIGHT_WAIT_S": "how long install waits for the weights probe agent; a timeout is its own verdict, never a lane's outcome (#705)",
    **{f"harness/context.py:SWA_PERIOD[{a}]": "llama.cpp's hard-coded sliding-window period of an architecture, a fact of "
       "the model (#692)" for a in ("gemma2", "gemma3", "cohere2", "gpt-oss")},
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
        "scripts/serve-otel.sh:OTEL_PORT",
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
    **{site: "a ceiling held above the slowest load_timeout plus the longest reply_budget by a test, so the "
       "server or gateway never ends a request before the eval's own limit does (#694)" for site in (
        "scripts/serve-llamacpp.sh:LLAMACPP_TIMEOUT",
        "gateway/config.yaml:litellm_settings.request_timeout",
        "gateway/config.cuda.yaml:litellm_settings.request_timeout",
    )},
    **{f"gateway/{name}:litellm_settings.num_retries": "pinned at 0 by a test, so no retry hides a failed "
       "upstream or folds two attempts into one timing (#694)" for name in ("config.yaml", "config.cuda.yaml")},
}

NEVER_CUTS = {
    "scripts/h3-weights-status.sh:H3_TARGET_GIB": "the size the H3 status script reports progress against; it stops "
                                                  "and drops no download (#1087)",
    "scripts/router-sleep-idle.sh:LLAMACPP_SLEEP_IDLE": "seconds an idle llama-server waits before it sleeps; no request "
                                                        "is in flight, the next one pays a load (#1087)",
    "scripts/router-sleep-idle.sh:SERVE_IDLE_UNLOAD_S": "seconds an idle model stays loaded on a Mac; no request is in "
                                                        "flight, the next one pays a load (#1087)",
    "scripts/serve-llamacpp.sh:LLAMACPP_GPU_LAYERS": "layers placed on the GPU; placement sets speed, every layer still "
                                                     "runs (#1087)",
    "scripts/slots-sweep.sh:SWEEP_LONG": "tokens of an optional long-context probe, 0 to skip it by choice; it drops no "
                                         "config (#1087)",
    "harness/context.py:STEP": "the granularity a context is rounded down to; the KV room or trained context that binds "
                               "records under its own knob (#498)",
    **{f"evals/run.py:{f}(max_tokens)": "0 passes no override, so the runner asks at the lane's reply_budget, which "
       "records its own binding (#628)" for f in ("build_runner", "_agent_runner", "_build_runner")},
    "harness/vllm.py:_probe->_DIRECT.open(timeout)": "how long one readiness probe waits; a slow answer reads as not "
                                                     "up yet and is probed again, and served(timeout) records the cut",
}

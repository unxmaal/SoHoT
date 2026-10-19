"""Knobs of how big a weight, download or repo may be (#751)."""
from harness.knobs.base import GIB, MACHINE, _k

KNOBS = [
    _k("adapter_floor", ["harness/screen.py:ADAPTER_FLOOR_BYTES"], [1 * GIB, 2 * GIB, 4 * GIB, 8 * GIB],
       note="loose weights under this, named a LoRA or adapter by a tag, are an attachment (#949)"),
    _k("clone_kb_cap", ["harness/inspect.py:CLONE_KB_CAP"], [10_000, 50_000, 250_000, 1_000_000],
       probe="clone_kb_cap", note="KB of weight files in a shallow clone above which a repo is weights in git (#991)"),
    _k("dead_days", ["harness/inspect.py:UPSTREAM_DEAD_DAYS"], [180, 365, 730, 1095, 3650], probe="dead_days",
       note="when a repo counts as abandoned"),
    _k("download_budget", ["scripts/serve-discover.sh:DISCOVER_BUDGET_GIB"], [20, 40, 80, 160],
       limit="download_budget_gib", note="GiB one scheduled sweep may download in all (#704)"),
    _k("download_cap", ["harness/fetching.py:MAX_DOWNLOAD"],
       [20 * GIB, 40 * GIB, 60 * GIB, 120 * GIB], limit="download_gib", scale=GIB,
       note="the largest download one fetch may take"),
    _k("memory_ceiling", ["harness/inspect.py:MEMORY_CEILING", "harness/inspect.py:MEMORY_CEILING_RAM_GB"],
       [8 * GIB, 16 * GIB, 22 * GIB, 32 * GIB, 96 * GIB], limit="ceiling_gb", predicate=MACHINE,
       scale=GIB, probe="memory_ceiling",
       note="the largest weight this machine can hold; measured on 32 GB and scaled by RAM (#96)"),
    _k("size_limit", ["harness/inspect.py:SIZE_LIMIT"], [2, 4, 12, 24, 64], probe="size_limit",
       note="how many named weights get sized per repo"),
]

NOT_GATING = {
    "harness/inspect.py:Fit.ceiling": "the ceiling decide() judged against, recorded on the verdict; its default 0 means none (#880)",
    "harness/torch_device.py:MAX_HEADER": "refuses a safetensors header past 64 MiB as unreadable; no dtype choice or run gates on it (#1013)",
    "harness/variants.py:LORA_FRACTION": "tells an add-on file from a checkpoint in one listing; no size, run or machine gates on it (#947)",
    "harness/memory_store/revisit.py:STALE_CEILING_GB":"absorbs rounding of one machine's probed ceiling; a real ceiling change is GiBs (#880)",
}

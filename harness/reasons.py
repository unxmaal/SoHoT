"""Why a verdict happened, as a column and a class rather than prose. #408.

The vocabulary for verdicts.reason, the failure classes a runner reports on
each result row, the one adapter that reads upstream error text, and the
legacy classifier that backfills rows written before the column existed.
"""
from __future__ import annotations

import re

#: verdicts.reason. The only place the vocabulary is defined.
REASONS = {
    "candidate": "the candidate's own result: it ran and passed or failed, its "
                 "snapshot lacks a file, it is not a model, it scored low",
    "harness": "this harness could not deliver the request; nothing is known "
               "about the candidate",
    "runtime": "the installed runtimes cannot build it; a newer version, or a runner, format "
               "reader or policy this harness lacks (the until names which), may",
    "machine": "this machine lacks the runtime, ceiling or disk it needs, or "
               "faulted running it; another machine may not",
    "memory": "not enough free memory right now",
    "limit": "a limit this harness chose was hit: token budget, timeout, "
             "download cap",
    "upstream": "the candidate's upstream is gone or idle",
    "reopened": "a named reopen (retraction, retest) of an earlier verdict",
}
CANDIDATE, HARNESS, RUNTIME, MACHINE, MEMORY, LIMIT, UPSTREAM, REOPENED = REASONS

# Failure classes, set on each result row by the runner where it failed.
SERVER_DEAD = "server_dead"
GPU_FAULT = "gpu_fault"
REFUSED_BY_GATEWAY = "refused_by_gateway"
HARNESS_ERROR = "harness_error"
LOAD_FAILED_RUNTIME = "load_failed_runtime"
LOAD_FAILED_LAYOUT = "load_failed_layout"
#: llama-server said it failed to load and no loader log says why: nothing is known yet. #953.
LOAD_LOG_UNREAD = "load_log_unread"
#: The GGUF's own header disagrees with itself: a fault in the upload, not the runtime. #953.
LOAD_FAILED_FILE = "load_failed_file"
#: Our copy of the GGUF is shorter than its header says: refetch it. #953.
SHORT_COPY = "short_copy"
TIMEOUT = "timeout"
TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
#: An agent run stopped at the step cap we chose. #695.
STEP_CAP = "step_cap"
#: A case whose prompt and reply budget do not fit the context the candidate is served at. #695.
CONTEXT_EXCEEDED = "context_exceeded"
#: llama-server's shared KV pool filled and it failed every request in flight; says nothing about the model. #748.
POOL_FULL = "pool_full"
MISSING_FILE_IN_SNAPSHOT = "missing_file_in_snapshot"
CRASHED = "crashed"
CONTENT_FAILED = "content_failed"
#: Speech that ran past the runaway rate: the candidate's failure, cut by a ceiling we chose. #637.
RUNAWAY = "runaway"
#: A reply cut at the token budget that was looping or collapsed: no budget limit; a screen declines it per #691. #955.
DEGENERATE = "degenerate"
#: An abort inside Apple's MPS backend (LLVM ERROR on an mps op, MPSGraph assertion). #604.
BACKEND_FAULT = "backend_fault"
#: A repo-lane reply whose diff git cannot apply: the candidate's own failure. #887.
INVALID_PATCH = "invalid_patch"
#: The repo lane's mirror, checkout or environment could not be built; the model never ran. #887.
ENVIRONMENT_ERROR = "environment_error"

#: A verdict's class, not a row's: the adopt gate lacked the power to see the effect. #479.
UNDERPOWERED = "underpowered"
#: A verdict's class: the paired run stopped at its deadline, so it decided nothing. #673.
INCONCLUSIVE = "inconclusive"
#: A verdict's class: the lane has too few cases for any repeat to see the effect, so nothing ran. #993.
LANE_TOO_SMALL = "lane_too_small"

#: class -> (screen outcome, reason), in precedence order when rows disagree.
CLASSES = {
    SERVER_DEAD: ("queued", HARNESS),
    GPU_FAULT: ("declined", MACHINE),
    REFUSED_BY_GATEWAY: ("queued", HARNESS),
    HARNESS_ERROR: ("queued", HARNESS),
    ENVIRONMENT_ERROR: ("queued", HARNESS),
    LOAD_LOG_UNREAD: ("queued", HARNESS),
    SHORT_COPY: ("queued", HARNESS),
    POOL_FULL: ("queued", LIMIT),
    TIMEOUT: ("declined", LIMIT),
    TOKEN_BUDGET_EXHAUSTED: ("declined", LIMIT),
    STEP_CAP: ("declined", LIMIT),
    CONTEXT_EXCEEDED: ("declined", LIMIT),
    LOAD_FAILED_RUNTIME: ("declined", RUNTIME),
    LOAD_FAILED_FILE: ("declined", CANDIDATE),
    LOAD_FAILED_LAYOUT: ("declined", RUNTIME),
    BACKEND_FAULT: ("declined", RUNTIME),
    MISSING_FILE_IN_SNAPSHOT: ("broken", CANDIDATE),
    CRASHED: ("broken", CANDIDATE),
    DEGENERATE: ("broken", CANDIDATE),
    CONTENT_FAILED: ("broken", CANDIDATE),
    INVALID_PATCH: ("broken", CANDIDATE),
    RUNAWAY: ("broken", CANDIDATE),
}

#: After one of these the shared server or the GPU is suspect, so a loop stops.
STOPS = (SERVER_DEAD, GPU_FAULT)

#: Classes that mean the request never reached a model.
NEVER_RAN = tuple(c for c, (_, r) in CLASSES.items() if r == HARNESS)


def first(classes) -> str:
    """The class that decides a run whose rows report several."""
    have = set(classes or ())
    return next((c for c in CLASSES if c in have), "")


def limits() -> dict:
    """The limits this harness currently chooses, by `limit:` predicate name; the knob registry is the source. #636."""
    from harness import knobs
    return knobs.limits()


# ---------------------------------------------------------------------------
# The adapter: upstream error text read once, where a runner catches it.
# ---------------------------------------------------------------------------

RUNNER, STDERR = "runner", "stderr"

_SERVER_DEAD = ("generation thread died",)
#: llama-server 0.5.0's error to every in-flight task when a decode finds no room in the pool. #748.
_POOL_FULL = ("context size has been exceeded",)
_GPU_FAULT = ("kiogpucommandbuffercallbackerrortimeout", "gpu timeout error")
_GATEWAY = ("invalid model name", "gateway returned http 400",
            "is the gateway up", "connection refused",
            # gateway_switch.DRAINING: a switch refused the request, the model never saw it. #703.
            "the gateway is draining",
            # batch.BUSY: another batch holds the serving machine, the model never saw it. #769.
            "the serving machine is busy with another batch")
#: What a server says when a request does not fit the context it is served at: llama-server, vLLM, LiteLLM. #695, #692.
OVER_CONTEXT = re.compile(r"exceeds? the available context|context.?window.?exceeded|maximum context length"
                          r"|context length exceeded|exceeds? (the )?context (size|window|length)|max_model_len", re.I)
_HARNESS = ("no cases of a modality it can run", "no candidate matched any case",
            "no module named", "error while finding module specification",
            "command not found", "guidance_scale has to be",
            # A package our hf-task venv lacks, not the model. #562.
            "installed to convert a slow tokenizer",
            # transformers offline with weights the fetch never finished. #563.
            "run the library in offline mode",
            # huggingface_hub offline with no snapshot its refs resolve to, through the gateway. #799.
            "cannot find an appropriate cached snapshot folder",
            # transformers' requires_backends tail: a backend the venv lacks (torchvision). #601.
            "restart your runtime after installation", "venv lacks a package")
#: In stderr this is our missing script; in a loader's error it is the snapshot's.
_ABOUT_THE_SNAPSHOT = ("no such file or directory",
                       "does not appear to have a file named")
#: A loader naming a file absent from our own hub snapshot: we sent it to the wrong runtime or under-fetched. #911.
_OUR_SNAPSHOT = re.compile(r"no such file or directory: '[^']*/snapshots/[^/']+/[^']+'")
_LOAD_FAILED = "gateway returned http 404"
_ARCHITECTURE_GAPS = ("model type", "modelargs", "parameters not in model",
                      "required positional argument")
_LLAMACPP_LOAD_FAILED = ("failed to load",)
#: llama-server's own 500 body names the router alias that failed. #953.
_LLAMACPP_ALIAS = re.compile(r"model name=(\S+?) failed to load")
#: A router child's error line: `[<port>] <time> E <message>`. #953.
_CHILD_ERROR = re.compile(r"^\[\d+\] \S+ E (.+)$", re.M | re.I)
#: The loader read past the end of our copy. #953.
_GGUF_SHORT = ("not within the file bounds", "unexpectedly reached end of file",
               "failed to read magic")
#: The file's header is inconsistent with itself, before any tensor data is read. #953.
_GGUF_HEADER_FAULT = re.compile(r"tensor '[^']*' has offset \d+, expected \d+|invalid magic characters"
                                r"|failed to read key-value pairs|failed to read tensor info"
                                r"|duplicate key|duplicate tensor name|not a multiple of block size")
#: What a newer llama.cpp can add. #953.
_LLAMACPP_GAPS = ("unknown model architecture", "unknown pre-tokenizer type", "invalid ggml type")
_DIFFUSERS_LAYOUT_GAPS = ("can't find a pipeline linked to", "were passed")
#: A lane's runner that cannot open the repo's layout: a runner gap, never a fault of the repo. #951.
_RUNNER_LAYOUT_GAPS = ("does not appear to have a file named model_index.json",
                       "no safetensors found", "could not determine model type",
                       # scripts/acestep_generate.py's own exit for a checkpoint ACE-Step cannot build.
                       "dit init failed")
_NO_PIPELINE_CLASS = re.compile(r"has no attribute \w+pipeline\b")
_ACESTEP_INIT_EXIT = re.compile(r"\bexit 3\b")
_ENGINE_HEADS = ("mflux", "diffusers", "diffusers-video", "acestep", "hf-ocr",
                 "rerank", "embed", "hf-pii")
#: A repo whose modelling code is its own: hf-task never executes it. #562.
_REMOTE_CODE = ("trust_remote_code",)
#: The audio server (mlx-audio) answers 500 when it cannot build the model.
_AUDIO_HEADS = ("tts", "stt")
_AUDIO_LOAD_FAILED = ("failed to load model",)
_RUNAWAY = ("tts ran away",)


def _any(low: str, phrases) -> str:
    return next((p for p in phrases if p in low), "")


def mps_abort(text: str) -> bool:
    """An abort inside the MPS backend: LLVM ERROR on an mps op, or an MPSGraph assertion. #604."""
    low = (text or "").lower()
    if "failed assertion" in low:
        return "mpsgraph" in low
    if "llvm error" in low:
        return '"mps.' in low or "mps_" in low
    return False


def backend_abort(lines) -> str:
    """The one line naming an MPS abort in a stderr tail, or ""; the LLVM line takes the op after it."""
    lines = list(lines)
    for i, line in enumerate(lines):
        if "llvm error" in line.lower():
            joined = " ".join(s.strip() for s in lines[i:i + 2])
            if mps_abort(joined):
                return joined
        elif mps_abort(line):
            return line.strip()
    return ""


def in_our_snapshot(text: str) -> bool:
    """A failure naming a file missing from a snapshot on this machine. #911."""
    return bool(_OUR_SNAPSHOT.search((text or "").lower()))


def llamacpp_alias(text: str) -> str:
    """The router alias llama-server's 500 says failed to load, or "". #953."""
    got = _LLAMACPP_ALIAS.search(text or "")
    return got.group(1) if got else ""


def child_errors(lines) -> list[str]:
    """A router child's error messages, prefix and level cut, whitespace folded. #953."""
    return [" ".join(m.group(1).split()) for line in lines
            for m in [_CHILD_ERROR.match(line.rstrip())] if m]


def _llamacpp_load(low: str) -> str:
    """A llama-server load failure's class, read from the child's own log when the text carries it. #953."""
    if _any(low, _GGUF_SHORT):
        return SHORT_COPY
    if _GGUF_HEADER_FAULT.search(low):
        return LOAD_FAILED_FILE
    if _any(low, _LLAMACPP_GAPS) or _CHILD_ERROR.search(low):
        return LOAD_FAILED_RUNTIME
    return LOAD_LOG_UNREAD


def runner_layout_gap(text: str, head: str = "") -> bool:
    """A runner that cannot open the repo's layout, unless the file it missed is in our own snapshot. #951, #911."""
    low = (text or "").lower()
    if _OUR_SNAPSHOT.search(low):
        return False
    return bool(_any(low, _RUNNER_LAYOUT_GAPS) or _NO_PIPELINE_CLASS.search(low)
                or (head == "acestep" and _ACESTEP_INIT_EXIT.search(low)))


def classify(text: str, where: str = RUNNER, candidate: str = "") -> str:
    """The failure class an upstream error text names, or "" from stderr."""
    from harness.serving import LLAMACPP_PREFIX
    low = (text or "").lower()
    head = candidate.partition(",")[0].partition(":")[0].strip()
    if _any(low, _SERVER_DEAD):
        return SERVER_DEAD
    if _any(low, _GPU_FAULT):
        return GPU_FAULT
    if mps_abort(low):
        return BACKEND_FAULT
    if _any(low, _POOL_FULL):
        return POOL_FULL
    if runner_layout_gap(low, head):
        return LOAD_FAILED_LAYOUT
    if candidate.startswith(LLAMACPP_PREFIX) and all(
            p in low for p in _LLAMACPP_LOAD_FAILED):
        return _llamacpp_load(low)
    if (_LOAD_FAILED in low or head in _ENGINE_HEADS) and _any(
            low, _ARCHITECTURE_GAPS):
        return LOAD_FAILED_RUNTIME
    if head in _AUDIO_HEADS and _any(low, _AUDIO_LOAD_FAILED):
        return LOAD_FAILED_RUNTIME
    if OVER_CONTEXT.search(low):
        return CONTEXT_EXCEEDED
    if _any(low, _GATEWAY):
        return REFUSED_BY_GATEWAY
    if _any(low, _HARNESS) or _OUR_SNAPSHOT.search(low):
        return HARNESS_ERROR
    if where == STDERR:
        return HARNESS_ERROR if _any(low, _ABOUT_THE_SNAPSHOT) else ""
    if _any(low, _RUNAWAY):
        return RUNAWAY
    if _any(low, _DIFFUSERS_LAYOUT_GAPS) or _any(low, _REMOTE_CODE):
        return LOAD_FAILED_LAYOUT
    if _any(low, _ABOUT_THE_SNAPSHOT):
        return MISSING_FILE_IN_SNAPSHOT
    return CRASHED


# ---------------------------------------------------------------------------
# Backfill only: rows written before failure_class and verdicts.reason.
# ---------------------------------------------------------------------------

def legacy_class(detail: str, candidate: str = "") -> str:
    """A pre-#408 receipt row's class, read from its detail."""
    if not detail:
        return ""
    return classify(detail, RUNNER, candidate)


def legacy_refused(detail: str) -> str:
    """The phrase saying a pre-#408 verdict never reached the candidate."""
    low = (detail or "").lower()
    return (_any(low, ("no measured size",)) or _any(low, _SERVER_DEAD)
            or _any(low, _GATEWAY) or _any(low, _HARNESS)
            or _any(low, ("no such file or directory",)))


def legacy_architecture_gap(detail: str) -> bool:
    low = (detail or "").lower()
    return _LOAD_FAILED in low and bool(_any(low, _ARCHITECTURE_GAPS))


def legacy_layout_gap(detail: str) -> bool:
    return bool(_any((detail or "").lower(), _DIFFUSERS_LAYOUT_GAPS))


def legacy_reason(outcome: str, tier: str, detail: str,
                  reopen_kind: str = "") -> str:
    """verdicts.reason for a row written before the column. "" if unknown."""
    d = (detail or "").strip()
    low = d.lower()
    if reopen_kind or low.startswith("retracted:"):
        return REOPENED
    if outcome in ("screened", "measured"):
        return CANDIDATE
    if tier in ("inspect", "fetch"):
        if low.startswith("too-big") or low.startswith("needs-") \
                or "would leave under the" in low:
            return MACHINE
        if low.startswith("dead") or low.startswith("404") \
                or "not found" in low or "gone" in low:
            return UPSTREAM
        if "no measured size" in low or "no runner in the" in low:
            return HARNESS
        if "past its" in low and "budget" in low or " gib cap" in low:
            return LIMIT
        if low.startswith(("fits", "no-entry-point", "unknown", "bytes=",
                           "downloaded")) or "attaches to a model" in low \
                or outcome == "ignored":
            return CANDIDATE
        return ""
    if tier in ("judge", "adopt"):
        if low.startswith("not measured:"):
            return HARNESS
        return CANDIDATE
    if low.startswith("not screened:") and "safely available" in low:
        return MEMORY
    if "spent the whole" in low and "budget" in low:
        return LIMIT
    if "timed out after" in low:
        return LIMIT
    if low.startswith("the installed runtime could not load it") \
            or low.startswith("needs its own runner") \
            or low.startswith("the mps backend aborted"):
        return RUNTIME
    if _any(low, _GPU_FAULT) or "[metal]" in low:
        return MACHINE
    if low.startswith("it ran and passed nothing"):
        head = low.split("||", 1)[0]
        return HARNESS if (_any(head, _SERVER_DEAD) or _any(head, _GATEWAY)
                           or _any(head, _HARNESS)) else CANDIDATE
    if low.startswith("not screened:") or low.startswith("not measured:") \
            or legacy_refused(low):
        return HARNESS
    if outcome in ("broken", "declined"):
        return CANDIDATE
    return ""

"""The needle: runner kind: Cactus-Compute/needle3 through its own CLI, decide and agent lanes. #312."""
from __future__ import annotations

import atexit
import json
import os
import platform
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PREFIX = "needle"
REPO = "Cactus-Compute/needle3"
REVISION = "2ae11323dc000f5e70c49f7403efa6af12ba9e67"
WEIGHTS = "needle3.cact"
MODELS = ("needle3",)
OPTIONS = ("layers", "threads", "max")
MIN_LAYERS, MAX_LAYERS = 2, 20
#: The lanes a needle candidate runs.
LANES = ("decide", "agent")
TOOL = "answer"
#: Card platform folders; the binary is the only per-platform file.
PLATFORMS = {
    ("darwin", "arm64"): "macos-arm64/needle",
    ("linux", "x86_64"): "linux-x86_64/needle",
    ("linux", "aarch64"): "linux-arm64/needle",
    ("linux", "arm64"): "linux-arm64/needle",
    ("win32", "amd64"): "windows-x86_64/needle.exe",
    ("win32", "arm64"): "windows-arm64/needle.exe",
}
SERVE_START_S = 60.0
FIELD_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class Spec:
    spec: str
    model: str
    layers: int | None = None
    threads: int | None = None
    max: int | None = None

    @property
    def name(self) -> str:
        opts = ",".join(f"{k}={getattr(self, k)}" for k in sorted(OPTIONS)
                        if getattr(self, k) is not None)
        return f"needle/{self.model}" + (f"@{opts}" if opts else "")


def parse(spec: str) -> Spec:
    head, _, optstr = spec.partition(",")
    kind, _, model = head.partition(":")
    model = model.strip()
    if kind.strip() != PREFIX:
        raise ValueError(f"not a needle spec: {spec!r}")
    if model not in MODELS:
        raise ValueError(f"needle runs {', '.join(MODELS)} (the card's one .cact), got {model!r}")
    opts: dict[str, int] = {}
    for chunk in filter(None, (c.strip() for c in optstr.split(","))):
        key, eq, value = chunk.partition("=")
        if not eq or key not in OPTIONS:
            raise ValueError(f"bad needle option {chunk!r}; allowed: {', '.join(OPTIONS)}")
        try:
            opts[key] = int(value)
        except ValueError:
            raise ValueError(f"needle option {key} takes an integer, got {value!r}") from None
    layers = opts.get("layers")
    if layers is not None and not MIN_LAYERS <= layers <= MAX_LAYERS:
        raise ValueError(f"needle layers must be {MIN_LAYERS}-{MAX_LAYERS}, got {layers}")
    return Spec(spec=spec, model=model, **opts)


def platform_binary(system: str | None = None, machine: str | None = None) -> str:
    key = (system or sys.platform, (machine or platform.machine()).lower())
    if key not in PLATFORMS:
        raise ValueError(f"needle3 ships no engine for {key[0]}/{key[1]}")
    return PLATFORMS[key]


def child_env(base: dict | None = None) -> dict:
    """The package and engine report usage by default; never from here."""
    return {**(os.environ if base is None else base), "NEEDLE_TELEMETRY": "0"}


def _fetch(name: str, download: bool) -> str:
    from huggingface_hub import hf_hub_download, try_to_load_from_cache
    if download:
        return hf_hub_download(REPO, name, revision=REVISION)
    got = try_to_load_from_cache(REPO, name, revision=REVISION)
    if not isinstance(got, str):
        raise LookupError(f"{REPO}@{REVISION[:7]}:{name} is not in the HF cache")
    return got


def installed(download: bool = True) -> tuple[list[str], str]:
    """(binary argv prefix, weights path); $NEEDLE_BIN and $NEEDLE_MODEL override."""
    binary = os.environ.get("NEEDLE_BIN") or _fetch(platform_binary(), download)
    weights = os.environ.get("NEEDLE_MODEL") or _fetch(WEIGHTS, download)
    if not os.environ.get("NEEDLE_BIN"):
        _fetch("config.json", download)
    real = Path(binary).resolve()
    if os.name != "nt" and not os.access(real, os.X_OK):
        real.chmod(real.stat().st_mode | 0o111)
    return [binary], weights


def installed_version(lookup=None) -> str:
    """`<engine_version>@<revision>` when the pinned config is cached, else ""."""
    if lookup is None:
        try:
            from huggingface_hub import try_to_load_from_cache as lookup
        except ImportError:
            return ""
    try:
        path = lookup(REPO, "config.json", revision=REVISION)
        if not isinstance(path, str):
            return ""
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return f"{cfg.get('engine_version') or '?'}@{REVISION[:7]}"


def _common(spec: Spec, command: list[str], weights: str) -> list[str]:
    argv = [*command, "--model", str(weights), "--fail-input-overflow"]
    for flag, value in (("--depth", spec.layers), ("--threads", spec.threads),
                        ("--max", spec.max)):
        if value is not None:
            argv += [flag, str(value)]
    return argv


def argv(spec: Spec, command: list[str], weights: str, tools: Path, prompt: str) -> list[str]:
    """One forced call: the field tool is always dispatched, never refused."""
    return [*_common(spec, command, weights), "--tools", str(tools), "--forced",
            "--prompt", prompt]


def serve_argv(spec: Spec, command: list[str], weights: str, tools: Path,
               system: Path, port: int) -> list[str]:
    return [*_common(spec, command, weights), "--tools", str(tools),
            "--system", str(system), "--serve", "--port", str(port)]


# ---- decide -----------------------------------------------------------------

def _key(value) -> str:
    from harness.checks.decide import key
    return key(value)


def task_of(prompt: str, schema: dict) -> str:
    """The case's instruction without the lettered block text runners read."""
    from harness.checks.decide import render
    block = render(schema)
    return (prompt.split(block)[0] if block in prompt else prompt).strip()


def field_tools(name: str, spec: dict) -> list[dict]:
    desc = str(spec.get("description") or name).strip()
    notes = spec.get("choice_descriptions") or {}
    notes = {_key(k): v for k, v in notes.items() if v} if isinstance(notes, dict) else {}
    if spec.get("type") == "boolean":
        value = {"type": "boolean", "description": desc}
    else:
        value = {"type": "string", "enum": [str(c) for c in spec.get("choices") or []],
                 "description": desc}
    text = f"Record the answer to: {desc}"
    if notes:
        text += " (" + "; ".join(f"{k}: {v}" for k, v in notes.items()) + ")"
    return [{"type": "function", "function": {
        "name": TOOL, "description": text,
        "parameters": {"type": "object", "properties": {"value": value},
                       "required": ["value"]}}}]


def field_input(task: str, context: str, spec: dict) -> str:
    """The material first, the question last: needle loses what it read first."""
    question = str(spec.get("description") or "").strip()
    return "\n\n".join(x for x in (context.strip(), task.strip(), question) if x)


def field_answer(response: dict, spec: dict) -> dict:
    """answer key, probabilities from the one confidence, and why when none."""
    from harness.checks.decide import code_map
    allowed = list(code_map(spec).values())
    calls = response.get("function_calls") or []
    suppressed = not calls and bool(response.get("suppressed_calls"))
    calls = calls or response.get("suppressed_calls") or []
    answer = None
    for call in calls:
        args = call.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if "value" in args and _key(args["value"]) in allowed:
            answer = _key(args["value"])
            break
    error = response.get("error") or (None if answer else "no call answered the field")
    conf = response.get("confidence")
    probs = None
    if answer is not None and isinstance(conf, (int, float)) and 0 <= conf <= 1:
        rest = (1.0 - float(conf)) / (len(allowed) - 1)
        probs = {a: (float(conf) if a == answer else rest) for a in allowed}
    return {"answer": answer, "probs": probs, "suppressed": suppressed,
            "error": None if answer else error}


def ask_field(spec: Spec, command: list[str], weights: str, name: str, field: dict,
              task: str, context: str, workdir: Path) -> dict:
    """One field through one process; peak_kb is the needle process's own."""
    from harness import proc
    tools = Path(workdir) / f"tools-{name}.json"
    tools.write_text(json.dumps(field_tools(name, field)), encoding="utf-8")
    r = proc.run(argv(spec, command, weights, tools, field_input(task, context, field)),
                 timeout=FIELD_TIMEOUT_S, env=child_env({}))
    try:
        body = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    got = field_answer(body, field) if r.ok else {
        "answer": None, "probs": None, "suppressed": False,
        "error": f"exit {r.returncode}: {(r.stderr or '').strip()[-200:]}"}
    return {**got, "confidence": body.get("confidence"), "peak_kb": r.peak_kb,
            "seconds": r.seconds, "runtime_peak_mb": body.get("peak_ram_mb")}


def decide(spec: Spec, command: list[str], weights: str, schema: dict, task: str,
           context: str, workdir: Path) -> dict:
    """The canonical decide artifact, plus what needle said and could not do."""
    answers, probs, conf, errors, peak = {}, {}, {}, {}, 0
    suppressed = []
    for name, field in schema.items():
        got = ask_field(spec, command, weights, name, field, task, context, workdir)
        peak = max(peak, int(got["peak_kb"] or 0))
        conf[name] = got["confidence"]
        if got["answer"] is not None:
            answers[name] = got["answer"]
        if got["probs"]:
            probs[name] = got["probs"]
        if got["error"]:
            errors[name] = got["error"]
        if got["suppressed"]:
            suppressed.append(name)
    return {"answers": answers, "probabilities": probs, "per_option": False,
            "probability_source": "needle confidence: one calibrated score per call, "
                                  "the rest spread evenly over the other choices",
            "confidence": conf, "errors": errors, "suppressed": suppressed,
            "model": f"{REPO}@{REVISION[:7]}", "peak_kb": peak}


# ---- agent ------------------------------------------------------------------

def message(response: dict, step: int) -> dict:
    """A needle turn as the OpenAI assistant message the tool loop reads."""
    calls = response.get("function_calls") or []
    if not calls:
        return {"role": "assistant", "content": str(response.get("reasoning") or "")}
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"call_{step}_{i}", "type": "function",
         "function": {"name": str(c.get("name") or ""),
                      "arguments": json.dumps(c.get("arguments") or {})}}
        for i, c in enumerate(calls)]}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """One `needle --serve` process for one tool set and system prompt."""

    def __init__(self, argv_for, port: int | None):
        self.port = free_port() if port is None else port
        self.proc = subprocess.Popen(
            argv_for(self.port), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=child_env())
        atexit.register(self.close)
        lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._drain, args=(lines,), daemon=True).start()
        deadline = time.monotonic() + SERVE_START_S
        self.base = ""
        while not self.base:
            left = deadline - time.monotonic()
            try:
                line = lines.get(timeout=max(left, 0.01))
            except queue.Empty:
                line = None
            if line is None or left <= 0:
                self.close()
                raise RuntimeError("needle --serve did not report its address")
            if "serving on http://" in line:
                url = line.split("serving on ", 1)[1].split()[0].rstrip("/")
                host, _, port = url.rpartition(":")
                self.base = f"{host}:{self.port if port == '0' else port}"

    def _drain(self, lines: queue.Queue) -> None:
        for line in self.proc.stdout:
            lines.put(line)
        lines.put(None)

    def post(self, path: str, body: dict, timeout: float) -> dict:
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            got = json.loads(r.read().decode("utf-8") or "{}")
        return got if isinstance(got, dict) else {}

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Chat:
    """completion.chat's shape over a needle server, for evals.runners.agent."""

    def __init__(self, spec: Spec, command: list[str], weights: str, workdir: Path,
                 port: int | None = None):
        self.spec, self.command, self.weights = spec, command, weights
        self.workdir = Path(workdir)
        self.port = port
        self.server: Server | None = None
        self.key = ""
        self.head = None
        self.sent = 0
        self.steps = 0
        self.peak_mb = 0.0
        self.withheld = 0

    def _start(self, tools: list, system: str) -> None:
        self.close()
        self.workdir.mkdir(parents=True, exist_ok=True)
        t, s = self.workdir / "tools.json", self.workdir / "system.txt"
        t.write_text(json.dumps(tools), encoding="utf-8")
        s.write_text(system, encoding="utf-8")
        self.server = Server(lambda port: serve_argv(self.spec, self.command, self.weights,
                                                     t, s, port), self.port)

    def inputs(self, new: list) -> list[str]:
        """Consecutive tool results become one JSON turn; a user message is text."""
        names = {}
        out, results = [], []
        for m in new:
            role = m.get("role")
            if role == "assistant":
                for c in m.get("tool_calls") or []:
                    names[c.get("id")] = (c.get("function") or {}).get("name")
                continue
            if role == "tool":
                results.append({"name": names.get(m.get("tool_call_id"), ""),
                                "result": m.get("content") or ""})
                continue
            if results:
                out.append(json.dumps(results))
                results = []
            out.append(str(m.get("content") or ""))
        if results:
            out.append(json.dumps(results))
        return out

    def __call__(self, messages: list, model: str = "", gateway: str = "",
                 tools: list | None = None, timeout: float = 300.0,
                 max_tokens: int = 0, sampling: dict | None = None, stream: bool = True):
        from harness import completion
        system = messages[0]["content"] if messages and messages[0].get("role") == "system" else ""
        convo = messages[1:] if system else list(messages)
        key = json.dumps([tools or [], system], sort_keys=True)
        try:
            if key != self.key or self.server is None:
                self._start(tools or [], system)
                self.key, self.head, self.sent = key, None, 0
            if not convo or convo[0] != self.head or len(convo) < self.sent:
                if self.head is not None:
                    self.server.post("/reset", {}, timeout)
                self.head, self.sent = (convo[0] if convo else None), 0
                self.peak_mb, self.withheld = 0.0, 0
            t0 = time.perf_counter()
            body: dict = {}
            for text in self.inputs(convo[self.sent:]):
                body = self.server.post("/complete", {"input": text}, timeout)
            self.sent = len(convo)
        except (OSError, RuntimeError, ValueError) as exc:
            raise completion.CompletionError(f"needle: {exc}") from exc
        if body.get("success") is False and body.get("error"):
            raise completion.CompletionError(f"needle: {body['error']}")
        self.steps += 1
        if not body.get("function_calls") and body.get("suppressed_calls"):
            # The loop confirms what the engine withheld, as its confidence guide allows.
            self.withheld += len(body["suppressed_calls"])
            body = {**body, "function_calls": body["suppressed_calls"]}
        if isinstance(body.get("peak_ram_mb"), (int, float)):
            self.peak_mb = max(self.peak_mb, float(body["peak_ram_mb"]))
        msg = message(body, self.steps)
        return completion.Completion(text=msg.get("content") or "",
                                     timing={"seconds": round(time.perf_counter() - t0, 4)},
                                     model=self.spec.name, message=msg)

    def close(self) -> None:
        if self.server is not None:
            self.server.close()
            self.server = None

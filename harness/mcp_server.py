"""SoHoT over MCP: the same `soh`, reachable from the LAN.

A second agent on another machine (its own Claude Code, its own context) asks
this one to draw something. What crosses the network is a tool call; what runs
here is the same command line a local agent would type.

THAT IS THE DESIGN CONSTRAINT. Every media tool shells out to `lh`. The repo's
standing rule is that the CLI and the eval suite run identical commands,
because for a while only the eval knew how to invoke a generator and the
harness could measure something the product did not ship. A third caller obeys
the same rule, and shelling out is how it stays true by construction rather
than by discipline.

local_complete and local_decide (#475) call harness.delegate in-process, because
the caller wants the first-token time and the model that answered; they share
the lane commands' route rather than their argv.

svg, web and code answer directly. image and video go on the shared work
queue (harness/workqueue.py, #353): they return a job id at once, run in order
while memory pressure is normal, and job_result hands back the file.

    ./scripts/serve-mcp.sh          # 0.0.0.0, no auth, trusted LAN only

The other machine adds one entry pointing at http://<host>.local:8899/mcp
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from harness import completion, delegate, env, exclusive, paths, workqueue


class JobInfo(BaseModel):
    """What a caller gets back about a queued generation.

    A declared return type, not a bare dict: without one the SDK ships the
    result as JSON inside a text block and structured_content comes back None,
    leaving an agent to parse a string to learn whether its image is ready.

    The optional fields are optional in the honest sense. `ahead` means nothing
    once a job is running, and `path` does not exist until it is done.
    """
    job: str
    kind: str
    state: str                       # queued | running | done | failed | unknown
    seconds: float = 0.0
    #: Jobs in front of this one, and what is currently holding the machine, so
    #: a wait is attributable rather than mysterious.
    ahead: int | None = None
    waiting_for: str | None = None
    #: Where the artifact landed. It stays on the serving machine.
    path: str | None = None
    error: str | None = None

# Artifacts stay on this machine and are downloaded when wanted, so the path is
# what a tool result carries rather than the bytes. Under the ONE output root,
# in its own subdirectory: a caller should be able to tell what a remote agent
# asked for from what someone typed here.
#: None means paths.outputs()/mcp, resolved per call so LOCALHARNESS_HOME is read when used.
OUTDIR: Path | None = None
#: This interpreter, not `lh` on PATH, which runs whatever checkout installed it. #290.
LH = [sys.executable, "-m", "harness.cli"]
DEFAULT_TIMEOUT = 300.0

SERVER = MCPServer(
    name="SoHoT",
    instructions=(
        "Local media generation on Apple Silicon. svg, web and code answer in "
        "a few seconds. image and video go on this machine's work queue and "
        "return a job id at once: jobs run in order, and wait while the "
        "machine is short of memory. Poll job_status; when it is "
        "done, job_result returns the file itself. local_complete and "
        "local_decide hand a text subtask to this machine's adopted local "
        "model and answer directly."),
)


def run_lh(argv: list[str], timeout: float = DEFAULT_TIMEOUT) -> str:
    """Run `lh` and return stdout, or raise with what it said on stderr."""
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                       env=_child_env())
    if r.returncode != 0:
        # ToolError, or the SDK hides the message from the caller. #477.
        raise ToolError(
            (r.stderr or r.stdout).strip()[:600] or f"{argv[len(LH)]} exited {r.returncode}")
    return r.stdout.strip()


def _child_env() -> dict:
    import os
    child = dict(os.environ)
    # The server may itself be started by launchd with nothing sourced, and an
    # unset HF_HOME sends huggingface_hub to ~/.cache to re-download weights
    # that are already on the volume.
    env.apply(child)
    return child


def _out(kind: str, suffix: str) -> Path:
    return paths.artifact(kind, suffix, where=OUTDIR or paths.outputs() / "mcp")


SUFFIX = {"svg": ".svg", "web": ".html", "code": ".txt"}


def _text_tool(verb: str, prompt: str, model: str = "") -> str:
    """Run `lh` and return the DOCUMENT, not the path it was written to.

    `lh svg` and `lh web` always write a file and print where it went; only
    `lh code` prints its content. A caller on another machine cannot open a
    path on this one, so every verb is given an explicit -o and the file is
    read back. It stays on disk afterwards, which is what makes a bad result
    inspectable rather than merely reported.
    """
    out = _out(verb, SUFFIX[verb])
    argv = [*LH, verb, prompt, "-o", str(out)]
    if model:
        argv += ["-m", model]
    run_lh(argv)
    if not out.exists():
        raise ToolError(f"soh {verb} exited 0 but wrote nothing to {out}")
    return out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The cheap lane: a few seconds, straight through the gateway, no queue needed.
# ---------------------------------------------------------------------------

@SERVER.tool(description=(
    "Write a prompt for whatever engine this machine runs in a lane "
    "(image or video). The caller says what they want; which engine serves it, "
    "and how to command it, is this tool's problem. With no `about`, returns "
    "the engine's prompting guide."))
def prompt(lane: str, about: str = "", model: str = "") -> str:
    """Shells out like every other tool here, so the CLI and the MCP cannot
    disagree about which engine a lane runs."""
    argv = [*LH, "prompt", lane, "--quiet"]
    if about:
        argv.append(about)
    if model:
        argv += ["-m", model]
    return run_lh(argv).strip()


@SERVER.tool(description="Generate an SVG document. Returns the markup.")
def svg(prompt: str, model: str = "") -> str:
    return _text_tool("svg", prompt, model)


@SERVER.tool(description="Generate a self-contained HTML page. Returns the "
                         "document, with all CSS and JS inlined.")
def web(prompt: str, model: str = "") -> str:
    return _text_tool("web", prompt, model)


@SERVER.tool(description="Generate code. Returns the source with no prose "
                         "around it.")
def code(prompt: str, model: str = "") -> str:
    return _text_tool("code", prompt, model)


# ---------------------------------------------------------------------------
# Delegation: a text subtask on the lane's adopted model, answered directly. #475.
# ---------------------------------------------------------------------------

class LocalCompletion(BaseModel):
    text: str
    lane: str
    #: What the lane resolved to (alias or repo id); `model` is what answered.
    spec: str
    model: str
    ttft_s: float | None = None
    seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    #: An adopted method's cost: method, base, calls, and for best-of samples and chosen. #581.
    method: dict | None = None


class LocalDecision(BaseModel):
    answers: dict[str, str]
    probabilities: dict[str, dict[str, float]]
    spec: str
    model: str
    ttft_s: float | None = None
    seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def _delegated(call, *args, **kw) -> dict:
    try:
        return call(*args, **kw)
    except (ValueError, completion.CompletionError) as exc:
        raise ToolError(str(exc)) from exc


@SERVER.tool(description=(
    "Hand a text subtask to this machine's adopted local model for a lane "
    "(code, web, svg, extract, decide) and get the text back with the model "
    "that answered, time to first token and total seconds. Good for "
    "boilerplate, test scaffolding, summaries and bulk rewriting; it sees only "
    "the prompt you pass. `system` replaces the lane's own system prompt. "
    "While a batch run holds the machine it answers only if the model is "
    "already loaded; otherwise it refuses rather than waits. `thinking` false "
    "turns a hybrid thinking model's reasoning off; left out, the lane is "
    "served as it was measured. max_tokens may go up to the model's served "
    "context less the prompt (8192 when that context is unknown)."))
def local_complete(prompt: str, lane: str = "code", system: str | None = None,
                   max_tokens: int = 2048, temperature: float | None = None,
                   thinking: bool | None = None) -> LocalCompletion:
    got = _delegated(delegate.complete, lane, prompt, system=system,
                     max_tokens=max_tokens, temperature=temperature,
                     thinking=thinking)
    return LocalCompletion(**{k: got[k] for k in LocalCompletion.model_fields})


@SERVER.tool(description=(
    "Classify with the decide lane's adopted local model. `schema` maps each "
    "snake_case field name to {\"type\": \"enum\", \"choices\": [...], "
    "\"description\": ...} or {\"type\": \"boolean\", \"description\": ...}; "
    "returns the "
    "chosen answer per field and a probability per choice. `context` is the "
    "material to judge. Cheap enough for bulk labelling."))
def local_decide(question: str, schema: dict, context: str = "") -> LocalDecision:
    got = _delegated(delegate.decide, question, schema, context=context)
    return LocalDecision(**{k: got[k] for k in LocalDecision.model_fields})


# ---------------------------------------------------------------------------
# The expensive lanes, on the shared work queue. #353.
# ---------------------------------------------------------------------------

#: Someone waiting on a picture goes ahead of overnight batch work. #361.
INTERACTIVE_PRIORITY = 10


def _queue(kind: str, prompt: str, argv: list[str], out: Path) -> JobInfo:
    job = workqueue.add(argv, title=f"{kind}: {prompt[:80]}", kind=kind,
                        output=str(out), cwd=str(Path(__file__).resolve().parents[1]),
                        priority=INTERACTIVE_PRIORITY, requested_by="mcp")
    return _describe(job)


@SERVER.tool(description="Generate an image. Queued on this machine's work "
                         "queue: returns a job id at once. Poll job_status, "
                         "then job_result for the PNG. About 3 s once started.")
def image(prompt: str, width: int = 512, height: int = 512,
          seed: int = 0, model: str = "") -> JobInfo:
    out = _out("image", ".png")
    argv = [*LH, "image", prompt, "-o", str(out),
            "--width", str(width), "--height", str(height)]
    if seed:
        argv += ["--seed", str(seed)]
    if model:
        argv += ["-m", model]
    return _queue("image", prompt, argv, out)


@SERVER.tool(description="Generate a short video clip (MP4). Queued on this "
                         "machine's work queue: returns a job id at once. Poll "
                         "job_status, then job_result for the file. Minutes "
                         "once started.")
def video(prompt: str, width: int = 512, height: int = 512, frames: int = 22,
          seed: int = 0) -> JobInfo:
    out = _out("video", ".mp4")
    argv = [*LH, "video", prompt, "-o", str(out), "--width", str(width),
            "--height", str(height), "--frames", str(frames)]
    if seed:
        argv += ["--seed", str(seed)]
    return _queue("video", prompt, argv, out)


@SERVER.tool(description="Check a queued job. States: queued, running, done, "
                         "failed. A queued job says what it is waiting for.")
def job_status(job: str) -> JobInfo:
    got = workqueue.get(job)
    if got is None:
        return JobInfo(job=job, kind="", state="unknown", error="no such job")
    return _describe(got)


#: An artifact larger than this is reported by path rather than sent inline.
MAX_INLINE_BYTES = 50 * 1024 * 1024
MIME = {".png": "image/png", ".mp4": "video/mp4", ".wav": "audio/wav"}


@SERVER.tool(description="The finished artifact of a done job: the image "
                         "itself, or the video as an embedded file, so it "
                         "reaches a caller on another machine.")
def job_result(job: str) -> list:
    import base64

    from mcp.server.mcpserver import Image
    from mcp.types import BlobResourceContents, EmbeddedResource, TextContent

    got = workqueue.get(job)
    if got is None or got["state"] != workqueue.DONE:
        state = "unknown" if got is None else _STATE.get(got["state"], got["state"])
        return [TextContent(type="text", text=f"job {job} is {state}; nothing to return yet")]
    path = Path(got.get("output") or "")
    if not path.is_file():
        return [TextContent(type="text", text=f"job {job} finished but {path} is missing")]
    size = path.stat().st_size
    note = TextContent(type="text", text=f"{got['kind']} {path.name}, {size} bytes")
    if size > MAX_INLINE_BYTES:
        return [TextContent(type="text", text=f"{path} is {size} bytes, over the "
                            f"{MAX_INLINE_BYTES} inline limit; it stays on this machine")]
    if path.suffix == ".png":
        return [note, Image(path=path)]
    return [note, EmbeddedResource(type="resource", resource=BlobResourceContents(
        uri=path.resolve().as_uri(), mime_type=MIME.get(path.suffix, "application/octet-stream"),
        blob=base64.b64encode(path.read_bytes()).decode("ascii")))]


_STATE = {workqueue.PENDING: "queued"}


def _describe(job: dict) -> JobInfo:
    info = JobInfo(job=job["id"], kind=job.get("kind", ""),
                   state=_STATE.get(job["state"], job["state"]))
    if job["state"] == workqueue.PENDING:
        everyone = workqueue.jobs()
        line = [j["id"] for j in workqueue.pending()]
        info.ahead = (sum(1 for j in everyone if j["state"] == workqueue.RUNNING)
                      + line.index(job["id"]))
        running = next((j for j in everyone if j["state"] == workqueue.RUNNING), None)
        if running:
            info.waiting_for = running.get("kind") or "a job"
        else:
            ok, why = workqueue.gate()
            info.waiting_for = None if ok else why
            if ok and exclusive.holder().get("kind"):
                info.waiting_for = exclusive.holder().get("kind")
    if job["state"] == workqueue.DONE:
        info.path = job.get("output") or None
    if job["state"] == workqueue.FAILED:
        info.error = job.get("note") or f"exited {job.get('rc')}; log {job.get('log')}"
    return info


def transport_security(host: str, port: int, extra=()):
    """Who is allowed to name this server in a Host header.

    MCP 2.x enables DNS-rebinding protection with an EMPTY allowlist, so
    binding 0.0.0.0 is not enough: a request carrying `Host: <host>.local:8899`
    is refused before it reaches a tool, and the error says nothing useful.

    The protection STAYS ON. "No LAN auth, this network is trusted" is a decision
    about who can reach the port, and DNS rebinding does not need the port to
    be reachable from outside -- it needs someone on the LAN to open a web
    page, and then their browser makes the request. Different threat, so it
    keeps its guard and gets an allowlist instead.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    names = ["localhost", "127.0.0.1", _local_hostname(), *extra]
    if host not in ("0.0.0.0", "::", ""):
        names.append(host)
    allowed = []
    for name in dict.fromkeys(n for n in names if n):
        allowed += [f"{name}:{port}", name]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed,
        allowed_origins=[f"http://{n}" for n in allowed])


def _local_hostname() -> str:
    import socket
    import subprocess
    try:
        name = subprocess.run(["scutil", "--get", "LocalHostName"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        name = ""
    return f"{name}.local" if name else socket.gethostname()


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="soh-mcp")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--allow", action="append", default=[],
                    help="another hostname clients may use, e.g. an IP or the "
                         "Studio's name")
    ap.add_argument("--transport", default="streamable-http",
                    choices=["streamable-http", "stdio", "sse"])
    a = ap.parse_args()
    if a.transport == "stdio":
        SERVER.run(transport="stdio")
        return
    SERVER.run(transport=a.transport, host=a.host, port=a.port,
               transport_security=transport_security(a.host, a.port, a.allow))


if __name__ == "__main__":
    main()

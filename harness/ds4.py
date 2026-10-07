"""antirez/ds4 (DwarfStar): its own GGUFs served by ds4-server. #611.

`ds4:<stem>[,ssd_streaming=on|off][,expert_cache=32GB][,ctx=N][,temperature=...]`
names one file in the ds4 models dir and the launch that serves it. One
ds4-server holds one launch, so the launch is recorded on the receipt
(core.Receipt.launch) and a run starts or reuses the server that matches it.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from harness import paths

PREFIX = "ds4:"
ENGINE = "ds4-server"
URL = "http://127.0.0.1:8087"
PORT_VAR = "DS4_PORT"
BIN_VAR = "DS4_BIN"
MODELS_VAR = "DS4_MODELS_DIR"
SPEC_VAR = "DS4_SPEC"
DEFAULT_CTX = 32768
#: Options that change the launch; the rest of a spec's tail is sampling.
OPTIONS = ("ssd_streaming", "expert_cache", "ctx")
#: ds4-server has no response_format and returns no logprobs.
NOT_SERVED = {"decide": "ds4-server ignores response_format and returns no logprobs, "
                        "which every decide request needs"}
#: ds4's own GGUF architecture tag; general GGUFs of the same model do not carry it.
ARCH_TAGS = ("qwen4exp",)
GIB = 1024 ** 3


@dataclass(frozen=True)
class Model:
    """One file ds4's download_model.sh names, at the pinned commit."""
    repo: str
    file: str
    target: str
    #: The file's size on the hub, GiB, when the pin was read.
    gib: float
    #: Tables ds4 reads from the file on demand and never loads (n-grams, Engram).
    on_disk_gib: float = 0.0
    #: Whether ds4 implements SSD expert streaming for this model.
    streams: bool = True

    @property
    def stem(self) -> str:
        return self.file[:-len(".gguf")]


_DS4F = "antirez/deepseek-v4-gguf"
_QWEN = "antirez/qwen3.8-flash-next-gguf"
#: From download_model.sh and docs/MODELS.md at DS4_REV; a file not here is not guessed at.
MODELS = (
    Model(_QWEN, "Qwen3.8-Flash-Next-Q2.gguf", "qwen38-q2", 137.10, 95.37, streams=False),
    Model(_QWEN, "Qwen3.8-Flash-Next-Q4.gguf", "qwen38-q4k", 165.11, 95.37, streams=False),
    Model(_DS4F, "DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix-0731.gguf",
          "ds4f-q2", 80.76),
    Model(_DS4F, "DeepSeek-V4-Flash-Layers37-42Q4KExperts-OtherExpertLayersIQ2XXSGateUp-"
                 "Q2KDown-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix-fixed-0731.gguf", "ds4f-q2-q4", 90.89),
    Model(_DS4F, "DeepSeek-V4-Flash-Q4KExperts-F16HC-F16Compressor-F16Indexer-Q8Attn-Q8Shared-"
                 "Q8Out-chat-v2-imatrix-0731.gguf", "ds4f-q4", 153.33),
    Model(_DS4F, "DeepSeek-V4-Flash-MXFP4Experts-F16HC-F16Compressor-F16Indexer-Q8Attn-"
                 "Q8Shared-Q8Out-chat-v2-mxfp4-0731.gguf", "ds4f-mxfp4", 145.26),
    Model("antirez/deepseek-v4.1-flash-gguf", "DeepSeek-V4.1-Flash-Q2.gguf", "ds41f-q2", 341.0, 189.0),
    Model("antirez/deepseek-v4.1-flash-gguf", "DeepSeek-V4.1-Flash-Q4.gguf", "ds41f-q4", 483.0, 189.0),
)
REPOS = tuple(dict.fromkeys(m.repo for m in MODELS))


class Unservable(RuntimeError):
    """ds4-server cannot serve this spec here, for a reason that is the harness's."""


def model_of(stem: str) -> Model | None:
    return next((m for m in MODELS if m.stem == stem), None)


def recognised(repo: str, data: dict | None = None) -> bool:
    """A repo of ds4's own GGUFs: one ds4 publishes, or one carrying its architecture tag."""
    if (repo or "").strip().lower() in {r.lower() for r in REPOS}:
        return True
    raw = (data or {}).get("tags") or []
    if isinstance(raw, str):
        raw = raw.split(",")
    tags = {str(t).strip().lower() for t in raw}
    return any(t in tags for t in ARCH_TAGS)


# ---- the spec ---------------------------------------------------------------

@dataclass(frozen=True)
class Spec:
    stem: str
    ssd_streaming: bool = False
    expert_cache: str = "auto"
    ctx: int = DEFAULT_CTX
    sampling: dict = field(default_factory=dict)


_CACHE = re.compile(r"^(auto|\d+|\d+(\.\d+)?GB)$")


def parse(spec: str) -> Spec:
    """The spec's file and launch, or ValueError naming what is wrong with it."""
    from harness.serving import SAMPLING_KEYS
    head, _, optstr = (spec or "").partition(",")
    head = head.strip()
    if not head.startswith(PREFIX):
        raise ValueError(f"{spec!r} is not a ds4 spec; {PREFIX}<gguf stem>")
    stem = head[len(PREFIX):].strip()
    if not stem:
        raise ValueError(f"{spec!r} names no model; {PREFIX}<gguf stem>")
    opts, sampling = {}, {}
    for part in (p.strip() for p in optstr.split(",") if p.strip()):
        key, eq, value = part.partition("=")
        key, value = key.strip(), value.strip()
        if not eq or key not in (*OPTIONS, *SAMPLING_KEYS):
            raise ValueError(f"{spec}: unknown option {key}; ds4 takes "
                             f"{', '.join((*OPTIONS, *SAMPLING_KEYS))}")
        if key in SAMPLING_KEYS:
            try:
                sampling[key] = float(value)
            except ValueError:
                raise ValueError(f"{spec}: {key} must be a number") from None
        else:
            opts[key] = value
    streaming = opts.get("ssd_streaming", "off").lower()
    if streaming not in ("on", "off"):
        raise ValueError(f"{spec}: ssd_streaming must be on or off")
    cache = opts.get("expert_cache", "auto")
    if not _CACHE.match(cache):
        raise ValueError(f"{spec}: expert_cache is auto, a slot count, or a size like 32GB")
    if cache != "auto" and streaming != "on":
        raise ValueError(f"{spec}: expert_cache needs ssd_streaming=on")
    try:
        ctx = int(opts.get("ctx", DEFAULT_CTX))
    except ValueError:
        ctx = 0
    if ctx <= 0:
        raise ValueError(f"{spec}: ctx must be a positive token count")
    known = model_of(stem)
    if streaming == "on" and known is not None and not known.streams:
        raise ValueError(f"{spec}: ds4 has SSD expert streaming not implemented for "
                         f"{known.target}; serve it resident")
    return Spec(stem, streaming == "on", cache, ctx, sampling)


def key(spec: str) -> str:
    return PREFIX + parse(spec).stem


def launch(spec: str) -> dict:
    """What the server must have been started with for this spec's exam."""
    s = parse(spec)
    return {"ssd_streaming": "on" if s.ssd_streaming else "off",
            "expert_cache": s.expert_cache, "ctx": s.ctx, "ds4": version()}


def launch_text(got: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted(got.items()))


# ---- where things are -------------------------------------------------------

def url(environ=None) -> str:
    environ = os.environ if environ is None else environ
    got = (environ.get(PORT_VAR) or "").strip()
    return f"{URL.rsplit(':', 1)[0]}:{got}" if got.isdigit() else URL


def port() -> int:
    return int(url().rsplit(":", 1)[1])


def home() -> Path:
    """Under the localharness home, not the models volume, so a volume swap leaves the build."""
    return paths.home() / "ds4"


def checkout() -> Path:
    return home() / "checkout"


def binary() -> list[str]:
    named = (os.environ.get(BIN_VAR) or "").strip()
    return [named or str(checkout() / "ds4-server")]


def models_dir() -> Path:
    raw = (os.environ.get(MODELS_VAR) or "").strip()
    if raw:
        return Path(raw)
    from harness import env
    return env.beside() / "ds4"


def model_path(stem: str) -> Path:
    """The recorded file for this stem if it is still there, else where a fetch would put it."""
    for row in _rows(stem):
        if Path(row["path"]).exists():
            return Path(row["path"])
    return models_dir() / f"{stem}.gguf"


def _rows(stem: str) -> list:
    from harness import downloads
    try:
        with downloads.store() as c:
            return [r for r in downloads.live(c, kind=downloads.GGUF)
                    if r.get("file") == f"{stem}.gguf"]
    except Exception:  # noqa: BLE001 - an unreadable store falls back to the dir
        return []


def pinned_rev() -> str:
    text = (paths.REPO / "scripts" / "versions.sh").read_text(encoding="utf-8")
    m = re.search(r'^DS4_REV="([0-9a-f]{40})"$', text, re.M)
    return m.group(1) if m else ""


def version() -> str:
    """The checkout's commit date as YYYY.MM.DD, orderable for `version:ds4>X`; "" if unbuilt."""
    try:
        out = subprocess.run(["git", "-C", str(checkout()), "log", "-1", "--format=%cd",
                              "--date=format:%Y.%m.%d"], capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def available() -> bool:
    """The built ds4-server is there; a test may run it through an interpreter."""
    cmd = binary()
    exe = Path(cmd[-1])
    return exe.is_file() and (len(cmd) > 1 or os.access(exe, os.X_OK))


# ---- the launch -------------------------------------------------------------

def argv(spec: str, port_: int) -> list[str]:
    s = parse(spec)
    cmd = [*binary(), "-m", str(model_path(s.stem)), "--ctx", str(s.ctx),
           "--host", "127.0.0.1", "--port", str(port_), "--chdir", str(checkout())]
    if s.ssd_streaming:
        cmd.append("--ssd-streaming")
        if s.expert_cache != "auto":
            cmd += ["--ssd-streaming-cache-experts", s.expert_cache]
    return cmd


def state_path(port_: int) -> Path:
    return paths.home() / "run" / f"ds4-{port_}.json"


def write_state(spec: str, port_: int, pid: int) -> dict:
    got = {"spec": spec, "key": key(spec), "launch": launch(spec), "pid": pid,
           "port": port_}
    path = state_path(port_)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(got), encoding="utf-8")
    return got


def alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _models(base: str) -> dict | None:
    try:
        with _DIRECT.open(base + "/v1/models", timeout=3) as r:
            return json.loads(r.read() or b"{}") if r.status == 200 else None
    except Exception:  # noqa: BLE001 - not up
        return None


def live(port_: int | None = None) -> dict | None:
    """What answers on the port: its recorded launch, {} when nothing recorded it, None if down."""
    port_ = port() if port_ is None else port_
    listing = _models(f"http://127.0.0.1:{port_}")
    if listing is None:
        return None
    try:
        got = json.loads(state_path(port_).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"models": listing}
    if not alive(got.get("pid")):
        return {"models": listing}
    return {**got, "models": listing}


def served_ctx(spec: str) -> int | None:
    """The context the live server reports for this spec's file, else the spec's own."""
    try:
        s = parse(spec)
    except ValueError:
        return None
    got = live()
    if got and got.get("key") == PREFIX + s.stem:
        for m in (got.get("models") or {}).get("data") or []:
            if isinstance(m, dict) and m.get("context_length"):
                return int(m["context_length"])
    return s.ctx


def preflight(spec: str, port_: int | None = None) -> dict | None:
    """The live server to reuse, None when one must be started, or Unservable saying why not."""
    port_ = port() if port_ is None else port_
    want, stem = launch(spec), parse(spec).stem
    got = live(port_)
    if got is not None:
        if "launch" not in got:
            raise Unservable(f"ds4-server on :{port_} was not started by this harness, so "
                             f"which model and flags it holds is unknown; stop it to "
                             f"measure {spec}")
        if got.get("key") == PREFIX + stem and got["launch"] == want:
            return got
        raise Unservable(f"ds4-server on :{port_} serves {got.get('spec')} "
                         f"({launch_text(got['launch'])}); this run needs {spec} "
                         f"({launch_text(want)}). Stop it (scripts/launchd.sh or "
                         f"scripts/services.sh stop ds4) or measure that launch")
    if not available():
        raise Unservable(f"no ds4-server at {binary()[-1]}; build it with "
                         f"scripts/ds4-build.sh")
    path = model_path(stem)
    if not path.exists():
        hint = model_of(stem)
        raise Unservable(f"{path} is not on disk; fetch it with `uv run python -m "
                         f"harness.ds4 fetch {hint.repo if hint else '<repo>'} {stem}.gguf`")
    return None


#: Seconds to wait for a launch: a floor, plus a budget per resident GiB read at a slow volume's pace.
START_FLOOR_S = 300.0
START_S_PER_GIB = 20.0


def start_timeout(spec: str) -> float:
    """How long this spec's launch may take to answer, from its own resident size."""
    s = parse(spec)
    m = model_of(s.stem)
    path = model_path(s.stem)
    size = path.stat().st_size if path.exists() else int(m.gib * GIB) if m else 0
    resident = resident_bytes(spec, size)
    gib = (size if resident is None else resident) / GIB
    return START_FLOOR_S + START_S_PER_GIB * gib


@contextlib.contextmanager
def serving(spec: str, port_: int | None = None, timeout: float | None = None):
    """Yield the state of a ds4-server holding this spec's launch, starting one if none is up."""
    port_ = port() if port_ is None else port_
    reuse = preflight(spec, port_)
    if reuse is not None:
        yield reuse
        return
    from harness import vllm
    log = paths.home() / "logs" / f"ds4-{port_}.log"
    try:
        wait = start_timeout(spec) if timeout is None else timeout
        with vllm.served(argv(spec, port_), port_, log=log, timeout=wait) as srv:
            state = write_state(spec, port_, srv.proc.pid)
            yield state
    except RuntimeError as exc:
        if isinstance(exc, Unservable):
            raise
        raise Unservable(str(exc)) from exc
    finally:
        with contextlib.suppress(OSError):
            got = json.loads(state_path(port_).read_text(encoding="utf-8"))
            if not alive(got.get("pid")):
                state_path(port_).unlink()


def adopted(conn=None) -> str:
    """The ds4 spec a text lane has adopted here, which the service serves, or ""."""
    from harness import adopt, lanes
    try:
        defaults = adopt.lane_defaults(conn)
    except Exception:  # noqa: BLE001
        return ""
    for lane in lanes.TEXT_SERVED:
        spec = defaults.get(lane) or ""
        if spec.startswith(PREFIX):
            return spec
    return ""


# ---- choosing and fetching a file -------------------------------------------

def _resident(model: Model, size: int) -> int:
    return max(0, size - int(model.on_disk_gib * GIB))


def pick(repo: str, siblings, ceiling: int):
    """(model, file bytes, resident bytes, streaming) for the file to serve, or None.

    The largest file whose resident weights fit; else the smallest one ds4 can stream.
    """
    sized = {str(f.get("rfilename", "")): int(f.get("size") or 0) for f in siblings or []}
    known = [(m, sized[m.file]) for m in MODELS
             if m.repo.lower() == repo.lower() and sized.get(m.file)]
    if not known:
        known = [(m, sized[m.file]) for m in MODELS if sized.get(m.file)]
    fits = [(m, s, _resident(m, s)) for m, s in known if _resident(m, s) <= ceiling]
    if fits:
        m, s, r = max(fits, key=lambda x: x[2])
        return m, s, r, False
    streams = [(m, s, _resident(m, s)) for m, s in known if m.streams]
    if streams:
        m, s, r = min(streams, key=lambda x: x[2])
        return m, s, r, True
    if known:
        m, s = min(known, key=lambda x: _resident(*x))
        return m, s, _resident(m, s), False
    return None


def spec_for(repo: str, siblings=None, ceiling: int | None = None, conn=None) -> str:
    """The ds4 spec a recognised repo is screened as: its fetched file, else the file to fetch."""
    from harness import gguf
    stem = gguf.fetched(repo, conn)
    if stem and model_of(stem):
        m = model_of(stem)
        streaming = False
        if ceiling is None:
            from harness import inspect as ins
            ceiling = ins.ceiling_bytes()
        path = gguf.path_of(repo, conn)
        size = path.stat().st_size if path and path.exists() else 0
        streaming = m.streams and _resident(m, size) > ceiling
        return PREFIX + stem + (",ssd_streaming=on" if streaming else "")
    if siblings is None:
        siblings = [{"rfilename": m.file, "size": int(m.gib * GIB)} for m in MODELS
                    if m.repo.lower() == repo.lower()]
    if ceiling is None:
        from harness import inspect as ins
        ceiling = ins.ceiling_bytes()
    got = pick(repo, siblings, ceiling)
    if got is None:
        return ""
    m, _, _, streaming = got
    return PREFIX + m.stem + (",ssd_streaming=on" if streaming else "")


def resident_bytes(spec: str, file_bytes: int) -> int | None:
    """What loading this spec keeps in memory; None when ds4 sizes it (streaming, auto cache).

    On-disk tables never count; with streaming only the expert cache budget does.
    """
    s = parse(spec)
    m = model_of(s.stem)
    if s.ssd_streaming:
        cache = s.expert_cache
        if cache.endswith("GB"):
            return int(float(cache[:-2]) * GIB)
        return None
    return _resident(m, file_bytes) if m else file_bytes


def fetch(repo: str, filename: str, hf_download=None, conn=None) -> str:
    """Download one ds4 file into the ds4 models dir and record it. By hand only."""
    from harness import downloads
    if not any(m.repo.lower() == repo.lower() and m.file == filename for m in MODELS):
        raise ValueError(f"ds4 lists no {filename} in {repo} at {pinned_rev()[:7]}: "
                         f"{', '.join(m.file for m in MODELS if m.repo == repo)}")
    if hf_download is None:
        from huggingface_hub import hf_hub_download

        def hf_download(repo, filename, local_dir):
            return hf_hub_download(repo_id=repo, filename=filename, local_dir=local_dir)
    dest = models_dir()
    dest.mkdir(parents=True, exist_ok=True)
    with downloads.store(conn) as c:
        rid = downloads.start(c, repo, downloads.GGUF, dest / filename, file=filename,
                              origin=downloads.SCRIPT)
        try:
            where = hf_download(repo, filename, str(dest))
        except BaseException:
            downloads.finish(c, rid, failed=True)
            raise
        downloads.finish(c, rid)
    return str(where)


def main(args=None, out=None) -> int:
    out = out or sys.stdout
    args = list(sys.argv[1:] if args is None else args)
    if not args:
        print("usage: python -m harness.ds4 {argv SPEC [--port N] [--pid P] | adopted | "
              "fetch REPO FILE}", file=sys.stderr)
        return 2
    verb, rest = args[0], args[1:]
    if verb == "adopted":
        print(adopted(), file=out)
        return 0
    if verb == "fetch" and len(rest) == 2:
        print(fetch(rest[0], rest[1]), file=out)
        return 0
    if verb == "argv" and rest:
        spec, p, pid = rest[0], port(), 0
        if "--port" in rest:
            p = int(rest[rest.index("--port") + 1])
        if "--pid" in rest:
            pid = int(rest[rest.index("--pid") + 1])
        try:
            cmd = argv(spec, p)
        except ValueError as exc:
            print(f"ds4: {exc}", file=sys.stderr)
            return 2
        write_state(spec, p, pid)
        for part in cmd:
            print(part, file=out)
        return 0
    print(f"ds4: unknown command {' '.join(args)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

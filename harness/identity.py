"""A candidate's content identity: the bytes of its runtime and model, what it is sent, the exam, the harness and the machine. #1094."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

#: Machine facts that only time a run; recorded beside the identity, never matched.
TIMING = ("swap_used_mb", "available_gb", "thermal")
#: Library files of a llama.cpp build that a llama-server binary loads.
_RUNTIME_LIB = re.compile(r"(llama|ggml|mtmd)[^/\\]*\.(dylib|so|dll)$", re.IGNORECASE)
#: Installed distributions that are the mlx_lm.server runtime.
MLX_DISTS = ("mlx", "mlx-metal", "mlx-lm")
_READ = 8 * 1024 * 1024


def _sh(*argv: str) -> str:
    from evals.environment import _sh as sh
    return sh(*argv)


def cache_path() -> Path:
    from harness import paths
    return paths.home() / "cache" / "digests.json"


def _load_cache(path: Path) -> dict:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _save_cache(path: Path, got: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(got, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        if sys.platform == "darwin":
            import fcntl
            # An uncached read, so hashing a model does not evict a loaded one's pages.
            fcntl.fcntl(fh.fileno(), getattr(fcntl, "F_NOCACHE", 48), 1)
        for block in iter(lambda: fh.read(_READ), b""):
            h.update(block)
    return h.hexdigest()


def file_digest(path, cache: Path | None = None) -> str:
    """sha256 of a file's bytes, cached by (real path, size, mtime) so a large GGUF is read once."""
    real = Path(os.path.realpath(path))
    st = real.stat()
    key = f"{real}|{st.st_size}|{st.st_mtime_ns}"
    where = cache or cache_path()
    got = _load_cache(where)
    if key in got:
        return got[key]
    digest = _sha256(real)
    got = {k: v for k, v in _load_cache(where).items() if not k.startswith(f"{real}|")}
    got[key] = digest
    _save_cache(where, got)
    return digest


def files_digest(files, cache: Path | None = None) -> dict:
    """{name: sha256} for each file, by its name relative to the first file's directory when it is under it."""
    files = sorted({Path(os.path.realpath(f)) for f in files})
    return {f.name if len({x.name for x in files}) == len(files) else str(f): file_digest(f, cache)
            for f in files}


def _linked(exe: Path) -> list[Path]:
    """Absolute non-system libraries a binary links, on the platform that reads them."""
    if sys.platform == "darwin":
        text, skip = _sh("otool", "-L", str(exe)), ("/System/", "/usr/lib/")
        found = [line.strip().split(" (")[0] for line in text.splitlines()[1:]]
    elif sys.platform.startswith("linux"):
        text, skip = _sh("ldd", str(exe)), ("/lib", "/usr/lib")
        found = [m.group(1) for m in re.finditer(r"=>\s*(/\S+)", text)]
    else:
        return []
    return [Path(p) for p in found if p.startswith("/") and not p.startswith(skip)]


def runtime_files(binary) -> list[Path]:
    """A llama-server binary and the llama.cpp and ggml libraries beside it, its links and their backends."""
    exe = Path(os.path.realpath(binary))
    dirs = {exe.parent, exe.parent.parent / "lib"}
    dirs |= {Path(os.path.realpath(p)).parent for p in _linked(exe) if Path(p).exists()}
    dirs |= {d.parent / "libexec" for d in list(dirs)}
    libs = {Path(os.path.realpath(f)) for d in dirs if d.is_dir() for f in d.iterdir()
            if f.is_file() and _RUNTIME_LIB.search(f.name)}
    return [exe, *sorted(libs - {exe})]


def llama_server() -> Path | None:
    import shutil

    from harness import serving
    name = os.environ.get("LLAMACPP_BIN") or serving.LLAMACPP
    got = name if os.path.isfile(name) else shutil.which(name)
    return Path(got) if got else None


def dist_digest(name: str) -> str:
    """sha256 over an installed distribution's RECORD hashes, one per installed file."""
    from importlib import metadata
    try:
        files = metadata.distribution(name).files or []
    except metadata.PackageNotFoundError:
        return ""
    lines = sorted(f"{f}|{f.hash.value if f.hash else ''}" for f in files)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest() if lines else ""


def preset_path() -> Path:
    """The --models-preset INI scripts/serve-llamacpp.sh writes for the eval router's port."""
    from harness import paths, router
    return paths.home() / f"llamacpp-preset-{router.url().rsplit(':', 1)[1]}.ini"


def preset_section(stem: str, path: Path | None = None) -> dict:
    """The router preset's [*] and [stem] key lines, comments dropped."""
    path = path or preset_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict = {}
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section in ("*", stem):
            out.setdefault(section, []).append(re.sub(r"\s*=\s*", " = ", line))
    for line in out.get(stem, []):
        key, _, value = line.partition(" = ")
        if key in ("chat-template-file", "jinja-template-file") and os.path.isfile(value):
            out.setdefault("template_file", file_digest(value))
    return out


def snapshot_files(repo: str) -> list[Path]:
    """The hub snapshot main points at for a repo: its weights, index, config and tokenizer files."""
    from harness import downloads
    root = downloads.hub_dir(repo)
    try:
        rev = (root / "refs" / "main").read_text(encoding="utf-8").strip()
    except OSError:
        return []
    snap = root / "snapshots" / rev
    return sorted(f for f in snap.rglob("*") if f.is_file()) if snap.is_dir() else []


def served(spec: str) -> dict:
    """{"engine", "runtime", "model", "preset"} for a text spec, with "unresolved" naming what had no bytes to read."""
    from harness import context, gguf, serving
    base = spec.partition(",")[0].strip()
    try:
        engine = serving.engine_for(base)
    except ValueError as exc:
        return {"unresolved": [f"engine: {exc}"]}
    out: dict = {"engine": engine}
    where = context._upstream(base)
    if engine == serving.LLAMACPP:
        if where is None or not serving.loopback(where[0]):
            return {**out, "unresolved": [f"model: {base} is not served from this machine"]}
        stem = where[1]
        exe = llama_server()
        gguf_path = gguf.models_dir() / f"{stem}.gguf"
        missing = ([] if exe else ["runtime: no llama-server binary"]) + (
            [] if gguf_path.exists() else [f"model: no {gguf_path.name} in the models dir"])
        if missing:
            return {**out, "unresolved": missing}
        return {**out, "engine": serving.LLAMACPP, "runtime": files_digest(runtime_files(exe)),
                "model": files_digest([gguf_path]), "preset": preset_section(stem)}
    repo = base if "/" in base else (where[1] if where else "")
    if engine == serving.DEFAULT and "/" in repo:
        runtime = {d: dist_digest(d) for d in MLX_DISTS if dist_digest(d)}
        files = snapshot_files(repo)
        missing = ([] if runtime.get("mlx-lm") else ["runtime: mlx-lm is not installed here"]) + (
            [] if files else [f"model: no hub snapshot of {repo}"])
        if missing:
            return {**out, "unresolved": missing}
        return {**out, "runtime": runtime, "model": files_digest(files)}
    return {**out, "unresolved": [f"runtime: no content identity for {engine}"]}


def harness_state(root: Path | None = None) -> dict:
    """The harness commit, whether the checkout is dirty, and the hash of its tracked diff when it is."""
    from harness import paths
    root = root or paths.REPO
    sha = _sh("git", "-C", str(root), "rev-parse", "HEAD")
    dirty = bool(_sh("git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"))
    diff = (hashlib.sha256(_sh("git", "-C", str(root), "diff", "HEAD").encode("utf-8")).hexdigest()
            if dirty else "")
    return {"git_sha": sha or "unknown", "git_dirty": dirty, "diff": diff}


def _pmset(*args: str) -> str:
    return _sh("pmset", *args) if sys.platform == "darwin" else ""


def machine_state() -> tuple[dict, dict]:
    """(what is matched: hw_model, OS build, memory, power mode; what only times a run)."""
    import platform

    from evals import environment
    from harness import memory
    me = environment.identity()
    mem = _sh("sysctl", "-n", "hw.memsize")
    build = _sh("sw_vers", "-buildVersion") if sys.platform == "darwin" else platform.platform()
    power = re.findall(r"^\s*(powermode|lowpowermode|highpowermode)\s+(\d+)", _pmset("-g"), re.MULTILINE)
    swap = re.search(r"used\s*=\s*([\d.]+)M", _sh("sysctl", "-n", "vm.swapusage"))
    matched = {"hw_model": me["hw_model"], "os_build": build, "arch": me["arch"],
               "memory_gb": round(int(mem) / 1024 ** 3) if mem.isdigit() else round(memory.system_memory_gb()),
               "power": dict(sorted(power))}
    timing = {"swap_used_mb": round(float(swap.group(1))) if swap else 0,
              "available_gb": round(memory.available_gb(), 2),
              "thermal": " ".join(_pmset("-g", "therm").split())}
    return matched, timing


def lane_cases(lane: str) -> list:
    """The lane's cases as a paired evals.run with no --cases loads them."""
    from evals import run
    return run.load_selected(run.parse_args(["--modality", lane]))


def settings(lane: str, spec: str, budget: int, ladder=(), overrides=None) -> dict:
    """The reply settings and sampling this spec is sent in this lane."""
    from evals import run
    from harness import knobs
    text = run.text_candidate(spec)
    return {"spec": spec, "max_tokens": int(budget), "budget_ladder": list(ladder),
            "sampling": run.effective_sampling(lane, [spec]).get(lane, {}) if text else {},
            "template": run.effective_template(lane, [spec]).get(lane, {}) if text else {},
            "knobs": knobs.settings(lane, overrides or {})}


def digest_of(parts: dict) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def of(lane: str, spec: str, *, budget: int, ladder=(), overrides=None, cases=None,
       machine=None, harness=None) -> dict:
    """{"digest", "parts", "timing", "unresolved"}; the digest is "" when any part has no bytes to read."""
    from evals import core, run
    from harness import holdout
    cases = lane_cases(lane) if cases is None else cases
    matched, timing = machine if machine is not None else machine_state()
    target = run.text_spec(spec) if run.text_candidate(spec) else ""
    serving_part = served(target) if target else {"unresolved": [f"runtime: {spec} is not a text spec"]}
    unresolved = list(serving_part.pop("unresolved", []))
    parts = {"served": serving_part, "settings": settings(lane, spec, budget, ladder, overrides),
             "exam": {"lane": lane, "split_version": holdout.version(lane),
                      "cases_digest": core.cases_digest(cases)},
             "harness": harness if harness is not None else harness_state(), "machine": matched}
    return {"digest": "" if unresolved else digest_of(parts), "parts": parts, "timing": timing,
            "unresolved": unresolved}


def moved(before: dict, after: dict) -> list[str]:
    """'runtime'/'model' changes between two recorded identities, for the reverify trigger. #480."""
    a = (before or {}).get("parts", {}).get("served", {})
    b = (after or {}).get("parts", {}).get("served", {})
    out = []
    for part in ("runtime", "model"):
        x, y = a.get(part), b.get(part)
        if x and y and x != y:
            changed = sorted(k for k in set(x) | set(y) if x.get(k) != y.get(k))
            out.append(f"{part} bytes changed: {', '.join(changed)}")
    return out

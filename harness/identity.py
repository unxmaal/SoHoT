"""A candidate's content identity: the bytes of its runtime and model, what it is sent, the exam and the machine; the harness commit is recorded, not matched. #1094."""
from __future__ import annotations

import ast
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


def settings(lane: str, spec: str, budget: int, ladder=(), overrides=None, repo_harness: str = "patch") -> dict:
    """The reply settings and sampling this spec is sent in this lane, and a method's template digest."""
    from evals import run
    from harness import knobs
    from harness.knobs.repo import REPAIR
    text = run.text_candidate(spec)
    exam = {k: v for k, v in knobs.settings(lane, overrides or {}).items()
            if repo_harness != "patch" or k not in REPAIR}
    return {"spec": spec, "max_tokens": int(budget), "budget_ladder": list(ladder),
            "sampling": run.effective_sampling(lane, [spec]).get(lane, {}) if text else {},
            "template": run.effective_template(lane, [spec]).get(lane, {}) if text else {},
            "method": run.method_receipts({"spec": spec}).get("spec", {}),
            "knobs": exam}


def digest_of(parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def as_now(stored: dict, now: dict) -> str:
    """The digest of stored parts with each knob now recorded but absent there filled at its unrecorded value. #1353."""
    from harness import knobs
    have = ((stored.get("settings") or {}).get("knobs"))
    want = ((now.get("settings") or {}).get("knobs")) or {}
    if not isinstance(have, dict):
        return ""
    fill = {k: knobs.UNRECORDED[k] for k in want if k not in have and k in knobs.UNRECORDED}
    if not fill:
        return ""
    return digest_of({**stored, "settings": {**stored["settings"], "knobs": {**have, **fill}}})


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _small_sha(path) -> str:
    """sha256 of a small file read whole, uncached: a case file or a grader module."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


#: Repo packages whose code a grader can reach; anything else (stdlib, third party) is pinned by the machine and venv.
GRADER_PACKAGES = ("harness", "evals")
#: Where every lane's checker is registered, and the scoring entry every lane runs through.
CHECKER_REGISTRY = ("evals.core", "CHECKERS")
SCORE_ENTRY = (("evals.core", "score"),)
_BODY = "<body>"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


class _Module:
    """One repo module read by ast: its top-level statements by the names they bind, its imports, its loose statements."""

    def __init__(self, name: str, path: Path):
        self.name, self.package = name, name if path.name == "__init__.py" else name.rpartition(".")[0]
        self.lines = path.read_text(encoding="utf-8").splitlines()
        tree = ast.parse("\n".join(self.lines), filename=str(path))
        self.stmts: dict = {}
        self.imports: dict = {}
        self.stars: list = []
        self.loose: list = []
        self.main: list = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bound = self.bind_import(node)
                self.imports.update(bound)
                continue
            names = sorted(_bound(node))
            if names:
                for n in names:
                    self.stmts[n] = (",".join(names), node)
            elif _is_main(node):
                self.main.append(node)
            elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
                self.loose.append(node)

    def bind_import(self, node) -> dict:
        """{local name: (module, attr or "")} for one import statement; star imports go to self.stars."""
        out = {}
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.partition(".")[0]] = (a.name if a.asname else a.name.partition(".")[0], "")
            return out
        base = node.module or ""
        if node.level:
            parts = self.package.split(".")
            parts = parts[:len(parts) - node.level + 1]
            base = ".".join(parts + ([base] if base else []))
        for a in node.names:
            if a.name == "*":
                self.stars.append(base)
            else:
                out[a.asname or a.name] = (base, a.name)
        return out

    def source(self, node) -> str:
        first = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
        return "\n".join(self.lines[first - 1:node.end_lineno])


def _is_main(node) -> bool:
    test = getattr(node, "test", None) if isinstance(node, ast.If) else None
    return (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "__name__"
            and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in test.comparators))


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda,
           ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _bound(node) -> set:
    """The module-level names a top-level statement binds; names inside a nested scope are not module names."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    out, todo = set(), [node]
    while todo:
        sub = todo.pop()
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            out.add(sub.id)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(sub.name)
            continue
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            out |= {(a.asname or a.name).partition(".")[0] for a in sub.names if a.name != "*"}
        if not isinstance(sub, _SCOPES):
            todo.extend(ast.iter_child_nodes(sub))
    return out


def _uses(node) -> tuple[set, list]:
    """(bare names loaded, attribute chains as name lists) in a statement or expression."""
    chains, inner, heads = [], set(), set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and id(sub) not in inner:
            chain, cur = [], sub
            while isinstance(cur, ast.Attribute):
                inner.add(id(cur))
                chain.insert(0, cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                heads.add(id(cur))
                chains.append([cur.id, *chain])
    names = {sub.id for sub in ast.walk(node)
             if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and id(sub) not in heads}
    return names, chains


def grader_digest(lane: str, *, root=None, packages=GRADER_PACKAGES, registry=CHECKER_REGISTRY,
                  also=SCORE_ENTRY) -> dict:
    """{"modules", "names"}: the repo modules a lane's checker reaches by static import and name analysis (nothing is imported), a sha256 per statement reached."""
    root = Path(root) if root is not None else _repo_root()
    parsed: dict = {}

    def module(name: str):
        if not name or not any(name == p or name.startswith(p + ".") for p in packages):
            return None
        if name not in parsed:
            base = root.joinpath(*name.split("."))
            path = next((f for f in (base / "__init__.py", base.with_suffix(".py")) if f.is_file()), None)
            try:
                parsed[name] = _Module(name, path) if path else None
            except (OSError, SyntaxError, UnicodeDecodeError):
                parsed[name] = None
        return parsed[name]

    reg_mod = module(registry[0])
    entry = None
    if reg_mod and registry[1] in reg_mod.stmts:
        value = getattr(reg_mod.stmts[registry[1]][1], "value", None)
        if isinstance(value, ast.Dict):
            entry = next((v for k, v in zip(value.keys, value.values)
                          if isinstance(k, ast.Constant) and k.value == lane), None)
    if entry is None:
        return {}
    out: dict = {}
    seen: set = set()
    todo: list = []

    def visit(mod, node, key):
        out[f"{mod.name}:{key}"] = _text_sha(mod.source(node))
        local = {}
        for sub in ast.walk(node):
            if isinstance(sub, (ast.Import, ast.ImportFrom)) and sub is not node:
                local.update(mod.bind_import(sub))
        names, chains = _uses(node)
        for n in names:
            todo.append((mod.name, n, local.get(n)))
        for chain in chains:
            todo.append((mod.name, chain, local.get(chain[0])))

    def reach_module(name: str, whole: bool) -> None:
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            todo.append((".".join(parts[:i]), _BODY, None))
        if whole:
            todo.append((name, "*", None))

    def resolve(modname: str, ref, binding) -> None:
        """Reach what `ref` (a name or an attribute chain) names in module `modname`."""
        mod = module(modname)
        if mod is None:
            return
        chain = ref if isinstance(ref, list) else [ref]
        head, rest = chain[0], chain[1:]
        if head == _BODY:
            if (modname, _BODY) in seen:
                return
            seen.add((modname, _BODY))
            for target, attr in mod.imports.values():
                reach_module(target if module(f"{target}.{attr}") is None else f"{target}.{attr}", False)
            for i, node in enumerate(mod.loose):
                visit(mod, node, f"{_BODY}{i}")
            return
        if head == "<main>":
            if (modname, head) not in seen:
                seen.add((modname, head))
                for i, node in enumerate(mod.main):
                    visit(mod, node, f"<main>{i}")
            return
        if head == "*":
            if (modname, "*") in seen:
                return
            seen.add((modname, "*"))
            for name in list(mod.stmts):
                todo.append((modname, name, None))
            for local in mod.imports:
                todo.append((modname, local, None))
            return
        binding = binding or mod.imports.get(head)
        if binding is None:
            if head in mod.stmts:
                key, node = mod.stmts[head]
                if (modname, key) in seen:
                    return
                seen.add((modname, key))
                reach_module(modname, False)
                todo.append((modname, "<main>", None))
                visit(mod, node, key)
            elif (modname, f"*{head}") not in seen:
                seen.add((modname, f"*{head}"))
                for star in mod.stars:
                    todo.append((star, chain, None))
            return
        target, attr = binding
        path = [*target.split("."), *([attr] if attr else []), *rest]
        for cut in range(len(path), 0, -1):
            name = ".".join(path[:cut])
            if module(name) is not None:
                if cut == len(path):
                    reach_module(name, True)
                else:
                    reach_module(name, False)
                    todo.append((name, path[cut], None))
                return

    out[f"{reg_mod.name}:{registry[1]}[{lane}]"] = _text_sha(ast.get_source_segment("\n".join(reg_mod.lines), entry) or "")
    seen.add((reg_mod.name, registry[1]))
    names, chains = _uses(entry)
    todo += [(reg_mod.name, n, None) for n in names] + [(reg_mod.name, c, None) for c in chains]
    todo += [(m, n, None) for m, n in also]
    while todo:
        modname, ref, binding = todo.pop()
        resolve(modname, ref, binding)
    return {"modules": sorted({k.partition(":")[0] for k in out}), "names": dict(sorted(out.items()))}


def _grader_part(lane: str) -> dict:
    got = grader_digest(lane)
    return {"grader": got.get("names", {}), "grader_modules": got.get("modules", [])}


def _request_settings(spec: str) -> tuple[dict, dict]:
    """(sampling, template kwargs) the text runner is built with for this spec, as serving.route gives them."""
    from harness import serving
    base = spec.partition(",")[0].strip()
    try:
        where = serving.route(spec)
        return dict(where.sampling or {}), dict(getattr(where, "template", None) or {})
    except ValueError:
        optstr = spec.partition(",")[2]
        return serving._sampling(optstr, base), serving.template_options(optstr, base)


def case_digests(spec: str, cases, budget: int) -> dict:
    """{case id: sha256} over each case's content, its case file and, for a text spec, the request body it is sent."""
    from evals import core, repo, run
    from evals.runners.text import CompletionRunner
    from harness import completion
    text = run.text_candidate(spec)
    sampling, template = _request_settings(run.text_spec(spec)) if text else ({}, {})
    out = {}
    for c in cases:
        source = getattr(c, "source", None)
        parts = {"case": core.case_digest(c),
                 "file": _small_sha(source) if source and Path(source).is_file() else ""}
        if text:
            asked = repo.as_asked(c) if c.modality == "repo" else c
            body = completion.payload_for(
                asked.prompt, "", asked.modality, asked.context, None,
                budget or completion.budget(c.modality) or completion.MAX_TOKENS,
                sampling or None, template or None,
                completion.TOP_LOGPROBS if c.modality == "decide" else 0, True,
                CompletionRunner._system(asked),
                CompletionRunner._reply_shape(c))
            body.pop("model", None)
            parts["request"] = body
        out[c.id] = digest_of(parts)
    return out


def of(lane: str, spec: str, *, budget: int, ladder=(), overrides=None, cases=None,
       machine=None, harness=None, repo_harness: str = "patch") -> dict:
    """{"digest", "cases", "parts", "recorded", "timing", "unresolved"}; the digest is "" when any part has no bytes to read.

    The digest matches a run; "cases" matches each case. The harness commit is recorded, never matched.
    """
    from evals import run
    from harness import holdout
    cases = lane_cases(lane) if cases is None else cases
    matched, timing = machine if machine is not None else machine_state()
    target = run.text_spec(spec) if run.text_candidate(spec) else ""
    serving_part = served(target) if target else {"unresolved": [f"runtime: {spec} is not a text spec"]}
    unresolved = list(serving_part.pop("unresolved", []))
    parts = {"served": serving_part, "settings": settings(lane, spec, budget, ladder, overrides, repo_harness),
             "exam": {"lane": lane, "split_version": holdout.version(lane), **_grader_part(lane)},
             "machine": matched}
    if repo_harness != "patch":
        parts["exam"]["harness"] = repo_harness
    return {"digest": "" if unresolved else digest_of(parts), "cases": case_digests(spec, cases, budget),
            "parts": parts, "recorded": {"harness": harness if harness is not None else harness_state()},
            "timing": timing, "unresolved": unresolved}


def combined(ident: dict) -> str:
    """One digest over a run's identity and its per-case digests, for a checkpoint to compare."""
    return digest_of([ident.get("digest", ""), ident.get("cases") or {}]) if ident.get("digest") else ""


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

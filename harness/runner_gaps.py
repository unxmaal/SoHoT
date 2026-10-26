"""Why a runner here cannot load a repo, and the until naming what would. #950, #951.

    uv run python -m harness.runner_gaps   rewrite both snapshots (mlx-lm from this venv, diffusers from its venv)
"""
from __future__ import annotations

import ast
import functools
import json
import re
import sys
from collections import Counter
from pathlib import Path

#: Model types the locked mlx-lm builds (its models/ modules and MODEL_REMAPPING keys); first line `# <pin>`.
MLX_LM_SNAPSHOT = Path(__file__).with_name("mlx_lm_model_types.txt")
#: Pipeline classes the pinned diffusers ships; first line `# <pin>`.
DIFFUSERS_SNAPSHOT = Path(__file__).with_name("diffusers_pipelines.txt")

#: Runners no engine is registered for; an until naming one is met once engines.names() has it.
VLM_RUNNER = "mlx-vlm"
TEXT_RUNNER = "transformers"

#: Card tasks whose model takes more than text, so the text server builds at most a part of it.
VLM_TASKS = frozenset({"image-text-to-text", "any-to-any", "image-to-text", "video-text-to-text",
                       "visual-question-answering", "audio-text-to-text"})
#: Text model types mlx-lm declined upstream, so no release of it builds them.
DECLINED = {"qwen3_5_text": "ml-explore/mlx-lm#869 added qwen3_5 and left qwen3_5_text out (RULE #350)"}
#: Card tags naming a weight format mlx-lm does not read.
VENDOR_FORMATS = ("eschamoe", "zml", "exl2", "exl3", "aqlm", "hqq", "gptq")
#: Libraries whose checkpoints the bare text spec reaches: mlx-lm, or llama-server for a GGUF.
TEXT_LIBRARIES = frozenset({"transformers", "mlx", "mlx-lm", "mlx_lm", "gguf", "llama.cpp",
                            "vllm", "sglang", "safetensors", "peft"})
#: Engines that build generation pipelines from a model_index.json.
DIFFUSERS_HEADS = ("diffusers", "diffusers-video")
#: Engines that load a discovered repo through a stock loader, so its card can say they cannot.
CARD_CHECKED = DIFFUSERS_HEADS + ("acestep",)
#: Tensor names a stock checkpoint ends in; any other leaf names the format the runner could not read.
_STOCK_LEAVES = frozenset({"weight", "bias", "scales", "biases"})

REMOTE_CODE = "policy:trust_remote_code"
#: The venv each process engine runs in, under <home>/venvs or the env var its script reads. #1008.
RUNNER_VENVS = {"diffusers": "diffusers-cuda", "diffusers-video": "diffusers-cuda",
                "hf-ocr": "hf-task", "rerank": "hf-task", "embed": "hf-task", "hf-pii": "hf-task",
                "transnetv2": "shots", "scenedetect": "shots"}
#: The in-process stt runner (audio.transcribe_whisper); the uv `whisper` group installs it. #1021.
WHISPER_PACKAGE = "mlx-whisper"
WHISPER_VENV = "whisper"
#: Runner venvs uv syncs from this project's lock plus one dependency group when a run first needs them: venv -> group. #1024.
GROUP_VENVS = {WHISPER_VENV: "whisper"}
_VENV_ENV = {"diffusers-cuda": "DIFFUSERS_VENV", "hf-task": "HF_TASK_VENV", WHISPER_VENV: "WHISPER_VENV",
             "nimble": "NIMBLE_VENV", "decider": "DECIDER_VENV", "shots": "SHOTS_VENV"}
#: Venvs kept at <home>/<name>/venv beside the checkout their script clones, and the env var that moves that home. #1037.
_CHECKOUT_VENVS = {"nimble": "NIMBLE_HOME", "decider": "DECIDER_HOME"}
#: The script that builds each process engine's venv and the bash arrays of pins it installs. #1024, #1037.
VENV_SCRIPTS = {"diffusers-cuda": ("scripts/diffusers-venv.sh", "DIFFUSERS_VENV_PINS", "DIFFUSERS_TORCH"),
                "hf-task": ("scripts/hf-task-venv.sh", "HF_TASK_PINS", "HF_TASK_TORCH"),
                "nimble": ("scripts/nimble-venv.sh", "NIMBLE_VENV_PINS"),
                "decider": ("scripts/decider-venv.sh", "DECIDER_VENV_PINS", "DECIDER_MLX"),
                "shots": ("scripts/shots-venv.sh", "SHOTS_PINS", "SHOTS_TORCH")}
#: The audio server's env: its script's `uv run --no-project --with` pins layered over the checkout's .venv. #1030.
AUDIO_ENV = "audio-server"
#: Envs uv builds when their run or service starts, so the deploy declaring a package ends a wait on it.
LAUNCH_BUILT = frozenset({*GROUP_VENVS, AUDIO_ENV})

_NAMED_TYPE = re.compile(r"model type ([\w.\-]+?)\.? not supported")
_PARAMS = re.compile(r"parameters not in model:(.*)", re.S)
#: A loader naming the pipeline class it could not build: (pattern, suffix the runner route takes).
_PIPELINE_NAMED = ((re.compile(r"has no attribute (\w+Pipeline)", re.I), ""),
                   (re.compile(r"pipeline linked to (\w+Pipeline)", re.I), ""),
                   (re.compile(r"Pipeline <class '[\w.]*?(\w+Pipeline)'> expected"), "-layout"))


def _snapshot(path: Path) -> tuple[str, frozenset]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return lines[0].lstrip("# ").strip(), frozenset(x.strip() for x in lines[1:] if x.strip())


@functools.lru_cache(maxsize=1)
def mlx_lm_types() -> tuple[str, frozenset]:
    return _snapshot(MLX_LM_SNAPSHOT)


@functools.lru_cache(maxsize=1)
def diffusers_pipelines() -> tuple[str, frozenset]:
    return _snapshot(DIFFUSERS_SNAPSHOT)


def head_of(spec: str) -> str:
    """The engine a spec names, "" for a bare repo id the text server swaps to."""
    first = (spec or "").partition(",")[0]
    head = first.partition(":")[0].strip()
    if ":" in first:
        return head
    from harness import engines
    return head if head in engines.names() else ""


def tags_of(card) -> list[str]:
    tags = (card or {}).get("card_tags", (card or {}).get("tags")) or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = [tags]
    return [str(t).strip() for t in tags if str(t).strip()]


def _task(card) -> str:
    card = card or {}
    return str(card.get("hf_task") or card.get("pipeline_tag") or "").strip().lower()


def _library(card) -> str:
    card = card or {}
    return str(card.get("library") or card.get("library_name") or "").strip().lower()


def model_type(card, evidence: str = "") -> str:
    """The card's model type, else the one a loader's `Model type X not supported` names."""
    got = str((card or {}).get("model_type") or "").strip()
    if got:
        return got
    m = _NAMED_TYPE.search((evidence or "").lower())
    return m.group(1) if m else ""


def mlx_lm_builds(mtype: str) -> bool:
    return bool(mtype) and mtype in mlx_lm_types()[1]


def native_in_transformers(mtype: str) -> bool:
    from harness import remote_code
    return bool(mtype) and mtype in remote_code.native_types()[1]


def remote_code_gap(card, evidence: str = "") -> str:
    """Why a runner that never executes a repo's own code cannot load it, or "". #567."""
    from harness import remote_code
    got = remote_code.gap(card)
    if got:
        return got
    mtype = model_type(card, evidence)
    # A card read before #567 has no remote_code column; its custom_code tag and an unshipped type stand in.
    if (not (card or {}).get("remote_code") and mtype and not native_in_transformers(mtype)
            and "custom_code" in [t.lower() for t in tags_of(card)]):
        return (f"its card is tagged custom_code and its model type {mtype!r} is not one "
                f"{remote_code.native_types()[0]} ships")
    return ""


def remote_code_until(mtype: str) -> str:
    """Met once the pinned transformers ships the type natively; no remote-code runner exists."""
    return f"{REMOTE_CODE}@{mtype}" if mtype else REMOTE_CODE


def vendor_format(card) -> str:
    low = [t.lower() for t in tags_of(card)]
    return next((f for f in VENDOR_FORMATS if f in low), "")


def pipeline_class(card) -> str:
    """The pipeline class a card's `diffusers:<Class>` tag names, or ""."""
    for tag in tags_of(card):
        head, sep, cls = tag.partition(":")
        if sep and head.lower() == "diffusers" and cls.endswith("Pipeline"):
            return cls
    return ""


def text_gap(card) -> tuple[str, str]:
    """(why, until) the bare text spec cannot load the repo its card describes, or ("", "")."""
    if not card:
        return "", ""
    library = _library(card)
    if library and library not in TEXT_LIBRARIES:
        return (f"its card names the {library} library, which neither mlx-lm nor llama-server loads",
                f"runner:{library}")
    mtype = model_type(card)
    task = _task(card)
    if task in VLM_TASKS and mtype and not mlx_lm_builds(mtype):
        return (f"a {task} model of type {mtype!r}, which {mlx_lm_types()[0]} does not build, "
                f"and no {VLM_RUNNER} runner is registered here", f"runner:{VLM_RUNNER}")
    if not mlx_lm_builds(mtype):
        code = remote_code_gap(card)
        if code:
            return code, remote_code_until(mtype)
    if mtype in DECLINED:
        return f"model type {mtype!r}: {DECLINED[mtype]}", f"runner:{TEXT_RUNNER}"
    fmt = vendor_format(card)
    if fmt:
        return f"its card is tagged {fmt}, a weight format mlx-lm does not read", f"format:{fmt}"
    return "", ""


def engine_gap(head: str, card) -> tuple[str, str]:
    """(why, until) engine `head` cannot load the repo its card describes, or ("", "")."""
    if not card:
        return "", ""
    code = remote_code_gap(card)
    if code:
        return code, remote_code_until(model_type(card))
    if head not in DIFFUSERS_HEADS:
        return "", ""
    library, task = _library(card), _task(card)
    if library and library != "diffusers":
        return (f"its card names the {library} library, and {head} assembles diffusers pipelines",
                f"runner:{head}/{library}")
    if task in VLM_TASKS:
        return f"a {task} model, and {head} assembles generation pipelines", f"runner:{head}/{task}"
    cls = pipeline_class(card)
    pin, known = diffusers_pipelines()
    if cls and cls not in known:
        return f"its model_index.json names {cls}, which {pin} does not ship", f"runner:{head}/{cls}"
    siblings = (card or {}).get("siblings")
    if siblings is not None and not any(
            str(s.get("rfilename", s) if isinstance(s, dict) else s).rsplit("/", 1)[-1] == "model_index.json"
            for s in siblings):
        return ("it ships no model_index.json, so the stock pipeline loader cannot assemble it",
                f"runner:{head}/single-file")
    return "", ""


def pre_screen(spec: str, card) -> tuple[str, str]:
    """(why, until) the runner `spec` names cannot load this repo, read from its card before any download."""
    head = head_of(spec)
    if not head:
        return text_gap(card)
    return engine_gap(head, card) if head in CARD_CHECKED else ("", "")


def format_name(card, evidence: str) -> str:
    """The weight format a `parameters not in model` failure names: a vendor tag, else the commonest odd tensor leaf."""
    fmt = vendor_format(card)
    if fmt:
        return fmt
    m = _PARAMS.search(evidence or "")
    names = re.findall(r"[A-Za-z_][\w.]*", m.group(1).replace("\\n", " ")) if m else []
    leaves = Counter(n.rsplit(".", 1)[-1] for n in names if "." in n)
    odd = [leaf for leaf, _ in leaves.most_common() if leaf not in _STOCK_LEAVES]
    return odd[0] if odd else "unread-tensors"


def layout_name(card, evidence: str) -> str:
    """What a stock loader could not assemble, named for a runner route nobody has registered."""
    for pattern, suffix in _PIPELINE_NAMED:
        m = pattern.search(evidence or "")
        if m:
            return m.group(1) + suffix
    low = (evidence or "").lower()
    library, task = _library(card), _task(card)
    if "model_index.json" in low:
        if library and library != "diffusers":
            return library
        return task if task in VLM_TASKS else "single-file"
    if "no safetensors found" in low:
        return library or "no-safetensors"
    return model_type(card) or ("no-model-type" if "could not determine model type" in low else "layout")


def venv_path(name: str) -> Path:
    import os
    from harness import paths
    if os.environ.get(_VENV_ENV.get(name, "")):
        return Path(os.environ[_VENV_ENV[name]])
    if name in _CHECKOUT_VENVS:
        return Path(os.environ.get(_CHECKOUT_VENVS[name]) or paths.home() / name) / "venv"
    return paths.home() / "venvs" / name


def _canonical(dist: str) -> str:
    return re.sub(r"[-_.]+", "-", dist).lower()


def venv_packages(name: str) -> frozenset:
    """The distributions installed in a runner venv, read from its dist-info directories, never imported."""
    root = venv_path(name)
    sites = [*root.glob("lib/python*/site-packages"), root / "Lib" / "site-packages"]
    return frozenset(_canonical(d.name[:-len(".dist-info")].rpartition("-")[0])
                     for site in sites if site.is_dir() for d in site.glob("*.dist-info"))


def has_package(dist: str, venv: str = "") -> bool:
    """Whether the venv (or, unnamed, this interpreter) has the distribution installed. #1008."""
    if venv:
        return _canonical(dist) in venv_packages(venv)
    from importlib import metadata
    try:
        metadata.distribution(dist)
    except metadata.PackageNotFoundError:
        return False
    return True


def whisper_repo(model: str, card=None) -> bool:
    """An mlx whisper checkpoint, the layout mlx-whisper reads, by its card or its repo name. #1021."""
    name = (model or "").partition(",")[0].lower()
    mtype = str((card or {}).get("model_type") or "").strip().lower()
    mlx = "mlx" in name or _library(card) == "mlx" or "mlx" in [t.lower() for t in tags_of(card)]
    return mlx and (mtype == "whisper" or "whisper" in name)


def whisper_in_process(model: str, card=None) -> bool:
    """Whether a whisper repo can screen through mlx-whisper, in the whisper group's env. #1021, #1024."""
    return whisper_repo(model, card) and provides(WHISPER_PACKAGE, WHISPER_VENV)


def _options(spec: str) -> dict:
    tail = (spec or "").partition(",")[2]
    return {k.strip(): v.strip() for k, _, v in (kv.partition("=") for kv in tail.split(",")) if k.strip()}


def venv_of(spec: str) -> str:
    """The venv the spec's runner imports from: a process engine's, the whisper group's, the audio server's, or "" (this interpreter). #1024, #1030."""
    options = _options(spec)
    if options.get("backend") == "whisper" or options.get("ear", "").partition(":")[0] == "whisper":
        return WHISPER_VENV
    from harness import reasons
    head = head_of(spec)
    if head in reasons._AUDIO_HEADS:
        # The audio server loads the model unless `backend=` names another runner.
        return AUDIO_ENV if options.get("backend", "server") == "server" else ""
    return RUNNER_VENVS.get(head, "")


def launcher(specs, default: list[str]) -> list[str]:
    """The interpreter an evals.run over `specs` starts with: a group venv's uv run when a spec needs one, else `default`. #1024."""
    venv = next((v for v in map(venv_of, specs) if v in GROUP_VENVS), "")
    if not venv:
        return list(default)
    return ["env", "-u", "VIRTUAL_ENV", f"UV_PROJECT_ENVIRONMENT={venv_path(venv)}",
            "uv", "run", "--group", GROUP_VENVS[venv], "python"]


def _requirements(names) -> frozenset:
    """Canonical names of the requirements whose markers hold on this interpreter."""
    from packaging.requirements import InvalidRequirement, Requirement
    out = set()
    for text in names:
        try:
            req = Requirement(text)
        except InvalidRequirement:
            continue
        # packaging caches its marker environment per process; sys.platform is read here, at call time.
        if req.marker is None or req.marker.evaluate({"sys_platform": sys.platform}):
            out.add(_canonical(req.name))
    return frozenset(out)


def _pyproject(repo: Path) -> dict:
    import tomllib
    try:
        return tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _bash_values(text: str, name: str) -> list[str]:
    """Each word of the bash array `name=(...)`, in every branch that assigns it."""
    words = []
    for body in re.findall(rf"^\s*{re.escape(name)}=\((.*?)\)", text, re.M | re.S):
        words += [w.strip("\"'") for w in body.split()]
    return words


def _pinned(repo: Path, words) -> frozenset:
    """The distributions `words` name, each `$X_PIN` read from scripts/versions.sh."""
    try:
        versions = (repo / "scripts" / "versions.sh").read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    pins = dict(re.findall(r'^([A-Z0-9_]+)="([^"]*)"', versions, re.M))
    found = []
    for word in words:
        ref = re.fullmatch(r"\$\{?([A-Z0-9_]+)\}?", word)
        value = pins.get(ref.group(1), "") if ref else word
        if value and not value.startswith(("-", "http")):
            found.append(value)
    return _requirements(found)


def _script_pins(repo: Path, script: str, *arrays: str) -> frozenset:
    """The distributions a venv script's pin arrays name."""
    try:
        text = (repo / script).read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    return _pinned(repo, [w for array in arrays for w in _bash_values(text, array)])


def audio_script() -> str:
    """The script that starts the audio server on this platform, read at call time."""
    return "scripts/serve-tts.sh" if sys.platform == "darwin" else "scripts/serve-audio-cuda.sh"


def _service_pins(repo: Path, script: str) -> frozenset:
    """The distributions the `--with` words of a service script's `exec uv run` install."""
    try:
        text = (repo / script).read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    command = next((line for line in text.replace("\\\n", " ").splitlines()
                    if line.strip().startswith("exec uv run")), "")
    return _pinned(repo, [w.strip("\"'") for w in re.findall(r"--with\s+(\"[^\"]*\"|'[^']*'|\S+)", command)])


def installs(venv: str, repo: Path | None = None) -> frozenset:
    """The distributions some deploy step installs into `venv` ("" is the project's own) on this platform, directly. #1024."""
    from harness import paths
    repo = repo or paths.REPO
    if venv in VENV_SCRIPTS:
        return _script_pins(repo, *VENV_SCRIPTS[venv])
    if venv == AUDIO_ENV:
        return installs("", repo) | _service_pins(repo, audio_script())
    if venv and venv not in GROUP_VENVS:
        return frozenset()
    project = _pyproject(repo)
    groups = project.get("dependency-groups") or {}
    wanted = list((project.get("project") or {}).get("dependencies") or [])
    for group in ("dev", *([GROUP_VENVS[venv]] if venv else [])):
        wanted += [g for g in groups.get(group) or () if isinstance(g, str)]
    return _requirements(wanted)


def provides(dist: str, venv: str, repo: Path | None = None) -> bool:
    """Whether a deploy step installs `dist` into `venv` here, so a wait on it can end. #1024."""
    return _canonical(dist) in installs(venv, repo)


def uninstalled_runner_packages(repo: Path | None = None) -> list[str]:
    """The reasons.RUNNER_PACKAGES distributions no deploy step installs into any venv here. #1024."""
    from harness import reasons
    venvs = ("", *VENV_SCRIPTS, *LAUNCH_BUILT)
    have = frozenset().union(*(installs(v, repo) for v in venvs))
    return sorted({_canonical(d) for d in reasons.RUNNER_PACKAGES.values()} - have)


def package_until(evidence: str, candidate: str) -> str:
    """`package:<dist>@<venv>` for a package the candidate's runner venv lacks, or "". #1008."""
    from harness import reasons
    dist = reasons.missing_package(evidence)
    if not dist:
        return ""
    venv = venv_of(candidate)
    return f"package:{dist}@{venv}" if venv else f"package:{dist}"


def cause_until(cls: str, evidence: str, candidate: str, card=None) -> str:
    """The until a runtime-class screen failure waits on, from its cause; "" when a newer runtime release is the wait. #950."""
    from harness import reasons
    if cls == reasons.MISSING_PACKAGE:
        return package_until(evidence, candidate)
    if cls not in (reasons.LOAD_FAILED_RUNTIME, reasons.LOAD_FAILED_LAYOUT):
        return ""
    card = card or {}
    head = head_of(candidate)
    low = (evidence or "").lower()
    mtype = model_type(card, low)
    if head == "stt" and "processor not found" in low and whisper_repo(candidate.partition(":")[2], card):
        # A whisper repo mlx-audio's server cannot load waits on the whisper group's env. #1021, #1024.
        return f"package:{WHISPER_PACKAGE}@{WHISPER_VENV}"
    if not head:
        if _task(card) in VLM_TASKS:
            return f"runner:{VLM_RUNNER}"
        library = _library(card)
        if library and library not in TEXT_LIBRARIES:
            return f"runner:{library}"
    if "trust_remote_code" in low or (
            not (not head and mlx_lm_builds(mtype)) and remote_code_gap(card, low)):
        return remote_code_until(mtype)
    if head:
        return f"runner:{head}/{layout_name(card, evidence)}" if cls == reasons.LOAD_FAILED_LAYOUT else ""
    if mtype in DECLINED or (_NAMED_TYPE.search(low) and native_in_transformers(mtype)):
        return f"runner:{TEXT_RUNNER}"
    if "parameters not in model" in low:
        return f"format:{format_name(card, evidence)}"
    if cls == reasons.LOAD_FAILED_LAYOUT:
        return f"runner:mlx-lm/{layout_name(card, evidence)}"
    return ""


def write_mlx_lm(path: Path = MLX_LM_SNAPSHOT) -> int:
    """Rewrite the mlx-lm snapshot from this interpreter's mlx_lm, read as source so mlx is never imported."""
    import importlib.util
    from importlib import metadata
    spec = importlib.util.find_spec("mlx_lm")
    if spec is None or not spec.submodule_search_locations:
        print("mlx_lm is not installed in this interpreter", file=sys.stderr)
        return 1
    root = Path(next(iter(spec.submodule_search_locations)))
    names = {p.stem for p in (root / "models").glob("*.py") if not p.stem.startswith("_")}
    tree = ast.parse((root / "utils.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "MODEL_REMAPPING" for t in node.targets):
            names |= {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    version = metadata.version("mlx-lm")
    path.write_text(f"# mlx-lm=={version}\n" + "\n".join(sorted(names)) + "\n", encoding="utf-8")
    print(f"{path.name}: {len(names)} model types from mlx-lm {version}")
    return 0


def write_diffusers(venv: Path | None = None, path: Path = DIFFUSERS_SNAPSHOT) -> int:
    """Rewrite the diffusers snapshot from the diffusers venv's package source, without importing it."""
    import os
    from harness import paths, stages
    venv = Path(venv or os.environ.get("DIFFUSERS_VENV") or paths.home() / "venvs" / "diffusers-cuda")
    for site in [*sorted(venv.glob("lib/python*/site-packages")), venv / "Lib" / "site-packages"]:
        init = site / "diffusers" / "__init__.py"
        if init.is_file():
            names = sorted(set(re.findall(r'"([A-Za-z0-9]+Pipeline)"', init.read_text(encoding="utf-8"))))
            version = stages.dist_versions(site).get("diffusers", "")
            path.write_text(f"# diffusers=={version}\n" + "\n".join(names) + "\n", encoding="utf-8")
            print(f"{path.name}: {len(names)} pipeline classes from diffusers {version}")
            return 0
    print(f"no diffusers package under {venv}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(write_mlx_lm() or write_diffusers())

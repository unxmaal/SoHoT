"""A newer release of a pinned runtime as a candidate: watch, sandboxed trial install, re-screen, paired verdict. #1474."""
from __future__ import annotations

import ast
import hashlib
import json
import platform as _platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYPI = "pypi"
GITHUB = "github"
PYPI_JSON = "https://pypi.org/pypi/{package}/json"
PYPI_INDEX = "https://pypi.org/simple"
RELEASE_DOWNLOAD = "https://github.com/{repo}/releases/download/{tag}/"
#: The release assets a llama.cpp trial installs on each (sys.platform, machine) it can run on, newest packaging first.
LLAMACPP_ASSETS = {("darwin", "arm64"): ("llama-{tag}-bin-macos-arm64.tar.gz", "llama-{tag}-bin-macos-arm64.zip")}
#: The asset of llama.cpp's versioned (latest) release naming the build tag it was cut from.
BUILD_TAG_ASSET = "nightly-tag.txt"

PROPOSED, BLOCKED, UNMEASURED, KEPT, REGRESSED, HELD = (
    "proposed", "blocked", "unmeasured", "kept", "regressed", "held")
#: Outcomes a person is told about the moment they are recorded, not only in the morning.
PUSHED = (BLOCKED, REGRESSED)
BUILDS, MISSING, UNKNOWN = "builds", "missing", "needs a load"

#: How many proposed releases one loop trial-installs; the rest wait for the next.
TRIALS_PER_LOOP = 1
INSTALL_TIMEOUT_S = 1800.0
SMOKE_TIMEOUT_S = 120.0
FETCH_TIMEOUT_S = 60.0
NOTIFY_TITLE = "SoHoT runtimes"
TRIALS_DIR = "runtime-trials"
SANDBOX_DIR = ".sandbox"


@dataclass(frozen=True)
class Runtime:
    name: str
    channel: str
    source: str
    key: str
    pin_file: str = ""
    pin_name: str = ""
    module: str = ""
    tag_prefix: str = ""


RUNTIMES = {r.name: r for r in (
    Runtime("llama.cpp", GITHUB, "ggml-org/llama.cpp", "llama.cpp", "scripts/versions.sh", "LLAMACPP_BUILD",
            tag_prefix="b"),
    Runtime("mlx-lm", PYPI, "mlx-lm", "mlx-lm", "uv.lock", "mlx-lm", "mlx_lm"),
    Runtime("mlx-vlm", PYPI, "mlx-vlm", "mlx-vlm", "scripts/versions.sh", "MLX_VLM_PIN", "mlx_vlm"),
    Runtime("mlx-audio", PYPI, "mlx-audio", "mlx-audio", "scripts/versions.sh", "MLX_AUDIO_PIN", "mlx_audio"),
    Runtime("transformers", PYPI, "transformers", "hf-task/transformers", "scripts/versions.sh",
            "TRANSFORMERS_PIN", "transformers"),
    Runtime("diffusers", PYPI, "diffusers", "diffusers", "scripts/versions.sh", "DIFFUSERS_PIN", "diffusers"),
    Runtime("mflux", PYPI, "mflux", "mflux", module="mflux"),
)}


def _version(v):
    from packaging.version import InvalidVersion, Version
    try:
        return Version(str(v or "").strip().lstrip("b"))
    except InvalidVersion:
        return None


def newer(candidate: str, pinned: str) -> bool:
    """Whether `candidate` is a final release past `pinned`; never when either is unreadable."""
    a, b = _version(candidate), _version(pinned)
    return a is not None and b is not None and not a.is_prerelease and not a.is_devrelease and a > b


def repo_pin(rt: Runtime, repo: Path | None = None) -> str:
    """The version the repo pins `rt` at: its versions.sh variable or its uv.lock entry; "" when unpinned."""
    path = (repo or REPO) / rt.pin_file if rt.pin_file else None
    if path is None or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if path.name == "uv.lock":
        m = re.search(rf'^name = "{re.escape(rt.pin_name)}"\nversion = "([^"]+)"', text, re.M)
    else:
        m = re.search(rf'^{re.escape(rt.pin_name)}="(?:[\w.\-\[\]]+==)?{re.escape(rt.tag_prefix)}([^"]+)"', text, re.M)
    return m.group(1) if m else ""


def pinned(rt: Runtime, versions: dict, repo: Path | None = None) -> str:
    """The version serving here (machines.versions), else the repo's pin."""
    return str(versions.get(rt.key) or "").lstrip(rt.tag_prefix) or repo_pin(rt, repo)


def _get_json(url: str):
    """One JSON read from a release channel. Replaced wholesale in tests."""
    from harness import ratelimit
    return ratelimit.get_json(url)


def _gh(path: str) -> str:
    """One `gh api` call. Replaced wholesale in tests."""
    from harness import github
    return github._gh(path)


def _get_text(url: str) -> str:
    """One small text asset from a release channel. Replaced wholesale in tests."""
    import httpx

    from harness import cuts
    with cuts.timeout("runtime_fetch_timeout_s", f"{url}: no answer in time"):
        got = httpx.get(url, timeout=FETCH_TIMEOUT_S, follow_redirects=True)
    got.raise_for_status()
    return got.text


def _run(argv, **kw):
    """One sandboxed install or smoke step. Replaced wholesale in tests."""
    return subprocess.run(argv, **kw)


def latest(rt: Runtime, get_json=None, gh=None, get_text=None) -> str:
    """Upstream's newest release from its official channel: PyPI's JSON API, or GitHub's latest release's build tag."""
    if rt.channel == PYPI:
        data = (get_json or _get_json)(PYPI_JSON.format(package=rt.source))
        return str((data.get("info") or {}).get("version") or "")
    data = json.loads((gh or _gh)(f"repos/{rt.source}/releases/latest"))
    tag = str(data.get("tag_name") or "")
    if not tag.startswith(rt.tag_prefix) or not tag[len(rt.tag_prefix):].isdigit():
        # A versioned release (v0.8.0) names the build it was cut from in an asset; builds are what versions records.
        asset = next((a for a in data.get("assets") or [] if a.get("name") == BUILD_TAG_ASSET), None)
        url = str((asset or {}).get("browser_download_url") or "")
        if not url.startswith(RELEASE_DOWNLOAD.format(repo=rt.source, tag=tag)):
            raise ValueError(f"release {tag} names no build tag in {BUILD_TAG_ASSET}")
        tag = (get_text or _get_text)(url).strip()
    return tag.removeprefix(rt.tag_prefix)


def watch(conn, versions: dict | None = None, *, get_json=None, gh=None, get_text=None, now: float | None = None,
          repo: Path | None = None) -> list[dict]:
    """Propose each pinned runtime's newer release once; one row per runtime saying what was read."""
    if versions is None:
        from harness import machine
        versions = machine.versions()
    now = time.time() if now is None else now
    out = []
    for rt in RUNTIMES.values():
        pin = pinned(rt, versions, repo)
        row = {"runtime": rt.name, "pinned": pin, "latest": "", "proposed": False, "why": ""}
        if not pin:
            row["why"] = "not pinned or installed here"
            out.append(row)
            continue
        try:
            row["latest"] = latest(rt, get_json, gh, get_text)
        except Exception as exc:  # noqa: BLE001 - one unreachable channel must not stop the others
            row["why"] = f"could not read {rt.channel}: {type(exc).__name__}: {exc}"[:300]
            out.append(row)
            continue
        if newer(row["latest"], pin):
            got = conn.execute("INSERT INTO runtime_trials (runtime, version, pinned, channel, seen_at) "
                               "VALUES (?, ?, ?, ?, ?) ON CONFLICT (runtime, version) DO NOTHING",
                               (rt.name, row["latest"], pin, rt.channel, now))
            row["proposed"] = bool(got.rowcount)
        out.append(row)
    conn.commit()
    return out


@dataclass
class Trial:
    runtime: str
    version: str
    dir: Path
    installed: bool = False
    why: str = ""
    log: str = ""
    site: Path | None = None
    binary: Path | None = None


def trial_dir(rt: Runtime, version: str, home: Path | None = None) -> Path:
    from harness import paths
    return Path(home or paths.home()) / TRIALS_DIR / f"{rt.name}-{version}"


def can_sandbox(platform: str | None = None) -> bool:
    from evals import repo
    return (platform or sys.platform) == "darwin" and Path(repo.SANDBOX_EXEC).is_file()


def profile(network: bool) -> str:
    """The repo lane's sandbox-exec profile (RULE #768); an install keeps the network to reach its channel."""
    from evals import repo
    return repo.PROFILE.replace("(deny network*)\n", "") if network else repo.PROFILE


def sandboxed(argv: list, task: Path, network: bool) -> list:
    from evals import repo
    prof = task / SANDBOX_DIR / ("install.sb" if network else "run.sb")
    prof.parent.mkdir(parents=True, exist_ok=True)
    prof.write_text(profile(network), encoding="utf-8")
    return [repo.SANDBOX_EXEC, "-f", str(prof), "-D", f"TASK={task}", *map(str, argv)]


def _env(task: Path) -> dict:
    home, tmp = task / SANDBOX_DIR / "home", task / SANDBOX_DIR / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(tmp), "UV_NO_CONFIG": "1",
            "UV_CACHE_DIR": str(task / SANDBOX_DIR / "uv-cache"), "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1"}


def _sandbox_run(argv: list, task: Path, network: bool, timeout: float, run) -> tuple[int, str]:
    """(returncode, output tail) of argv under sandbox-exec, writing nowhere but `task`."""
    from harness import cuts
    try:
        got = run(sandboxed(argv, task, network), cwd=task, env=_env(task), capture_output=True, text=True,
                  timeout=timeout)
    except subprocess.TimeoutExpired:
        knob = "runtime_install_timeout_s" if network else "runtime_smoke_timeout_s"
        cuts.cut(knob, f"{Path(str(argv[0])).name} in a runtime trial", value=timeout, kept=0, dropped=1)
        return -9, f"timed out after {timeout:g}s"
    except OSError as exc:
        return -1, f"{type(exc).__name__}: {exc}"
    return got.returncode, ((got.stdout or "") + (got.stderr or ""))[-2000:]


def _python(venv: Path, platform: str) -> Path:
    return venv / "Scripts" / "python.exe" if platform == "win32" else venv / "bin" / "python"


def site_packages(venv: Path) -> Path | None:
    return next(iter(sorted(venv.glob("lib/python*/site-packages"))), None) or (
        venv / "Lib" / "site-packages" if (venv / "Lib" / "site-packages").is_dir() else None)


def _install_pypi(rt: Runtime, t: Trial, run, platform: str) -> Trial:
    from harness import stages
    uv = shutil.which("uv") or "uv"
    venv = t.dir / "venv"
    steps = [[uv, "venv", "--no-config", "--python", sys.executable, venv],
             [uv, "pip", "install", "--no-config", "--python", _python(venv, platform),
              "--index-url", PYPI_INDEX, f"{rt.source}=={t.version}"]]
    for argv in steps:
        rc, out = _sandbox_run(argv, t.dir, True, INSTALL_TIMEOUT_S, run)
        t.log += out
        if rc:
            t.why = f"`{' '.join(map(str, argv[1:3]))}` exited {rc}: {out.strip()[-300:]}"
            return t
    t.site = site_packages(venv)
    got = stages.dist_versions(t.site).get(rt.source, "") if t.site else ""
    if got != t.version:
        t.why = f"the trial venv holds {rt.source} {got or 'nothing'}, not {t.version}"
        return t
    rc, out = _sandbox_run([_python(venv, platform), "-c", f"import {rt.module}"], t.dir, False,
                           SMOKE_TIMEOUT_S, run)
    t.log += out
    t.installed, t.why = (rc == 0), ("" if rc == 0 else f"`import {rt.module}` exited {rc}: {out.strip()[-300:]}")
    return t


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _install_github(rt: Runtime, t: Trial, run, gh, platform: str, machine: str) -> Trial:
    tag = f"{rt.tag_prefix}{t.version}"
    patterns = LLAMACPP_ASSETS.get((platform, machine))
    if not patterns:
        t.why = f"{rt.source} publishes no release asset this harness trials on {platform}/{machine}"
        return t
    release = json.loads((gh or _gh)(f"repos/{rt.source}/releases/tags/{tag}"))
    assets = {a.get("name"): a for a in release.get("assets") or []}
    name = next((p.format(tag=tag) for p in patterns if p.format(tag=tag) in assets), "")
    if not name:
        t.why = f"release {tag} has none of {', '.join(p.format(tag=tag) for p in patterns)}"
        return t
    asset = assets[name]
    url = str(asset.get("browser_download_url") or "")
    if not url.startswith(RELEASE_DOWNLOAD.format(repo=rt.source, tag=tag)):
        t.why = f"asset {name} is served from {url}, outside {rt.source}'s release downloads"
        return t
    archive = t.dir / name
    rc, out = _sandbox_run(["/usr/bin/curl", "-fsSL", "--proto", "=https", "-o", archive, url], t.dir, True,
                           INSTALL_TIMEOUT_S, run)
    t.log += out
    if rc:
        t.why = f"download of {name} exited {rc}: {out.strip()[-300:]}"
        return t
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:") and (not archive.is_file() or _sha256(archive) != digest[7:]):
        t.why = f"{name} does not match the release's {digest}"
        return t
    (t.dir / "build").mkdir(exist_ok=True)
    unpack = (["/usr/bin/tar", "-xzf", archive, "-C", t.dir / "build"] if name.endswith(".tar.gz")
              else ["/usr/bin/ditto", "-x", "-k", archive, t.dir / "build"])
    rc, out = _sandbox_run(unpack, t.dir, False, SMOKE_TIMEOUT_S, run)
    t.log += out
    t.binary = next(iter(sorted((t.dir / "build").rglob("llama-server"))), None)
    if rc or t.binary is None:
        t.why = f"{name} unpacked to no llama-server (exit {rc}): {out.strip()[-300:]}"
        return t
    rc, out = _sandbox_run([t.binary, "--version"], t.dir, False, SMOKE_TIMEOUT_S, run)
    t.log += out
    t.installed, t.why = (rc == 0), ("" if rc == 0 else f"llama-server --version exited {rc}: {out.strip()[-300:]}")
    return t


def install(rt: Runtime, version: str, *, run=None, gh=None, home: Path | None = None,
            platform: str | None = None, machine: str | None = None) -> Trial:
    """Install exactly `version` from `rt`'s official channel into its own trial dir, sandboxed; never the served one."""
    platform = platform or sys.platform
    machine = machine or _platform.machine()
    t = Trial(rt.name, version, trial_dir(rt, version, home))
    if t.dir.exists():
        shutil.rmtree(t.dir)
    t.dir.mkdir(parents=True)
    t.dir = t.dir.resolve()
    run = run or _run
    try:
        if rt.channel == PYPI:
            return _install_pypi(rt, t, run, platform)
        return _install_github(rt, t, run, gh, platform, machine)
    except Exception as exc:  # noqa: BLE001 - an install that raises is a blocked install, said in the verdict
        t.why = f"{type(exc).__name__}: {exc}"[:300]
        return t


def _transformers_types(package: Path) -> set[str]:
    path = package / "models" / "auto" / "configuration_auto.py"
    if not path.is_file():
        return set()
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "CONFIG_MAPPING_NAMES" for t in node.targets):
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Tuple) and sub.elts and isinstance(sub.elts[0], ast.Constant):
                    names.add(str(sub.elts[0].value))
                if isinstance(sub, ast.Dict):
                    names |= {str(k.value) for k in sub.keys if isinstance(k, ast.Constant)}
    return names


def built(rt: Runtime, site: Path | None) -> frozenset | None:
    """What the trial's source builds (model types, or diffusers pipeline classes); None when only a load can tell."""
    from harness import runner_gaps
    if site is None:
        return None
    pkg = site / rt.module if rt.module else None
    if rt.name == "mlx-lm":
        return frozenset(runner_gaps.mlx_lm_names(pkg))
    if rt.name == "mlx-vlm":
        return frozenset(runner_gaps.mlx_vlm_names(pkg))
    if rt.name == "mlx-audio":
        return frozenset(p.name for sub in ("stt", "tts") for p in (pkg / sub / "models").glob("*") if p.is_dir())
    if rt.name == "transformers":
        return frozenset(_transformers_types(pkg))
    if rt.name == "diffusers":
        init = pkg / "__init__.py"
        return frozenset(re.findall(r'"([A-Za-z0-9]+Pipeline)"', init.read_text(encoding="utf-8"))) \
            if init.is_file() else None
    return None


def waits_on(rt: Runtime, row) -> bool:
    """Whether a runtime decline's until names `rt`, or names transformers for a type a newer mlx-lm may build."""
    from harness import runner_gaps
    key, _, want = str(row["until"] or "").partition(":")
    if key == "version":
        return want.partition(">")[0] in (rt.name, rt.key)
    if key != "runner":
        return False
    mtype = str(row["model_type"] or "")
    return want == rt.name or (rt.name == "mlx-lm" and want == runner_gaps.TEXT_RUNNER and bool(mtype)
                               and mtype not in runner_gaps.DECLINED)


def waiting(conn, rt: Runtime) -> list[dict]:
    from harness.memory_store import revisit
    return [dict(r) for r in revisit._runtime_declines(conn) if waits_on(rt, r)]


def rescreen(rt: Runtime, declines: list[dict], types: frozenset | None) -> list[dict]:
    """Each waiting decline against what the trial builds: builds, missing, or needs a load."""
    from harness import runner_gaps
    out = []
    for r in declines:
        want = (runner_gaps.pipeline_class(r) if rt.name == "diffusers"
                else runner_gaps.model_type(r, r.get("detail") or ""))
        screen = UNKNOWN if types is None or not want else (BUILDS if want in types else MISSING)
        out.append({"name": r["name"], "lane": r.get("lane") or "", "until": r.get("until") or "",
                    "wants": want, "screen": screen})
    return out


def runtime_of(spec: str, lane: str = "") -> str:
    """The watched runtime that serves a lane's spec, "" for one none of RUNTIMES serves."""
    from harness import reasons, runner_gaps, screen, serving
    if spec.startswith(serving.LLAMACPP_PREFIX):
        return "llama.cpp"
    head = runner_gaps.head_of(spec)
    if head == runner_gaps.VLM_RUNNER:
        return runner_gaps.VLM_RUNNER
    got = screen.engine_runtime(spec).rpartition("/")[2]
    if got or head:
        return got if got in RUNTIMES else ""
    if lane in reasons._AUDIO_HEADS:
        return "mlx-audio"
    try:
        engine = serving.engine_for(spec)
    except ValueError:
        return ""
    return {serving.LLAMACPP: "llama.cpp", serving.DEFAULT: "mlx-lm"}.get(engine, "")


def incumbents(conn, rt: Runtime, incumbent_of=None) -> list[tuple[str, str]]:
    """(lane, spec) of each unparked lane whose incumbent `rt` serves."""
    from harness import adopt, lanes, winners
    if incumbent_of is None:
        typed = winners.typed()

        def incumbent_of(lane):
            return adopt.default_for(lane, typed.get(lane, ""), conn=conn)
    return [(lane, spec) for lane in lanes.ALL if not lanes.parked(lane)[0]
            for spec in [incumbent_of(lane) or ""] if spec and runtime_of(spec, lane) == rt.name]


def arm(spec: str, rt: Runtime, version: str) -> str:
    """The receipt name of `spec` run on `rt` at `version`, so paired rows tell the two runtimes apart."""
    return f"{spec}@{rt.name}=={version}"


@dataclass
class Verdict:
    outcome: str
    detail: str
    lane: str = ""
    evidence: dict = field(default_factory=dict)
    body: str = ""


def decide(rt: Runtime, version: str, pin: str, trial: Trial, rescreened: list[dict],
           served: list[tuple[str, str]], paired: dict | None) -> Verdict:
    """Blocked, regressed (naming the lane), kept, unmeasured, or held: the incumbents held and a pin bump is ready."""
    from harness import adopt
    ready = [r["name"] for r in rescreened if r["screen"] == BUILDS]
    evidence = {"rescreen": rescreened, "served": [list(s) for s in served], "dir": str(trial.dir),
                "install": trial.log[-600:]}
    if not trial.installed:
        return Verdict(BLOCKED, f"{rt.name} {version} did not trial-install, so the pin stays at {pin}: {trial.why}",
                       evidence=evidence)
    head = f"{rt.name} {pin} -> {version}: {len(ready)} of {len(rescreened)} waiting decline(s) build on it"
    cells = {}
    unmeasured = [lane for lane, _ in served if not (paired or {}).get(lane)]
    for lane, spec in served:
        rows = (paired or {}).get(lane)
        if not rows:
            continue
        old, new = arm(spec, rt, pin), arm(spec, rt, version)
        cell, p, _ = adopt.paired_p(rows, old, new, lane, against="incumbent")
        cells[lane] = {"spec": spec, "gained": cell.gained, "lost": cell.lost, "p": p}
        worse = adopt._worse(rows, old, new, lane)
        if worse:
            evidence["cells"] = cells
            return Verdict(REGRESSED, f"{rt.name} {version} regressed the {lane} lane's incumbent {spec}: {worse}; "
                           f"the pin stays at {pin}", lane=lane, evidence=evidence)
    evidence["cells"] = cells
    if unmeasured:
        return Verdict(UNMEASURED, f"{head}; the pin stays at {pin} until the incumbents of "
                       f"{', '.join(unmeasured)} are measured on it", evidence=evidence)
    behind = [lane for lane, c in cells.items() if c["lost"] > c["gained"]]
    if behind:
        return Verdict(KEPT, f"{head}; {', '.join(behind)} lost more cases than it gained, short of significance, "
                       f"so the pin stays at {pin}", lane=behind[0], evidence=evidence)
    v = Verdict(HELD, f"{head}; every incumbent held, so the pin can move to {version}", evidence=evidence)
    v.body = pin_bump_body(rt, pin, version, trial, cells, rescreened)
    return v


def pin_bump_body(rt: Runtime, pin: str, version: str, trial: Trial, cells: dict, rescreened: list[dict]) -> str:
    """The pin-bump PR's body: what moved, where the trial came from, each incumbent's paired cell, what it unblocks."""
    where = f"`{rt.pin_name}` in {rt.pin_file}" if rt.pin_file else "not pinned in the repo (installed version)"
    lines = [f"Bump {rt.name} {pin} -> {version}, {where}.", "",
             f"Trial: exactly {version} from {rt.channel} ({rt.source}), installed beside the served one in "
             f"{trial.dir} under the repo lane's sandbox-exec profile.", ""]
    if cells:
        lines += ["| lane | incumbent | gained | lost | p |", "|---|---|---|---|---|"]
        lines += [f"| {lane} | {c['spec']} | {c['gained']} | {c['lost']} | {c['p']:.3f} |"
                  for lane, c in sorted(cells.items())]
    else:
        lines.append(f"No lane's incumbent runs on {rt.name}, so no incumbent could regress.")
    ready = [r for r in rescreened if r["screen"] == BUILDS]
    lines += ["", f"Waiting declines that build on {version} ({len(ready)} of {len(rescreened)}), reopened after "
              f"the deploy:"] + [f"- {r['name']} ({r['lane']}, {r['wants']})" for r in ready]
    return "\n".join(lines) + "\n"


def record(conn, rt: Runtime, version: str, v: Verdict, now: float | None = None) -> None:
    evidence = {**v.evidence, **({"body": v.body} if v.body else {})}
    conn.execute("UPDATE runtime_trials SET outcome = ?, detail = ?, lane = ?, dir = ?, evidence = ?, decided_at = ? "
                 "WHERE runtime = ? AND version = ?",
                 (v.outcome, v.detail, v.lane, evidence.get("dir", ""), json.dumps(evidence, sort_keys=True),
                  time.time() if now is None else now, rt.name, version))
    conn.commit()


def push(rt: Runtime, version: str, v: Verdict, notify=None) -> str:
    """A desktop notification for a blocked install or a regression (RULE #716); "" for any other verdict."""
    if v.outcome not in PUSHED:
        return ""
    from harness import watchdog
    return (notify or watchdog.desktop)(NOTIFY_TITLE, v.detail, f"{rt.name} {version} {v.outcome}")


def prune(rt: Runtime, keep: Path, home: Path | None = None) -> list[str]:
    """Remove this runtime's older trial dirs, keeping `keep`."""
    root = trial_dir(rt, "x", home).parent
    gone = []
    for d in sorted(root.glob(f"{rt.name}-*")):
        if d.is_dir() and d.resolve() != keep.resolve():
            shutil.rmtree(d)
            gone.append(d.name)
    return gone


def proposed(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT runtime, version, pinned FROM runtime_trials WHERE outcome = ? "
                                          "ORDER BY id", (PROPOSED,)).fetchall()]


def trial(conn, *, run=None, gh=None, measure=None, notify=None, home: Path | None = None,
          platform: str | None = None, machine: str | None = None, incumbent_of=None,
          limit: int | None = None, now: float | None = None, free: int | None = None) -> list[dict]:
    """Trial each proposed release: install, re-screen its waiting declines, measure its incumbents, record, push."""
    from harness import cuts, fetching
    if not can_sandbox(platform):
        return [{**r, "outcome": PROPOSED, "detail": "not tried: a trial install needs sandbox-exec (macOS)"}
                for r in proposed(conn)]
    free = fetching.free_bytes(trial_dir(RUNTIMES["mlx-lm"], "x", home).parent) if free is None else free
    if free < fetching.DISK_FLOOR:
        waiting_rows = proposed(conn)
        if waiting_rows:
            cuts.cut("disk_floor", "runtime trial installs refused at the disk floor", kept=0,
                     dropped=len(waiting_rows), conn=conn)
        return [{**r, "outcome": PROPOSED, "detail": f"not tried: {free / fetching.GIB:.1f} GiB free is under the "
                 f"{fetching.DISK_FLOOR / fetching.GIB:.0f} GiB disk floor"} for r in waiting_rows]
    rows = cuts.take(proposed(conn), TRIALS_PER_LOOP if limit is None else limit, "runtime_trials_per_loop",
                     "runtime releases left for the next loop", conn=conn)
    out = []
    for r in rows:
        rt = RUNTIMES.get(r["runtime"])
        if rt is None:
            continue
        t = install(rt, r["version"], run=run, gh=gh, home=home, platform=platform, machine=machine)
        rescreened = rescreen(rt, waiting(conn, rt), built(rt, t.site) if t.installed else None)
        served = incumbents(conn, rt, incumbent_of)
        paired = measure(rt, r["version"], t, served) if (measure and t.installed and served) else None
        v = decide(rt, r["version"], r["pinned"], t, rescreened, served, paired)
        v.evidence["notified"] = push(rt, r["version"], v, notify)
        record(conn, rt, r["version"], v, now)
        if t.installed:
            prune(rt, t.dir, home)
        out.append({**r, "outcome": v.outcome, "detail": v.detail, "lane": v.lane, "body": v.body})
    return out


def verdicts(conn, since: float) -> list[dict]:
    """Runtime verdicts recorded since `since`, newest first, for the morning brief."""
    from harness import morning
    if not morning._has(conn, "runtime_trials"):
        return []
    return [dict(r) for r in conn.execute(
        "SELECT runtime, version, pinned, outcome, detail, lane, decided_at FROM runtime_trials "
        "WHERE decided_at IS NOT NULL AND decided_at >= ? ORDER BY decided_at DESC, id DESC", (since,)).fetchall()]


def line(r: dict) -> str:
    return f"{r['runtime']} {r['pinned']} -> {r['version']} {r['outcome']}: {r['detail']}"


def lines(watched: list[dict], tried: list[dict]) -> list[str]:
    """The loop's `runtime upgrades` section: what each channel said and each verdict."""
    out = ["\n=== runtime upgrades ==="]
    for w in watched:
        state = (w["why"] or (f"{w['latest']} proposed" if w["proposed"] else
                              f"latest {w['latest'] or '?'}" + (" (already proposed)" if newer(w["latest"], w["pinned"])
                                                                 else "")))
        out.append(f"  {w['runtime']:13} pinned {w['pinned'] or '-':10} {state}")
    out += [f"  {line(r)}" for r in tried]
    return out

"""Engines and runners wanted, tested: classify a tooling repo, trial it sandboxed, screen what waits on it, file what cannot be tried. #1475."""
from __future__ import annotations

import base64
import contextlib
import json
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ENGINE, RUNNER, TECHNIQUE, UNRELATED = "engine", "runner", "technique", "unrelated"
KINDS = (ENGINE, RUNNER, TECHNIQUE, UNRELATED)
OPENAI, CLI = "openai", "cli"
PYPI, RELEASE = "pypi", "github-release"
#: Trial states: what the next sweep does with the row.
CLASSIFIED, INSTALLED, BLOCKED, DEFERRED, DROPPED = "classified", "installed", "blocked", "deferred", "dropped"
#: Screen verdicts of one waiting candidate on one trial engine.
PASS, FAIL, LOAD_FAILED = "pass", "fail", "load_failed"

#: Repos one sweep classifies with the local model.
PER_RUN = 6
#: Trial installs one sweep makes.
INSTALLS_PER_RUN = 2
#: Waiting candidates one sweep screens on trial engines.
SCREENS_PER_RUN = 4
CLASSIFY_TOKENS = 1200
README_CHARS = 6000
INSTALL_TIMEOUT_S = 900.0
SERVE_TIMEOUT_S = 600.0
GH_TIMEOUT_S = 60.0
PYTHON = "3.12"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
PYPI_INDEX = "https://pypi.org/simple"
GH_REPO = "unxmaal/SoHoT"
LABEL = "engine-trial"
MARKER = "engine-trial:"
#: Placeholders a serve argv may carry; nothing else is substituted.
PLACEHOLDERS = ("{model}", "{port}", "{host}")
#: The follow-up issue for the trial adapters this slice does not build.
FOLLOW_UP = "#1477"

PROFILE = """(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath (param "TRIAL")) (literal "/dev/null") (literal "/dev/zero")
       (regex #"^/dev/tty") (regex #"^/dev/fd/"))
"""
#: A served trial may answer loopback and reach nothing else.
SERVE_NET = """(deny network-outbound (remote ip "*:*"))
(allow network-outbound (remote ip "localhost:*"))
"""

SYSTEM = "You read one software repository's README and reply with one JSON object and nothing else."
PROMPT = """A repository recurs in a machine's model discovery feeds. Decide what it is.

kinds:
- "engine": an inference engine or server that loads model weights and answers requests, through an OpenAI-compatible HTTP API or a command line
- "runner": a library or CLI that runs one model family that an existing engine cannot load
- "technique": a decoding, serving or prompting technique, not a program that serves models
- "unrelated": anything else (a list of links, an app, a toolkit with no model serving)

Reply with one JSON object:
{{"kind": one of the kinds,
 "why": "one sentence",
 "interface": "openai" when it serves an OpenAI-compatible /v1/chat/completions, "cli" when it is run once per prompt, else "",
 "serve": the argv that serves one model as a list of strings, first the executable the package installs, with {{model}} where the model id goes and {{port}} for the port, else [],
 "model_types": the Hugging Face config model_type values it says it loads, else []}}

REPOSITORY: {name}
description: {description}
PyPI: {pypi}
release: {release}

README (cut):
{readme}
"""


@dataclass
class Evidence:
    readme: str = ""
    #: {"package", "version", "wheels"} when PyPI holds a project that links back to the repo.
    pypi: dict = field(default_factory=dict)
    #: {"tag", "wheels"} for the latest GitHub release.
    release: dict = field(default_factory=dict)


@dataclass
class Trial:
    id: int
    name: str
    kind: str
    state: str
    why: str = ""
    interface: str = ""
    channel: str = ""
    package: str = ""
    version: str = ""
    serve: list = field(default_factory=list)
    model_types: list = field(default_factory=list)
    blocker: str = ""
    dir: str = ""
    issue: int | None = None


class TrialError(RuntimeError):
    """A trial step that cannot go on; its text is the blocker."""


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "repo"


def _gh_json(client, path: str):
    try:
        return client.get(path)
    except Exception:  # noqa: BLE001 - absent evidence is evidence
        return None


def _pypi_json(package: str, opener=None) -> dict | None:
    import urllib.request
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with (opener or urllib.request.urlopen)(url, timeout=GH_TIMEOUT_S) as r:
            return json.load(r)
    except Exception:  # noqa: BLE001 - a missing project is no PyPI channel
        return None


def _links_back(info: dict, name: str) -> bool:
    urls = [info.get("home_page") or "", info.get("project_url") or "",
            *((info.get("project_urls") or {}).values())]
    want = f"github.com/{name.lower()}/"
    return any(want in re.sub(r"\.git$", "", str(u).lower().rstrip("/")) + "/" for u in urls)


def pypi_channel(name: str, pypi=_pypi_json) -> dict:
    """The PyPI project named after the repo that links back to it, at its current version; {} when none."""
    base = name.split("/")[-1]
    for package in dict.fromkeys((base, base.lower(), base.lower().replace("_", "-"))):
        got = pypi(package)
        if not got or not _links_back(got.get("info") or {}, name):
            continue
        version = str((got.get("info") or {}).get("version") or "")
        files = (got.get("releases") or {}).get(version) or got.get("urls") or []
        wheels = [f["filename"] for f in files if f.get("packagetype") == "bdist_wheel"]
        return {"package": (got.get("info") or {}).get("name") or package, "version": version, "wheels": wheels}
    return {}


def gather(name: str, client=None, pypi=_pypi_json) -> Evidence:
    """README, PyPI project and latest release of a GitHub repo; each part empty when it cannot be read."""
    if client is None:
        from harness import github
        client = github.Client()
    ev = Evidence()
    got = _gh_json(client, f"repos/{name}/readme") or {}
    if got.get("content"):
        try:
            ev.readme = base64.b64decode(got["content"]).decode("utf-8", "replace")[:README_CHARS]
        except ValueError:
            ev.readme = ""
    rel = _gh_json(client, f"repos/{name}/releases/latest") or {}
    if rel.get("tag_name"):
        ev.release = {"tag": rel["tag_name"],
                      "wheels": [a["name"] for a in rel.get("assets") or [] if str(a.get("name", "")).endswith(".whl")]}
    ev.pypi = pypi_channel(name, pypi)
    return ev


def ask_model(prompt: str) -> dict:
    """The adopted extract-lane model's reply; raises delegate.Refused or completion.CompletionError."""
    from harness import delegate
    return delegate.complete("extract", prompt, system=SYSTEM, max_tokens=CLASSIFY_TOKENS, thinking=False)


def classify(row: dict, ev: Evidence, ask=ask_model) -> dict:
    """The model's reading of one repo, checked as data; ValueError when the reply is not a usable answer."""
    from harness import technique_triage
    prompt = PROMPT.format(name=row["name"], description=row.get("description") or "",
                           pypi=json.dumps(ev.pypi) if ev.pypi else "none",
                           release=json.dumps(ev.release) if ev.release else "none",
                           readme=ev.readme or "(none)")
    got = ask(prompt)
    d = technique_triage.parse_draft(got.get("text") or "")
    if d.get("kind") not in KINDS:
        raise ValueError(f"the reply's kind is {d.get('kind')!r}, not one of {', '.join(KINDS)}")
    serve = d.get("serve") if isinstance(d.get("serve"), list) else []
    types = d.get("model_types") if isinstance(d.get("model_types"), list) else []
    return {"kind": d["kind"], "why": str(d.get("why") or "")[:300],
            "interface": d.get("interface") if d.get("interface") in (OPENAI, CLI) else "",
            "serve": [str(x) for x in serve], "model_types": sorted({str(t).strip().lower() for t in types if str(t).strip()}),
            "by": got.get("spec") or ""}


def serve_problem(serve: list) -> str:
    """Why a serve argv cannot be run as given, or ""."""
    if not serve:
        return "the README names no command that serves a model"
    if "/" in serve[0] or serve[0].startswith("-"):
        return f"the serve command {serve[0]!r} is not an executable the package installs"
    joined = " ".join(serve)
    if "{model}" not in joined or "{port}" not in joined:
        return "the serve command takes no {model} and {port}"
    for word in re.findall(r"\{[^}]*\}", joined):
        if word not in PLACEHOLDERS:
            return f"the serve command holds {word}, which is no placeholder this harness fills"
    return ""


def _version_key(v) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "")))


def plan(c: dict, ev: Evidence) -> tuple[str, str, str, str, str]:
    """(state, channel, package, version, blocker) for one classified repo."""
    if c["kind"] in (TECHNIQUE, UNRELATED):
        return DROPPED, "", "", "", ""
    if c["interface"] == CLI:
        return DEFERRED, "", "", "", f"a command-line engine needs the process-runner adapter ({FOLLOW_UP})"
    if c["interface"] != OPENAI:
        return BLOCKED, "", "", "", "its interface is neither an OpenAI-compatible server nor a known command line"
    why = serve_problem(c["serve"])
    if why:
        return BLOCKED, "", "", "", why
    newer_release = ev.release.get("wheels") and _version_key(ev.release["tag"]) > _version_key(ev.pypi.get("version"))
    if ev.pypi.get("version") and ev.pypi.get("wheels") and not newer_release:
        return CLASSIFIED, PYPI, ev.pypi["package"], ev.pypi["version"], ""
    if ev.release.get("wheels"):
        return CLASSIFIED, RELEASE, ev.release["wheels"][0], ev.release["tag"], ""
    if ev.pypi.get("version"):
        return BLOCKED, "", "", "", (f"PyPI {ev.pypi['package']}=={ev.pypi['version']} ships no wheel, "
                                     "so a trial would run its build outside the sandbox")
    return BLOCKED, "", "", "", "no PyPI project or GitHub release wheel at an exact version; it needs a build"


def can_sandbox() -> bool:
    return sys.platform == "darwin" and Path(SANDBOX_EXEC).is_file()


def sandboxed(argv: list, trial_dir: Path, serve: bool = False) -> list:
    """argv under sandbox-exec: no write outside the trial dir, and when serving no network beyond loopback."""
    trial_dir = Path(trial_dir).resolve()
    profile = trial_dir / ("serve.sb" if serve else "install.sb")
    profile.write_text(PROFILE + (SERVE_NET if serve else ""), encoding="utf-8")
    return [SANDBOX_EXEC, "-f", str(profile), "-D", f"TRIAL={trial_dir}", *argv]


def trial_env(trial_dir: Path, base: dict | None = None) -> dict:
    """Every cache and temp dir a trial writes, inside its own dir."""
    import os
    d = Path(trial_dir).resolve()
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if k in ("PATH", "LANG", "LC_ALL", "TERM", "HF_HUB_CACHE", "HF_HOME")}
    env.update(HOME=str(d / "home"), TMPDIR=str(d / "tmp"), UV_CACHE_DIR=str(d / "uv-cache"),
               UV_PYTHON_INSTALL_DIR=str(d / "python"), XDG_CACHE_HOME=str(d / "cache"),
               PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    for sub in ("home", "tmp", "cache"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return env


def _run(argv: list, env: dict, cwd: Path, timeout: float | None = None) -> None:
    timeout = INSTALL_TIMEOUT_S if timeout is None else float(timeout)
    try:
        got = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        from harness import cuts
        cuts.cut("engine_install_timeout_s", f"{argv[-1]} did not install in time", value=timeout, kept=0, dropped=1)
        raise TrialError(f"{Path(str(argv[-1])).name}: install ran past {timeout:.0f}s") from exc
    except OSError as exc:
        raise TrialError(f"could not start {argv[0]}: {exc}") from exc
    if got.returncode != 0:
        tail = (got.stderr or got.stdout or "").strip().splitlines()[-6:]
        raise TrialError(f"install exited {got.returncode}: " + " | ".join(tail)[:600])


def install(t: Trial, root: Path, run=_run) -> Path:
    """The trial's own venv with its package at the exact version, installed under the sandbox; TrialError says why not."""
    d = Path(root) / f"{slug(t.name)}-{slug(t.version)}"
    d.mkdir(parents=True, exist_ok=True)
    done = d / "installed.json"
    if done.is_file():
        return d
    env = trial_env(d)
    venv = d / "venv"
    run(sandboxed(["uv", "venv", "--python", PYTHON, str(venv)], d), env, d)
    py = str(venv / "bin" / "python")
    if t.channel == PYPI:
        want = f"{t.package}=={t.version}"
    elif t.channel == RELEASE:
        dist = d / "dist"
        dist.mkdir(exist_ok=True)
        run(["gh", "release", "download", t.version, "-R", t.name, "-p", t.package, "-D", str(dist),
             "--clobber"], env, d)
        want = str(dist / t.package)
    else:
        raise TrialError(f"no install channel {t.channel!r}")
    run(sandboxed(["uv", "pip", "install", "--python", py, "--only-binary", ":all:", "--index-url", PYPI_INDEX,
                   want], d), env, d)
    done.write_text(json.dumps({"name": t.name, "channel": t.channel, "package": t.package,
                                "version": t.version}), encoding="utf-8")
    return d


def free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def serve_argv(t: Trial, model: str, port: int) -> list:
    """The trial's serve command for one model, its executable resolved inside the trial venv."""
    exe = str(Path(t.dir) / "venv" / "bin" / t.serve[0])
    fill = {"{model}": model, "{port}": str(port), "{host}": "127.0.0.1"}
    out = [exe]
    for word in t.serve[1:]:
        for k, v in fill.items():
            word = word.replace(k, v)
        out.append(word)
    return out


@dataclass
class Screened:
    verdict: str
    passed: int = 0
    total: int = 0
    detail: str = ""


def screen(t: Trial, cand: dict, served=None, cases=None, runner=None, hold=None) -> Screened:
    """Serve the candidate on the trial engine under the sandbox, holding the machine, and run its lane's screen cases."""
    from harness import exclusive
    with (hold or exclusive.held)("eval", deadline_s=SERVE_TIMEOUT_S * 2):
        return _screen(t, cand, served, cases, runner)


def _screen(t: Trial, cand: dict, served, cases, runner) -> Screened:
    from harness import downloads, screen as screening, vllm
    from evals.run import screen_cases
    lane = cand["lane"]
    mine = [c for c in (cases if cases is not None else screening._cases(str(screening.CASES))) if c.modality == lane]
    picked = screen_cases(mine)
    if not picked:
        return Screened(FAIL, detail=f"the {lane} lane has no screen case")
    d = Path(t.dir)
    port = free_port()
    env = {**trial_env(d), "HF_HUB_OFFLINE": "1", "HF_HUB_CACHE": str(downloads.hub_root())}
    argv = sandboxed(serve_argv(t, cand["name"], port), d, serve=True)
    log = d / "logs" / f"{slug(cand['name'])}.log"
    try:
        with (served or vllm.served)(argv, port, log=log, env=env, timeout=SERVE_TIMEOUT_S,
                                     timeout_knob="harness/engine_trials.py:SERVE_TIMEOUT_S") as srv:
            if runner is None:
                from evals.runners.text import CompletionRunner
                runner = CompletionRunner(srv.base, candidate=f"trial:{slug(t.name)}/{cand['name']}",
                                          model=cand["name"])
            rows = [runner.run(c) for c in picked]
    except RuntimeError as exc:
        return Screened(LOAD_FAILED, detail=str(exc)[-600:])
    passed = sum(1 for r in rows if r.passed)
    return Screened(PASS if passed else FAIL, passed, len(rows),
                    f"{passed}/{len(rows)} {lane} screen case(s) passed on {t.package}=={t.version}")


def _row(r) -> Trial:
    return Trial(id=r[0], name=r[1], kind=r[2], state=r[3], why=r[4], interface=r[5], channel=r[6], package=r[7],
                 version=r[8], serve=json.loads(r[9] or "[]"), model_types=json.loads(r[10] or "[]"),
                 blocker=r[11], dir=r[12], issue=r[13])


_COLS = ("t.id, p.name, t.kind, t.state, t.why, t.interface, t.channel, t.package, t.version, t.serve, "
         "t.model_types, t.blocker, t.dir, t.issue")


def trials(conn, state: str = "") -> list[Trial]:
    sql = f"SELECT {_COLS} FROM engine_trials t JOIN proposals p ON p.id = t.proposal_id"
    rows = conn.execute(sql + (" WHERE t.state = ?" if state else "") + " ORDER BY t.id", (state,) if state else ())
    return [_row(r) for r in rows]


def by_name(conn) -> dict:
    return {t.name: t for t in trials(conn)}


def _set(conn, t: Trial, now: float, **kw) -> None:
    for k, v in kw.items():
        setattr(t, k, v)
    cols = ", ".join(f"{k} = ?" for k in kw)
    conn.execute(f"UPDATE engine_trials SET {cols}, updated_at = ? WHERE id = ?", (*kw.values(), now, t.id))
    conn.commit()


def record(conn, row: dict, c: dict, state: str, channel: str, package: str, version: str, blocker: str,
           now: float) -> Trial:
    from harness.memory_store.schema import TECHNIQUE as TECHNIQUE_CATEGORY
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (row["name"],)).fetchone()[0]
    conn.execute("INSERT INTO engine_trials (proposal_id, kind, state, why, interface, channel, package, version, "
                 "serve, model_types, blocker, classified_by, classified_at, updated_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (pid, c["kind"], state, c["why"], c["interface"], channel, package, version, json.dumps(c["serve"]),
                  json.dumps(c["model_types"]), blocker, c.get("by") or "", now, now))
    if c["kind"] == TECHNIQUE:
        # The technique path reads proposals by category; this hands the repo to it.
        conn.execute("UPDATE proposals SET category = ? WHERE id = ?", (TECHNIQUE_CATEGORY, pid))
    conn.commit()
    return by_name(conn)[row["name"]]


def model_type(conn, name: str) -> str:
    got = conn.execute("SELECT model_type FROM proposals WHERE name = ?", (name,)).fetchone()
    return str((got[0] if got else "") or "").strip().lower()


def screened(conn, trial_id: int) -> set:
    return {r[0] for r in conn.execute("SELECT candidate FROM engine_screens WHERE trial_id = ?", (trial_id,))}


def matches(conn, t: Trial, waiting: list) -> list:
    """Waiting candidates whose model type the trial engine's table lists and that it has not screened."""
    from harness import gateway
    done = screened(conn, t.id)
    out = []
    for cand in waiting:
        kind = model_type(conn, cand["name"]) or str(cand.get("model_type") or "").lower()
        if kind and kind in t.model_types and cand["name"] not in done and cand.get("lane") in gateway.TEXT_LANES:
            out.append(cand)
    return out


def save_screen(conn, t: Trial, cand: dict, got: Screened, now: float) -> None:
    conn.execute("INSERT INTO engine_screens (trial_id, candidate, lane, verdict, passed, total, detail, screened_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (t.id, cand["name"], cand.get("lane") or "", got.verdict, got.passed, got.total, got.detail[:1000], now))
    conn.commit()


def screens(conn) -> list[dict]:
    rows = conn.execute("SELECT p.name, s.candidate, s.lane, s.verdict, s.passed, s.total, s.detail FROM engine_screens s "
                        "JOIN engine_trials t ON t.id = s.trial_id JOIN proposals p ON p.id = t.proposal_id "
                        "ORDER BY s.id")
    return [dict(zip(("engine", "candidate", "lane", "verdict", "passed", "total", "detail"), r)) for r in rows]


def gh_run(argv: list) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["gh", *argv, "-R", GH_REPO], capture_output=True, text=True, encoding="utf-8",
                              timeout=GH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(["gh", *argv], 1, "", str(exc))


def scrub(text: str, known=None, roots=()) -> str:
    """Text with this machine's hosts, accounts, names and whole local paths replaced by placeholders, for a public tracker."""
    from evals import redact
    for root in sorted({str(r) for r in roots if str(r) not in ("", ".", "/")}, key=len, reverse=True):
        text = text.replace(root, "<TRIAL_DIR>")
    got = redact.redact(text, redact.known_here() if known is None else known).text
    # redact keeps what follows a home or tmp prefix; the layout under it is local too.
    return re.sub(r"<(PATH_HOME|PATH_TMP|TRIAL_DIR)>[^\s'\"`)]*", r"<\1>", got)


def body_for(t: Trial, row: dict, waiting: list) -> str:
    seen = int(row.get("times") or 0)
    models = "\n".join(f"- `{c['name']}` ({c.get('lane') or 'no lane'}): {c.get('why_not') or ''}".rstrip(": ")
                       for c in waiting) or "- none waiting yet"
    return (f"The discovery sweep sighted [{t.name}](https://github.com/{t.name}) {seen} time(s) and could not trial "
            f"it automatically (#1475).\n\n"
            f"**What it is**, as the local model read its README: {t.kind}"
            f"{f', {t.interface} interface' if t.interface else ''}. {t.why}\n\n"
            f"**What blocked the trial**: {t.blocker}\n\n"
            f"**Models waiting on a runner it may provide**:\n{models}\n\n"
            f"A trial installs only from PyPI or a GitHub release at an exact version, into its own directory, and "
            f"runs it under sandbox-exec. Close this once an engine entry exists or the repo is judged not worth one.\n\n"
            f"{MARKER} {t.name}\n")


def existing_issue(gh, name: str) -> int | None:
    """The issue already carrying this repo's marker line, open or closed."""
    got = gh(["issue", "list", "--state", "all", "--search", f'"{MARKER} {name}" in:body', "--json", "number,body",
              "--limit", "20"])
    try:
        rows = json.loads(got.stdout or "[]") if got.returncode == 0 else []
    except ValueError:
        rows = []
    line = f"{MARKER} {name}"
    for r in rows:
        if any(ln.strip() == line for ln in str(r.get("body") or "").splitlines()):
            return int(r["number"])
    return None


def file_issue(conn, t: Trial, row: dict, waiting: list, gh=gh_run, known=None, now: float | None = None,
               roots=()) -> int:
    """One issue per blocked engine: the stored number, else one found by its marker, else a new one. Idempotent."""
    from harness import privacy
    now = time.time() if now is None else float(now)
    if t.issue:
        return int(t.issue)
    got = existing_issue(gh, t.name)
    if got is None:
        title = f"Engine trial blocked: {t.name}"
        body = scrub(body_for(t, row, waiting), known, roots)
        leaks = privacy.check_post(f"{title}\n{body}")
        if leaks:
            raise TrialError(f"privacy: the issue would hold {', '.join(sorted({f.name for f in leaks}))}")
        labels = gh(["label", "list", "--search", LABEL, "--json", "name"])
        try:
            have = {r.get("name") for r in json.loads(labels.stdout or "[]")}
        except ValueError:
            have = set()
        if LABEL not in have:
            gh(["label", "create", LABEL, "--description", "An engine the discovery loop could not trial (#1475)",
                "--color", "c5def5"])
        made = gh(["issue", "create", "--title", title, "--body", body, "--label", LABEL])
        hit = re.search(r"/issues/(\d+)", made.stdout or "")
        if made.returncode != 0 or not hit:
            raise TrialError(f"gh issue create: {(made.stderr or made.stdout or '').strip()[:300]}")
        got = int(hit.group(1))
    conn.execute("UPDATE engine_trials SET issue = ?, filed_at = ?, updated_at = ? WHERE id = ?", (got, now, now, t.id))
    conn.commit()
    t.issue = got
    return got


def filed_since(conn, since: float) -> list[dict]:
    """Engines whose blocked trial was filed at or after `since`, for the morning brief."""
    rows = conn.execute("SELECT p.name, t.blocker, t.issue FROM engine_trials t JOIN proposals p ON p.id = t.proposal_id "
                        "WHERE t.issue IS NOT NULL AND t.filed_at >= ? ORDER BY t.filed_at, p.name", (since,))
    return [{"name": r[0], "blocker": r[1], "issue": r[2]} for r in rows]


@dataclass
class Sweep:
    classified: list = field(default_factory=list)
    installed: list = field(default_factory=list)
    screened: list = field(default_factory=list)
    filed: list = field(default_factory=list)
    stopped: str = ""


def sweep(conn, tools: list, waiting: list, *, ask=ask_model, evidence=gather, installer=install, screener=screen,
          gh=gh_run, root: Path | None = None, now: float | None = None, known=None) -> Sweep:
    """One pass: classify new tooling repos, install trials, screen waiting candidates on them, file what cannot be tried."""
    from harness import completion, cuts, delegate, paths, reasons
    now = time.time() if now is None else float(now)
    root = Path(root) if root is not None else paths.home() / "engine-trials"
    out = Sweep()
    have = by_name(conn)
    fresh = [r for r in tools if r["name"] not in have]
    if len(fresh) > PER_RUN:
        cuts.cut("engine_classify_per_run", "tooling repos left unclassified this sweep", kept=PER_RUN,
                 dropped=len(fresh) - PER_RUN, conn=conn)
    for row in fresh[:PER_RUN]:
        ev = evidence(row["name"])
        try:
            c = classify(row, ev, ask)
        except completion.CompletionError as exc:
            if exc.failure_class != reasons.TOKEN_BUDGET_EXHAUSTED:
                out.stopped = f"the extract lane's model did not answer: {str(exc)[:160]}"
                break
            cuts.cut("engine_classify_tokens", f"the reading of {row['name']} ran past its reply budget", conn=conn)
            c = {"kind": ENGINE, "why": "", "interface": "", "serve": [], "model_types": [], "by": ""}
            state, channel, package, version, blocker = (DEFERRED, "", "", "",
                                                         f"the classification ran past {CLASSIFY_TOKENS} tokens")
        except delegate.Refused as exc:
            out.stopped = f"the extract lane's model did not answer: {str(exc)[:160]}"
            break
        except ValueError as exc:
            c = {"kind": ENGINE, "why": "", "interface": "", "serve": [], "model_types": [], "by": ""}
            state, channel, package, version, blocker = BLOCKED, "", "", "", f"the model's reading was unusable: {exc}"
        else:
            state, channel, package, version, blocker = plan(c, ev)
        if state == CLASSIFIED and not can_sandbox():
            state, blocker = DEFERRED, f"a trial runs under {SANDBOX_EXEC}, which this host lacks"
        out.classified.append(record(conn, row, c, state, channel, package, version, blocker, now))
    ready = trials(conn, CLASSIFIED)
    if len(ready) > INSTALLS_PER_RUN:
        cuts.cut("engine_installs_per_run", "trial installs left for a later sweep", kept=INSTALLS_PER_RUN,
                 dropped=len(ready) - INSTALLS_PER_RUN, conn=conn)
    for t in ready[:INSTALLS_PER_RUN]:
        try:
            d = installer(t, root)
        except TrialError as exc:
            _set(conn, t, now, state=BLOCKED, blocker=str(exc)[:1000])
            continue
        _set(conn, t, now, state=INSTALLED, dir=str(d))
        out.installed.append(t)
    pairs = [(t, cand) for t in trials(conn, INSTALLED) for cand in matches(conn, t, waiting)]
    if len(pairs) > SCREENS_PER_RUN:
        cuts.cut("engine_screens_per_run", "trial screens left for a later sweep", kept=SCREENS_PER_RUN,
                 dropped=len(pairs) - SCREENS_PER_RUN, conn=conn)
    for t, cand in pairs[:SCREENS_PER_RUN]:
        got = screener(t, cand)
        save_screen(conn, t, cand, got, now)
        out.screened.append((t.name, cand["name"], got))
    rows = {r["name"]: r for r in tools}
    for t in trials(conn, BLOCKED):
        if t.issue:
            continue
        mine = [c for c in waiting if model_type(conn, c["name"]) in t.model_types] if t.model_types else []
        try:
            out.filed.append((t.name, file_issue(conn, t, rows.get(t.name) or {"name": t.name}, mine, gh=gh,
                                                 known=known, now=now, roots=(root, root.resolve(), paths.home()))))
        except TrialError as exc:
            out.stopped = out.stopped or str(exc)[:300]
    return out


def dropped(conn) -> dict:
    """Repos classified out of the engines list, with the model's reason."""
    return {t.name: f"{t.kind}: {t.why}" for t in trials(conn, DROPPED)}


def lines(conn, tools: list, stuck: list, got: Sweep | None) -> list[str]:
    """The loop's `engines/tools wanted` and `runners wanted` sections, as summaries of the trials."""
    have = by_name(conn)
    gone = dropped(conn)
    left = [r for r in tools if r["name"] not in gone]
    out = []
    if tools:
        out += ["\n=== engines/tools wanted ===",
                f"{len(left)} tooling repo(s) recur with no model task; each is classified and trialed "
                f"({len(tools) - len(left)} dropped as not an engine):"]
        for r in left[:10]:
            t = have.get(r["name"])
            state = "unread" if t is None else t.state + (f" #{t.issue}" if t.issue else "")
            why = "" if t is None else (t.blocker or t.why)
            out.append(f"  {r.get('times', 0)}x  {r['name']}  [{state}]{f'  {why[:120]}' if why else ''}")
        for name in [r["name"] for r in tools if r["name"] in gone][:5]:
            out.append(f"  dropped {name}: {gone[name][:140]}")
    if got is not None:
        out.append(f"  this run: {len(got.classified)} classified, {len(got.installed)} installed, "
                   f"{len(got.screened)} screened, {len(got.filed)} filed"
                   + (f"; stopped at {got.stopped}" if got.stopped else ""))
        for engine, cand, s in got.screened:
            out.append(f"    {s.verdict:11} {cand} on {engine}: {s.detail[:120]}")
    elif tools:
        out.append("  --run classifies, trials and files them")
    if stuck:
        out += ["\n=== runners wanted ===",
                f"{len(stuck)} candidate(s) have a lane and no runner that can load them; each is retried on every "
                f"trial engine whose model types list it:"]
        tried = {}
        for s in screens(conn):
            tried.setdefault(s["candidate"], []).append(f"{s['verdict']} on {s['engine']}")
        for row in stuck[:10]:
            out.append(f"  {row.get('lane', ''):8} {row['name']}\n           {row['why_not']}"
                       + (f"\n           trials: {', '.join(tried[row['name']])}" if row["name"] in tried else ""))
    return out

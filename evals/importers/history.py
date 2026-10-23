"""A repository's merged fix commits as repo-lane tasks, in a spec and a symptom variant; SoHoT's own here. #888, #889."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from evals import interface, repo
from evals.importers import Imported, provenance

LANE = "repo"
SOURCE = "git:unxmaal/SoHoT"
DATASET = "SoHoT fix history (unxmaal/SoHoT)"
URL = "https://github.com/unxmaal/SoHoT"
REPO_URL = "https://github.com/unxmaal/SoHoT.git"
LICENSE = "generated"
REVISION = "35ac01f5c487124fb40fc7a94680178c22b78ac6"
MANIFEST = Path(__file__).with_name("history.json")
VERSION = 1
SUBJECT = re.compile(r"\(#(?P<issue>\d+)\) \(#(?P<pr>\d+)\)$")
MAX_SOURCE_FILES = 8
MAX_LINES = 400
#: The #888 pilot's cap: a task at or under both is the small stratum, the one local models were sized for. #997.
SMALL = {"files": 3, "lines": 150}
SIZES = ("small", "large")
TIMEOUT_S = 300.0
RUNS = 2
#: The repo's default deselection, kept although the grader's `-o addopts=` drops it, so no slow test enters the ids.
MARKERS = "not slow and not network and not postgres and not litellm"
VARIANTS = ("spec", "symptom")
#: Sections dropped from both variants, then from symptom only (headings or labels, lower case, matched as a prefix).
NOT_PROMPT = ("prior art checked",)
SOLUTION = ("fix", "the fix", "shape", "shape of the fix", "design", "options", "remedy",
            "proposal", "build", "what to change", "what to build", "what to do")
TRANSFORM = ("issue title and body from `gh issue view` at survey time, home paths as ~/, "
             "'Prior art checked' removed "
             "(spec), and the Fix/Shape/Design/Options/Remedy/Proposal/Build/What-to sections and "
             "labelled paragraphs too (symptom); base = fix^; fail_to_pass and pass_to_pass from "
             f"{RUNS} sandboxed pytest runs of the fix's test files at base+hidden tests and at "
             "base+reference diff, in the lane's own environment and sandbox (evals/repo.py); "
             "the names the hidden tests use that the fix adds or re-signs, with the fix's signatures, "
             "appended to both variants (evals/interface.py)")

#: The held-out split of tasks, frozen per fix commit by this seed and never by a case's text. #995.
SPLIT_SEED = 995
HOLDOUT_FRACTION = 0.5

#: Cases dropped after the survey because validation fails, with why; unfair cases stay, tagged in labels.json. #920.
DROPPED: dict[str, str] = {
    "sohot-455-spec": "validation error: tests/test_live_store_guard.py does not collect at base",
    "sohot-455-symptom": "validation error: tests/test_live_store_guard.py does not collect at base",
}

#: Cases the #1141 audit found graded on a design their prompt hides or contradicts, which no sentence repairs.
RETIRED: dict[str, str] = {
    "infovore-338-symptom": "the tests need the clustering, ordering, --grouping and output design the symptom hides",
    "infovore-340-spec": "the gold departs from the controls the issue specifies and invents every shape and line",
    "mcm-engine-145-symptom": "the tests need save_snapshot and a SessionStart(compact) restore, not the PostCompact "
                              "hook the title names",
    "mcm-engine-160-spec": "the labelling rules, policies, interval phase and classifier the tests pin are invented "
                           "in the fix",
    "mcm-engine-171-symptom": "the tests need a per-type hit cap and an inline pointer the symptom hides",
    "mcm-engine-199-symptom": "the tests need the size report design of the hidden Build section",
    "mcm-engine-31-spec": "the tests need a conflict-candidates report the issue never asks for",
    "sohot-396-symptom": "the tests need the backpressure threshold design the symptom hides",
    "sohot-647-symptom": "the tests need a per-step timeout and a .deb cache the symptom never mentions",
}
#: What the hidden tests hold a fix to that the prompt did not say, stated after its tests-call block. #1141.
STATED: dict[str, str] = json.loads(Path(__file__).with_name("history_stated.json").read_text(encoding="utf-8"))
STATED_HEAD = "The hidden tests also hold a fix to these details (stated for this exam):"
#: Per task, fail_to_pass ids (or id prefixes) that check the gold fix's mechanism, not behaviour, left ungraded. #1141.
LOOSENED: dict[str, dict[str, str]] = {
    "mcm-engine-116": {"tests/test_seam_inventory.py::test_sql_site_count_per_file[":
                       "the count of .execute call sites per file the fix edits is the gold's layout"},
    "mcm-engine-170": {"tests/test_seam_inventory.py::test_sql_site_count_per_file[":
                       "the count of .execute call sites per file the fix edits is the gold's layout"},
}


def graded(task: str, ids) -> list:
    """`ids` less the ones LOOSENED leaves ungraded for `task`."""
    off = LOOSENED.get(task, {})
    return [i for i in ids if not any(i.startswith(x) for x in off)]

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LABEL = re.compile(r"^(?:\*\*([^*\n]{1,60}?)[:.]?\*\*:?|([A-Z][A-Za-z ]{0,40}?):(?=\s|$))")
_LIST = re.compile(r"^(\s+|[-*+] |\d+[.)] )")
_HOME = re.compile(r"/(?:Users|home)/[^/\s]+/")
_HOST = re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+\b"
                   r"|(?<![\w<])(?!cluster\.local)[a-z0-9-]+\.local\b")


@dataclass(frozen=True)
class Repo:
    """One source: its history, its issue tracker and how its tests run, so no SoHoT constant leaks into another. #889."""
    name: str
    prefix: str
    url: str
    tracker: str
    revision: str
    subject: re.Pattern = SUBJECT
    merges: bool = False
    markers: str = ""
    pytest_args: tuple = ()
    extras: tuple = ()
    #: Headings this tracker gives the fix, cut from symptom beside SOLUTION.
    solution: tuple = ()
    dropped: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def manifest(self) -> Path:
        return Path(__file__).with_name(f"{self.name}.json")

    @property
    def source(self) -> str:
        return f"git:{self.tracker}"

    @property
    def dataset(self) -> str:
        return f"{self.tracker.split('/')[-1]} fix history ({self.tracker})"

    @property
    def home(self) -> str:
        return f"https://github.com/{self.tracker}"


SOHOT = Repo("history", "sohot", REPO_URL, "unxmaal/SoHoT", REVISION, markers=MARKERS, dropped=DROPPED)
REPO = SOHOT


def _norm(heading: str) -> str:
    text = re.sub(r"\(.*?\)", "", heading).strip().strip(":.").strip().lower()
    return re.sub(r"\s+", " ", text)


def _named(heading: str, names) -> bool:
    h = _norm(heading)
    return any(h == n or h.startswith(n + " ") for n in names)


def strip_sections(body: str, names) -> str:
    """`body` without the sections, or labelled paragraphs ("Fix: ...", "**Shape:**"), named in `names`."""
    out, level, label, text, gap = [], None, False, False, False
    for line in body.replace("\r\n", "\n").split("\n"):
        h = _HEADING.match(line)
        m = None if h else _LABEL.match(line)
        if h:
            if level is not None and len(h.group(1)) > level:
                continue
            level, label = (len(h.group(1)) if _named(h.group(2), names) else None), False
        elif level is not None:
            continue
        elif m:
            label, text, gap = _named(m.group(1) or m.group(2), names), bool(line[m.end():].strip()), False
        elif label and not line.strip():
            gap = True
        elif label:
            if gap and text and not _LIST.match(line):
                label = False
            text, gap = True, False
        if level is None and not label:
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def prompts(title: str, body: str, solution=()) -> dict[str, str]:
    """variant -> prompt text; symptom is None when it would only repeat spec or say nothing."""
    body = _HOST.sub("<host>", _HOME.sub("~/", body))
    spec = strip_sections(body, NOT_PROMPT)
    symptom = strip_sections(body, NOT_PROMPT + SOLUTION + tuple(solution))
    head = f"# {title.strip()}\n\n"
    return {"spec": head + spec,
            "symptom": head + symptom if symptom and symptom != spec else None}


def git(path, *args) -> str:
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True,
                          text=True).stdout


def private(text: str) -> list:
    """What the privacy lint would refuse in text bound for a committed case: a prompt or a test id. #889."""
    from harness import privacy
    return privacy.scan(text, "prompt", privacy.name_pattern(Path(__file__).resolve().parents[2]))


def candidates(mirror, revision: str, src: Repo = SOHOT) -> list[dict]:
    """Fix commits on `revision`'s first-parent line, newest first, with their changed files.

    A squash source's fix is a one-parent commit; a merge source's is the merge, its base the first parent. #889.
    """
    out = []
    for line in git(mirror, "log", "--first-parent", "--format=%H%x00%P%x00%cI%x00%s",
                    revision).splitlines():
        sha, parents, date, subject = line.split("\0")
        m = src.subject.search(subject)
        if not m or len(parents.split()) != (2 if src.merges else 1):
            continue
        parents = parents.split()[0]
        files = {}
        for row in git(mirror, "diff", "--numstat", "--no-renames", parents, sha).splitlines():
            added, deleted, path = row.split("\t")
            files[path] = 10 ** 6 if added == "-" else int(added) + int(deleted)
        source = sorted(p for p in files if not repo.is_test_path(p))
        context, new = split_new(mirror, parents, sha, source)
        out.append({"issue": int(m.group("issue")), "pr": int(m.group("pr")), "fix": sha,
                    "base": parents, "date": date[:10], "subject": subject,
                    "source_files": source, "context_files": context, "new_files": new,
                    "test_files": sorted(p for p in files if repo.is_test_path(p)),
                    "lines": sum(files[p] for p in source)})
    return out


def split_new(mirror, base: str, fix: str, source) -> tuple[list, list]:
    """(source files base has, source files the fix created): only the first can be shown at base. #913."""
    added = {line.split("\t", 1)[1] for line in
             git(mirror, "diff", "--name-status", "--no-renames", "--diff-filter=A", base, fix).splitlines()
             if "\t" in line}
    return sorted(p for p in source if p not in added), sorted(p for p in source if p in added)


def refresh(got: dict, mirror) -> dict:
    """The manifest with every task's context_files, new_files and interface recomputed from the mirror. #913, #1103."""
    tasks = []
    for t in got["tasks"]:
        source = sorted({*t["context_files"], *t.get("new_files", [])})
        context, new = split_new(mirror, t["base"], t["fix"], source)
        calls = tests_call(mirror, t["base"], t["fix"])
        tasks.append({**t, "context_files": context, "new_files": new, "interface": calls,
                      "unlisted": unlisted(mirror, t, calls)})
    return {**got, "tasks": tasks}


def tests_call(mirror, base: str, fix: str) -> list[str]:
    """The interface lines a task's prompts show, with home paths and LAN hosts masked as in the prompt. #1103."""
    return [_HOST.sub("<host>", _HOME.sub("~/", line)) for line in interface.tests_call(mirror, base, fix)]


def unlisted(mirror, t: dict, calls) -> dict:
    """Per variant, the fix's new names the hidden tests or graded ids spell that its prompt never does. #1141."""
    block = interface.block(calls)
    return {v: interface.unlisted(mirror, t["base"], t["fix"], f"{text}\n\n{block}", t["fail_to_pass"])
            for v, text in (t.get("prompts") or {}).items() if text}


def _test_module(path: str) -> bool:
    return path.endswith(".py") and Path(path).name.startswith("test_")


def screen(c: dict) -> str | None:
    """Why a candidate is out before anything runs, or None."""
    if not any(_test_module(p) for p in c["test_files"]):
        return "no_test_change"
    if not c["source_files"]:
        return "no_source_change"
    if len(c["source_files"]) > MAX_SOURCE_FILES or c["lines"] > MAX_LINES:
        return "too_big"
    if set(repo.ENV_FILES) & set(c["source_files"]):
        return "dependency_change"
    if not c["context_files"]:
        return "only_new_files"
    return None


def size_of(strata: dict) -> str:
    """small or large: a task's stratum from its source file and line counts. #997."""
    return "small" if strata["files"] <= SMALL["files"] and strata["lines"] <= SMALL["lines"] else "large"


def sizes(got: dict | None = None) -> dict:
    """fix sha -> size stratum for every task in the manifest, or in every source's manifest. #997, #889."""
    every = [got] if got else [manifest(r.manifest) for r in repos()]
    return {t["fix"]: size_of(t["strata"]) for g in every for t in g["tasks"]}


def repos() -> list[Repo]:
    """Every registered repo-lane history source, SoHoT's first. #889."""
    from evals import importers
    return [importers.module(s.name).REPO for s in importers.REGISTRY
            if s.lane == LANE and hasattr(importers.module(s.name), "REPO")]


def source_of(params: dict) -> str:
    """The source a repo case came from, by its params.source_repo: a registered source's prefix, else the url. #889."""
    url = str((params or {}).get("source_repo", ""))
    return next((r.prefix for r in repos() if r.url == url), url)


def only_size(cases, size: str, got: dict | None = None) -> list:
    """The cases of history tasks in one size stratum; "all" keeps every case. #997."""
    if size == "all":
        return list(cases)
    by = sizes(got)
    return [c for c in cases if by.get(str((getattr(c, "params", None) or {}).get("fix", ""))) == size]


def issue(number: int, tracker: str = SOHOT.tracker) -> dict | None:
    """The issue's title and body; None only when GitHub says it does not exist, never when gh fails. #997."""
    got = subprocess.run(["gh", "issue", "view", str(number), "-R", tracker, "--json",
                          "title,body"], capture_output=True, text=True)
    if got.returncode == 0:
        return json.loads(got.stdout)
    if re.search(r"could not resolve to an? (issue|pullrequest)", got.stderr, re.I):
        return None
    raise RuntimeError(f"gh issue view {number}: {got.stderr.strip()[-300:]}")


def _junit(xml: Path) -> dict:
    """junit key -> passed|failed|error|skipped; a file that does not collect is keyed `::<dotted module>`."""
    out = {}
    for case in ET.parse(xml).getroot().iter("testcase"):
        key = f"{case.get('classname') or ''}::{case.get('name') or ''}"
        tags = {child.tag for child in case}
        out[key] = ("failed" if "failure" in tags else "error" if "error" in tags else
                    "skipped" if "skipped" in tags else "passed")
    return out


def _pytest(task: Path, python: Path, args, log, timeout, src: Repo = SOHOT) -> int | str:
    mark = ["-m", src.markers] if src.markers else []
    rc, tail, late = repo.run_sandboxed([str(python), "-m", "pytest", "-p", "no:cacheprovider",
                                         "-q", "-o", "addopts=", *src.pytest_args, *mark, *args],
                                        task, timeout)
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n$ {task.name}: pytest {' '.join(args)}\n[exit {rc}{' timeout' if late else ''}]\n"
                f"{tail}\n")
    return "timeout" if late else rc


def outcomes(task: Path, python: Path, files, log, timeout=TIMEOUT_S, src: Repo = SOHOT) -> dict | str:
    """{"outcomes": junit key -> outcome, "seconds": s} of one sandboxed run, or a drop reason."""
    report = task / repo.HARNESS_DIR / "survey.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    t0 = time.perf_counter()
    got = _pytest(task, python, ["--continue-on-collection-errors", f"--junitxml={report}", *files], log, timeout, src)
    if isinstance(got, str):
        return got
    if not report.is_file():
        return "pytest_crashed"
    return {"outcomes": _junit(report), "seconds": round(time.perf_counter() - t0, 2),
            "collect": repo.collect_errors(report)}


def node_ids(keys, files) -> list[str]:
    """Junit keys back to the pytest node ids the grader takes, resolved against the files run."""
    out = []
    for key in keys:
        cls, _, name = key.partition("::")
        parts = cls.split(".")
        for k in range(len(parts), 0, -1):
            path = "/".join(parts[:k]) + ".py"
            if path in files:
                out.append("::".join([path, *parts[k:], name]))
                break
    return sorted(out)


def classify(base_runs: list[dict], fix_runs: list[dict], files, tree: Path | None = None) -> dict:
    """fail_to_pass and pass_to_pass from repeated runs, or {"drop": reason}."""
    if any(r["outcomes"] != base_runs[0]["outcomes"] for r in base_runs) or \
            any(r["outcomes"] != fix_runs[0]["outcomes"] for r in fix_runs):
        return {"drop": "flaky"}
    base, fix = base_runs[0]["outcomes"], fix_runs[0]["outcomes"]
    if any(v in ("failed", "error") for v in fix.values()):
        return {"drop": "reference_fails"}
    passing = node_ids([k for k, v in fix.items() if v == "passed"], files)
    f2p = [i for i in passing if base.get(repo.junit_key(i)) != "passed"]
    if not f2p:
        return {"drop": "no_flip"}
    # An id that errors at base is a base_error, as the case control calls it, unless the control admits it. #889, #1098.
    causes = {k: repo.collect_cause(e, tree) for k, e in (base_runs[0].get("collect") or {}).items()}
    why = repo.base_causes(f2p, {i: base.get(repo.junit_key(i)) for i in f2p}, causes)
    held = sorted({c for c in why.values() if c != repo.ADMIT})
    if held:
        return {"drop": "base_error", "cause": ",".join(held)}
    return {"fail_to_pass": f2p, "pass_to_pass": [i for i in passing if i not in f2p],
            "test_s": fix_runs[0]["seconds"], **({"admitted_by": "base_collect_" + repo.ADMIT} if why else {})}


def probe(mirror: Path, c: dict, log, timeout=TIMEOUT_S, runs=RUNS, env=None, src: Repo = SOHOT) -> dict:
    """Run the fix's tests at base+hidden tests, then with the reference diff applied, the grader's way."""
    task = repo.restore(mirror, c["base"])
    try:
        try:
            built = env(task) if env else repo.prepare(task, src.extras) if src.extras else repo.prepare(task)
            python = repo.python_of(Path(built))
        except repo.RepoEnvError:
            return {"drop": "environment_error"}
        repo.install_tests(mirror, task, c["base"], c["fix"])
        files = [p for p in repo.hidden_tests(mirror, c["base"], c["fix"]) if _test_module(p)]
        if not files:
            return {"drop": "no_test_change"}
        base_runs = [outcomes(task, python, files, log, timeout, src) for _ in range(runs)]
        applied, _ = repo.apply(task, repo.reference_diff(mirror, c["base"], c["fix"]))
        if not applied:
            return {"drop": "reference_unappliable"}
        repo.install_tests(mirror, task, c["base"], c["fix"])
        fix_runs = [outcomes(task, python, files, log, timeout, src) for _ in range(runs)]
        bad = next((r for r in [*base_runs, *fix_runs] if isinstance(r, str)), None)
        return {"drop": bad} if bad else classify(base_runs, fix_runs, files, task)
    finally:
        repo.discard(mirror, task)


def area(source_files) -> str:
    return ",".join(sorted({str(Path(p).parent) for p in source_files}))


def _fetch(mirror: Path, revision: str) -> None:
    """Fetch the mirror unless `revision` is a commit it already holds: a cached mirror never moves by itself. #997."""
    if not (re.fullmatch(r"[0-9a-f]{40}", revision) and repo._has(mirror, revision)):
        git(mirror, "fetch", "--quiet", "--prune", "origin")


def survey(source: str, revision: str, limit: int | None, log, get_issue=None, timeout=TIMEOUT_S,
           env=None, keep: dict | None = None, probes: int | None = None, run: bool = True,
           src: Repo = SOHOT) -> dict:
    """Examine fix commits newest first until `limit` tasks are kept (None: all); `keep`'s tasks stay as they are.

    run=False screens and reads issues but probes nothing: what would be probed is listed in "pending". #997.
    """
    get_issue = get_issue or (lambda n: issue(n, src.tracker))
    mirror = repo.mirror(source)
    _fetch(mirror, revision)
    revision = git(mirror, "rev-parse", revision).strip()
    pool = candidates(mirror, revision, src)
    old = {t["fix"]: t for t in (keep or {}).get("tasks", [])}
    lost = sorted(t["id"] for f, t in old.items() if f not in {c["fix"] for c in pool})
    if lost:
        raise RuntimeError(f"tasks not on {revision[:10]}'s fix history, so they cannot be kept: {lost}")
    kept, drops, pending, seen = [], [], [], {t["issue"] for t in old.values()}
    ran = 0
    for c in pool:
        if limit is not None and len(kept) >= limit or probes is not None and ran >= probes:
            break
        if c["fix"] in old:
            kept.append(old[c["fix"]])
            continue
        why = "duplicate_issue" if c["issue"] in seen else screen(c)
        text = res = None
        if why is None:
            got = get_issue(c["issue"])
            text = prompts(got["title"], got["body"] or "", src.solution) if got else None
            why = "no_issue" if not got else "private_text" if any(
                private(t) for t in text.values() if t) else None
        if why is None and not run:
            pending.append({"issue": c["issue"], "fix": c["fix"],
                            "size": size_of({"files": len(c["source_files"]), "lines": c["lines"]}),
                            "variants": [v for v in VARIANTS if text[v]]})
            continue
        if why is None:
            t0, ran = time.monotonic(), ran + 1
            res = probe(mirror, c, log, timeout, env=env, src=src)
            why = res.get("drop") or ("private_text" if any(private(i) for i in res["fail_to_pass"]) else None)
            if not why:
                # A test id the lint would refuse (a LAN host as a parametrize id) leaves the regression set.
                res = {**res, "pass_to_pass": [i for i in res["pass_to_pass"] if not private(i)]}
            print(f"{c['issue']:>4} {c['fix'][:10]} {why or 'kept'} {time.monotonic() - t0:.0f}s",
                  file=sys.stderr, flush=True)
        if why:
            drops.append({"issue": c["issue"], "pr": c["pr"], "fix": c["fix"], "reason": why,
                          **({"cause": res["cause"]} if res and res.get("cause") else {})})
            continue
        seen.add(c["issue"])
        kept.append(task_row(src.prefix, c, res, text, tests_call(mirror, c["base"], c["fix"])))
    kept += [t for f, t in old.items() if t not in kept]
    return {"version": VERSION, "source": src.source, "repo": source, "revision": revision,
            "criteria": {"subject": src.subject.pattern, "first_parent": True, "merges": src.merges,
                         "max_source_files": MAX_SOURCE_FILES, "max_lines": MAX_LINES,
                         "small": SMALL, "symptom_without_fix_section": "spec kept, symptom dropped",
                         "tests_changed": "a test_*.py the grader would install",
                         "no_env_file_change": list(repo.ENV_FILES), "runs": RUNS,
                         "markers": src.markers, "pytest_args": list(src.pytest_args),
                         "extras": list(src.extras),
                         "pytest_timeout_s": timeout,
                         "order": "newest first", "limit": limit, "probes": probes,
                         "kept_from": (keep or {}).get("revision")},
            "candidates": len(pool), "examined": len(kept) + len(drops) + len(pending),
            "dropped": dict(sorted(Counter(d["reason"] for d in drops).items())),
            "tasks": kept, "split": split(kept), "drops": drops,
            **({} if run else {"pending": pending})}


def task_row(prefix: str, c: dict, res: dict, text: dict, calls=()) -> dict:
    """One manifest task from a candidate commit, its probe result and its prompts; any importer may build one. #889."""
    lost_variants = {v: "no_fix_section" for v in VARIANTS if not text[v]}
    return {"id": f"{prefix}-{c['issue']}", "issue": c["issue"], "pr": c["pr"],
            "base": c["base"], "fix": c["fix"], "date": c["date"],
            "subject": c["subject"], "context_files": c["context_files"],
            "new_files": c["new_files"],
            "test_files": c["test_files"], "fail_to_pass": res["fail_to_pass"],
            "pass_to_pass": res["pass_to_pass"], "prompts": text, "interface": list(calls),
            "strata": {"files": len(c["source_files"]), "lines": c["lines"],
                       "test_s": res["test_s"], "area": area(c["source_files"]),
                       "size": size_of({"files": len(c["source_files"]), "lines": c["lines"]})},
            **({"variant_drops": lost_variants} if lost_variants else {}),
            **({"admitted_by": res["admitted_by"]} if res.get("admitted_by") else {})}


#: Reasons only a probe gives: the share of probed candidates kept is the yield a projection prices pending ones at.
PROBE_DROPS = ("base_error", "environment_error", "flaky", "no_flip", "pytest_crashed", "reference_fails",
               "reference_unappliable", "timeout")


def probe_yield(got: dict) -> tuple[int, int]:
    """(kept, probed) over a manifest's candidates that a probe decided."""
    probed = len(got["tasks"]) + sum(n for r, n in got["dropped"].items() if r in PROBE_DROPS)
    return len(got["tasks"]), probed


def yield_table(got: dict, dropped=None, priced=None) -> list[str]:
    """`N candidates, M tasks, K dropped`, the count per reason and per lost variant, and a projection of what awaits a probe."""
    dropped = DROPPED if dropped is None else dropped
    ids = {t["id"] for t in got["tasks"]}
    gone = sorted(i for i in ids if all(f"{i}-{v}" in dropped for v in VARIANTS))
    reasons = Counter(got["dropped"])
    if gone:
        reasons["validation"] += len(gone)
    pool, pending = got.get("candidates", got["examined"]), got.get("pending", [])
    usable = [t for t in got["tasks"] if t["id"] not in gone]
    unexamined = pool - got["examined"]
    lines = [f"{pool} candidates, {len(usable)} tasks, {sum(reasons.values())} dropped"
             + (f", {len(pending)} awaiting a probe" if pending else "")
             + (f", {unexamined} not examined (limit {got['criteria']['limit']}, "
                f"probes {got['criteria'].get('probes')})" if unexamined else "")]
    lines += [f"  {n:>4}  {r}" for r, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))]
    causes = Counter(d["cause"] for d in got.get("drops", []) if d.get("cause"))
    if causes:
        lines.append("base_error by cause: " + ", ".join(f"{c} {n}" for c, n in sorted(causes.items())))
    lost = Counter()
    for t in usable:
        for v in VARIANTS:
            why = (t.get("variant_drops") or {}).get(v) or ("validation" if f"{t['id']}-{v}" in dropped else None)
            if why:
                lost[(v, why)] += 1
    cases = sum(1 for t in usable for v in VARIANTS if t["prompts"].get(v) and f"{t['id']}-{v}" not in dropped)
    lines.append(f"cases: {cases}" + "".join(f"; {v} dropped on {n} tasks ({why})" for (v, why), n in sorted(lost.items())))
    by = Counter(size_of(t["strata"]) for t in usable)
    lines.append("size: " + ", ".join(f"{by[s]} {s}" for s in SIZES))
    sides = Counter(side_of(t["fix"]) for t in usable)
    lines.append(f"split: {sides['holdout']} held out, {sides['dev']} dev")
    if pending:
        k, n = probe_yield(priced or got)
        rate = k / n if n else 0.0
        size = Counter(p["size"] for p in pending)
        each = {s: by[s] + round(size[s] * rate) for s in SIZES}
        spec_only = sum(1 for p in pending if p["variants"] == ["spec"])
        lines.append(f"projected: {len(usable)} + {len(pending)} x {k}/{n} probed kept = {sum(each.values())} tasks ("
                     + ", ".join(f"{each[s]} {s}" for s in SIZES) + f"); {spec_only} pending are spec only")
    return lines


def side_of(fix: str, seed: int = SPLIT_SEED, fraction: float = HOLDOUT_FRACTION) -> str:
    """'holdout' or 'dev' for a task: a draw on its fix sha alone, so a new task never moves an old one."""
    import hashlib
    h = hashlib.sha256(f"{seed}\0{fix}".encode("utf-8")).hexdigest()
    return "holdout" if int(h[:12], 16) / 16 ** 12 < fraction else "dev"


def split(tasks) -> dict:
    """The manifest's split record for these task rows."""
    sides = {t["id"]: side_of(t["fix"]) for t in tasks}
    return {"seed": SPLIT_SEED, "fraction": HOLDOUT_FRACTION,
            **{s: sorted(k for k, v in sides.items() if v == s) for s in ("dev", "holdout")}}


def manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_rows(got: dict, dropped=None) -> list[dict]:
    """One row per task and variant a manifest holds a prompt for, less the cases dropped after the survey."""
    dropped = DROPPED if dropped is None else dropped
    return [{**t, "variant": v} for t in got["tasks"] for v in VARIANTS
            if t["prompts"].get(v) and f"{t['id']}-{v}" not in dropped and f"{t['id']}-{v}" not in RETIRED]


def fetch(path: Path | None = None, src: Repo = SOHOT) -> list[dict]:
    """One row per task and variant, from the committed manifest."""
    path = path or src.manifest
    got = manifest(path)
    if got["revision"] != src.revision:
        raise RuntimeError(f"{path.name} was surveyed at {got['revision']}, not REVISION")
    return fetch_rows(got, src.dropped)


def convert(row: dict, src: Repo = SOHOT, mod=None, transform: str = TRANSFORM) -> Imported | None:
    """A manifest row as a repo case; `mod` is the importer module its provenance names (this one by default)."""
    calls = row.get("interface") or []
    shown = interface.block(calls)
    cid = f"{row['id']}-{row['variant']}"
    stated = STATED.get(cid, "")
    case = {"id": cid, "modality": LANE,
            "prompt": row["prompts"][row["variant"]] + (f"\n\n{shown}" if shown else "")
            + (f"\n\n{STATED_HEAD}\n{stated}" if stated else ""),
            "params": {"source_repo": src.url, "base": row["base"], "fix": row["fix"],
                       "variant": row["variant"], "context": "oracle",
                       "context_files": row["context_files"],
                       **({"new_files": row["new_files"]} if row.get("new_files") else {}),
                       **({"pytest_args": list(src.pytest_args)} if src.pytest_args else {}),
                       **({"extras": list(src.extras)} if src.extras else {}),
                       **({"interface": list(calls)} if calls else {}),
                       **({"stated": stated} if stated else {}),
                       "fail_to_pass": graded(row["id"], row["fail_to_pass"]), "pass_to_pass": row["pass_to_pass"]},
            "attribution": provenance(mod or sys.modules[__name__], f"#{row['issue']} (PR #{row['pr']})",
                                      transform + ("; what the hidden tests also require, stated after it (#1141)"
                                                   if stated else ""), row["date"])}
    return Imported(case)


def _reference(case) -> str:
    p = case.params
    return repo.reference_diff(repo.mirror(p["source_repo"]), p["base"], p["fix"])


#: The negative control: the fix's own diff must resolve, the empty patch must not.
RESPONDERS = {"reference": _reference, "empty": lambda case: ""}


def passes(case, answer: str) -> bool:
    a = repo.Attempt.open(case.params)
    try:
        if not answer:
            p = case.params
            repo.install_tests(a.mirror, a.task, p["base"], p["fix"])
            return repo.grade(a.task, a.python, p["fail_to_pass"], p["pass_to_pass"],
                              p.get("pytest_args") or ()).resolved
        return a.submit(answer).resolved
    finally:
        a.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.importers.history")
    ap.add_argument("--repo", default=None, help="the registered history source (default: SoHoT; --yield: every one)")
    ap.add_argument("--source", default=None, help="clone this instead of the source's own url")
    ap.add_argument("--revision", default="HEAD")
    ap.add_argument("--limit", type=int, default=None, help="stop at this many tasks; default the whole pool")
    ap.add_argument("--project", action="store_true",
                    help="screen the pool and read its issues but probe nothing; prints the projected yield")
    ap.add_argument("--probes", type=int, default=None, help="stop after running this many candidates (a dry run)")
    ap.add_argument("--restart", action="store_true",
                    help="start over instead of keeping the committed manifest's tasks as they are")
    ap.add_argument("--yield", dest="table", action="store_true",
                    help="print the yield of the manifest at --out; no survey")
    ap.add_argument("--log", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--refresh", action="store_true",
                    help="recompute context_files, new_files and interface of the committed manifest; no survey")
    a = ap.parse_args(argv)
    if a.table and a.repo is None and a.out is None:
        for r in repos():
            print("\n".join([f"{r.prefix} ({r.tracker}):"] + yield_table(manifest(r.manifest), dropped=r.dropped)))
        return 0
    src = next((r for r in repos() if r.name == (a.repo or SOHOT.name)), None)
    if src is None:
        ap.error(f"--repo {a.repo}: not a registered history source; known: {', '.join(r.name for r in repos())}")
    a.source, a.out = a.source or src.url, a.out or src.manifest
    if a.refresh:
        got = refresh(manifest(a.out), repo.mirror(a.source))
        a.out.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
        moved = {t["id"]: t["new_files"] for t in got["tasks"] if t["new_files"]}
        print(f"refreshed {len(got['tasks'])} tasks; files to create: {moved}", file=sys.stderr)
        return 0
    if a.table:
        print("\n".join(yield_table(manifest(a.out), dropped=src.dropped)))
        return 0
    if a.log is None:
        ap.error("--log is required for a survey")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    held = manifest(src.manifest) if src.manifest.is_file() else None
    got = survey(a.source, a.revision, a.limit, a.log, keep=None if a.restart else held,
                 probes=a.probes, run=not a.project, src=src)
    a.out.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
    print("\n".join(yield_table(got, dropped=src.dropped, priced=held or got)), file=sys.stderr)
    print(f"set {src.name} REVISION = {got['revision']!r}, copy {a.out} to {src.manifest.name}, then "
          f"`soh cases import {src.name}`", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

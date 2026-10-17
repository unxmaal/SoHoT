"""SoHoT's own merged fix commits as repo-lane tasks, in a spec and a symptom variant. #888."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from evals import repo
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
SUBJECT = re.compile(r"\(#(\d+)\) \(#(\d+)\)$")
MAX_SOURCE_FILES = 3
MAX_LINES = 150
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
             "base+reference diff, in the lane's own environment and sandbox (evals/repo.py)")

#: Cases dropped after the survey, with why: both fairness labellers flagged them, or validation failed. #920.
DROPPED: dict[str, str] = {}

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LABEL = re.compile(r"^(?:\*\*([^*\n]{1,60}?)[:.]?\*\*:?|([A-Z][A-Za-z ]{0,40}?):(?=\s|$))")
_LIST = re.compile(r"^(\s+|[-*+] |\d+[.)] )")
_HOME = re.compile(r"/(?:Users|home)/[^/\s]+/")


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


def prompts(title: str, body: str) -> dict[str, str]:
    """variant -> prompt text; symptom is None when it would only repeat spec or say nothing."""
    body = _HOME.sub("~/", body)
    spec = strip_sections(body, NOT_PROMPT)
    symptom = strip_sections(body, NOT_PROMPT + SOLUTION)
    head = f"# {title.strip()}\n\n"
    return {"spec": head + spec,
            "symptom": head + symptom if symptom and symptom != spec else None}


def git(path, *args) -> str:
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True,
                          text=True).stdout


def candidates(mirror, revision: str) -> list[dict]:
    """Fix commits on `revision`'s first-parent line, newest first, with their changed files."""
    out = []
    for line in git(mirror, "log", "--first-parent", "--format=%H%x00%P%x00%cI%x00%s",
                    revision).splitlines():
        sha, parents, date, subject = line.split("\0")
        m = SUBJECT.search(subject)
        if not m or len(parents.split()) != 1:
            continue
        files = {}
        for row in git(mirror, "diff", "--numstat", "--no-renames", f"{sha}^", sha).splitlines():
            added, deleted, path = row.split("\t")
            files[path] = 10 ** 6 if added == "-" else int(added) + int(deleted)
        source = sorted(p for p in files if not repo.is_test_path(p))
        context, new = split_new(mirror, parents.strip(), sha, source)
        out.append({"issue": int(m.group(1)), "pr": int(m.group(2)), "fix": sha,
                    "base": parents.strip(), "date": date[:10], "subject": subject,
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
    """The manifest with every task's context_files and new_files recomputed from the mirror. #913."""
    tasks = []
    for t in got["tasks"]:
        source = sorted({*t["context_files"], *t.get("new_files", [])})
        context, new = split_new(mirror, t["base"], t["fix"], source)
        tasks.append({**t, "context_files": context, "new_files": new})
    return {**got, "tasks": tasks}


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


def issue(number: int) -> dict | None:
    got = subprocess.run(["gh", "issue", "view", str(number), "-R", "unxmaal/SoHoT", "--json",
                          "title,body"], capture_output=True, text=True)
    return json.loads(got.stdout) if got.returncode == 0 else None


def _junit(xml: Path) -> dict:
    """junit key -> passed|failed|skipped."""
    out = {}
    for case in ET.parse(xml).getroot().iter("testcase"):
        key = f"{case.get('classname') or ''}::{case.get('name') or ''}"
        tags = {child.tag for child in case}
        out[key] = ("failed" if tags & {"failure", "error"} else
                    "skipped" if "skipped" in tags else "passed")
    return out


def _pytest(task: Path, python: Path, args, log, timeout) -> int | str:
    rc, tail, late = repo.run_sandboxed([str(python), "-m", "pytest", "-p", "no:cacheprovider",
                                         "-q", "-o", "addopts=", "-m", MARKERS, *args],
                                        task, timeout)
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n$ {task.name}: pytest {' '.join(args)}\n[exit {rc}{' timeout' if late else ''}]\n"
                f"{tail}\n")
    return "timeout" if late else rc


def outcomes(task: Path, python: Path, files, log, timeout=TIMEOUT_S) -> dict | str:
    """{"outcomes": junit key -> outcome, "seconds": s} of one sandboxed run, or a drop reason."""
    report = task / repo.HARNESS_DIR / "survey.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    t0 = time.perf_counter()
    got = _pytest(task, python, [f"--junitxml={report}", *files], log, timeout)
    if isinstance(got, str):
        return got
    if not report.is_file():
        return "pytest_crashed"
    return {"outcomes": _junit(report), "seconds": round(time.perf_counter() - t0, 2)}


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


def classify(base_runs: list[dict], fix_runs: list[dict], files) -> dict:
    """fail_to_pass and pass_to_pass from repeated runs, or {"drop": reason}."""
    if any(r["outcomes"] != base_runs[0]["outcomes"] for r in base_runs) or \
            any(r["outcomes"] != fix_runs[0]["outcomes"] for r in fix_runs):
        return {"drop": "flaky"}
    base, fix = base_runs[0]["outcomes"], fix_runs[0]["outcomes"]
    if any(v == "failed" for v in fix.values()):
        return {"drop": "reference_fails"}
    passing = node_ids([k for k, v in fix.items() if v == "passed"], files)
    f2p = [i for i in passing if base.get(repo.junit_key(i)) != "passed"]
    if not f2p:
        return {"drop": "no_flip"}
    return {"fail_to_pass": f2p, "pass_to_pass": [i for i in passing if i not in f2p],
            "test_s": fix_runs[0]["seconds"]}


def probe(mirror: Path, c: dict, log, timeout=TIMEOUT_S, runs=RUNS, env=None) -> dict:
    """Run the fix's tests at base+hidden tests, then with the reference diff applied, the grader's way."""
    task = repo.restore(mirror, c["base"])
    try:
        try:
            python = repo.python_of(Path((env or repo.prepare)(task)))
        except repo.RepoEnvError:
            return {"drop": "environment_error"}
        repo.install_tests(mirror, task, c["base"], c["fix"])
        files = [p for p in repo.hidden_tests(mirror, c["base"], c["fix"]) if _test_module(p)]
        if not files:
            return {"drop": "no_test_change"}
        base_runs = [outcomes(task, python, files, log, timeout) for _ in range(runs)]
        applied, _ = repo.apply(task, repo.reference_diff(mirror, c["base"], c["fix"]))
        if not applied:
            return {"drop": "reference_unappliable"}
        repo.install_tests(mirror, task, c["base"], c["fix"])
        fix_runs = [outcomes(task, python, files, log, timeout) for _ in range(runs)]
        bad = next((r for r in [*base_runs, *fix_runs] if isinstance(r, str)), None)
        return {"drop": bad} if bad else classify(base_runs, fix_runs, files)
    finally:
        repo.discard(mirror, task)


def area(source_files) -> str:
    return ",".join(sorted({str(Path(p).parent) for p in source_files}))


def survey(source: str, revision: str, limit: int, log, get_issue=issue, timeout=TIMEOUT_S,
           env=None) -> dict:
    """Examine fix commits newest first until `limit` tasks are kept; the manifest dict."""
    mirror = repo.mirror(source)
    revision = git(mirror, "rev-parse", revision).strip()
    kept, drops, seen = [], [], set()
    for c in candidates(mirror, revision):
        if len(kept) >= limit:
            break
        why = "duplicate_issue" if c["issue"] in seen else screen(c)
        text = res = None
        if why is None:
            got = get_issue(c["issue"])
            text = prompts(got["title"], got["body"] or "") if got else None
            why = "no_issue" if not got else ("no_fix_section" if text["symptom"] is None else None)
        if why is None:
            t0 = time.monotonic()
            res = probe(mirror, c, log, timeout, env=env)
            why = res.get("drop")
            print(f"{c['issue']:>4} {c['fix'][:10]} {why or 'kept'} {time.monotonic() - t0:.0f}s",
                  file=sys.stderr, flush=True)
        if why:
            drops.append({"issue": c["issue"], "pr": c["pr"], "fix": c["fix"], "reason": why})
            continue
        seen.add(c["issue"])
        kept.append({"id": f"sohot-{c['issue']}", "issue": c["issue"], "pr": c["pr"],
                     "base": c["base"], "fix": c["fix"], "date": c["date"],
                     "subject": c["subject"], "context_files": c["context_files"],
                     "new_files": c["new_files"],
                     "test_files": c["test_files"], "fail_to_pass": res["fail_to_pass"],
                     "pass_to_pass": res["pass_to_pass"], "prompts": text,
                     "strata": {"files": len(c["source_files"]), "lines": c["lines"],
                                "test_s": res["test_s"], "area": area(c["source_files"])}})
    return {"version": VERSION, "source": SOURCE, "repo": source, "revision": revision,
            "criteria": {"subject": SUBJECT.pattern, "first_parent": True,
                         "max_source_files": MAX_SOURCE_FILES, "max_lines": MAX_LINES,
                         "tests_changed": "a test_*.py the grader would install",
                         "no_env_file_change": list(repo.ENV_FILES), "runs": RUNS,
                         "markers": MARKERS, "pytest_timeout_s": timeout,
                         "order": "newest first", "limit": limit},
            "examined": len(kept) + len(drops),
            "dropped": dict(sorted(Counter(d["reason"] for d in drops).items())),
            "tasks": kept, "drops": drops}


def manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch(path: Path = MANIFEST) -> list[dict]:
    """One row per task and variant, from the committed manifest."""
    got = manifest(path)
    if got["revision"] != REVISION:
        raise RuntimeError(f"{path.name} was surveyed at {got['revision']}, not REVISION")
    return [{**t, "variant": v} for t in got["tasks"] for v in VARIANTS
            if t["prompts"].get(v) and f"{t['id']}-{v}" not in DROPPED]


def convert(row: dict) -> Imported | None:
    case = {"id": f"{row['id']}-{row['variant']}", "modality": LANE,
            "prompt": row["prompts"][row["variant"]],
            "params": {"source_repo": REPO_URL, "base": row["base"], "fix": row["fix"],
                       "variant": row["variant"], "context": "oracle",
                       "context_files": row["context_files"],
                       **({"new_files": row["new_files"]} if row.get("new_files") else {}),
                       "fail_to_pass": row["fail_to_pass"], "pass_to_pass": row["pass_to_pass"]},
            "attribution": provenance(sys.modules[__name__], f"#{row['issue']} (PR #{row['pr']})",
                                      TRANSFORM, row["date"])}
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
            return repo.grade(a.task, a.python, p["fail_to_pass"], p["pass_to_pass"]).resolved
        return a.submit(answer).resolved
    finally:
        a.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.importers.history")
    ap.add_argument("--source", default=REPO_URL)
    ap.add_argument("--revision", default="HEAD")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--log", type=Path)
    ap.add_argument("--out", type=Path, default=MANIFEST)
    ap.add_argument("--refresh", action="store_true",
                    help="recompute context_files and new_files of the committed manifest; no survey")
    a = ap.parse_args(argv)
    if a.refresh:
        got = refresh(manifest(a.out), repo.mirror(a.source))
        a.out.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
        moved = {t["id"]: t["new_files"] for t in got["tasks"] if t["new_files"]}
        print(f"refreshed {len(got['tasks'])} tasks; files to create: {moved}", file=sys.stderr)
        return 0
    if a.log is None:
        ap.error("--log is required for a survey")
    got = survey(a.source, a.revision, a.limit, a.log)
    a.out.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
    print(f"{len(got['tasks'])} tasks of {got['examined']} examined, dropped {got['dropped']}; "
          f"set REVISION = {got['revision']!r}, then `soh cases import history`", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

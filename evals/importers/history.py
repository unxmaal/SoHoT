"""SoHoT's own merged fix commits as repo-lane tasks, in a spec and a symptom variant. #888."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from evals.importers import Imported, provenance

LANE = "repo"
SOURCE = "git:unxmaal/SoHoT"
DATASET = "SoHoT fix history (unxmaal/SoHoT)"
URL = "https://github.com/unxmaal/SoHoT"
REPO_URL = "https://github.com/unxmaal/SoHoT.git"
LICENSE = "generated"
REVISION = "35ac01f5c487124fb40fc7a94680178c22b78ac6"
MANIFEST = Path(__file__).with_name("history.json")
ROOT = Path(__file__).resolve().parents[2]
VERSION = 1
SUBJECT = re.compile(r"\(#(\d+)\) \(#(\d+)\)$")
MAX_SOURCE_FILES = 3
MAX_LINES = 150
TIMEOUT_S = 300
SYNC_TIMEOUT_S = 600
RUNS = 2
PYTHON = ("uv", "run", "--frozen", "--no-sync", "python")
SYNC = ("uv", "sync", "--frozen")
#: Seam for #887: its sandbox-exec argv prefix, so the survey grades under the same profile as the lane.
WRAP: tuple = ()
LOCKFILES = {"uv.lock", "pyproject.toml"}
VARIANTS = ("spec", "symptom")
#: Sections dropped from both variants, then from symptom only (headings, lower case, matched as a prefix).
NOT_PROMPT = ("prior art checked",)
SOLUTION = ("fix", "the fix", "shape", "shape of the fix", "design", "options", "remedy",
            "proposal", "build", "what to change", "what to build", "what to do")
TRANSFORM = ("issue title and body from `gh issue view` at survey time, 'Prior art checked' removed "
             "(spec), and the Fix/Shape/Design/Options/Remedy/Proposal/Build/What-to sections too "
             "(symptom); base = fix^; fail_to_pass and pass_to_pass from pytest runs of the fix's "
             f"changed test files at base+tests and at fix, {RUNS} runs each, in base's uv.lock env")

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LABEL = re.compile(r"^(?:\*\*([^*\n]{1,60}?)[:.]?\*\*:?|([A-Z][A-Za-z ]{0,40}?):(?=\s|$))")
_LIST = re.compile(r"^(\s+|[-*+] |\d+[.)] )")

_PLUGIN = '''
import json, os
_out = {}
_dur = {}
_RANK = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}
def _set(nodeid, outcome):
    _out[nodeid] = max(outcome, _out.get(nodeid, outcome), key=_RANK.get)
def pytest_collectreport(report):
    if report.failed:
        _set(report.nodeid, "error")
def pytest_runtest_logreport(report):
    _dur[report.nodeid] = _dur.get(report.nodeid, 0.0) + report.duration
    if report.when == "call":
        _set(report.nodeid, "skipped" if report.skipped else report.outcome)
    elif report.failed:
        _set(report.nodeid, "error")
    elif report.skipped:
        _set(report.nodeid, "skipped")
def pytest_sessionfinish(session):
    with open(os.environ["SOH_OUTCOMES"], "w") as f:
        json.dump({"outcomes": _out, "seconds": sum(_dur.values())}, f)
'''


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
    spec = strip_sections(body, NOT_PROMPT)
    symptom = strip_sections(body, NOT_PROMPT + SOLUTION)
    head = f"# {title.strip()}\n\n"
    return {"spec": head + spec,
            "symptom": head + symptom if symptom and symptom != spec else None}


def git(repo, *args, check=True) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True,
                          text=True).stdout


def _is_test(path: str) -> bool:
    return path.startswith("tests/")


def candidates(repo, revision: str) -> list[dict]:
    """Fix commits on `revision`'s first-parent line, newest first, with their changed files."""
    out = []
    for line in git(repo, "log", "--first-parent", "--format=%H%x00%P%x00%cI%x00%s",
                    revision).splitlines():
        sha, parents, date, subject = line.split("\0")
        m = SUBJECT.search(subject)
        if not m or len(parents.split()) != 1:
            continue
        files, lines = {}, 0
        for row in git(repo, "diff", "--numstat", "--no-renames", f"{sha}^", sha).splitlines():
            added, deleted, path = row.split("\t")
            n = 10 ** 6 if added == "-" else int(added) + int(deleted)
            files[path] = n
        source = sorted(p for p in files if not _is_test(p))
        out.append({"issue": int(m.group(1)), "pr": int(m.group(2)), "fix": sha,
                    "base": parents.strip(), "date": date[:10], "subject": subject,
                    "source_files": source, "test_files": sorted(p for p in files if _is_test(p)),
                    "lines": sum(files[p] for p in source)})
    return out


def screen(c: dict) -> str | None:
    """Why a candidate is out before anything runs, or None."""
    if not any(p.endswith(".py") and Path(p).name.startswith("test_") for p in c["test_files"]):
        return "no_test_change"
    if not c["source_files"]:
        return "no_source_change"
    if len(c["source_files"]) > MAX_SOURCE_FILES or c["lines"] > MAX_LINES:
        return "too_big"
    if LOCKFILES & set(c["source_files"]):
        return "dependency_change"
    return None


def issue(number: int) -> dict | None:
    got = subprocess.run(["gh", "issue", "view", str(number), "-R", "unxmaal/SoHoT", "--json",
                          "title,body,url"], capture_output=True, text=True)
    return json.loads(got.stdout) if got.returncode == 0 else None


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}}


def _run(cmd, cwd, timeout, log, env=None) -> int | None:
    """Exit code, or None on timeout (the whole process group is killed)."""
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n$ (cd {cwd} && {' '.join(map(str, cmd))})\n")
        f.flush()
        p = subprocess.Popen(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, env=env or _env(),
                             start_new_session=True)
        try:
            return p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
            f.write(f"\n[timeout after {timeout}s]\n")
            return None


def pytest_outcomes(tree: Path, files, log, timeout=TIMEOUT_S, python=PYTHON) -> dict | str:
    """{"outcomes": nodeid -> passed|failed|error|skipped, "seconds": s}, or a drop reason."""
    with tempfile.TemporaryDirectory(prefix="soh-pytest-") as tmp:
        (Path(tmp) / "soh_outcomes.py").write_text(_PLUGIN, encoding="utf-8")
        out = Path(tmp) / "outcomes.json"
        env = {**_env(), "PYTHONPATH": tmp, "SOH_OUTCOMES": str(out)}
        code = _run([*WRAP, *python, "-m", "pytest", "-p",
                     "soh_outcomes", "-p", "no:cacheprovider", *files], tree, timeout, log, env)
        if code is None:
            return "timeout"
        if not out.exists():
            return "pytest_crashed"
        return json.loads(out.read_text(encoding="utf-8"))


def classify(base_runs: list[dict], fix_runs: list[dict]) -> dict:
    """fail_to_pass and pass_to_pass from repeated runs, or {"drop": reason}."""
    if any(r["outcomes"] != base_runs[0]["outcomes"] for r in base_runs) or \
            any(r["outcomes"] != fix_runs[0]["outcomes"] for r in fix_runs):
        return {"drop": "flaky"}
    base, fix = base_runs[0]["outcomes"], fix_runs[0]["outcomes"]
    if any(v in {"failed", "error"} for v in fix.values()):
        return {"drop": "reference_fails"}
    passing = sorted(k for k, v in fix.items() if v == "passed")
    f2p = [k for k in passing if base.get(k) != "passed"]
    if not f2p:
        return {"drop": "no_flip"}
    return {"fail_to_pass": f2p, "pass_to_pass": [k for k in passing if base.get(k) == "passed"],
            "test_s": round(fix_runs[0]["seconds"], 2)}


def probe(repo, c: dict, work: Path, log, timeout=TIMEOUT_S, runs=RUNS, python=PYTHON,
          sync=SYNC) -> dict:
    """Run the fix's changed tests at base+tests and at fix in a throwaway worktree."""
    tree = work / f"wt-{c['fix'][:12]}"
    git(repo, "worktree", "add", "--detach", "-f", str(tree), c["base"])
    try:
        if sync and _run(list(sync), tree, SYNC_TIMEOUT_S, log) != 0:
            return {"drop": "environment_error"}
        at_fix = set(git(repo, "ls-tree", "-r", "--name-only", c["fix"], "--", "tests").split())
        for path in c["test_files"]:
            if path in at_fix:
                git(tree, "checkout", c["fix"], "--", path)
            elif (tree / path).exists():
                (tree / path).unlink()
        files = [p for p in c["test_files"]
                 if p in at_fix and p.endswith(".py") and Path(p).name.startswith("test_")]
        if not files:
            return {"drop": "no_test_change"}
        base_runs = [pytest_outcomes(tree, files, log, timeout, python) for _ in range(runs)]
        git(tree, "checkout", "-f", "--detach", c["fix"])
        fix_runs = [pytest_outcomes(tree, files, log, timeout, python) for _ in range(runs)]
        bad = next((r for r in base_runs + fix_runs if isinstance(r, str)), None)
        return {"drop": bad} if bad else classify(base_runs, fix_runs)
    finally:
        git(repo, "worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(tree, ignore_errors=True)


def area(source_files) -> str:
    return ",".join(sorted({str(Path(p).parent) for p in source_files}))


def survey(repo, revision: str, limit: int, log, work: Path | None = None, get_issue=issue,
           timeout=TIMEOUT_S, python=PYTHON, sync=SYNC) -> dict:
    """Examine fix commits newest first until `limit` tasks are kept; the manifest dict."""
    revision = git(repo, "rev-parse", revision).strip()
    kept, drops, seen = [], [], set()
    work = Path(work or tempfile.mkdtemp(prefix="soh-history-"))
    for c in candidates(repo, revision):
        if len(kept) >= limit:
            break
        why = "duplicate_issue" if c["issue"] in seen else screen(c)
        text = None
        if why is None:
            got = get_issue(c["issue"])
            text = prompts(got["title"], got["body"] or "") if got else None
            why = "no_issue" if not got else ("no_fix_section" if text["symptom"] is None else None)
        if why is None:
            t0 = time.monotonic()
            res = probe(repo, c, work, log, timeout, python=python, sync=sync)
            why = res.get("drop")
            print(f"{c['issue']:>4} {c['fix'][:10]} {why or 'kept'} {time.monotonic() - t0:.0f}s",
                  file=sys.stderr, flush=True)
        if why:
            drops.append({"issue": c["issue"], "pr": c["pr"], "fix": c["fix"], "reason": why})
            continue
        seen.add(c["issue"])
        kept.append({"id": f"sohot-{c['issue']}", "issue": c["issue"], "pr": c["pr"],
                     "base": c["base"], "fix": c["fix"], "date": c["date"],
                     "subject": c["subject"], "context_files": c["source_files"],
                     "test_files": c["test_files"], "fail_to_pass": res["fail_to_pass"],
                     "pass_to_pass": res["pass_to_pass"], "prompts": text,
                     "strata": {"files": len(c["source_files"]), "lines": c["lines"],
                                "test_s": res["test_s"], "area": area(c["source_files"])}})
    return {"version": VERSION, "source": SOURCE, "revision": revision,
            "criteria": {"subject": SUBJECT.pattern, "first_parent": True,
                         "max_source_files": MAX_SOURCE_FILES, "max_lines": MAX_LINES,
                         "tests_changed": "tests/**/test_*.py", "no_lockfile_change": True,
                         "runs": RUNS, "pytest_timeout_s": timeout, "order": "newest first",
                         "limit": limit},
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
    return [{**t, "variant": v} for t in got["tasks"] for v in VARIANTS if t["prompts"].get(v)]


def convert(row: dict) -> Imported | None:
    case = {"id": f"{row['id']}-{row['variant']}", "modality": LANE,
            "prompt": row["prompts"][row["variant"]],
            "params": {"source_repo": REPO_URL, "base": row["base"], "fix": row["fix"],
                       "context_files": row["context_files"],
                       "fail_to_pass": row["fail_to_pass"], "pass_to_pass": row["pass_to_pass"],
                       "variant": row["variant"], "context": "oracle"},
            "attribution": provenance(sys.modules[__name__], f"#{row['issue']} (PR #{row['pr']})",
                                      TRANSFORM, row["date"])}
    return Imported(case)


def reference(case, repo=ROOT) -> str:
    """The fix's diff over its context files: the patch a perfect answer would send."""
    p = case.params if hasattr(case, "params") else case["params"]
    return git(repo, "diff", p["base"], p["fix"], "--", *p["context_files"])


RESPONDERS = {"reference": reference, "empty": lambda case: ""}


def passes(case, answer: str) -> bool:
    raise NotImplementedError("repo cases are graded by the repo lane runner's sandboxed grader (#887)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.importers.history")
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--revision", default="origin/main")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--work", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=MANIFEST)
    a = ap.parse_args(argv)
    got = survey(a.repo, a.revision, a.limit, a.log, a.work)
    a.out.write_text(json.dumps(got, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(f"{len(got['tasks'])} tasks of {got['examined']} examined, dropped {got['dropped']}; "
          f"set REVISION = {got['revision']!r}, then `soh cases import history`", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

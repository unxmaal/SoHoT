"""The release a queued job was built against, and where it starts after a deploy moved the link (#1788)."""
from __future__ import annotations

import contextlib
import io
import ntpath
import os
import sys
import time
from pathlib import Path

from harness import job_state as js
from harness import paths

#: What happens to a job built by another release when it starts.
STAYS, MOVES, REFUSED = "stays", "moves", "refused"
#: Reasons a pending job holds that mean its command never ran.
UNSTARTED = frozenset({js.ADDED, js.UNCLAIMED})


def releases_dir() -> Path:
    return paths.home() / "releases"


def release_of(path) -> Path | None:
    """The release directory holding `path`, or None outside every release of this home."""
    if not path:
        return None
    root = releases_dir().resolve()
    try:
        rel = Path(path).resolve().relative_to(root)
    except ValueError:
        return None
    return root / rel.parts[0] if rel.parts else None


def here() -> Path | None:
    """The release this code runs from; None for a checkout outside the releases."""
    return release_of(paths.REPO)


def target() -> Path | None:
    """The release the deploy link names now; None without one."""
    return release_of(paths.deploy_checkout())


def moved(argv, old: Path, new: Path) -> list[str]:
    """argv with every word naming a path inside release `old` named at the same place in `new`."""
    out = []
    for word in map(str, argv):
        for prefix in (str(old), os.path.realpath(old)):
            rest = _within(word, prefix)
            if rest is not None:
                word = str(new) + rest
                break
        out.append(word)
    return out


def _within(word: str, top: str) -> str | None:
    """What follows directory `top` in `word` ('' for `top` itself), or None outside it; on Windows either separator and any case."""
    win = sys.platform == "win32"
    seps = "\\/" if win else "/"
    head, rest = word[:len(top)], word[len(top):]
    same = ntpath.normcase(head) == ntpath.normcase(top) if win else head == top
    return rest if same and (not rest or rest[0] in seps) else None


def _after(words: list[str], module: str, names=()) -> list[str] | None:
    for i, w in enumerate(words):
        if (w == module and i and words[i - 1] == "-m") or os.path.basename(w) in names:
            return words[i + 1:]
    return None


def _parse(parser, rest: list[str]) -> str:
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            parser().parse_args(rest)
    except SystemExit as exc:
        if exc.code in (0, None):
            return ""
        lines = [ln for ln in err.getvalue().splitlines() if ln.strip()]
        return lines[-1] if lines else f"its arguments exit {exc.code}"
    return ""


def refusal(argv, new: Path) -> str:
    """Why release `new` would refuse argv, read with this code (so only meaningful when this code is `new`), or ''."""
    words = [str(a) for a in argv]
    for w in words:
        if _within(w, str(new)) and not Path(w).exists():
            return f"{w} is not in release {new.name}"
    rest = _after(words, "harness.cli", ("soh", "lh"))
    if rest is not None:
        from harness import cli
        why = _parse(cli.build_parser, rest)
        return f"release {new.name} refuses its soh arguments: {why}" if why else ""
    rest = _after(words, "evals.run")
    if rest is not None:
        from evals import run
        why = _parse(run._parser, rest)
        return f"release {new.name} refuses its evals.run arguments: {why}" if why else ""
    return ""


def stale_schema(cwd, conn) -> str:
    """Why a job in cwd would refuse this store (older code), or, on the live store, be refused migrating it (newer), or ''. #1348, #1788."""
    from harness import workqueue as wq
    code = wq.code_schema(cwd)
    row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    store = int(row["value"]) if row else 0
    if code is None or code == store:
        return ""
    top = wq._schema_file(cwd).parents[2]
    if code < store:
        return (f"the job's code ({top}) speaks schema {code} but the store is schema {store}, "
                f"so it would refuse the store when it starts; queue from the deploy or update that checkout")
    if not paths.is_live(paths.home() / "discovery.db") or os.environ.get(paths.ALLOW_MIGRATE_ENV) == "1":
        return ""
    return (f"the job's code ({top}) speaks schema {code}, ahead of the live store's schema {store}, "
            f"and only the deploy migrates the live store; queue from the deploy or deploy that code")


def plan(job: dict, new: Path | None, stale: str = "", check=refusal) -> dict | None:
    """Where a job built by another release than `new` starts (stale: stale_schema of its own cwd); None when `new` or no release built it."""
    built = release_of(job.get("cwd"))
    if built is None or new is None or built == new:
        return None
    base = {"job": job["id"], "built": built.name, "release": new.name}
    started = (job.get("reason") or js.ADDED) not in UNSTARTED
    if started and built.is_dir() and not stale:
        return {**base, "action": STAYS, "why": f"a started step resumes in release {built.name}, which built it"}
    cwd = new / Path(job["cwd"]).resolve().relative_to(built)
    argv = moved(job["argv"], built, new)
    gone = "is gone" if not built.is_dir() else (stale and "cannot run on this store") or "is not the deployed release"
    why = (not cwd.is_dir() and f"{cwd} is not in release {new.name}") or (check(argv, new) if check else "")
    if why:
        return {**base, "action": REFUSED, "why": f"release {built.name} built it and {gone}; {why}"}
    return {**base, "action": MOVES, "cwd": str(cwd), "argv": argv,
            "why": f"release {built.name} built it and {gone}; started on release {new.name}"}


def repoint(conn, job: dict, p: dict) -> bool:
    """Point a claimed job at release p['release']: its cwd and argv, with a note naming the release that built it. Does not commit."""
    import json
    from harness import workqueue as wq
    took = conn.execute("UPDATE jobs SET cwd = ?, argv = ?, note = ? WHERE id = ? AND state = ?",
                        (p["cwd"], json.dumps(p["argv"]), p["why"], int(job["id"]), wq.RUNNING)).rowcount == 1
    if took:
        job.update(cwd=p["cwd"], argv=p["argv"], note=p["why"])
    return took


def start(conn, job: dict, log, stale: str) -> str | None:
    """At a claimed job's start: refuse it by name, or point it at this release; the action taken, None when it runs as queued."""
    from harness import workqueue as wq
    p = plan(job, here(), stale)
    if p is None or p["action"] == STAYS:
        return None
    refused = p["action"] == REFUSED
    if refused:
        took = js.move(conn, job["id"], wq.RUNNING, wq.FAILED, js.RELEASE_REFUSED, f"not started: {p['why']}",
                       rc=None, finished_at=time.time())
    else:
        took = repoint(conn, job, p)
    if not took:
        return None
    conn.commit()
    # The row's note is the durable record; the log line is its copy, so a death before it loses nothing.
    with open(log, "a", encoding="utf-8") as out:
        out.write(f"{'not started: ' if refused else ''}{p['why']}\n")
    return p["action"]


def suffix(p: dict | None) -> str:
    """A soh jobs line's tail for a job built by another release; '' for one built by the linked release."""
    if p is None:
        return ""
    if p["action"] == STAYS:
        return f" [release {p['built']}, where it resumes]"
    if p["action"] == REFUSED:
        return f" [release {p['built']}; refused at start: {p['why']}]"
    return f" [release {p['built']}; starts on {p['release']}]"


def plans(conn, jobs: list[dict], new: Path | None = None) -> dict:
    """{job id: plan} for each pending job built by another release than the linked one."""
    from harness import workqueue as wq
    waiting = [j for j in jobs if j["state"] == wq.PENDING and release_of(j.get("cwd")) is not None]
    if not waiting:
        return {}
    new = target() if new is None else new
    check = refusal if new is not None and new == here() else None
    out = {}
    for j in waiting:
        p = plan(j, new, stale_schema(j["cwd"], conn), check)
        if p is not None:
            out[j["id"]] = p
    return out


def morning(conn, since: float, where=None) -> dict:
    """Pending jobs built by another release than the deploy, and jobs refused at start for it since `since`."""
    from harness import workqueue as wq
    got = wq.jobs(conn)
    new = release_of(where) if where is not None else None
    refused = [{"job": j["id"], "title": j["title"], "why": j["note"] or ""} for j in got
               if j["state"] == wq.FAILED and j["reason"] == js.RELEASE_REFUSED
               and (wq._epoch(j["finished"]) or 0) >= since]
    return {"pending": list(plans(conn, got, new).values()) if new is not None else [], "refused": refused}


def morning_lines(r: dict | None) -> list[str]:
    if not r or not (r["pending"] or r["refused"]):
        return []
    out = [f"releases  {len(r['pending'])} pending job(s) built by another release; "
           f"{len(r['refused'])} refused at start"]
    out.extend(f"          {p['job']}{suffix(p)}" for p in r["pending"])
    out.extend(f"          {x['job']} refused: {x['why']}" for x in r["refused"])
    return out

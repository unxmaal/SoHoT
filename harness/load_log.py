"""A llama-server child's load log, cut out of the router's log by the port its spawn line names. #953."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import NamedTuple

#: The excerpt's name in a run directory.
FILE = "server-load.log"
#: The home whose services an isolated home's screen goes through; their router logs there. #1006.
SERVING_ENV = "LH_SERVING_HOME"

_SPAWN = re.compile(r"spawning server instance with name=(\S+) on port (\d+)")
_ARGS = re.compile(r"^\S+ I srv +load: ")
_EXITED = re.compile(r"instance name=(\S+) exited with status (-?\d+)")


class Excerpt(NamedTuple):
    log: str
    first: int
    last: int
    lines: list
    status: int


def router_logs() -> list[Path]:
    """Where the serving router's stderr lands: launchd's eval service, else services.sh's llamacpp files."""
    import os

    from harness import paths
    serving = os.environ.get(SERVING_ENV)
    d = Path(serving).expanduser() / "logs" if serving else paths.logs()
    return [d / "eval.log", d / "llamacpp.err.log", d / "llamacpp.log"]


def cut(lines, alias: str, log: str = "") -> Excerpt | None:
    """The last load of `alias` that exited non-zero: spawn and args lines, its port's lines, the exit line."""
    found = cur = None
    port, args = "", False
    for n, line in enumerate(lines, 1):
        spawn = _SPAWN.search(line) if "spawning server instance" in line else None
        if spawn and spawn.group(1) == alias:
            cur, port, args = [n, [line]], f"[{spawn.group(2)}]", True
            continue
        if cur is None:
            continue
        if line.startswith(port):
            cur[1].append(line)
            args = False
        elif args and _ARGS.match(line):
            cur[1].append(line)
        else:
            args = False
            done = _EXITED.search(line) if "exited with status" in line else None
            if done and done.group(1) == alias:
                cur[1].append(line)
                if int(done.group(2)) != 0:
                    found = Excerpt(log, cur[0], n, cur[1], int(done.group(2)))
                cur = None
    return found


def find(alias: str, logs=None) -> Excerpt | None:
    """The excerpt from the first router log that holds one."""
    for path in router_logs() if logs is None else logs:
        path = Path(path)
        if not alias or not path.is_file():
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            got = cut(fh, alias, str(path))
        if got:
            return got
    return None


def source(ex: Excerpt) -> str:
    return f"{Path(ex.log).name} lines {ex.first}-{ex.last}"


def write(outdir: Path, ex: Excerpt) -> Path:
    path = Path(outdir) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {source(ex)}\n" + "".join(
        line if line.endswith("\n") else line + "\n" for line in ex.lines), encoding="utf-8")
    return path


def file_until(conn, repo: str) -> str:
    """A malformed upload reopens once its repo commits after our copy was fetched."""
    row = conn.execute("SELECT max(finished_at) FROM downloads WHERE repo = ?", (repo,)).fetchone()
    at = row[0] if row and row[0] else time.time()
    return "commit_after:" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(at)))


def decided(text: str, ex: Excerpt, candidate: str, repo: str, conn, where: str):
    """The screen verdict the child's own log decides, quoting its first error line."""
    from harness import reasons, screen
    cls = reasons.classify(text + "\n" + "".join(ex.lines), reasons.RUNNER, candidate)
    errors = reasons.child_errors(ex.lines)
    why = f"llama-server: {errors[0] if errors else f'exited {ex.status}'} ({where})"
    got = screen.decide_class(cls, why, candidate)
    return got._replace(until=file_until(conn, repo)) if cls == reasons.LOAD_FAILED_FILE else got


def redecide(verdict, candidate: str, repo: str, outdir: Path, conn, logs=None):
    """A llama-server load failure decided from the child's log, kept in the run directory; unchanged without one."""
    from harness import reasons, router
    alias = reasons.llamacpp_alias(verdict.detail) or router.stem_of(candidate)
    ex = find(alias, logs)
    if ex is None:
        return verdict
    path = write(outdir, ex)
    return decided(verdict.detail, ex, candidate, repo, conn, f"{path.name}, {source(ex)}")


#: Screen runtime verdicts holding a llama.cpp candidate's state, with the run they came from.
HELD = ("SELECT v.id, p.name, v.outcome, v.reason, v.until, v.detail, v.run_id, v.candidate_id, c.spec, "
        "coalesce(r.path, v.run_path, '') AS path FROM proposals p "
        "JOIN verdicts v ON v.id = p.state_verdict_id JOIN candidates c ON c.id = v.candidate_id "
        "LEFT JOIN runs r ON r.id = v.run_id "
        "WHERE v.tier = 'screen' AND v.reason = 'runtime' AND c.spec LIKE 'llamacpp:%' ORDER BY v.id")


def _run_dir(path: str, root=None) -> Path | None:
    from harness import runs
    if not path:
        return None
    return Path(root) / Path(path).name if root else runs.run_dir(path)


def unkept(conn, root=None) -> list[dict]:
    """Held llama.cpp runtime verdicts whose run directory has no load log."""
    out = []
    for r in conn.execute(HELD).fetchall():
        where = _run_dir(r["path"], root)
        if where is None or not (where / FILE).is_file():
            out.append({**dict(r), "dir": str(where or "")})
    return out


def changes(conn, logs=None, root=None) -> list[dict]:
    """Each unkept verdict as its child's log in the router log decides it; the version it failed on is kept."""
    from harness import reasons, router
    found = []
    for r in unkept(conn, root):
        base = {"verdict_id": r["id"], "name": r["name"], "dir": r["dir"],
                "was": [r["outcome"], r["reason"], r["until"]]}
        ex = find(reasons.llamacpp_alias(r["detail"]) or router.stem_of(r["spec"]), logs)
        if ex is None or not r["dir"]:
            found.append({**base, "skipped": "no run directory" if ex else "no failed load in the router log"})
            continue
        got = decided(r["detail"], ex, r["spec"], r["name"], conn,
                      f"{source(ex)}, cut after the verdict, not kept by the run")
        if got.reason == reasons.RUNTIME and (r["until"] or "").startswith("version:llama.cpp>"):
            got = got._replace(until=r["until"])
        found.append({**base, "now": [got.outcome, got.reason, got.until], "detail": got.detail,
                      "excerpt": ex, "run_id": r["run_id"], "candidate_id": r["candidate_id"]})
    return found


def apply(conn, found: list[dict]) -> list[int]:
    """Keep each excerpt in its run directory and write the verdict through the one state writer."""
    from harness import memory_store as ms
    ids = []
    for c in found:
        if "now" not in c:
            continue
        write(Path(c["dir"]), c["excerpt"])
        outcome, reason, until = c["now"]
        ids.append(ms.decide(conn, c["name"], outcome, tier=ms.SCREEN, run_id=c["run_id"], run_path=c["dir"],
                             detail=f"re-decided from the router log (#953): {c['detail']}"[:600],
                             reason=reason, until=until, candidate_id=c["candidate_id"]))
    conn.commit()
    return ids

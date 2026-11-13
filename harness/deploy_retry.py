"""Whether the poll may queue a sha again: never one whose deploy rolled back here, until a person retries it (#1913)."""
from __future__ import annotations

from harness import deploy_state as ds

#: Outcomes after which the switch ran and could not keep the sha: the poll never queues that sha again on its own.
FINAL = (ds.ROLLED_BACK, ds.FAILED_FORWARD)


def command(sha: str) -> str:
    """The one command that deploys sha again past its rollback."""
    return f"soh deploy now {sha}"


def rolled_back(conn, sha: str) -> dict | None:
    """This machine's newest deploy of sha that ended in FINAL, else None."""
    from harness import machine_scope
    here, args = machine_scope.here(conn, "deploys.mine")
    marks = ",".join("?" * len(FINAL))
    row = conn.execute(f"SELECT id, outcome FROM deploys WHERE sha = ? AND outcome IN ({marks}) AND {here} "
                       "ORDER BY id DESC LIMIT 1", (sha, *FINAL, *args)).fetchone()
    return {"id": row["id"], "outcome": row["outcome"]} if row else None


def why(conn, sha: str) -> str:
    """'' when no deploy of sha rolled back here, else why the poll leaves it."""
    row = rolled_back(conn, sha)
    if row is None:
        return ""
    return f"{row['outcome']} as deploy {row['id']}; the poll does not retry it, `{command(sha)}` does"

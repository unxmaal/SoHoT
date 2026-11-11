"""Put a test's job row in any state outside job_state's moves: a fixture, never a transition. #1728."""
from harness import workqueue as wq


def put(job: dict, conn=None) -> None:
    """Store a job dict's mutable fields back to its row, as workqueue._write did before #1728."""
    with wq._store(conn) as c:
        c.execute("UPDATE jobs SET state = ?, started_at = ?, finished_at = ?, rc = ?, log = ?, note = ?, "
                  "priority = ? WHERE id = ?",
                  (job["state"], wq._epoch(job.get("started")), wq._epoch(job.get("finished")), job.get("rc"),
                   job.get("log") or "", job.get("note") or "", int(job.get("priority") or 0), int(job["id"])))
        c.commit()

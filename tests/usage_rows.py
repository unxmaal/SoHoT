"""Read gateway_requests once the rows a test reads have landed. #1248."""
import time


def _store():
    from harness import memory_store as ms
    return ms.connect()


def wait_rows(want, key, timeout=20.0, poll=0.25, connect=None, clock=time.time, sleep=time.sleep):
    """Every gateway_requests row, once each of `want` is some row's `key`, or as they stand at the deadline."""
    deadline = clock() + timeout
    while True:
        conn = (connect or _store)()
        try:
            rows = [dict(r) for r in conn.execute("SELECT * FROM gateway_requests ORDER BY id")]
        finally:
            conn.close()
        if set(want) <= {key(r) for r in rows} or clock() > deadline:
            return rows
        sleep(poll)

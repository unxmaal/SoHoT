"""A connect that waits out the host port forwarder in front of a docker Postgres when it drops new connections in a burst. #2203."""
import time

BUDGET_S = 180.0
DROPPED = "server closed the connection unexpectedly"


def retrying(real, sleep=time.sleep, budget: float = BUDGET_S):
    import psycopg

    def connect(*args, **kwargs):
        waited, delay = 0.0, 0.5
        while True:
            try:
                return real(*args, **kwargs)
            except psycopg.OperationalError as exc:
                if DROPPED not in str(exc) or waited >= budget:
                    raise
                sleep(delay)
                waited, delay = waited + delay, min(delay * 2, 10.0)
    connect.real = real
    return connect

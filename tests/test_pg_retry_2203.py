"""A docker Postgres behind the host's port forwarder drops connects in bursts; the suite waits them out instead of failing a batch of tests. #2203."""
import psycopg
import pytest

from tests import pg_retry

DROP = psycopg.OperationalError(f"connection failed: connection to server at 127.0.0.1, port 1 failed: {pg_retry.DROPPED}")


def flaky(*errors):
    calls = []

    def real(*a, **k):
        calls.append(a)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return "conn"
    return real, calls


def test_a_dropped_connect_is_tried_again_with_a_growing_wait_until_it_gets_through():
    real, calls = flaky(DROP, DROP, DROP)
    slept = []
    assert pg_retry.retrying(real, sleep=slept.append)("dsn") == "conn"
    assert len(calls) == 4 and slept == [0.5, 1.0, 2.0]


def test_a_forwarder_that_never_recovers_fails_with_its_own_error_once_the_budget_is_spent():
    real, calls = flaky(*[DROP] * 1000)
    slept = []
    with pytest.raises(psycopg.OperationalError, match=pg_retry.DROPPED):
        pg_retry.retrying(real, sleep=slept.append, budget=20.0)("dsn")
    assert sum(slept) >= 20.0 and len(calls) == len(slept) + 1 and max(slept) == 10.0


@pytest.mark.parametrize("err", [psycopg.OperationalError("connection refused"),
                                 psycopg.OperationalError('FATAL:  password authentication failed for user "discovery"'),
                                 ValueError("bad dsn")])
def test_any_other_failure_is_raised_at_once(err):
    real, calls = flaky(err)
    slept = []
    with pytest.raises(type(err)):
        pg_retry.retrying(real, sleep=slept.append)("dsn")
    assert slept == [] and len(calls) == 1

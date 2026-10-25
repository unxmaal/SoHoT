"""#1248: the real-proxy usage tests wait for each row they read, not for a row count."""
from tests.usage_rows import wait_rows

UNAUTH = {"id": 1, "alias": "", "stream": 0, "call_type": "acompletion"}
PLAIN = {"id": 2, "alias": "sohot-code", "stream": 0, "call_type": "acompletion"}
BOOM = {"id": 3, "alias": "boom", "stream": 0, "call_type": "acompletion"}
ANTH = {"id": 4, "alias": "sohot-code", "stream": 0, "call_type": "anthropic_messages"}


def _key(r):
    return (r["alias"], r["stream"], r["call_type"])


class _Store:
    """Each read sees the next batch of landed rows, as the gateway's writer thread lands them."""

    def __init__(self, *landings):
        self.landings, self.reads = list(landings), 0

    def __call__(self):
        return self

    def execute(self, sql):
        got = self.landings[min(self.reads, len(self.landings) - 1)]
        self.reads += 1
        return got

    def close(self):
        pass


def test_the_usage_test_waits_for_every_row_it_reads():
    store = _Store([UNAUTH, PLAIN, BOOM], [UNAUTH, PLAIN, BOOM, ANTH])
    want = {_key(PLAIN), _key(BOOM), _key(ANTH)}
    rows = wait_rows(want, _key, connect=store, sleep=lambda s: None)
    assert {_key(r) for r in rows} >= want and store.reads == 2


def test_a_row_that_never_lands_is_waited_for_until_the_deadline():
    clock = {"t": 0.0}
    store = _Store([UNAUTH, PLAIN, BOOM])

    def sleep(s):
        clock["t"] += s

    rows = wait_rows({_key(ANTH)}, _key, timeout=2.0, connect=store, clock=lambda: clock["t"],
                     sleep=sleep)
    assert _key(ANTH) not in {_key(r) for r in rows} and clock["t"] >= 2.0

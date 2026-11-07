"""gateway_requests.at is when a request started; every reader of a request's span gets it from usage. #1560."""
import re
import time
from pathlib import Path

from harness import contention, idle_unload, interactive, inventory_time, ledger, paths, residency_trace, usage
from harness import memory_store as ms

ROOT = Path(__file__).resolve().parent.parent
NOW = time.time()
T = NOW - 3600
LONG = 600.0
MODEL = "Ornith-1.5-35B-Q4_K_M"


def _plant(rows):
    conn = ms.connect()
    conn.executemany("INSERT INTO gateway_requests (at, alias, lane, served, purpose, total_s) VALUES (?,?,?,?,?,?)",
                     rows)
    conn.commit()
    return conn


def _long():
    return _plant([(T, "sohot-code", "code", "openai/" + MODEL, "work", LONG)])


def test_a_long_request_s_span_starts_at_at_and_ends_its_duration_later():
    assert usage.span(T, LONG) == (T, T + LONG)
    assert usage.span(T, None) == (T, T)
    conn = _long()
    try:
        assert idle_unload.uses(conn, T - 60) == {MODEL: [(T, T + LONG)]}
    finally:
        conn.close()


def test_the_idle_gap_before_a_long_request_is_read_from_its_start():
    conn = _plant([(T - 1000, "sohot-code", "code", MODEL, "work", 0.0),
                   (T, "sohot-code", "code", MODEL, "work", 3000.0)])
    try:
        spans = idle_unload.uses(conn, T - 2000)[MODEL]
    finally:
        conn.close()
    assert idle_unload.cost(spans, 900, 1) == {"loads_per_day": 2.0, "idle_h_per_day": round(1800 / 3600, 2)}


def test_every_reader_of_a_request_span_gives_one_answer():
    conn = _plant([(T + 300, "sohot-code", "code", "openai/" + MODEL, "work", 10.0),
                   (T, "sohot-code", "code", "openai/" + MODEL, "work", LONG)])
    try:
        assert idle_unload.uses(conn, T - 60)[MODEL] == [(T, T + LONG), (T + 300, T + 310)]
        got, _ = residency_trace.requests(conn, T - 60, NOW)
        assert [(s, e) for s, e, m, _ in got if m == MODEL] == [(T, T + LONG), (T + 300, T + 310)]
        assert ("sohot-code", T + LONG) in contention.requests(conn, T + LONG - 1)
        assert interactive.demand(conn, "code", set(), now=NOW)["peak"] == 2
        ms.remember_machine(conn)
        conn.commit()
    finally:
        conn.close()
    ro = ledger.open_ro(ms.db_path())
    try:
        spans = [(b, e) for b, e, _ in inventory_time.gather(ro, paths.home(), NOW, since=T - 60)["intervals"]]
    finally:
        ro.close()
    assert (T, T + LONG) in spans and (T + 300, T + 310) in spans


def test_no_module_but_usage_works_out_a_request_span_itself():
    own = re.compile(r"usage\.(span|ENDED_SQL)\b")
    loose = []
    for p in sorted((ROOT / "harness").rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        text = p.read_text(encoding="utf-8")
        if rel in ("harness/usage.py", "harness/memory_store/schema.py") or "gateway_requests" not in text:
            continue
        if "total_s" in text and not own.search(text):
            loose.append(rel)
    assert loose == []

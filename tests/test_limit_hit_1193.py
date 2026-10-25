"""Every recorded limit is built through knobs.hit, so its name is a knob's limit in the unit it was written in (#1193)."""
import pytest

from harness import contamination, knobs, limit_trace, yield_stop
from harness.memory_store import revisit

#: Hand-built limits waiting on another issue; this may only shrink.
AWAITING: dict[str, str] = {}
#: Hand-built limits in code that cannot import harness.knobs; their reader checks them.
OUTSIDE = {"harness/hf_task.py": "runs in the hf-task venv; ProcessRunner reads its limit through knobs.limit_read",
           "harness/knobs/__init__.py": "limit_text is the one place a limit body is formatted",
           "harness/memory_store/migrations/prose.py": "a migration rewrites stored prose in the forms of its day"}


def _hand(src: str) -> list[str]:
    return limit_trace.hand_built_in(src, "harness/x.py")


@pytest.mark.parametrize("src", [
    'x = f"code_check_timeout_s>{timeout:g}"',
    'x = f"{name}>{timeout:g}"',
    'x = f"{exc.limit[0]}>{exc.limit[1]:g}"',
    'x = f"limit:download_gib>{cap / GIB:g}"',
    'x = f"limit:{name}.{lane}>{want}"',
    'x = f"limit {LIMIT}>{n}: cut"',
    'exc.limit = ("served_ctx", ctx)',
    'exc.limit = ("not_a_knob", n) if n else ()',
    'raise CompletionError("stopped", "x", ("yield_stop", n))',
    'f(limit=("anything", n))',
    'pair = ("timeout_s", t)',
])
def test_the_scan_finds_each_way_a_limit_is_built_by_hand(src):
    assert _hand(src) == ["harness/x.py:1"]


@pytest.mark.parametrize("src", [
    'x = knobs.limit("code_check_timeout_s", timeout, "s")',
    'x = f"limit:{knobs.limit(name, v, unit)}"',
    'x = f"<span class=tag good>{why}</span>"',
    'x = f"cases:{lane}>{n}"',
    'x = f"version:{runtime}>{have}"',
    'x = f"{a} > {b}"',
    'x = ("max_tokens", "budget")',
    'x = ("served_ctx", ctx, 3)',
    'exc.failure_class, exc.limit = cut(x)',
])
def test_the_scan_leaves_alone_what_is_no_hand_built_limit(src):
    assert _hand(src) == []


def test_no_production_code_builds_a_limit_by_hand():
    found = limit_trace.hand_built()
    allowed = {**AWAITING, **OUTSIDE}
    stray = [w for w in found if w.split(":")[0] not in allowed]
    assert not stray, f"build these through knobs.hit / knobs.limit / knobs.limit_text: {stray}"
    stale = sorted(rel for rel in AWAITING if not any(w.startswith(rel + ":") for w in found))
    assert not stale, f"no longer hand-built; drop from AWAITING: {stale}"


def test_every_literal_limit_call_names_a_knob_in_the_unit_it_writes():
    calls = limit_trace.unit_calls()
    assert len(calls) > 40, "the scan should see the converted producers"
    units = knobs.limit_units()
    wrong = [(name, unit, where) for name, unit, where in calls if units.get(name) != unit]
    assert not wrong, f"limit names in no knob or in another unit: {wrong}"


def test_a_lane_scoped_limit_is_registered_for_every_lane_it_is_written_for():
    for lane in knobs.TEXT_LANES:
        assert knobs.limit(f"max_tokens.{lane}", 4000, "tokens") == f"max_tokens.{lane}>4000"
    with pytest.raises(ValueError, match="no knob"):
        knobs.limit("max_tokens.nolane", 4000, "tokens")


def test_a_limit_prints_an_int_exactly_and_a_float_shortest():
    assert knobs.limit("served_ctx", 1048576, "tokens") == "served_ctx>1048576"
    assert knobs.limit("timeout_s", 180.0, "s") == "timeout_s>180"
    assert knobs.limit("tts_budget_s", 8.04, "s") == "tts_budget_s>8.04"
    assert knobs.limit_text(("served_ctx", 1048576)) == "served_ctx>1048576"
    assert knobs.limit_text(()) == ""


def test_a_limit_another_process_wrote_is_checked_where_it_is_read():
    assert knobs.limit_read("hf_max_new_tokens>512", "tokens") == "hf_max_new_tokens>512"
    assert knobs.limit_read("", "tokens") == ""
    with pytest.raises(ValueError):
        knobs.limit_read("hf_max_new_tokens>512", "s")
    with pytest.raises(ValueError):
        knobs.limit_read("made_up>3", "tokens")


def test_the_yield_stop_and_contamination_limits_name_their_knobs():
    assert knobs.limit_units()["yield_stop"] == "tokens"
    assert knobs.KNOBS["yield_stop_ratio"].limit == "yield_stop"
    assert knobs.limit_units()["contamination_max_tokens"] == "tokens"
    assert knobs.limits()["contamination_max_tokens"] == contamination.MAX_TOKENS
    assert contamination.Cut("empty", 1024).limit == "contamination_max_tokens>1024"


def test_a_yield_stop_has_no_single_value_so_no_until_on_it_is_met_by_the_ratio():
    assert knobs.limits().get("yield_stop") is None
    assert not revisit.until_met("limit:yield_stop>1348", {"limits": knobs.limits()})
    got = yield_stop.rescore([{"passed": True, "seconds": 1.0, "metrics": {"completion_tokens": 2000}}], 1348)
    assert got["rows"][0]["limit"] == "yield_stop>1348"

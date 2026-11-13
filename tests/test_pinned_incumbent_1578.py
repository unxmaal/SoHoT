"""A paired eval's incumbent pinned on the interactive server is answered there; only the challenger loads. #1578."""
import argparse
import json
from pathlib import Path

import pytest

from evals import run as R
from harness import context, identity, interactive, router, serving
from harness import memory_store as ms
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd
from tests.test_context import LLAMA, ORNITH, write_gguf
from tests.test_interleave_816 import Named
from tests.test_pause_813 import _args, clock, quiet  # noqa: F401
from tests.test_resume_813 import Eval, _rows, _sweep

GIB = 1024 ** 3
STEM = context.ORNITH_STEM
INC = f"llamacpp:{STEM}"
CH_STEM = "Chal-27B-Q4_K_M"
CH = f"llamacpp:{CH_STEM}"
#: Job 1616's refusal of the incumbent on the eval router, after #1651.
INC_WHY = ("refused: 20.2 GiB of weights over the 10.8 GiB budget, 33.0 GiB of the machine held by the "
           "interactive server's pinned models, 16.0 GiB by the co-resident MLX model")


def _pin(url=None, lanes=None):
    interactive.write({"url": url or interactive.url(), "budget_bytes": 35 * GIB, "bytes": 33 * GIB,
                       "lanes": lanes or {"code": {"stem": STEM, "ctx": 55296, "slots": 2, "bytes": int(21.2 * GIB),
                                                   "served": INC},
                                          "decide": {"stem": "imajev-4b-Q8_0", "ctx": 61440, "slots": 4,
                                                     "bytes": int(5.1 * GIB), "served": "llamacpp:imajev-4b-Q8_0"}},
                       "skipped": {}})


@pytest.fixture
def world(monkeypatch, tmp_path):
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    monkeypatch.setattr("harness.adopt.default_for", lambda lane, fallback, conn=None: INC)
    monkeypatch.setattr(loop_cmd.repo_gate, "args_for", lambda a, row: a)
    monkeypatch.setattr(loop_cmd, "_gated", lambda row, want: "")
    conn = real(tmp_path / "d.db")
    ms.record(conn, ms.Seen(name=CH, source="t", lane="code", resolved=CH))
    ms.decide(conn, CH, "screened", tier=ms.SCREEN, reason="candidate")
    conn.close()
    return lambda: real(tmp_path / "d.db")


def _refuse(monkeypatch, why: dict):
    monkeypatch.setattr(context, "refusal", lambda s, conn=None: why.get(s, ""))


def _ns():
    return argparse.Namespace(lane="", repeat=1, effect=0.4, power_budget_min=60.0)


# --- routing ---------------------------------------------------------------------

def test_inside_a_paired_run_the_pinned_incumbent_goes_to_the_interactive_server_and_the_challenger_to_the_router(
        monkeypatch):
    _pin()
    _refuse(monkeypatch, {STEM: INC_WHY})
    with pytest.raises(ValueError, match="is not served"):
        serving.route(INC)
    with interactive.answer([INC, CH]) as got:
        assert got == {STEM: interactive.url()}
        assert serving.route(INC).base == interactive.url() and serving.route(INC).model == STEM
        assert serving.route(CH).base == router.url()
        assert context._upstream(INC) == (interactive.url(), STEM)
        assert serving.engine_at(interactive.url()) == serving.LLAMACPP
    assert interactive.answering(STEM) == "", "the routing ends with the run"


def test_a_pinned_set_on_another_machine_answers_nothing_here(monkeypatch):
    _pin(url="http://198.51.100.7:8083")
    _refuse(monkeypatch, {STEM: INC_WHY})
    with interactive.answer() as got:
        assert got == {}
        with pytest.raises(ValueError, match="is not served"):
            serving.route(INC)


def test_the_pinned_arm_is_served_at_the_interactive_pool_and_identified_by_its_preset(monkeypatch, tmp_path):
    _pin()
    preset = interactive.preset_path()
    preset.write_text(f"[{STEM}]\nc = 55296\nparallel = 2\n", encoding="utf-8")
    monkeypatch.setattr(identity, "llama_server", lambda: str(tmp_path / "llama-server"))
    monkeypatch.setattr(identity, "runtime_files", lambda exe: [])
    monkeypatch.setattr("harness.gguf.models_dir", lambda: tmp_path)
    (tmp_path / f"{STEM}.gguf").write_bytes(b"x")
    with interactive.answer([INC]):
        assert context.served_ctx(INC) == 55296
        got = identity.served(INC)
    assert got["server"] == "interactive" and got["preset"] == {STEM: ["c = 55296", "parallel = 2"]}
    assert "server" not in identity.served(INC)


# --- the measure step ----------------------------------------------------------------

def test_a_paired_code_measure_with_its_incumbent_pinned_launches_and_loads_only_the_challenger(
        monkeypatch, world, tmp_path):
    """Job 1616: the incumbent refused on the eval router no longer stops the pair when the interactive server pins it."""
    monkeypatch.setattr(measure_cmd.paths, "home", lambda: tmp_path)
    _pin()
    _refuse(monkeypatch, {STEM: INC_WHY})
    fake = Eval(rows=_rows(5))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    sweep, failed = _sweep(), []
    loaded = []
    monkeypatch.setattr(router, "release_spec", lambda spec, why, **kw: loaded.append(spec) or [])
    assert loop_cmd._measure_all(_ns(), [{"name": CH, "lane": "code"}], sweep, failed) == 0
    assert failed == [] and len(fake.argvs) == 1
    argv = fake.argvs[0]
    assert "--pinned-arms" in argv and argv[argv.index("--candidates") + 1] == f"{INC},{CH}"
    assert not any("plan:" in line for line in sweep.lines)
    assert loaded == [CH], "the router is asked to drop only the challenger it loaded"


def test_without_a_pinned_copy_the_refused_incumbent_is_still_a_limit(monkeypatch, world, tmp_path):
    monkeypatch.setattr(measure_cmd.paths, "home", lambda: tmp_path)
    _refuse(monkeypatch, {STEM: INC_WHY})
    fake = Eval(rows=_rows(5))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    sweep = _sweep()
    assert loop_cmd._measure_all(_ns(), [{"name": CH, "lane": "code"}], sweep, []) == 0
    assert fake.argvs == [] and any(f"plan:{STEM}" in line for line in sweep.lines)


def _plan_rows(tmp_path, monkeypatch, weights: dict, models_max=1):
    rows = []
    for i, (stem, size) in enumerate(weights.items()):
        path = tmp_path / f"{stem}.gguf"
        write_gguf(path, ORNITH if stem == STEM else LLAMA)
        rows.append({"path": str(path), "id": i})
    monkeypatch.setattr(context, "router_rows", lambda conn: rows)
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 16 * GIB)
    monkeypatch.setattr(context, "_weights", lambda p: weights[Path(p).stem])
    return {p["stem"]: p for p in context.plan(None, budget=int(59.8 * GIB), kv_cap=64 * GIB,
                                               models_max=models_max, record=False)}


def test_a_challenger_over_the_room_the_pinned_set_leaves_is_a_limit_naming_the_numbers(monkeypatch, world, tmp_path):
    monkeypatch.setattr(measure_cmd.paths, "home", lambda: tmp_path)
    _pin()
    got = _plan_rows(tmp_path, monkeypatch, {STEM: int(20.2 * GIB), CH_STEM: int(17.0 * GIB)})
    why = got[CH_STEM]["why"]
    assert got[CH_STEM]["ctx"] == 0
    assert why.startswith("refused: 17.0 GiB of weights over the 10.8 GiB budget"), why
    assert "33.0 GiB of the machine held by the interactive server's pinned models" in why
    assert "16.0 GiB by the co-resident MLX model" in why
    _refuse(monkeypatch, {s: p["why"] for s, p in got.items() if not p["ctx"]})
    fake = Eval(rows=_rows(5))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    sweep, failed = _sweep(), []
    assert loop_cmd._measure_all(_ns(), [{"name": CH, "lane": "code"}], sweep, failed) == 0
    assert fake.argvs == [] and failed == []
    conn = world()
    try:
        v = dict(conn.execute("SELECT v.outcome, v.reason, v.until, v.failure_class, v.detail FROM proposals p "
                              "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (CH,)).fetchone())
    finally:
        conn.close()
    assert (v["outcome"], v["reason"], v["until"], v["failure_class"]) == (
        "declined", "limit", f"plan:{CH_STEM}", "plan_refused")
    assert "17.0 GiB of weights over the 10.8 GiB budget" in v["detail"]
    said = [line for line in sweep.lines if CH in line]
    assert said and "10.8 GiB budget" in said[0] and "33.0 GiB" in said[0]


def test_a_stem_too_big_to_load_here_reserves_no_share_of_the_router(monkeypatch, tmp_path):
    """Two residents share what the heaviest two leave; the pinned Ornith, refused alone, is never one of them."""
    _pin()
    got = _plan_rows(tmp_path, monkeypatch, {STEM: int(20.2 * GIB), "a-3B": 3 * GIB, "b-3B": 3 * GIB}, models_max=2)
    assert got[STEM]["ctx"] == 0
    assert got["a-3B"]["ctx"] and "2 resident share 4915 MiB of KV" in got["a-3B"]["why"], got["a-3B"]["why"]


# --- the eval run ----------------------------------------------------------------------

def test_a_pinned_paired_run_flags_the_incumbent_rows_co_tenant_and_records_it_on_the_receipt(
        monkeypatch, tmp_path, quiet, clock):  # noqa: F811
    _pin()
    _refuse(monkeypatch, {STEM: INC_WHY})
    log, seen = [], {}
    runners = {INC: Named(INC, clock, log), CH: Named(CH, clock, log)}

    def build(candidate, gateway, *a, **k):
        seen[candidate] = serving.route(candidate, gateway).base
        return runners[candidate]
    monkeypatch.setattr(R, "build_runner", build)
    monkeypatch.setattr(R, "pair_block", lambda candidates, gateway: 1)
    out = tmp_path / "run"
    assert R._execute(_args(out, candidates=f"{INC},{CH}", gateway="", pinned_arms=True)) == 0
    assert seen == {INC: interactive.url(), CH: router.url()}
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    rows = data["rows"]
    flagged = {r["candidate"] for r in rows if (r.get("metrics") or {}).get("co_tenant")}
    assert flagged == {INC} and all(any("contended" in w for w in r["warnings"])
                                    for r in rows if r["candidate"] == INC)
    shared = data["receipt"]["co_tenancy"]
    assert set(shared) == {INC}
    assert shared[INC]["server"] == interactive.url() and shared[INC]["lanes"] == ["code"]
    assert shared[INC]["pinned"] == {"code": STEM, "decide": "imajev-4b-Q8_0"}


def test_without_the_flag_nothing_is_routed_to_the_interactive_server(monkeypatch, tmp_path, quiet, clock):  # noqa: F811
    _pin()
    _refuse(monkeypatch, {STEM: INC_WHY})
    monkeypatch.setattr(R, "build_runner", lambda c, g, *a, **k: serving.route(c, g))
    with pytest.raises(ValueError, match="is not served"):
        R._execute(_args(tmp_path / "run", candidates=f"{INC},{CH}", gateway=""))


def test_a_screen_refuses_the_flag(tmp_path):
    with pytest.raises(SystemExit, match="paired run"):
        with R.pinned_arms(argparse.Namespace(pinned_arms=True, screen=True, candidates=INC)):
            pass

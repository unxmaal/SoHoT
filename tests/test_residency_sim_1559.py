"""`soh residency-sim`: planted traces with known optima rank the policies, a one-model trace makes them equal, the store is only read. #1559."""
import hashlib
import json
import time

import pytest

from harness import cli, paths, residency, residency_trace
from harness import memory_store as ms
from harness.residency import BATCH, BELADY, GDS, INTERACTIVE, JOB, LRU, PINNED, POLICIES, Req


def _cycle(models, rounds, gap=100.0, length=1.0, kind=INTERACTIVE):
    out, t = [], 0.0
    for _ in range(rounds):
        for m in models:
            out.append(Req(t, t + length, m, kind))
            t += gap
    return out


def test_a_cyclic_trace_over_capacity_ranks_belady_over_gds_over_lru():
    reqs = _cycle("ABC", 3)
    got = residency.compare(reqs, {m: 10.0 for m in "ABC"}, {m: 10.0 for m in "ABC"}, 20.0)
    # Two of three fit: LRU always evicts the next one asked for; farthest-next-use keeps every other.
    assert (got[LRU]["hits"], got[LRU]["loads"], got[LRU]["load_s"]) == (0, 9, 90.0)
    assert (got[BELADY]["hits"], got[BELADY]["loads"], got[BELADY]["load_s"]) == (3, 6, 60.0)
    assert got[BELADY]["hits"] >= got[GDS]["hits"] >= got[LRU]["hits"]
    assert got[LRU]["interactive"] == {"n": 9, "p50_s": 10.0, "p95_s": 10.0, "max_s": 10.0}
    assert got[LRU]["hit_rate"] == 0.0 and got[BELADY]["hit_rate"] == round(3 / 9, 4)


def test_a_costly_large_model_is_kept_by_gds_while_belady_bounds_only_the_load_count():
    reqs = _cycle(["big", "s1", "s2"], 3)
    sizes = {"big": 8.0, "s1": 2.0, "s2": 2.0}
    loads = {"big": 100.0, "s1": 2.0, "s2": 2.0}
    got = residency.compare(reqs, sizes, loads, 10.0)
    assert (got[LRU]["loads"], got[LRU]["load_s"]) == (9, 312.0)
    assert (got[GDS]["loads"], got[GDS]["load_s"]) == (7, 112.0)
    # Farthest next use minimises loads, not load seconds: it evicts big at 400 because s1 and s2 come sooner.
    assert (got[BELADY]["loads"], got[BELADY]["load_s"]) == (6, 208.0)
    assert got[BELADY]["loads"] <= got[GDS]["loads"] <= got[LRU]["loads"]
    assert got[GDS]["load_s"] < got[BELADY]["load_s"] < got[LRU]["load_s"]


def test_a_request_during_a_load_waits_what_is_left_of_it_exactly():
    reqs = [Req(0.0, 1.0, "a"), Req(10.0, 11.0, "a"), Req(40.0, 41.0, "a")]
    got = residency.simulate(reqs, {"a": 1.0}, {"a": 30.0}, 10.0, LRU)
    assert got["interactive"] == {"n": 3, "p50_s": 20.0, "p95_s": 30.0, "max_s": 30.0}
    assert (got["hits"], got["loads"]) == (1, 1)


def test_a_pinned_interactive_model_survives_a_batch_flood_that_lru_evicts_it_for():
    reqs = [Req(0.0, 1.0, "p"), Req(100.0, 101.0, "x", BATCH), Req(200.0, 201.0, "y", BATCH), Req(300.0, 301.0, "p")]
    sizes = {"p": 4.0, "x": 4.0, "y": 4.0}
    loads = {"p": 50.0, "x": 1.0, "y": 1.0}
    lru = residency.simulate(reqs, sizes, loads, 8.0, LRU, pins=["p"])
    pin = residency.simulate(reqs, sizes, loads, 8.0, PINNED, pins=["p"])
    assert lru["interactive"] == {"n": 2, "p50_s": 50.0, "p95_s": 50.0, "max_s": 50.0}
    assert pin["interactive"] == {"n": 2, "p50_s": 0.0, "p95_s": 50.0, "max_s": 50.0}
    assert lru["batch"] == pin["batch"] == {"cases": 2, "loads": 2, "load_s": 2.0, "load_s_per_case": 1.0}


def test_two_busy_models_over_the_budget_are_a_swap_risk_moment_until_the_trace_ends():
    reqs = [Req(0.0, 100.0, "a"), Req(10.0, 20.0, "b")]
    got = residency.simulate(reqs, {"a": 6.0, "b": 6.0}, {"a": 0.0, "b": 0.0}, 10.0, LRU)
    assert got["over_budget"] == {"moments": 1, "seconds": 90.0, "peak_gb": 12.0}
    idle = residency.simulate([Req(0.0, 1.0, "a"), Req(10.0, 20.0, "b")], {"a": 6.0, "b": 6.0},
                              {"a": 0.0, "b": 0.0}, 10.0, LRU)
    assert idle["over_budget"] == {"moments": 0, "seconds": 0.0, "peak_gb": 0.0} and idle["evictions"] == 1


def test_a_job_hold_keeps_its_model_resident_and_its_load_is_batch():
    reqs = [Req(0.0, 500.0, "a", JOB), Req(10.0, 11.0, "b"), Req(20.0, 21.0, "a", BATCH)]
    got = residency.simulate(reqs, {"a": 6.0, "b": 6.0}, {"a": 5.0, "b": 3.0}, 10.0, LRU)
    assert got["requests"] == 2 and got["hits"] == 1
    assert got["batch"] == {"cases": 1, "loads": 1, "load_s": 5.0, "load_s_per_case": 5.0}
    assert got["over_budget"]["moments"] == 1


def test_one_model_makes_every_policy_equal():
    reqs = _cycle(["only"], 12, gap=37.0, length=5.0) + [Req(5.0, 300.0, "only", JOB)] + \
        _cycle(["only"], 5, gap=61.0, length=2.0, kind=BATCH)
    got = residency.compare(reqs, {"only": 40.0}, {"only": 12.0}, 50.0, pins=["only"])
    base = {k: v for k, v in got[LRU].items() if k != "policy"}
    assert base["loads"] == 1 and base["requests"] == 17
    for p in POLICIES:
        assert {k: v for k, v in got[p].items() if k != "policy"} == base, p


def test_an_unknown_policy_is_refused():
    with pytest.raises(ValueError, match="unknown policy"):
        residency.simulate([], {}, {}, 1.0, "fifo")


def test_the_size_fit_is_least_squares_through_the_origin_with_its_leave_one_out_error():
    got = residency.fit_rate({"a": 2.0, "b": 4.0, "c": 4.0}, {"a": 1.0, "b": 2.0, "c": 1.0})
    assert got == {"s_per_gb": round(14 / 6, 4), "models": 3, "error_s": 2.0, "fallback": False}
    assert residency.fit_rate({}, {"a": 1.0})["fallback"] is True


def test_a_spec_resolves_to_the_model_it_serves():
    alias = {"q3-4b": "mlx-community/Qwen3-4B-Instruct-2507-4bit"}
    assert residency_trace.model_of("llamacpp:Stem-Q4", alias) == "Stem-Q4"
    assert residency_trace.model_of("q3-4b", alias) == "mlx-community/Qwen3-4B-Instruct-2507-4bit"
    assert residency_trace.model_of("mlx-community/X-4bit", alias) == "mlx-community/X-4bit"
    assert residency_trace.model_of("mflux:dev", alias) == ""


NOW = time.time()
T0 = NOW - 86400
MLX = "mlx-community/Tiny-4bit"


def _req(conn, at, served, purpose, total=1.0, error=""):
    conn.execute("INSERT INTO gateway_requests (at, served, purpose, total_s, error_class) VALUES (?,?,?,?,?)",
                 (at, served, purpose, total, error))


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = paths.home()
    mlx = tmp_path / "hub" / "models--mlx-community--Tiny-4bit"
    mlx.mkdir(parents=True)
    (mlx / "config.json").write_text(json.dumps({"num_hidden_layers": 2, "num_attention_heads": 4,
                                                 "num_key_value_heads": 2, "head_dim": 8}), encoding="utf-8")
    conn = ms.connect()
    conn.execute("INSERT INTO downloads (repo, kind, path, file, bytes, ctx, kv_bytes_token) "
                 "VALUES ('o/Stem-GGUF', 'gguf', ?, 'Stem-Q4.gguf', 2000000000, 1000, 1000000)",
                 (str(tmp_path / "Stem-Q4.gguf"),))
    conn.execute("INSERT INTO downloads (repo, kind, path, bytes) VALUES (?, 'hub', ?, 1000000000)", (MLX, str(mlx)))
    _req(conn, T0, "openai/Stem-Q4", "work")
    _req(conn, T0 + 10, "openai/Stem-Q4", "eval")
    _req(conn, T0 + 20, "openai/Stem-Q4", "watchdog")
    _req(conn, T0 + 30, "openai/Stem-Q4", "work", error="NotFoundError")
    _req(conn, T0 + 40, "anthropic/claude-opus-5-5", "work")
    _req(conn, T0 + 50, f"openai/{MLX}", "unknown")
    _req(conn, T0 + 60, "openai/Unsized-Model", "work")
    argv = ["uv", "run", "python", "-m", "evals.run", "--candidates", "llamacpp:Stem-Q4,enable_thinking=true,q3-4b,mflux:dev"]
    # _claim stamps the machine that ran a job; the trace replays this machine's jobs only. #1771.
    conn.execute("INSERT INTO jobs (argv, state, created_at, started_at, finished_at, machine_id) "
                 "VALUES (?, 'done', ?, ?, ?, ?)", (json.dumps(argv), T0 + 100, T0 + 100, T0 + 200,
                                                     ms.remember_machine(conn)))
    conn.commit()
    conn.close()
    logs = paths.logs()
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "eval.log").write_text(
        "srv  spawning server instance with name=Stem-Q4 on port 5001\n"
        "[5001] 00.04.000.000 I srv  llama_server: model loaded\n"
        "srv  spawning server instance with name=Stem-Q4 on port 5002\n"
        "[5002] 00.06.000.000 I srv  llama_server: model loaded\n", encoding="utf-8")
    monkeypatch.setattr(residency_trace, "aliases", lambda config=None: {"q3-4b": MLX})
    return h


def _snapshot(home):
    # A mode=ro open of a WAL store leaves -shm and an empty -wal behind (#1152); the store itself must not move.
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in home.iterdir()
            if p.is_file() and not p.name.endswith(("-shm", "-wal"))}


def test_the_command_reads_the_store_and_router_log_and_writes_nothing(home, capsys):
    before = _snapshot(home)
    assert cli.main(["residency-sim", "--json", "--since", "2d", "--budget-gb", "100", "--pin", "Stem-Q4"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["requests"] == 3 and out["jobs"] == 2
    assert out["left_out"] == {"skipped_purpose": 1, "failed": 1, "hosted": 1}
    assert out["unsized"] == {"Unsized-Model": 1}
    stem, mlx = out["models"]["Stem-Q4"], out["models"][MLX]
    assert (stem["weights_gb"], stem["gb"], stem["source"]) == (2.0, 3.0, "router plan")
    assert (stem["load_s"], stem["load_source"]) == (5.0, "router log, median of 2")
    assert (mlx["weights_gb"], mlx["gb"], mlx["source"]) == (1.0, 1.004, "file + 1 request KV")
    assert (mlx["load_s"], mlx["load_source"]) == (2.5, "size fit")
    assert out["fit"] == {"s_per_gb": 2.5, "models": 1, "error_s": None, "fallback": False}
    assert set(out["policies"]) == set(POLICIES) and out["pins"] == ["Stem-Q4"]
    assert out["policies"][LRU]["loads"] == 2 and out["policies"][LRU]["batch"]["cases"] == 1
    assert _snapshot(home) == before
    wal = ms.db_path().with_name("discovery.db-wal")
    assert not wal.exists() or wal.stat().st_size == 0


def test_no_jobs_leaves_the_holds_out(home, capsys):
    assert cli.main(["residency-sim", "--json", "--since", "2d", "--budget-gb", "100", "--no-jobs"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["jobs"] == 0 and out["requests"] == 3


def test_the_pinned_lanes_resolve_through_the_lane_defaults(monkeypatch):
    from harness import adopt
    monkeypatch.setattr(adopt, "lane_defaults", lambda conn=None: {"decide": "llamacpp:D", "extract": "q3-4b",
                                                                   "code": "llamacpp:C", "svg": "llamacpp:S"})
    assert residency_trace.pins(None, alias={"q3-4b": MLX}) == (["C", "D", MLX], "")

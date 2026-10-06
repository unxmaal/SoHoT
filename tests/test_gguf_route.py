"""A GGUF-only text candidate reaches llama-server. #295."""
import re
from pathlib import Path

import pytest

from harness import downloads, fetching, gguf, screen, serving
from harness import inspect as ins
from harness import memory as mem
from harness import memory_store as ms

REPO = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


def sib(name, gib):
    return {"rfilename": name, "size": int(gib * GIB)}


SIBLINGS = [
    sib("README.md", 0.0001),
    sib("Model-4B-Q8_0.gguf", 4.3),
    sib("Model-4B-Q4_K_M.gguf", 2.5),
    sib("Model-4B-F16.gguf", 8.0),
    sib("mmproj-Model-4B-F16.gguf", 0.8),
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path / "lh"))
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(tmp_path / "gguf"))
    (tmp_path / "gguf").mkdir()
    return tmp_path


# --- choosing one file ------------------------------------------------------

def test_q4_k_m_is_preferred():
    assert gguf.choose(SIBLINGS, 22 * GIB) == ("Model-4B-Q4_K_M.gguf",
                                               int(2.5 * GIB))


def test_the_ceiling_moves_the_choice_to_a_quant_that_fits():
    big = [sib("M-Q4_K_M.gguf", 30), sib("M-IQ3_XS.gguf", 18),
           sib("M-Q2_K.gguf", 12)]
    assert gguf.choose(big, 22 * GIB)[0] == "M-IQ3_XS.gguf"


def test_nothing_that_fits_is_none():
    assert gguf.choose([sib("M-Q4_K_M.gguf", 30)], 22 * GIB) is None


@pytest.mark.parametrize("name", [
    "mmproj-M-F16.gguf",
    "M-Q4_K_M-00001-of-00002.gguf",
    "Q4_K_M/M-Q4_K_M.gguf",
    "M-Q4_K_M.safetensors",
])
def test_files_the_router_cannot_serve_alone_are_never_chosen(name):
    assert gguf.choose([sib(name, 2)], 22 * GIB) is None


def test_a_repo_with_safetensors_is_not_gguf_only():
    both = SIBLINGS + [sib("model.safetensors", 8)]
    assert gguf.only(SIBLINGS)
    assert not gguf.only(both)
    assert not gguf.only([sib("model.safetensors", 8)])


# --- inspect sizes the file, not the repo ----------------------------------

def test_inspect_sizes_a_gguf_repo_by_the_file_it_would_fetch():
    """Summing every quant called a 2.5 GiB model 15.6 GiB."""
    import dataclasses
    from harness import machine
    here = dataclasses.replace(machine.detect(),
                               runtimes=frozenset({"cpu", "llamacpp", "mlx"}))
    fit = ins.inspect_model("org/Model-4B-GGUF", ceiling=22 * GIB, machine=here,
                            data={"siblings": SIBLINGS, "tags": ["gguf"]})
    assert fit.verdict == "fits", fit.why
    assert fit.largest == int(2.5 * GIB)


def test_inspect_still_sums_a_safetensors_repo():
    fit = ins.inspect_model("org/M", ceiling=22 * GIB,
                            data={"siblings": [sib("a.safetensors", 2),
                                               sib("b.safetensors", 3)]})
    assert fit.largest == 5 * GIB


# --- fetch downloads one file ----------------------------------------------

def test_fetch_downloads_one_gguf_file_and_records_it(home, monkeypatch):
    db = ms.connect(home / "d.db")
    ms.record(db, ms.Seen(name="org/Model-4B-GGUF", source="t",
                          resolved="org/Model-4B-GGUF", kind="weights",
                          lane="code"))
    ms.set_size(db, "org/Model-4B-GGUF", int(2.5 * GIB))
    ms.decide(db, "org/Model-4B-GGUF", "queued", tier="inspect",
              size_bytes=int(2.5 * GIB))
    monkeypatch.setattr(fetching.rank, "unrunnable", lambda row, m=None: "")
    got = []

    def hf_download(repo, filename, local_dir):
        got.append((repo, filename))
        (Path(local_dir) / filename).write_bytes(b"GGUF")
        return str(Path(local_dir) / filename)

    def snapshot(**kw):
        raise AssertionError("a whole snapshot was downloaded")

    done = fetching.run(db, snapshot=snapshot, free=900 * GIB,
                        listing=lambda repo: SIBLINGS, hf_download=hf_download)
    assert done[0]["ok"], done
    assert got == [("org/Model-4B-GGUF", "Model-4B-Q4_K_M.gguf")]
    assert gguf.fetched("org/Model-4B-GGUF", db) == "Model-4B-Q4_K_M"
    assert fetching.have("org/Model-4B-GGUF", db)
    row = db.execute("SELECT * FROM downloads").fetchone()
    assert (row["kind"], row["file"], row["origin"], row["complete"]) == (
        "gguf", "Model-4B-Q4_K_M.gguf", "fetch", 1)
    db.close()


def _gguf(home, repo, name, data=b"GGUF"):
    (home / "gguf" / name).write_bytes(data)
    conn = ms.connect()
    try:
        return downloads.record(conn, repo, downloads.GGUF,
                                home / "gguf" / name, file=name)
    finally:
        conn.close()


def test_a_recorded_file_that_is_gone_is_not_fetched(home):
    _gguf(home, "org/M", "M-Q4_K_M.gguf")
    assert gguf.fetched("org/M") == "M-Q4_K_M"
    (home / "gguf" / "M-Q4_K_M.gguf").unlink()
    assert gguf.fetched("org/M") is None
    assert not fetching.have("org/M")


def test_a_file_on_disk_with_no_row_is_not_fetched(home):
    """The negative control: the directory alone is not the record. #411."""
    (home / "gguf" / "M-Q4_K_M.gguf").write_bytes(b"GGUF")
    assert gguf.fetched("org/M") is None


# --- screen and measure spell it for llama-server --------------------------

def test_a_fetched_gguf_is_spelled_for_llama_server(home):
    _gguf(home, "org/M-GGUF", "M-Q4_K_M.gguf")
    assert screen.candidate_for("code", "org/M-GGUF") == "llamacpp:M-Q4_K_M"
    assert screen.candidate_for("code", "org/other") == "org/other"
    assert screen.candidate_for("code", "llamacpp:M-Q4_K_M") == (
        "llamacpp:M-Q4_K_M")
    assert screen.routed_gateway("org/M-GGUF") == ""
    argv = screen.argv({"name": "org/M-GGUF", "modality": "code",
                        "candidate": "llamacpp:M-Q4_K_M"})
    assert "--gateway" not in argv


def test_the_receipt_key_of_a_llamacpp_run_is_found():
    summary = {"llamacpp:M-Q4_K_M": {"passed": 1}}
    assert screen.row_for(summary, "llamacpp:M-Q4_K_M") == {"passed": 1}
    assert screen.row_for(summary, "llamacpp:Other") is None


def test_the_headroom_guard_sizes_a_fetched_gguf(home):
    _gguf(home, "org/M-GGUF", "M-Q4_K_M.gguf", b"x" * 4096)
    assert mem.cache_path("org/M-GGUF") == str(home / "gguf" / "M-Q4_K_M.gguf")
    assert mem.size_gb(mem.cache_path("org/M-GGUF")) is not None


# --- the run labels each engine --------------------------------------------

def test_a_llamacpp_spec_runs_against_llama_server():
    from evals import run
    assert run.kind_of("llamacpp:M-Q4_K_M") == "llamacpp"
    r = run.build_runner("llamacpp:M-Q4_K_M,temperature=0", "http://gw", None)
    assert r.candidate == "llamacpp:M-Q4_K_M"
    assert r.model == "M-Q4_K_M"
    assert r.gateway == serving.LLAMACPP_URL
    assert r.sampling == {"temperature": 0.0}


def test_each_candidate_is_labelled_with_its_engine():
    assert serving.engine_for("llamacpp:M") == "llama-server"
    assert serving.engine_for("eval-4b") == "llama-server"
    assert serving.engine_for("q3-4b") == serving.DEFAULT
    assert serving.engine_for("q3-4b", {"TEXT_ENGINE": "x"}) == "x"


def test_a_mixed_run_names_both_engines():
    from evals import run
    got = run.instruments(["q3-4b", "llamacpp:M"])
    assert got["serving"] == "llama-server+mlx_lm.server"
    assert run.engines(["q3-4b", "llamacpp:M"]) == {
        "q3-4b": "mlx_lm.server", "llamacpp:M": "llama-server"}


def test_the_llama_server_url_is_the_one_serve_eval_starts():
    """Gauntlet #2: the port lives in the launcher and here."""
    text = (REPO / "scripts" / "serve-eval.sh").read_text(encoding="utf-8")
    port = re.search(r'LLAMACPP_PORT:-(\d+)', text).group(1)
    assert serving.LLAMACPP_URL == f"http://127.0.0.1:{port}"


# --- a retracted refusal goes back to inspect -------------------------------

def test_a_retracted_refusal_is_pending_again(tmp_path):
    db = ms.connect(tmp_path / "d.db")
    ms.record(db, ms.Seen(name="org/g", source="t", resolved="org/g",
                          kind="weights", lane="code"))
    ms.decide(db, "org/g", "declined", tier="inspect",
              detail="needs-llamacpp: GGUF")
    assert "org/g" not in ms.pending(db)
    ms.retract(db, "org/g", "runtime:llamacpp is met here")
    assert "org/g" in ms.pending(db)
    db.close()


def test_requeue_retracts_every_revisitable_verdict(tmp_path):
    db = ms.connect(tmp_path / "d.db")
    for name in ("org/a", "org/b"):
        ms.record(db, ms.Seen(name=name, source="t", resolved=name,
                              kind="weights", lane="code"))
    ms.decide(db, "org/a", "declined", tier="inspect", reason="machine",
              detail="needs-llamacpp: GGUF", until="runtime:llamacpp")
    ms.decide(db, "org/b", "declined", tier="inspect", reason="machine",
              detail="needs-cuda: torch", until="runtime:cuda")
    facts = {"fingerprint": "here", "runtimes": "cpu,llamacpp,mlx"}
    assert ms.requeue_revisitable(db, facts) == ["org/a"]
    assert ms.revisitable(db, facts) == []
    db.close()


def test_the_models_dir_is_the_one_the_router_reads(monkeypatch):
    text = (REPO / "scripts" / "serve-llamacpp.sh").read_text(encoding="utf-8")
    assert 'MODELS="${LLAMACPP_MODELS_DIR:-$HF_HOME/gguf}"' in text
    monkeypatch.delenv("LLAMACPP_MODELS_DIR", raising=False)
    monkeypatch.setenv("HF_HOME", "/hf")
    assert gguf.models_dir() == Path("/hf/gguf")


# --- #298 ---------------------------------------------------------------------

def test_an_imatrix_file_is_never_a_model():
    """command-a-plus: every quant over the ceiling, so the fallback took the
    208 MB calibration file."""
    sibs = [sib("C-Q4_K_M.gguf", 60), sib("C-imatrix.gguf", 0.2)]
    assert gguf.choose(sibs, 22 * GIB) is None


def test_inspect_calls_an_oversized_gguf_repo_too_big():
    import dataclasses
    from harness import machine
    here = dataclasses.replace(machine.detect(),
                               runtimes=frozenset({"cpu", "llamacpp", "mlx"}))
    sibs = [sib("C-Q4_K_M.gguf", 60), sib("C-Q2_K.gguf", 40),
            sib("C-imatrix.gguf", 0.2)]
    fit = ins.inspect_model("org/C-GGUF", ceiling=22 * GIB, machine=here,
                            data={"siblings": sibs, "tags": ["gguf"]})
    assert fit.verdict == "too-big", fit.why
    assert fit.largest == 40 * GIB


# --- #438 ---------------------------------------------------------------------

def _glm():
    """unsloth/GLM-5.2-GGUF as the registry lists it: every quant split, in a
    folder, each first part a 9 MB metadata shard."""
    sizes = {"UD-IQ1_S": [9423744, 49208128256, 49684417024, 49396052864,
                          49246275936, 19171063136],
             "UD-IQ1_M": [9423744, 49257241920, 48943068032, 48891518400,
                          49934857248, 31456857280]}
    sibs = [{"rfilename": "README.md", "size": 8048},
            {"rfilename": "imatrix_unsloth.gguf_file", "size": 1131474112}]
    for quant, parts in sizes.items():
        n = len(parts)
        sibs += [{"rfilename": f"{quant}/GLM-5.2-{quant}-{i:05d}-of-{n:05d}.gguf",
                  "size": s} for i, s in enumerate(parts, 1)]
    return sibs, sum(sizes["UD-IQ1_S"])


def test_a_split_repo_is_sized_by_its_cheapest_whole_variant():
    sibs, iq1_s = _glm()
    assert gguf.smallest(sibs) == iq1_s
    assert gguf.choose(sibs, 22 * GIB) is None, "fetch takes no shard"


def test_inspect_calls_the_split_glm_repo_too_big_not_nine_megabytes():
    import dataclasses
    from harness import machine
    here = dataclasses.replace(machine.detect(),
                               runtimes=frozenset({"cpu", "llamacpp", "mlx"}))
    sibs, iq1_s = _glm()
    fit = ins.inspect_model("unsloth/GLM-5.2-GGUF", ceiling=22 * GIB,
                            machine=here, data={"siblings": sibs, "tags": ["gguf"],
                                                "pipeline_tag": "text-generation"})
    assert fit.largest == iq1_s
    assert fit.verdict == "too-big", fit.why


def test_a_stray_small_gguf_beside_a_split_model_is_not_the_model():
    sibs, iq1_s = _glm()
    sibs.append(sib("GLM-5.2-vocab.gguf", 0.009))
    assert gguf.choose(sibs, 22 * GIB) is None
    assert gguf.smallest(sibs) == iq1_s


def test_an_incomplete_split_set_is_not_a_variant():
    sibs = [sib("M-Q4_K_M-00001-of-00003.gguf", 0.01),
            sib("M-Q4_K_M-00002-of-00003.gguf", 9)]
    assert gguf.shard_sets(sibs) == {}
    assert gguf.smallest(sibs) == 0


def test_a_real_single_quant_beside_a_split_one_is_still_chosen():
    """Negative control: a quant a few times smaller is a quant, not a stray."""
    sibs = [sib("M-Q8_0-00001-of-00002.gguf", 20),
            sib("M-Q8_0-00002-of-00002.gguf", 20),
            sib("M-Q4_K_M.gguf", 9.5)]
    assert gguf.choose(sibs, 22 * GIB) == ("M-Q4_K_M.gguf", int(9.5 * GIB))
    assert gguf.smallest(sibs) == int(9.5 * GIB)


def test_a_non_text_lane_keeps_the_snapshot_route(home):
    """magpie_tts ships only a GGUF; its runner wants the repo."""
    got = []
    where = fetching.download(
        "nvidia/magpie_tts", snapshot=lambda repo_id: got.append(repo_id) or "/x",
        listing=lambda r: [sib("magpie.f16.gguf", 0.5)],
        hf_download=lambda *a: (_ for _ in ()).throw(AssertionError("gguf")),
        text=False)
    assert got == ["nvidia/magpie_tts"] and where == "/x"


# --- #301 ---------------------------------------------------------------------

def _hub(home, monkeypatch, repo, files, lane):
    """A whole hub download, recorded, of a proposal in `lane`."""
    monkeypatch.setenv("HF_HOME", str(home / "hf"))
    snap = downloads.hub_dir(repo) / "snapshots" / "abc"
    snap.mkdir(parents=True)
    for name, size in files.items():
        (snap / name).write_bytes(b"x" * size)
    conn = ms.connect()
    ms.record(conn, ms.Seen(name=repo, source="t", lane=lane))
    downloads.record(conn, repo, downloads.HUB, snap.parent.parent)
    return conn


def test_a_gguf_repo_already_in_the_hub_cache_is_served_by_llama_server(
        home, monkeypatch):
    conn = _hub(home, monkeypatch, "org/A-GGUF",
                {"A-Q4_K_M.gguf": 64, "README.md": 1}, "code")
    assert screen.candidate_for("code", "org/A-GGUF") == "org/A-GGUF"
    assert gguf.adopt_pending(conn) == ["org/A-GGUF"]
    link = home / "gguf" / "A-Q4_K_M.gguf"
    assert link.is_symlink()
    row = conn.execute("SELECT * FROM downloads WHERE kind = 'gguf'").fetchone()
    assert (row["repo"], row["origin"], row["file"]) == (
        "org/A-GGUF", downloads.LINK, "A-Q4_K_M.gguf")
    assert row["source"] == str(link.resolve())
    assert screen.candidate_for("code", "org/A-GGUF") == "llamacpp:A-Q4_K_M"
    assert gguf.fetched("org/A-GGUF") == "A-Q4_K_M"
    assert gguf.adopt_pending(conn) == []
    conn.close()


def test_only_a_text_lane_adopts_from_the_hub(home, monkeypatch):
    """#303: magpie (tts) was linked by a read that had no lane."""
    conn = _hub(home, monkeypatch, "org/T", {"t.f16.gguf": 64}, "tts")
    assert screen.candidate_for("tts", "org/T") != "llamacpp:t.f16"
    assert fetching.have("org/T")
    mem.cache_path("org/T")
    screen.routed_gateway("org/T")
    assert gguf.adopt_pending(conn) == []
    assert not (home / "gguf" / "t.f16.gguf").exists()
    assert gguf.fetched("org/T") is None
    conn.close()


def test_a_read_never_adopts_even_in_a_text_lane(home, monkeypatch):
    """RULE #334: the side effect lives in the fetch tier, not the lookup."""
    conn = _hub(home, monkeypatch, "org/R-GGUF", {"r-Q4_K_M.gguf": 64}, "code")
    screen.candidate_for("code", "org/R-GGUF")
    fetching.have("org/R-GGUF")
    mem.cache_path("org/R-GGUF")
    assert not (home / "gguf" / "r-Q4_K_M.gguf").exists()
    conn.close()


def test_a_hub_repo_with_safetensors_stays_on_its_own_route(home, monkeypatch):
    conn = _hub(home, monkeypatch, "org/B",
                {"b.gguf": 64, "model.safetensors": 64}, "code")
    assert gguf.adopt_pending(conn) == []
    assert gguf.fetched("org/B") is None
    assert not (home / "gguf" / "b.gguf").exists()
    conn.close()


def test_a_downloaded_gguf_asks_for_the_router_to_rescan(home):
    """#319: the router only reads its directory at startup."""
    asked = []
    gguf.download("org/M", "M-Q4_K_M.gguf",
                  hf_download=lambda r, f, d: str(Path(d) / f),
                  refresh=lambda: asked.append(True))
    assert asked == [True]


def test_the_suite_can_never_restart_the_real_eval_server():
    real = gguf.__dict__["refresh_router"]
    assert real.__module__ != "harness.gguf" or real.__name__ == "<lambda>"

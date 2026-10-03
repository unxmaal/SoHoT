"""A GGUF-only text candidate reaches llama-server. #295."""
import re
from pathlib import Path

import pytest

from harness import fetching, gguf, screen, serving
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
    assert gguf.fetched("org/Model-4B-GGUF") == "Model-4B-Q4_K_M"
    assert fetching.have("org/Model-4B-GGUF")
    db.close()


def test_a_manifest_entry_whose_file_is_gone_is_not_fetched(home):
    gguf.remember("org/M", "M-Q4_K_M.gguf")
    assert gguf.fetched("org/M") is None
    (home / "gguf" / "M-Q4_K_M.gguf").write_bytes(b"GGUF")
    assert gguf.fetched("org/M") == "M-Q4_K_M"


# --- screen and measure spell it for llama-server --------------------------

def test_a_fetched_gguf_is_spelled_for_llama_server(home):
    gguf.remember("org/M-GGUF", "M-Q4_K_M.gguf")
    (home / "gguf" / "M-Q4_K_M.gguf").write_bytes(b"GGUF")
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
    gguf.remember("org/M-GGUF", "M-Q4_K_M.gguf")
    (home / "gguf" / "M-Q4_K_M.gguf").write_bytes(b"x" * 4096)
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
    ms.decide(db, "org/g", "queued", tier="inspect",
              detail="retracted: runtime:llamacpp is met here")
    assert "org/g" in ms.pending(db)
    db.close()


def test_requeue_retracts_every_revisitable_verdict(tmp_path):
    db = ms.connect(tmp_path / "d.db")
    for name in ("org/a", "org/b"):
        ms.record(db, ms.Seen(name=name, source="t", resolved=name,
                              kind="weights", lane="code"))
    ms.decide(db, "org/a", "declined", tier="inspect",
              detail="needs-llamacpp: GGUF")
    ms.decide(db, "org/b", "declined", tier="inspect",
              detail="needs-cuda: torch")
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

def _hub(home, monkeypatch, repo, files):
    monkeypatch.setenv("HF_HOME", str(home / "hf"))
    snap = (home / "hf" / "hub" / f"models--{repo.replace('/', '--')}"
            / "snapshots" / "abc")
    snap.mkdir(parents=True)
    for name, size in files.items():
        (snap / name).write_bytes(b"x" * size)
    return snap


def test_a_gguf_repo_already_in_the_hub_cache_is_served_by_llama_server(
        home, monkeypatch):
    _hub(home, monkeypatch, "org/A-GGUF", {"A-Q4_K_M.gguf": 64, "README.md": 1})
    assert screen.candidate_for("code", "org/A-GGUF") == "llamacpp:A-Q4_K_M"
    assert (home / "gguf" / "A-Q4_K_M.gguf").exists()
    assert gguf.fetched("org/A-GGUF") == "A-Q4_K_M"


def test_only_a_text_lane_adopts_from_the_hub(home, monkeypatch):
    """#303: magpie (tts) was linked by a read that had no lane."""
    _hub(home, monkeypatch, "org/T", {"t.f16.gguf": 64})
    assert screen.candidate_for("tts", "org/T") != "llamacpp:t.f16"
    assert fetching.have("org/T")
    mem.cache_path("org/T")
    screen.routed_gateway("org/T")
    assert not (home / "gguf" / "t.f16.gguf").exists()
    assert gguf.fetched("org/T") is None


def test_a_hub_repo_with_safetensors_stays_on_its_own_route(home, monkeypatch):
    _hub(home, monkeypatch, "org/B", {"b.gguf": 64, "model.safetensors": 64})
    assert gguf.fetched("org/B") is None
    assert not (home / "gguf" / "b.gguf").exists()

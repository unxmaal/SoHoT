"""Each lane's fetch takes the files its runner opens, a listing in no format its runner loads waits as a format gap, and an incomplete snapshot is ours to refetch. #1040."""
import re
import types
from pathlib import Path

import pytest

import fakes
from harness import downloads, fetching, reasons, screen, variants
from harness import inspect as ins
from harness import memory_store as ms
from harness.commands import discover as discover_cmd
from harness.commands import loop as loop_cmd

GIB = 1024 ** 3
CEILING = 66 * GIB
NEMOTRON = "nvidia/nemotron-3.5-asr-streaming-0.6b"
#: Verdict 12828's detail, as the live store holds it.
LIVE_12828 = ("the installed runtime could not load it: 1089-134686-0001: stt failed: HTTP 500: "
              "{\"detail\":\"Failed to load model 'nvidia/nemotron-3.5-asr-streaming-0.6b': The cached "
              "snapshot for 'nvidia/nemotron-3.5-asr-streaming-0.6b' (revision 'main', commit "
              "ea30d66debe3740a08b573244286791d423d6b3e) is incomplete: 1 file(s) are missing "
              "(model.safetensors)\"}")


def _machine(*runtimes):
    have = set(runtimes) | {"always"}
    return types.SimpleNamespace(runtimes=frozenset(have),
                                 refuses=lambda rt: None if rt in have else f"needs-{rt}")


MAC = _machine("mlx", "llamacpp")
CUDA = _machine("cuda", "llamacpp")


def _size(card, name) -> int:
    return next(s["size"] for s in card["siblings"] if s["rfilename"] == name)


def _fit(repo, machine=MAC):
    return ins.inspect_model(repo, data=fakes.card(repo), ceiling=CEILING, machine=machine)


def _pin(monkeypatch, machine=MAC):
    from harness import machine as machine_mod
    monkeypatch.setattr(machine_mod, "detect", lambda *a, **k: machine)
    monkeypatch.setattr(ins, "ceiling_bytes", lambda acc=None: CEILING)


def test_an_stt_listing_is_sized_by_what_mlx_audio_opens_not_its_gguf():
    card = fakes.card(NEMOTRON)
    fit = _fit(NEMOTRON)
    assert fit.lanes[NEMOTRON] == "stt"
    assert fit.verdict == "fits", fit.why
    assert fit.smallest == _size(card, "model.safetensors")
    assert "model.safetensors" in fit.why and ".gguf" not in fit.why


def test_the_stt_fetch_takes_the_safetensors_and_none_of_the_nemo_or_gguf(monkeypatch, tmp_path):
    _pin(monkeypatch)
    card = fakes.card(NEMOTRON)
    asked = {}

    def snapshot(repo_id, **kw):
        asked.update(kw)
        return str(tmp_path)

    fetching.download(NEMOTRON, snapshot=snapshot, listing=lambda r: card["siblings"], text=False,
                      require_weights=True, lane="stt", card={"model_type": "nemotron3_5_asr"})
    allow = set(asked["allow_patterns"])
    assert allow == {"config.json", "generation_config.json", "model.safetensors",
                     "processor_config.json", "tokenizer.json", "tokenizer_config.json"}
    names = {s["rfilename"] for s in card["siblings"]}
    # Exactly what mlx-audio's own snapshot_download asks for, so its offline open is complete.
    assert allow == {n for n in names if variants.matches(n, variants.MLX_AUDIO_FILES)}


def test_a_lane_llama_cpp_does_not_serve_never_picks_a_gguf_even_without_mlx():
    card = fakes.card(NEMOTRON)
    fit = _fit(NEMOTRON, machine=CUDA)
    assert fit.smallest == _size(card, "model.safetensors")
    assert fetching.lane_formats("stt") == (".safetensors", ".bin", ".npz", ".onnx")
    assert ".gguf" in fetching.lane_formats("code")


def test_a_text_lane_still_takes_the_smallest_gguf():
    siblings = fakes.card(NEMOTRON)["siblings"]
    found = variants.runnable(siblings, CEILING, lane="code")
    assert variants.pick(found).format == variants.GGUF


def test_an_mlx_whisper_repo_opens_the_whole_snapshot():
    card = {"model_type": "whisper", "library": "mlx"}
    assert variants.opens("stt", "mlx-community/whisper-tiny", card, {"mlx"}) == ()
    assert variants.opens("stt", NEMOTRON, {"model_type": "nemotron3_5_asr"}, {"mlx"}) \
        == variants.MLX_AUDIO_FILES
    assert variants.opens("code", NEMOTRON, None, {"mlx"}) == ()


@pytest.mark.parametrize("repo, formats", [
    ("nvidia/parakeet-tdt-0.6b-v2", [".nemo"]),
    ("nvidia/magpie_tts_multilingual_357m", [".gguf", ".nemo"]),
    ("Abiray/Kroma-v0.3.1-Turbo-OPD-GGUF", [".gguf"]),
])
def test_a_listing_in_no_format_its_lane_loads_is_a_format_gap_at_inspect(repo, formats):
    fit = _fit(repo)
    assert fit.verdict == "unknown"
    assert fit.formats == formats
    assert ins.reason_of(fit) == reasons.HARNESS
    assert ins.until_of(fit) == "format:" + "|".join(formats)
    assert fit.why.startswith("runners wanted: its weights are ")


def test_the_format_gap_is_queued_and_fetch_waits_on_it(monkeypatch):
    repo = "nvidia/magpie_tts_multilingual_357m"
    card = fakes.card(repo)
    conn = ms.connect()
    try:
        ms.record(conn, ms.Seen(name=repo, source="t", resolved=repo, kind="weights",
                                registry=ms.HUGGINGFACE, lane="tts"))
    finally:
        conn.close()
    monkeypatch.setattr(discover_cmd, "resolve_registry",
                        lambda name, client, model=None: (ms.HUGGINGFACE, card))
    real = ins.inspect_model
    monkeypatch.setattr(ins, "inspect_model",
                        lambda r, data=None, **kw: real(r, data=data, ceiling=CEILING, machine=MAC))
    from harness import cli
    assert cli.main(["discover", "--inspect", "--repos", repo]) == 0
    conn = ms.connect()
    try:
        row = conn.execute("SELECT p.lane, v.outcome, v.reason, v.until FROM proposals p JOIN verdicts v "
                           "ON v.id = p.state_verdict_id WHERE p.name = ?", (repo,)).fetchone()
    finally:
        conn.close()
    assert tuple(row) == ("tts", "queued", "harness", "format:.gguf|.nemo")
    got = fetching.why_not({"lane": "tts", "until": row["until"], "inspected": 1})
    assert got[0] == fetching.FORMAT


def test_a_gguf_wait_ends_only_on_a_lane_llama_cpp_serves():
    assert fetching.format_waits("format:.gguf", "tts", runtimes={"mlx"})
    assert not fetching.format_waits("format:.gguf", "code", runtimes={"mlx"})
    assert fetching.format_waits("format:.nemo", "code", runtimes={"mlx"})


def test_the_fetch_refuses_a_nemo_only_stt_listing_as_runners_wanted(monkeypatch):
    _pin(monkeypatch)
    card = fakes.card("nvidia/parakeet-tdt-0.6b-v2")
    with pytest.raises(fetching.Unloadable) as got:
        fetching.download(card["id"], snapshot=lambda **kw: pytest.fail(f"snapshot {kw}"),
                          listing=lambda r: card["siblings"], text=False, require_weights=True,
                          lane="stt")
    assert list(got.value.formats) == [".nemo"]


def test_an_incomplete_snapshot_is_ours_to_refetch():
    cls = reasons.classify(LIVE_12828, reasons.RUNNER, f"stt:{NEMOTRON}")
    assert cls == reasons.INCOMPLETE_COPY
    assert reasons.CLASSES[cls] == ("queued", reasons.HARNESS)
    assert cls in reasons.REFETCH
    assert screen._sentence(cls, "x", "").endswith("refetch: x")


def test_an_audio_load_failure_without_the_incomplete_text_stays_the_runtimes():
    text = re.sub(r"The cached snapshot.*\(model\.safetensors\)", "Unsupported model type", LIVE_12828)
    assert reasons.classify(text, reasons.RUNNER, f"stt:{NEMOTRON}") == reasons.LOAD_FAILED_RUNTIME


def test_the_loop_refetches_a_screen_that_blamed_the_runtime_for_our_snapshot(monkeypatch, tmp_path):
    conn = ms.connect()
    try:
        for name in (NEMOTRON, "org/real-runtime-gap"):
            ms.record(conn, ms.Seen(name=name, source="t", lane="stt"))
        ms.decide(conn, NEMOTRON, "declined", tier=ms.SCREEN, reason=reasons.RUNTIME,
                  until="version:mlx-audio>0.5.3", failure_class=reasons.LOAD_FAILED_RUNTIME,
                  detail=LIVE_12828)
        ms.decide(conn, "org/real-runtime-gap", "declined", tier=ms.SCREEN, reason=reasons.RUNTIME,
                  detail="the installed runtime could not load it: Model type x not supported")
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        snap = downloads.hub_dir(NEMOTRON) / "snapshots" / "abc"
        snap.mkdir(parents=True)
        (snap / "config.json").write_text("{}", encoding="utf-8")
        (snap / "model.q8_0.gguf").write_bytes(b"x")
        fakes.hub_ref(snap)
        downloads.record(conn, NEMOTRON, downloads.HUB, snap.parent.parent)
        conn.commit()
        assert downloads.have(NEMOTRON, conn, stat=False)
    finally:
        conn.close()
    assert loop_cmd._reopen_missing_in_snapshot() == [NEMOTRON]
    assert loop_cmd._reopen_missing_in_snapshot() == []
    conn = ms.connect()
    try:
        row = conn.execute("SELECT p.state, v.tier FROM proposals p JOIN verdicts v "
                           "ON v.id = p.state_verdict_id WHERE p.name = ?", (NEMOTRON,)).fetchone()
        other = conn.execute("SELECT state FROM proposals WHERE name = ?",
                             ("org/real-runtime-gap",)).fetchone()[0]
        had = downloads.have(NEMOTRON, conn, stat=False)
    finally:
        conn.close()
    assert tuple(row) == ("queued", ms.INSPECT)
    assert other == "declined"
    assert not had


def test_the_loop_reinspects_a_non_text_lane_sized_by_a_gguf(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        for name, lane in (("nvidia/magpie_tts_multilingual_357m", "tts"), ("org/text-gguf", "code")):
            ms.record(conn, ms.Seen(name=name, source="t", lane=lane))
            ms.decide(conn, name, "queued", tier=ms.INSPECT, reason=reasons.CANDIDATE,
                      detail=f"fits: {variants.MARK}m.f16.gguf: 0.5 GiB of 1 weight file")
        conn.commit()
        assert [r["name"] for r in ms.gguf_sized_off_lane(conn)] == ["nvidia/magpie_tts_multilingual_357m"]
        assert "nvidia/magpie_tts_multilingual_357m" in ms.requeue_old_sizing(conn)
        assert ms.gguf_sized_off_lane(conn) == []
    finally:
        conn.close()


def test_mlx_audio_files_are_the_pinned_mlx_audio_s():
    pins = (Path(__file__).resolve().parents[1] / "scripts" / "versions.sh").read_text(encoding="utf-8")
    assert 'MLX_AUDIO_PIN="mlx-audio==0.5.3"' in pins

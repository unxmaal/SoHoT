"""Drafters, MTP heads, adapters and shards are refused at fetch, get no preset section, and soh gguf-aux sets them aside. #1674."""
import configparser
import struct
import types
from pathlib import Path

import pytest

from harness import context, downloads, fetching, gguf, router
from harness import memory_store as ms
from harness.commands import gguf_aux
from tests.test_context import QWEN3_4B, _s, _value

GIB = 1024 ** 3
REPO = Path(__file__).resolve().parents[1]


def write(path, meta: dict, tensors=()) -> Path:
    """A GGUF v3 header with these key/values and tensor infos (one f32 dim each)."""
    body = b""
    for key, v in meta.items():
        kind, raw = _value(v)
        body += _s(key) + struct.pack("<I", kind) + raw
    for name in tensors:
        body += _s(name) + struct.pack("<IQIQ", 1, 8, 0, 0)
    path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(meta)) + body)
    return path


def blk(ids, kinds=("attn_q.weight", "ffn_up.weight")):
    return [f"blk.{i}.{k}" for i in ids for k in kinds]


QWEN = {"general.architecture": "qwen35moe", "general.type": "model", "qwen35moe.block_count": 4,
        "qwen35moe.nextn_predict_layers": 1}
NEXTN = ("attn_q.weight", "nextn.eh_proj.weight", "nextn.enorm.weight")
HEAD = ["token_embd.weight", "output_norm.weight", "output.weight"]
#: Each modelled on a file deploy 21's fetch linked (FINDING sohot-1674-aux-gguf-headers).
AUX = {
    "dspark-M-Q8_0.gguf": ({"general.architecture": "dflash", "general.type": "model",
                            "dflash.block_count": 3}, blk(range(3)) + ["fc.weight", "output_norm.weight"],
                           "a speculative drafter (architecture dflash)"),
    "mtp-M-Q8_0.gguf": (QWEN, HEAD + blk([3], NEXTN), "an MTP head (block 3 of 4)"),
    "blk-00041.gguf": ({"general.architecture": "inkling", "general.type": "model", "inkling.block_count": 1},
                       blk([0]), "a layer shard (block 0 of 1, no token embedding)"),
    "mtp-layer-donate.gguf": ({"split.no": 16, "split.count": 18, "split.tensors.count": 1118},
                              blk([60], NEXTN), "a split part (17 of 18)"),
    "M-Q4_K_M-00002-of-00003.gguf": (QWEN, blk([2]), "a split part (2 of 3)"),
    "lora-M.gguf": ({"general.architecture": "llama", "general.type": "adapter"}, blk([0]),
                    "an adapter file (general.type adapter)"),
    "half-M.gguf": (QWEN, HEAD + blk([0, 1]), "a layer shard (blocks 0, 1 of 4)"),
}


@pytest.mark.parametrize("name", sorted(AUX))
def test_a_file_llama_server_cannot_serve_alone_says_what_it_is(tmp_path, name):
    meta, tensors, why = AUX[name]
    assert gguf.auxiliary(write(tmp_path / name, meta, tensors)) == why


@pytest.mark.parametrize("meta,tensors", [
    (QWEN, HEAD + blk(range(3)) + blk([3], NEXTN)),
    ({**QWEN, "general.type": "model"}, HEAD + blk(range(4))),
    ({"general.architecture": "llama", "llama.block_count": 2}, ["token_embd.weight"] + blk(range(2))),
    (QWEN3_4B, ()),
])
def test_a_whole_model_is_kept_even_with_an_mtp_layer_or_no_tensor_table(tmp_path, meta, tensors):
    """Negative controls: Qwen3.6-27B-MTP-* carry their nextn block beside every other block."""
    assert gguf.auxiliary(write(tmp_path / "Qwen3.6-27B-MTP-Q4_K_M.gguf", meta, tensors)) == ""


def test_an_unreadable_header_is_not_this_checks_call(tmp_path):
    (tmp_path / "x.gguf").write_bytes(b"GGUF")
    (tmp_path / "y.gguf").write_bytes(b"not a gguf at all")
    assert gguf.auxiliary(tmp_path / "x.gguf") == gguf.auxiliary(tmp_path / "y.gguf") == ""
    assert gguf.auxiliary(tmp_path / "missing.gguf") == ""
    # A key length read from junk would allocate gigabytes; it is a corrupt header instead.
    (tmp_path / "z.gguf").write_bytes(b"GGUF" * 64)
    assert gguf.auxiliary(tmp_path / "z.gguf") == ""
    with pytest.raises(ValueError, match="not a GGUF header"):
        context.read_meta(tmp_path / "z.gguf")


@pytest.fixture
def models(tmp_path, monkeypatch):
    d = tmp_path / "hf" / "gguf"
    d.mkdir(parents=True)
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(d))
    return d


def _fill(models):
    for name, (meta, tensors, _) in AUX.items():
        write(models / name, meta, tensors)
    write(models / "Model-Q4_K_M.gguf", {**QWEN3_4B, "qwen3.block_count": 2},
          ["token_embd.weight"] + blk(range(2)))


def test_the_repair_dry_run_lists_exactly_the_auxiliary_files(models, capsys):
    _fill(models)
    assert gguf_aux.cmd_gguf_aux(types.SimpleNamespace(apply=False)) == 0
    out = capsys.readouterr().out
    assert sorted(p.name for p, _ in gguf.auxiliaries()) == sorted(AUX)
    for name, (_, _, why) in AUX.items():
        assert f"  {name}: {why}" in out
    assert "Model-Q4_K_M" not in out and "--apply moves them to" in out
    assert sorted(p.name for p in models.iterdir()) == sorted([*AUX, "Model-Q4_K_M.gguf"])


def test_the_repair_moves_them_aside_restarts_the_router_and_deletes_nothing(models, monkeypatch, capsys):
    _fill(models)
    conn = ms.connect()
    downloads.record(conn, "org/M-GGUF", downloads.GGUF, models / "mtp-M-Q8_0.gguf", file="mtp-M-Q8_0.gguf")
    conn.close()
    restarts = []
    monkeypatch.setattr(gguf, "refresh_router", lambda *a, **k: restarts.append(1) or "")
    assert gguf_aux.cmd_gguf_aux(types.SimpleNamespace(apply=True)) == 0
    assert [p.name for p in models.iterdir()] == ["Model-Q4_K_M.gguf"]
    aside = gguf.quarantine_dir()
    assert aside.parent == models.parent and sorted(p.name for p in aside.iterdir()) == sorted(AUX)
    assert restarts == [1]
    conn = ms.connect()
    row = conn.execute("SELECT removed_at, removed_by FROM downloads WHERE file = 'mtp-M-Q8_0.gguf'").fetchone()
    conn.close()
    assert row["removed_at"] and row["removed_by"] == "gguf-aux: an MTP head (block 3 of 4)"
    assert "nothing deleted" in capsys.readouterr().out
    assert gguf_aux.cmd_gguf_aux(types.SimpleNamespace(apply=True)) == 0 and restarts == [1]


def test_set_aside_never_overwrites_an_earlier_copy(tmp_path):
    (tmp_path / "a.gguf").write_bytes(b"one")
    first = gguf.set_aside(tmp_path / "a.gguf", tmp_path / "q")
    (tmp_path / "a.gguf").write_bytes(b"two")
    second = gguf.set_aside(tmp_path / "a.gguf", tmp_path / "q")
    assert first != second and first.read_bytes() == b"one" and second.read_bytes() == b"two"


def test_the_preset_writes_no_section_for_an_auxiliary_file(models):
    conn = ms.connect()
    mtp = write(models / "mtp-M-Q8_0.gguf", {**QWEN3_4B, "qwen3.block_count": 4}, HEAD + blk([3], NEXTN))
    whole = write(models / "Model-Q4_K_M.gguf", QWEN3_4B, HEAD + blk(range(36)))
    for p in (mtp, whole):
        downloads.record(conn, "org/m", downloads.GGUF, p, file=p.name)
    plans = context.plan(conn, budget=60 * GIB)
    conn.close()
    got = {p["stem"]: p for p in plans}
    assert got["Model-Q4_K_M"]["ctx"] and not got["mtp-M-Q8_0"]["ctx"]
    assert "an MTP head (block 3 of 4)" in got["mtp-M-Q8_0"]["why"] and gguf.REPAIR in got["mtp-M-Q8_0"]["why"]
    ini = configparser.ConfigParser()
    ini.read_string("[top]\n" + context.preset_text(plans, 16384, 1))
    assert "Model-Q4_K_M" in ini.sections() and "mtp-M-Q8_0" not in ini.sections()


def test_a_fetched_mtp_head_is_set_aside_and_the_candidate_declined(models, monkeypatch):
    db = ms.connect()
    ms.record(db, ms.Seen(name="org/Big-GGUF", source="t", resolved="org/Big-GGUF", kind="weights", lane="code"))
    ms.set_size(db, "org/Big-GGUF", GIB)
    ms.decide(db, "org/Big-GGUF", "queued", tier="inspect", size_bytes=GIB)
    monkeypatch.setattr(fetching.rank, "unrunnable", lambda row, m=None: "")
    sibs = [{"rfilename": "mtp-Big-Q8_0.gguf", "size": GIB}]

    def hf_download(repo, filename, local_dir):
        return str(write(Path(local_dir) / filename, QWEN, HEAD + blk([3], NEXTN)))

    done = fetching.run(db, snapshot=lambda **kw: None, free=900 * GIB,
                        listing=lambda repo: sibs, hf_download=hf_download)
    assert not done[0]["ok"] and "mtp-Big-Q8_0.gguf is an MTP head (block 3 of 4)" in done[0]["why"]
    assert not (models / "mtp-Big-Q8_0.gguf").exists()
    assert (gguf.quarantine_dir() / "mtp-Big-Q8_0.gguf").is_file()
    v = db.execute("SELECT outcome, tier FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()
    assert (v["outcome"], v["tier"]) == ("declined", "fetch")
    assert gguf.fetched("org/Big-GGUF", db) is None
    db.close()


def test_adopt_links_the_model_and_names_the_mtp_head_it_skips(models, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    snap = downloads.hub_dir("org/A-GGUF") / "snapshots" / "abc"
    snap.mkdir(parents=True)
    write(snap / "mtp-A-Q8_0.gguf", QWEN, HEAD + blk([3], NEXTN))
    import fakes
    fakes.hub_ref(snap)
    conn = ms.connect()
    ms.record(conn, ms.Seen(name="org/A-GGUF", source="t", lane="code"))
    downloads.record(conn, "org/A-GGUF", downloads.HUB, snap.parent.parent)
    assert gguf.hub_stem("org/A-GGUF", conn) is None
    assert gguf.adopt(conn, "org/A-GGUF") == ""
    assert "not linking mtp-A-Q8_0.gguf: an MTP head (block 3 of 4)" in capsys.readouterr().err
    write(snap / "A-Q4_K_M.gguf", QWEN, HEAD + blk(range(4)))
    assert gguf.adopt(conn, "org/A-GGUF") == "A-Q4_K_M.gguf"
    assert [p.name for p in models.iterdir()] == ["A-Q4_K_M.gguf"]
    conn.close()


def test_a_hand_placed_auxiliary_file_is_not_recorded(models):
    meta, tensors, _ = AUX["dspark-M-Q8_0.gguf"]
    with pytest.raises(gguf.Auxiliary, match="speculative drafter"):
        gguf.record_existing(write(models / "dspark-M-Q8_0.gguf", meta, tensors), refresh=lambda: None)


def test_a_phantom_backed_by_an_auxiliary_file_names_it_and_the_repair(models):
    meta, tensors, _ = AUX["mtp-M-Q8_0.gguf"]
    path = write(models / "mtp-M-Q8_0.gguf", meta, tensors)
    write(models / "Model.gguf", QWEN3_4B, HEAD + blk(range(36)))

    def get(_path):
        return {"data": [{"id": s, "source": "preset", "status": {"value": "unloaded", "args": ["llama-server"]}}
                         for s in ("mtp-M-Q8_0", "Model", "Ghost")]}
    got = router.phantoms(get)
    assert got["mtp-M-Q8_0"].endswith(f"; {path} is an MTP head (block 3 of 4), not a model: `{gguf.REPAIR}` sets it aside")
    assert got["Model"] == got["Ghost"] == "preset: no --model, a preset section with no file"


def test_smoke_names_the_repair_verb_on_a_phantom():
    text = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "router advertises models with no file" in ln)
    assert "soh gguf-aux" in line and "--apply" in line


def test_a_deploy_repairs_before_its_smoke_with_the_verb_that_exists():
    from harness import cli, deploy
    assert deploy.Steps().repair == [*deploy.SOH, "gguf-aux", "--apply"]
    args = cli.build_parser().parse_args(deploy.Steps().repair[deploy.Steps().repair.index("harness.cli") + 1:])
    assert args.func is gguf_aux.cmd_gguf_aux and args.apply


def test_the_repair_still_moves_the_files_when_the_store_refuses_it(models, monkeypatch, capsys):
    """A deploy runs the new release's verb beside a store on the old schema."""
    _fill(models)
    monkeypatch.setattr(ms, "connect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("schema 91 is newer")))
    monkeypatch.setattr(gguf, "refresh_router", lambda *a, **k: "")
    assert gguf_aux.cmd_gguf_aux(types.SimpleNamespace(apply=True)) == 0
    assert [p.name for p in models.iterdir()] == ["Model-Q4_K_M.gguf"]
    assert "downloads rows not stamped (schema 91 is newer)" in capsys.readouterr().out

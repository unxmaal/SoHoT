"""A fetch never downloads again a GGUF this machine already set aside in quarantine; a person still can. #1989."""
from pathlib import Path

import pytest

from harness import downloads, fetching, gguf
from harness import memory_store as ms
from tests.test_gguf_aux_1674 import AUX, HEAD, QWEN, blk, write

GIB = 1024 ** 3
DRAFTER = "dspark-X-Q8_0.gguf"
META, TENSORS, WHY = AUX["dspark-M-Q8_0.gguf"]


@pytest.fixture
def models(tmp_path, monkeypatch):
    d = tmp_path / "hf" / "gguf"
    d.mkdir(parents=True)
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(d))
    monkeypatch.setattr(fetching.rank, "unrunnable", lambda row, m=None: "")
    monkeypatch.setattr(gguf, "refresh_router", lambda *a, **k: "")
    return d


def _drafter_bytes(tmp_path) -> bytes:
    return write(tmp_path / "template.gguf", META, TENSORS).read_bytes()


def _plant(models, repo: str, data: bytes, name: str = DRAFTER, day: str = "2026-11-09", aside_as: str = "") -> Path:
    """A quarantine entry as gguf.download leaves one: the file aside, its downloads row removed."""
    aside = models.parent / gguf.QUARANTINE.format(day=day)
    aside.mkdir(exist_ok=True)
    (aside / (aside_as or name)).write_bytes(data)
    conn = ms.connect()
    downloads.removed(conn, models / name, by=f"auxiliary: {WHY}", repo=repo, kind=downloads.GGUF)
    conn.close()
    return aside / (aside_as or name)


def _queue(db, repo: str) -> None:
    ms.record(db, ms.Seen(name=repo, source="t", resolved=repo, kind="weights", lane="code"))
    ms.set_size(db, repo, GIB)
    ms.decide(db, repo, "queued", tier="inspect", size_bytes=GIB)


def _hub(tmp_path, got: list):
    def hf_download(repo, filename, local_dir):
        got.append((repo, filename))
        if filename == DRAFTER:
            return str(write(Path(local_dir) / filename, META, TENSORS))
        return str(write(Path(local_dir) / filename, QWEN, HEAD + blk(range(4))))
    return hf_download


def test_the_fetch_plans_nothing_for_a_file_already_set_aside(models, tmp_path, capsys):
    data = _drafter_bytes(tmp_path)
    copy = _plant(models, "org/X-GGUF", data)
    db = ms.connect()
    _queue(db, "org/X-GGUF")
    got: list = []
    done = fetching.run(db, snapshot=lambda **kw: None, free=900 * GIB, hf_download=_hub(tmp_path, got),
                        listing=lambda repo: [{"rfilename": DRAFTER, "size": len(data)}])
    assert got == []
    assert not done[0]["ok"] and "already set aside" in done[0]["why"] and str(copy) in done[0]["why"]
    assert f"not fetching {DRAFTER}: already set aside at {copy}" in capsys.readouterr().err
    v = db.execute("SELECT outcome, tier FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()
    assert (v["outcome"], v["tier"]) == ("declined", "fetch")
    assert not (models / DRAFTER).exists() and [p.name for p in copy.parent.iterdir()] == [DRAFTER]
    db.close()


def test_the_same_name_from_another_repo_is_still_fetched(models, tmp_path):
    data = _drafter_bytes(tmp_path)
    _plant(models, "org/X-GGUF", data)
    db = ms.connect()
    _queue(db, "other/Y-GGUF")
    got: list = []
    done = fetching.run(db, snapshot=lambda **kw: None, free=900 * GIB, hf_download=_hub(tmp_path, got),
                        listing=lambda repo: [{"rfilename": DRAFTER, "size": len(data)}])
    db.close()
    assert got == [("other/Y-GGUF", DRAFTER)]
    assert "already set aside" not in done[0]["why"]


def test_a_hub_file_of_another_size_is_fetched(models, tmp_path):
    data = _drafter_bytes(tmp_path)
    _plant(models, "org/X-GGUF", data)
    db = ms.connect()
    _queue(db, "org/X-GGUF")
    got: list = []
    fetching.run(db, snapshot=lambda **kw: None, free=900 * GIB, hf_download=_hub(tmp_path, got),
                 listing=lambda repo: [{"rfilename": DRAFTER, "size": len(data) + 1}])
    db.close()
    assert got == [("org/X-GGUF", DRAFTER)]


def test_the_repo_s_model_is_fetched_in_place_of_its_set_aside_drafter(models, tmp_path):
    data = _drafter_bytes(tmp_path)
    _plant(models, "org/X-GGUF", data, name=DRAFTER)
    db = ms.connect()
    _queue(db, "org/X-GGUF")
    got: list = []
    sibs = [{"rfilename": DRAFTER, "size": len(data)}, {"rfilename": "X-IQ2_M.gguf", "size": len(data) - 1}]
    done = fetching.run(db, snapshot=lambda **kw: None, free=900 * GIB, hf_download=_hub(tmp_path, got),
                        listing=lambda repo: sibs)
    db.close()
    assert got == [("org/X-GGUF", "X-IQ2_M.gguf")] and done[0]["ok"]


def test_a_renamed_copy_from_a_second_set_aside_counts(models, tmp_path):
    data = _drafter_bytes(tmp_path)
    _plant(models, "org/X-GGUF", data, day="2026-11-10", aside_as="dspark-X-Q8_0.1.gguf")
    assert gguf.held_aside("org/X-GGUF", DRAFTER, len(data)) is not None
    assert gguf.held_aside("org/X-GGUF", "dspark-X-Q8.gguf", len(data)) is None


def test_two_fetches_of_a_drafter_download_it_once_and_leave_one_copy(models, tmp_path):
    data = _drafter_bytes(tmp_path)
    db = ms.connect()
    got: list = []
    hub = _hub(tmp_path, got)
    listing = lambda repo: [{"rfilename": DRAFTER, "size": len(data)}]  # noqa: E731
    for _ in range(2):
        with pytest.raises(fetching.Unloadable):
            fetching.download("org/X-GGUF", listing=listing, hf_download=hub, conn=db)
    db.close()
    assert got == [("org/X-GGUF", DRAFTER)]
    assert [p.name for p in gguf.set_aside_copies(DRAFTER)] == [DRAFTER]


def test_a_person_can_still_fetch_a_set_aside_file_by_hand(models, tmp_path):
    data = _drafter_bytes(tmp_path)
    _plant(models, "org/X-GGUF", data)
    got: list = []
    with pytest.raises(gguf.Auxiliary):
        gguf.download("org/X-GGUF", DRAFTER, hf_download=_hub(tmp_path, got), refresh=lambda: None)
    assert got == [("org/X-GGUF", DRAFTER)]

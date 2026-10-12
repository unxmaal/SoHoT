"""Recording a GGUF that is already on disk. Issue #783.

scripts/fetch-gguf.sh was the only way a GGUF got a downloads row: it downloads
through harness.gguf.download and records as it goes. A file put into the
router's models dir by any other means was served and never recorded, and
harness.context.plan iterates the store, so it got no plan and no preset
section. It still appeared in /v1/models, because the router lists
--models-dir directly.

Measured on the 4070 with a 32B fetched by curl: served at the unplanned [*]
defaults it reached 30.4 of 30.9 GiB host RAM and generated 2.07 tok/s, against
2.52 at a planned ctx. Unrecorded is not merely unplanned; it is served worse,
with no headroom, and nothing says why.
"""
import pytest

from harness import downloads, gguf
from harness import memory_store as ms
from test_context import write_gguf

META = {"general.architecture": "qwen2", "qwen2.block_count": 2,
        "qwen2.embedding_length": 64, "qwen2.attention.head_count": 4,
        "qwen2.attention.head_count_kv": 2, "qwen2.context_length": 4096}


@pytest.fixture
def models(tmp_path, monkeypatch):
    d = tmp_path / "gguf"
    d.mkdir()
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(d))
    return d


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


class _Restart:
    """Stands in for refresh_router, which restarts a real service.

    Called with NO arguments, exactly as download() calls it. A stand-in
    taking one would pass here and fail in production, which is how the first
    version of this fixture was wrong.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


@pytest.fixture
def restarts():
    """No test may restart the real router. #319."""
    return _Restart()


def _placed(models, stem="Hand-Placed-Q4_K_M"):
    p = models / f"{stem}.gguf"
    write_gguf(p, META)
    return p


def test_a_hand_placed_gguf_can_be_recorded_without_downloading(conn, models, restarts):
    """THE POINT OF THIS FILE. The row is the one fetch-gguf.sh would have
    written, and no network is touched to get it."""
    p = _placed(models)
    got = gguf.record_existing(p, conn=conn, refresh=restarts)
    assert got == p.name
    rows = downloads.live(conn, kind=downloads.GGUF)
    assert [r["path"] for r in rows] == [downloads.key(p)]
    assert rows[0]["file"] == p.name
    assert rows[0]["bytes"] == p.stat().st_size


def test_the_recorded_file_is_planned_like_any_other(conn, models, restarts):
    """The reason to record at all. plan() reads the store, so an unrecorded
    file is unplannable however well it serves."""
    from harness import context
    p = _placed(models)
    assert not context.plan(conn, budget=60 * 1024 ** 3)
    gguf.record_existing(p, conn=conn, refresh=restarts)
    stems = [row["stem"] for row in context.plan(conn, budget=60 * 1024 ** 3)]
    assert stems == [p.name[:-len(".gguf")]]


def test_the_router_is_refreshed_so_the_preset_takes_effect(conn, models, restarts):
    """The file was already visible to the router; the PLAN is what is new, and
    the preset is only read at startup."""
    gguf.record_existing(_placed(models), conn=conn, refresh=restarts)
    assert restarts.calls == 1, "recording should refresh the router, as download() does"


def test_recording_the_same_file_twice_is_refused(conn, models, restarts):
    """Two live rows for one path make `disk` double-count it and leave
    `plan` planning the same stem twice."""
    p = _placed(models)
    gguf.record_existing(p, conn=conn, refresh=restarts)
    with pytest.raises(ValueError, match="already recorded"):
        gguf.record_existing(p, conn=conn, refresh=restarts)
    assert len(downloads.live(conn, kind=downloads.GGUF)) == 1


def test_a_file_outside_the_models_dir_is_refused(conn, models, tmp_path, restarts):
    """The router reads one directory. Recording a file it cannot see would
    put a row in the store for something that can never be served, and the
    plan would price VRAM for it."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    p = outside / "Away-Q4_K_M.gguf"
    write_gguf(p, META)
    with pytest.raises(ValueError, match="models dir"):
        gguf.record_existing(p, conn=conn, refresh=restarts)
    assert not downloads.live(conn, kind=downloads.GGUF)


def test_a_file_that_is_not_a_gguf_is_refused(conn, models, restarts):
    p = models / "notes.txt"
    p.write_text("not a model", encoding="utf-8")
    with pytest.raises(ValueError, match="gguf"):
        gguf.record_existing(p, conn=conn, refresh=restarts)


def test_a_missing_file_is_refused(conn, models, restarts):
    with pytest.raises(FileNotFoundError):
        gguf.record_existing(models / "Absent-Q4_K_M.gguf", conn=conn,
                             refresh=restarts)


def test_the_repo_is_recorded_when_one_is_known(conn, models, restarts):
    """A hand-placed file often has no provenance, so repo is optional. When
    the person doing it knows where it came from, the row should say."""
    p = _placed(models)
    gguf.record_existing(p, repo="bartowski/Hand-Placed-GGUF", conn=conn,
                         refresh=restarts)
    assert downloads.live(conn, kind=downloads.GGUF)[0]["repo"] == \
        "bartowski/Hand-Placed-GGUF"


def test_an_unknown_provenance_is_recorded_as_such_not_invented(conn, models, restarts):
    """An empty repo is honest. Inventing one would make `disk` and the fetch
    tier believe a hub repo exists that nobody can re-fetch from."""
    p = _placed(models)
    gguf.record_existing(p, conn=conn, refresh=restarts)
    assert downloads.live(conn, kind=downloads.GGUF)[0]["repo"] == ""

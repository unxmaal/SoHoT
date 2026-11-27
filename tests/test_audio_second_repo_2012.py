"""#2012: a tts model mlx-audio loads with a second repo (MOSS-TTS's audio tokenizer) has it fetched with the candidate."""
from pathlib import Path

import pytest

from harness import engines, fetching, machine
from harness import memory_store as ms

MOSS = "OpenMOSS-Team/MOSS-TTS-v1.5"
TOKENIZER = "OpenMOSS-Team/MOSS-Audio-Tokenizer"
VOICES = "prince-canuma/Kokoro-82M"
REAL_ROOT = engines.audio_root


def fake_audio(site: Path) -> Path:
    """site-packages laid out as mlx-audio 0.5.3's: the model-type remap and the moss_tts family's repo constant."""
    files = {
        "mlx_audio-0.5.3.dist-info/METADATA": "Name: mlx-audio\nVersion: 0.5.3\n",
        "mlx_audio/tts/utils.py": 'MODEL_REMAPPING = {"moss_tts_delay": "moss_tts", "kitten": "kitten_tts"}\n',
        "mlx_audio/tts/models/moss_tts/config.py": f'DEFAULT_AUDIO_TOKENIZER_REPO = "{TOKENIZER}"\n',
        "mlx_audio/tts/models/moss_tts/convert.py": 'SOURCE_REPO = "x/where-it-was-converted-from"\n',
        "mlx_audio/tts/models/kitten_tts/model.py": "def load():\n    pass\n",
        "mlx_audio/tts/models/kokoro/kokoro.py": f'class Model:\n    REPO_ID = "{VOICES}"\n',
    }
    for rel, text in files.items():
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_text(text, encoding="utf-8")
    return site


@pytest.fixture
def site(tmp_path, monkeypatch):
    got = fake_audio(tmp_path / "uv" / "archive-v0" / "Hb" / "lib" / "python3.12" / "site-packages")
    monkeypatch.setattr(engines, "audio_root", lambda: got)
    return got


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:UV_CACHE_DIR")
def test_the_tts_server_pin_is_found_in_uvs_cache(tmp_path, monkeypatch):
    site = fake_audio(tmp_path / "uv" / "archive-v0" / "Hb" / "lib" / "python3.12" / "site-packages")
    monkeypatch.setattr(machine, "_uv_with_pins", lambda path=None: {"mlx-audio": "0.5.3"})
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv"))
    assert REAL_ROOT() == site
    monkeypatch.setattr(machine, "_uv_with_pins", lambda path=None: {"mlx-audio": "0.6.0"})
    assert REAL_ROOT() is None


def test_a_moss_model_needs_the_tokenizer_its_family_loads_and_not_a_converter_source(site):
    assert engines.audio_needs(MOSS, "moss_tts_delay", site) == (TOKENIZER,)
    assert engines.audio_needs("x/kitten", "kitten", site) == ()
    assert engines.audio_needs(MOSS, "", site) == ()


def test_the_tokenizer_is_fetched_with_the_tts_candidate_and_never_for_another_lane(site):
    conn = ms.connect()
    try:
        for name, lane in ((MOSS, "tts"), ("org/code-model", "code")):
            ms.record(conn, ms.Seen(name=name, source="t", kind="weights", lane=lane, resolved=name))
            conn.execute("UPDATE proposals SET model_type = 'moss_tts_delay' WHERE name = ?", (name,))
        conn.commit()
        assert fetching.runner_bases(MOSS, conn) == [TOKENIZER]
        assert fetching.runner_bases("org/code-model", conn) == []
        fetched = []
        done, _, waiting = fetching._needs(conn, MOSS, free=900 * fetching.GIB, floor=0, sizer=lambda r: 1,
                                           snapshot=lambda repo_id, **k: fetched.append(repo_id) or "/x")
        assert fetched == [TOKENIZER] and waiting is None
        assert [d["why"] for d in done] == [f"base weights for {MOSS}"]
    finally:
        conn.close()


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/engines.py:_audio_remap:except")
def test_an_unreadable_remap_names_the_family_by_the_model_type(site):
    (site / "mlx_audio" / "tts" / "utils.py").write_text("MODEL_REMAPPING = {broken", encoding="utf-8")
    (site / "mlx_audio" / "tts" / "models" / "moss_tts_delay").mkdir()
    (site / "mlx_audio" / "tts" / "models" / "moss_tts_delay" / "config.py").write_text('X_REPO = "org/direct"\n', encoding="utf-8")
    assert engines.audio_needs(MOSS, "moss_tts_delay", site) == ("org/direct",)


def test_a_new_mlx_audio_remap_is_read_again(site):
    import os
    assert engines.audio_needs(MOSS, "moss_tts_delay", site) == (TOKENIZER,)
    utils = site / "mlx_audio" / "tts" / "utils.py"
    utils.write_text('MODEL_REMAPPING = {"moss_tts_delay": "kitten_tts"}\n', encoding="utf-8")
    st = utils.stat()
    os.utime(utils, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    assert engines.audio_needs(MOSS, "moss_tts_delay", site) == ()


def test_kokoro_keeps_the_voices_repo_its_model_class_names_so_the_disk_sweep_never_removes_it(site):
    assert engines.audio_needs("mlx-community/Kokoro-82M-bf16", "kokoro", site) == (VOICES,)

"""The split of cli.py and memory_store.py keeps every import, every patch and every migration. #484."""
import importlib
import os
import re
import time
from pathlib import Path

import pytest

import layout_scan as ls

WATCHED = ("harness.cli", "harness.memory_store")
#: Patches on these must reach every reader, since their code moves between modules.
STRICT = ("harness.cli", "harness.memory_store", "harness.commands")
BUDGET = 1500
#: Modules allowed over BUDGET, each with the reason it is not split yet.
OVER_BUDGET: dict = {}


def unresolved(refs) -> list:
    bad = []
    for mod, name in sorted(refs):
        m = importlib.import_module(mod)
        if not hasattr(m, name):
            bad.append(f"{mod}.{name}")
    return bad


def test_every_name_taken_from_cli_and_the_store_resolves():
    refs = ls.references(WATCHED)
    assert len(refs) > 100, "the scan found too little to be a scan"
    assert unresolved(refs) == []


def test_the_surface_scan_sees_a_name_that_is_gone():
    src = ("from harness.cli import main, no_such_verb\n"
           "from harness import memory_store as ms\n"
           "ms.connect; ms.no_such_reader\n")
    f = ls.facts("t", src, set(ls.code_modules()))
    refs = {(m, n) for m, n, _ in f.imported} | {(m, n) for m, n, c, _ in f.attrs}
    assert unresolved(refs) == ["harness.cli.no_such_verb",
                                "harness.memory_store.no_such_reader"]


def test_every_patch_reaches_the_code_that_reads_it():
    graph = ls.Graph(ls.code_modules())
    found = ls.patches(ls.py_files(["tests"]))
    assert len(found) > 300, "the scan found too few patches to be a scan"
    assert ls.ineffective(graph, found, STRICT) == []


SYNTHETIC = {
    "pkg": "from pkg.a import f\nfrom pkg import a\n",
    "pkg.a": "def f():\n    return 1\n\ndef g():\n    return f()\n",
    "pkg.b": "from pkg import a\n\ndef h():\n    return a.f()\n",
}


@pytest.mark.parametrize("target,caught", [
    (("pkg", "f"), "which nothing reads"),
    (("pkg.a", "f"), None),
])
def test_a_patch_of_a_re_export_is_caught(target, caught):
    graph = ls.Graph(SYNTHETIC, pkgs={"pkg"})
    got = ls.ineffective(graph, [("t.py", 1, *target)], strict=("pkg",))
    if caught is None:
        assert got == []
    else:
        assert len(got) == 1 and caught in got[0]


def test_a_patch_that_misses_one_reader_of_a_moved_name_is_caught():
    sources = dict(SYNTHETIC, **{"pkg.c": "from pkg.a import f\n\ndef k():\n    return f()\n"})
    graph = ls.Graph(sources, pkgs={"pkg"})
    got = ls.ineffective(graph, [("t.py", 1, "pkg.a", "f")], strict=("pkg",))
    assert got == ["t.py:1 patches pkg.a.f but pkg.c read it as pkg.c.f"]
    assert ls.ineffective(graph, [("t.py", 1, "pkg.a", "f")], strict=()) == []


def over_budget(root: Path = ls.REPO, budget: int = BUDGET) -> dict:
    got = {}
    for p in sorted((root / "harness").rglob("*.py")):
        n = len(p.read_text(encoding="utf-8").splitlines())
        if n > budget:
            got[p.relative_to(root).as_posix()] = n
    return got


def test_no_harness_module_is_over_budget():
    got = over_budget()
    assert {k: v for k, v in got.items() if k not in OVER_BUDGET} == {}
    assert [k for k in OVER_BUDGET if k not in got] == [], "a stale exception"


def test_the_budget_sees_a_long_module(tmp_path):
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "big.py").write_text("x = 1\n" * 12, encoding="utf-8")
    assert over_budget(tmp_path, budget=10) == {"harness/big.py": 12}


# The migration chain: every golden store migrates to exactly what it did before the split.

MIGRATED = ls.REPO / "tests" / "golden" / "migrated"
#: The speech defaults winners.typed() reads per platform, pinned to the Mac's the recording used.
MAC_SPEECH = {"DEFAULT_TTS_MODEL": "mlx-community/Kokoro-82M-bf16",
              "DEFAULT_STT_MODEL": "mlx-community/parakeet-tdt-0.6b-v2"}
_DRIVE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:/")


def dump(conn, started: float) -> str:
    """Every table's columns, indexes and rows, rendered by Python so no SQLite version shows."""
    out = []
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    for t in tables:
        cols = [tuple(r)[1:] for r in conn.execute(f'PRAGMA table_info("{t}")')]
        out.append(f"table {t} {cols!r}")
        for ix in sorted(tuple(r)[1:3] for r in conn.execute(f'PRAGMA index_list("{t}")')):
            on = [r[2] for r in conn.execute(f'PRAGMA index_info("{ix[0]}")')]
            out.append(f"  index {ix[0]} unique={ix[1]} {on!r}")
        for row in conn.execute(f'SELECT * FROM "{t}" ORDER BY rowid'):
            out.append("  " + repr(tuple("<now>" if isinstance(v, float) and v >= started
                                          else v for v in row)))
    return "\n".join(out)


def migrated_dump(version: int, tmp_path: Path, monkeypatch, speech=MAC_SPEECH) -> str:
    """The golden at `version` migrated to head, with this run's clock, paths and zone masked."""
    import test_golden_stores as tg
    if not hasattr(time, "tzset") and time.localtime(0).tm_gmtoff:
        pytest.skip("legacy JSON stamps are local time, and this platform cannot pin the zone")
    db, home = tg.open_golden(version, tmp_path, monkeypatch)
    from harness import audio
    for name, value in speech.items():
        monkeypatch.setattr(audio, name, value)
    started = time.time() - 1
    from harness import memory_store as ms
    zone = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    getattr(time, "tzset", lambda: None)()
    try:
        conn = ms.connect(db)
        try:
            text = dump(conn, started)
        finally:
            conn.close()
    finally:
        if zone is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = zone
        getattr(time, "tzset", lambda: None)()
    text = text.replace("\\\\", "/").replace("\\", "/")
    for path, mask in ((os.environ["HF_HOME"], "<hf>"), (tmp_path, "<tmp>")):
        for form in (Path(path).resolve(), path):
            text = text.replace(str(form).replace("\\", "/"), mask)
    return _DRIVE.sub("/", text)


def golden_eras():
    import test_golden_stores as tg
    return tg.ERAS


@pytest.mark.parametrize("version", golden_eras())
def test_each_golden_migrates_to_the_recorded_content(version, tmp_path, monkeypatch):
    """Regenerate after an intended change: LH_RECORD_MIGRATED=1 uv run pytest tests/test_module_layout.py."""
    got = migrated_dump(version, tmp_path, monkeypatch)
    want = MIGRATED / f"v{version}.sql"
    if os.environ.get("LH_RECORD_MIGRATED") == "1":
        want.parent.mkdir(parents=True, exist_ok=True)
        want.write_text(got + "\n", encoding="utf-8")
    assert got + "\n" == want.read_text(encoding="utf-8")


WINDOWS_SPEECH = {"DEFAULT_TTS_MODEL": "kokoro-onnx/Kokoro-82M",
                  "DEFAULT_STT_MODEL": "Systran/faster-whisper-base.en"}


@pytest.mark.parametrize("version", golden_eras())
def test_a_golden_migrates_the_same_under_every_platform_default(version, tmp_path,
                                                                 monkeypatch):
    """History comes from the record, not from the migrating machine's defaults. #516."""
    mac = migrated_dump(version, tmp_path / "mac", monkeypatch, speech=MAC_SPEECH)
    windows = migrated_dump(version, tmp_path / "win", monkeypatch, speech=WINDOWS_SPEECH)
    assert windows.splitlines() == mac.splitlines()


def test_the_speech_pin_reaches_the_typed_defaults(monkeypatch):
    """Negative control: the Windows pin is what winners.typed() reads, so the test above is not a no-op."""
    from harness import audio, winners
    for name, value in WINDOWS_SPEECH.items():
        monkeypatch.setattr(audio, name, value)
    assert winners.typed()["stt"] == "Systran/faster-whisper-base.en"
    assert winners.typed()["tts"] == "kokoro-onnx/Kokoro-82M"


def test_the_dump_sees_one_changed_row(tmp_path, monkeypatch):
    version = golden_eras()[-1]
    clean = migrated_dump(version, tmp_path / "a", monkeypatch)
    from harness import memory_store as ms
    real = ms.connect

    def connect_then_touch(path=None):
        conn = real(path)
        conn.execute("UPDATE proposals SET description = 'changed' WHERE id = 1")
        return conn
    monkeypatch.setattr(ms, "connect", connect_then_touch)
    assert migrated_dump(version, tmp_path / "b", monkeypatch) != clean


def chain_faults(steps, head: int) -> list[str]:
    from harness.memory_store import migrations
    faults = []
    versions = [s.VERSION for s in steps]
    if versions != list(range(1, head + 1)):
        faults.append(f"steps {versions} are not 1..{head}")
    for s in steps:
        name = s.__name__.rsplit(".", 1)[-1]
        if name != f"v{s.VERSION:02d}":
            faults.append(f"{name} says VERSION {s.VERSION}")
        stray = {n for n, v in vars(s).items() if callable(v) and not n.startswith("_")
                 and getattr(v, "__module__", "") == s.__name__} - set(migrations.PHASES)
        if stray:
            faults.append(f"{name} defines {sorted(stray)}, which no phase runs")
    return faults


def test_the_chain_has_one_step_per_schema_version():
    from harness import memory_store as ms
    assert chain_faults(ms.migrations.steps(), ms.SCHEMA_VERSION) == []


def test_the_chain_check_sees_a_gap_a_misnamed_step_and_a_stray_phase():
    import types
    from harness import memory_store as ms
    steps = ms.migrations.steps()
    stray = types.ModuleType(f"{ms.migrations.__name__}.v03")
    stray.VERSION = 3

    def date(conn):
        return None
    date.__module__ = stray.__name__
    stray.date = date
    got = chain_faults(steps[:2] + [stray] + steps[4:], ms.SCHEMA_VERSION)
    assert got[0].startswith("steps [1, 2, 3, 5,")
    assert got[1:] == ["v03 defines ['date'], which no phase runs"]
    misnamed = types.ModuleType(f"{ms.migrations.__name__}.v07")
    misnamed.VERSION = 8
    assert "v07 says VERSION 8" in chain_faults([misnamed], 1)

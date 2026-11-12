"""Whole-tree scan results are kept by the text they read: served while it is unchanged, scanned again once it changes (#1590)."""
import sqlite3

import gauntlet.ratchet
import pytest
from gauntlet import scanners as gscanners
from gauntlet.registry import Registry

from tests import tree_cache
from tests.gauntlet import registry, scanners
from tests.racing import race

BAD = "def f(x=[]):\n    return x\n"
GOOD = "def g(x=None):\n    return x\n"
PAIRED = ("def add(conn):\n    conn.execute(\"INSERT INTO a (x) VALUES (1)\")\n    conn.commit()\n    return 1\n\n"
          "def link(conn):\n    i = add(conn)\n    conn.execute(\"INSERT INTO b (a_id) VALUES (?)\", (i,))\n")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    for env in tree_cache.OFF_ENVS:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv(tree_cache.ENV, str(tmp_path / "cache"))
    return tmp_path / "cache" / tree_cache.FILE


def _tree(root, files):
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def _py(root):
    return sorted(root.rglob("*.py"))


def _forge(db, rel, value):
    conn = sqlite3.connect(db)
    with conn:
        assert conn.execute("UPDATE memo SET value = ? WHERE rel = ?", (value, rel)).rowcount == 1
    conn.close()


def _scan(root):
    return tree_cache.scan_tree(root, gscanners.mutable_defaults, gscanners.is_python, lister=_py)


def test_a_kept_scan_is_served_until_the_file_it_read_changes(tmp_path, cache):
    root = _tree(tmp_path / "repo", {"a.py": BAD, "b.py": GOOD})
    first = _scan(root)
    assert first == gscanners.scan_tree(root, gscanners.mutable_defaults, gscanners.is_python, lister=_py) != []
    _forge(cache, "b.py", '["b.py:1: forged"]')
    assert _scan(root) == [*first, "b.py:1: forged"], "an unchanged file is answered from the cache"
    (root / "b.py").write_text(GOOD + "\n", encoding="utf-8")
    assert _scan(root) == first, "an edited file is scanned again"
    (root / "c.py").write_text(BAD, encoding="utf-8")
    assert [f.split(":")[0] for f in _scan(root)] == ["a.py", "c.py"], "a new file is scanned"


def test_a_scanner_or_gauntlet_that_changed_is_never_answered_from_the_cache(tmp_path, cache, monkeypatch):
    root = _tree(tmp_path / "repo", {"a.py": BAD, "b.py": GOOD})
    first = _scan(root)
    _forge(cache, "b.py", '["b.py:1: forged"]')
    monkeypatch.setattr(tree_cache, "_package", lambda: "another gauntlet")
    assert _scan(root) == first


@pytest.mark.parametrize("off", tree_cache.OFF_ENVS)
def test_a_coverage_map_or_mutation_run_scans_every_file(tmp_path, cache, monkeypatch, off):
    root = _tree(tmp_path / "repo", {"a.py": BAD, "b.py": GOOD})
    first = _scan(root)
    _forge(cache, "b.py", '["b.py:1: forged"]')
    monkeypatch.setenv(off, "1")
    assert _scan(root) == first


def test_a_scanner_that_could_read_more_than_its_text_is_not_kept(tmp_path, cache):
    root = _tree(tmp_path / "repo", {"a.py": BAD})
    seen = []

    def local(text, rel):
        seen.append(rel)
        return [rel]
    assert tree_cache.code(local) is None and tree_cache.code(lambda t, r: []) is None
    assert tree_cache.code(_rels) is None, "a module the key does not read"
    assert tree_cache.code(gscanners.mutable_defaults) is not None
    for _ in range(2):
        assert tree_cache.scan_tree(root, local, gscanners.is_python, lister=_py) == ["a.py"]
    assert seen == ["a.py", "a.py"]
    assert not cache.exists()


def _rels(text, rel):
    return [rel]


def test_a_scanner_made_by_a_factory_is_not_kept_though_a_pure_module_holds_it(monkeypatch):
    def made(word):
        def scan(text, rel):
            return [rel] if word in text else []
        return scan
    fn = made("x")
    fn.__module__, fn.__qualname__, fn.__name__ = scanners.__name__, "made_x", "made_x"
    monkeypatch.setattr(scanners, "made_x", fn, raising=False)
    assert tree_cache.code(fn) is None
    plain = lambda text, rel: []  # noqa: E731
    plain.__module__, plain.__qualname__, plain.__name__ = scanners.__name__, "plain_x", "plain_x"
    monkeypatch.setattr(scanners, "plain_x", plain, raising=False)
    assert tree_cache.code(plain) is not None, "the same shape with nothing closed over is kept"


def test_workers_filling_one_new_cache_at_once_all_get_the_scan(tmp_path, cache):
    root = _tree(tmp_path / "repo", {f"m{i}.py": BAD if i % 2 else GOOD for i in range(20)})
    want = gscanners.scan_tree(root, gscanners.mutable_defaults, gscanners.is_python, lister=_py)
    got = []

    def racer(start):
        start()
        got.append(_scan(root))
    race([racer] * 8)
    assert got == [want] * 8


def test_precheck_runs_every_check_once_in_order_and_the_inventory_readers_in_one_process():
    from tests.gauntlet import precheck
    batches = precheck.groups()
    assert [n for b in batches for n in b] == [c.__name__ for c in precheck.CHECKS]
    assert ("knob_sites", "knob_backlog_lines", "knob_entries", "limit_traces") in batches
    assert len(batches) == len(precheck.CHECKS) - 3


def _registry(root):
    return Registry(root=root, index={registry.CR: registry.REGISTRY.index[registry.CR]},
                    snapshot_file=root / "s.json", defects_file=root / "d.json",
                    production=registry.production, files=_py)


def test_the_detector_hits_are_kept_until_a_production_source_changes(tmp_path, cache):
    root = _tree(tmp_path / "repo", {"harness/q.py": PAIRED, "tests/test_q.py": GOOD})
    reg = _registry(root)
    first = tree_cache.frontend_hits(reg)
    assert first == gauntlet.ratchet.frontend_hits(reg) and first[registry.CR]
    _forge(cache, "", '{"forged": [["harness/q.py:x", 1, "forged"]]}')
    assert list(tree_cache.frontend_hits(reg)) == ["forged"], "unchanged production code is answered from the cache"
    (root / "tests/test_q.py").write_text(BAD, encoding="utf-8")
    assert list(tree_cache.frontend_hits(reg)) == ["forged"], "a test file is no input to the hits"
    (root / "harness/q.py").write_text(PAIRED.replace("i = add(conn)", "i = 1"), encoding="utf-8")
    again = tree_cache.frontend_hits(reg)
    assert again == gauntlet.ratchet.frontend_hits(reg) and again != first, "edited production code is scanned again"


def test_a_kept_hit_reads_back_as_the_hit_gauntlet_returned(tmp_path, cache):
    reg = _registry(_tree(tmp_path / "repo", {"harness/q.py": PAIRED}))
    tree_cache.frontend_hits(reg)
    kept = tree_cache.frontend_hits(reg)
    assert kept == gauntlet.ratchet.frontend_hits(reg)
    assert all(type(h) is type(next(iter(kept[registry.CR]))) for hits in kept.values() for h in hits)

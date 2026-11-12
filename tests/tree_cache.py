"""Whole-tree scan results kept on disk and keyed by the exact text they read, shared by xdist workers and later runs (#1590)."""
import functools
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

from gauntlet import detectors
from gauntlet import ratchet as gratchet
from gauntlet import scanners as gscanners

#: Names the cache directory; conftest sets it under pytest's cache dir, and a precheck a test starts inherits it.
ENV = "SOHOT_TREE_CACHE"
#: A coverage-map run must execute every scanner, and mutmut keeps one source text for every mutant.
OFF_ENVS = ("SOHOT_COVERAGE_MAP", "MUTANT_UNDER_TEST")
#: Modules whose scanners read nothing but (text, rel), their own module and the gauntlet package.
PURE_MODULES = ("gauntlet.scanners", "tests.gauntlet.scanners")
#: conftest makes it under pytest's cache dir; CI's check-macos restores and saves that path.
CACHE_NAME = "tree-scan"
FILE = "scans.sqlite"
BUSY_S = 120
HERE = Path(__file__).resolve().parent


def directory():
    if any(os.environ.get(e) for e in OFF_ENVS):
        return None
    got = os.environ.get(ENV, "")
    return Path(got) if got else None


def _sha(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode("utf-8", "surrogatepass"))
        h.update(b"\0")
    return h.hexdigest()


@functools.cache
def _package() -> str:
    """Every file of the installed gauntlet package, so a re-pin or a local edit to it invalidates everything."""
    root = Path(gscanners.__file__).resolve().parent
    files = sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return _sha(sys.version, *(x for p in files for x in (p.relative_to(root).as_posix(), p.read_bytes())))


def code(fn) -> str | None:
    """The digest of what a scanner's answer depends on besides its arguments; None when that cannot be known."""
    mod = sys.modules.get(getattr(fn, "__module__", ""))
    if (mod is None or fn.__module__ not in PURE_MODULES or getattr(fn, "__closure__", None)
            or getattr(mod, getattr(fn, "__name__", ""), None) is not fn):
        return None
    return _sha(_package(), fn.__module__, fn.__qualname__, Path(mod.__file__).read_bytes())


def _connect(where: Path):
    where.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(where / FILE, timeout=BUSY_S, isolation_level=None)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("CREATE TABLE IF NOT EXISTS memo (kind TEXT, rel TEXT, code TEXT, digest TEXT, value TEXT,"
                  " PRIMARY KEY (kind, rel))")
    conn.execute("COMMIT")
    return conn


def _read(where: Path, kind: str) -> dict:
    conn = _connect(where)
    try:
        return {rel: (c, d, v) for rel, c, d, v in
                conn.execute("SELECT rel, code, digest, value FROM memo WHERE kind = ?", (kind,))}
    finally:
        conn.close()


def _write(where: Path, kind: str, rows: list) -> None:
    if not rows:
        return
    conn = _connect(where)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany("INSERT OR REPLACE INTO memo (kind, rel, code, digest, value) VALUES (?, ?, ?, ?, ?)",
                         [(kind, *r) for r in rows])
        conn.execute("COMMIT")
    finally:
        conn.close()


def each(scanner, items) -> list[str]:
    """scanner(text, rel) over (text, rel) items, findings in item order; a file is scanned again only once its text changes."""
    where, version = directory(), code(scanner)
    if where is None or version is None:
        return [f for text, rel in items for f in scanner(text, rel)]
    kind = f"{scanner.__module__}:{scanner.__qualname__}"
    known, out, fresh = _read(where, kind), [], []
    for text, rel in items:
        digest = _sha(text)
        held = known.get(rel)
        if held is not None and held[0] == version and held[1] == digest:
            found = json.loads(held[2])
        else:
            found = scanner(text, rel)
            fresh.append((rel, version, digest, json.dumps(found)))
        out += found
    _write(where, kind, fresh)
    return out


def listed(root, want, only=None, lister=None):
    """(text, rel) of each file gauntlet's scan_tree would scan, in its order."""
    root = Path(root)
    for path in (lister or gscanners._files.publishable)(root):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and want(path) and (only is None or only(rel)):
            yield path.read_text(encoding="utf-8", errors="replace"), rel


def scan_tree(root, scanner, want, only=None, lister=None) -> list[str]:
    """gauntlet.scanners.scan_tree, answered from the cache for every file whose text and scanner are unchanged."""
    return each(scanner, listed(root, want, only, lister))


def frontend_hits(reg, extra=None):
    """gauntlet.ratchet.frontend_hits for a registry, kept until a production source, the registry or gauntlet changes."""
    where = directory()
    if where is None or extra is not None:
        return _frontend_hits(reg, extra)
    texts = detectors.sources(reg.root, production=reg.production, lister=reg.files)
    mine = {p.relative_to(HERE).as_posix(): p.read_bytes() for p in sorted((HERE / "gauntlet").glob("*.py"))}
    config = json.dumps([reg.index, reg.detector_config], sort_keys=True, default=repr)
    digest = _sha(_package(), Path(reg.root).resolve(), repr(tuple(reg.frontends)), config,
                  *(x for rel in sorted(texts) for x in (rel, texts[rel])),
                  *(x for rel in sorted(mine) for x in (rel, mine[rel])))
    held = _read(where, "frontend_hits").get("")
    if held is not None and held[1] == digest:
        return {cid: [detectors.Hit(*h) for h in hits] for cid, hits in json.loads(held[2]).items()}
    got = _frontend_hits(reg, extra)
    _write(where, "frontend_hits", [("", "", digest, json.dumps({cid: [list(h) for h in hits] for cid, hits in got.items()}))])
    return got


_frontend_hits = gratchet.frontend_hits

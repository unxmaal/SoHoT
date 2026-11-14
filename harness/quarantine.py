"""The quarantine dirs beside the GGUF dir: their sizes, and exact-copy duplicates that may go (#1921)."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from harness import gguf


@dataclass(frozen=True)
class File:
    path: Path
    size: int
    ino: tuple[int, int]
    nlink: int
    mtime_ns: int


@dataclass(frozen=True)
class Pair:
    keep: File
    drop: File
    sha256: str


def root() -> Path:
    return gguf.models_dir().parent


def dirs(where=None) -> list[Path]:
    """Each quarantine-<day> dir, oldest day first; a link named like one is not followed."""
    where = Path(where) if where is not None else root()
    found = where.glob(gguf.QUARANTINE.format(day="*"))
    return sorted(p for p in found if p.is_dir() and not p.is_symlink())


def _entries(qdir: Path) -> tuple[list[File], list[tuple[Path, str]]]:
    files, odd = [], []
    for top, subdirs, names in os.walk(qdir, followlinks=False):
        subdirs.sort()
        for name in sorted(names):
            p = Path(top) / name
            st = os.lstat(p)
            if os.path.islink(p):
                odd.append((p, "a link, not a copy: deleting it frees nothing and its target is not ours"))
            elif not os.path.isfile(p):
                odd.append((p, "not a regular file"))
            else:
                files.append(File(p, st.st_size, (st.st_dev, st.st_ino), st.st_nlink, st.st_mtime_ns))
    return files, odd


def sizes(where=None) -> list[dict]:
    """Each quarantine dir's file count and bytes, a hard-linked file counted once over all of them."""
    seen, out = set(), []
    for d in dirs(where):
        files, _ = _entries(d)
        size = 0
        for f in files:
            if f.ino not in seen:
                seen.add(f.ino)
                size += f.size
        out.append({"dir": str(d), "files": len(files), "bytes": size})
    return out


def line(rows: list[dict]) -> str:
    """The one line `soh disk` prints about the quarantine."""
    from harness import disk
    total = sum(r["bytes"] for r in rows)
    return (f"quarantine: {len(rows)} dir(s), {sum(r['files'] for r in rows)} file(s), {disk.gib(total)} GiB; "
            f"never deleted automatically (`soh quarantine --dedupe` drops exact copies)")


def sha256(path: Path) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _linked(roots, targets: set[str]) -> dict[str, str]:
    """Each target path some symlink under `roots` resolves to, with that link."""
    hit = {}
    for r in roots:
        for top, _subdirs, names in os.walk(r, followlinks=False):
            for name in names:
                p = os.path.join(top, name)
                if os.path.islink(p):
                    real = os.path.realpath(p)
                    if real in targets:
                        hit.setdefault(real, p)
    return hit


def plan(where=None, link_roots=None, digest=sha256) -> tuple[list[Pair], list[tuple[Path, str]]]:
    """(kept, duplicate) pairs whose size and sha256 match, the first by day then path kept; and what is refused."""
    where = Path(where) if where is not None else root()
    qdirs = dirs(where)
    files, refused = [], []
    for d in qdirs:
        got, odd = _entries(d)
        files += got
        refused += odd
    by_size: dict[int, list[File]] = {}
    for f in files:
        by_size.setdefault(f.size, []).append(f)
    groups: dict[str, list[File]] = {}
    for same in by_size.values():
        if len(same) > 1:
            for f in same:
                groups.setdefault(digest(f.path), []).append(f)
    drops = [(g[0], f, h) for h, g in groups.items() for f in g[1:]]
    if link_roots is None:
        link_roots = [p for p in (where / "hub", gguf.models_dir()) if p.is_dir()]
    linked = _linked(link_roots, {os.path.realpath(f.path) for _, f, _ in drops})
    pairs = []
    for keep, f, h in drops:
        why = ""
        if f.nlink > 1:
            why = f"{f.nlink} links share its bytes (another may be a hub blob, or {keep.path})"
        elif os.path.realpath(f.path) in linked:
            why = f"the link {linked[os.path.realpath(f.path)]} points at it"
        if why:
            refused.append((f.path, why))
        else:
            pairs.append(Pair(keep, f, h))
    return pairs, refused


def _inside(path: Path, qdirs: list[Path]) -> bool:
    real = Path(os.path.realpath(path.parent))
    return any(real == q or q in real.parents for q in (Path(os.path.realpath(d)) for d in qdirs))


def _unchanged(f: File) -> str:
    try:
        st = os.lstat(f.path)
    except OSError as exc:
        return f"gone ({exc})"
    if os.path.islink(f.path) or (st.st_dev, st.st_ino) != f.ino or st.st_size != f.size \
            or st.st_mtime_ns != f.mtime_ns:
        return "changed since it was hashed"
    if st.st_nlink != f.nlink:
        return f"now has {st.st_nlink} links"
    return ""


def drop(pairs: list[Pair], where=None) -> list[dict]:
    """Delete each pair's duplicate, only inside a quarantine dir and only if neither file changed since hashing."""
    qdirs = dirs(where)
    out = []
    for p in pairs:
        row = {"keep": str(p.keep.path), "drop": str(p.drop.path), "bytes": p.drop.size, "sha256": p.sha256}
        why = ("outside every quarantine dir" if not _inside(p.drop.path, qdirs)
               else f"kept copy {_unchanged(p.keep)}" if _unchanged(p.keep)
               else _unchanged(p.drop))
        if why:
            out.append({**row, "error": why})
            continue
        try:
            os.unlink(p.drop.path)
        except OSError as exc:
            out.append({**row, "error": str(exc)})
            continue
        out.append(row)
    return out

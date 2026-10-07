"""Weights on disk: what was fetched or found, where, and when it went. #411.

The fetch tier writes a row when it downloads, `lh disk` and discovery's
cleanup stamp `removed_at` when they delete, and every reader asks this table
rather than decoding the HF hub tree. The hub tree stays the ground truth for
what is physically present; `drift` names where the two disagree.
"""
from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

HUB, GGUF = "hub", "gguf"
KINDS = (HUB, GGUF)
#: How a row arrived.
FETCH, LINK, SCRIPT, SCAN, BACKFILL, PARTIAL = (
    "fetch", "hub-link", "script", "scan", "backfill", "partial")

#: A snapshot with only a card is not a download: Marlin-2B had LICENSE and
#: README and was screened as if present. #399.
#: adapter_config.json: a peft adapter is loadable onto the base it names. #423.
LOADABLE = ("config.json", "model_index.json", "adapter_config.json")
WEIGHT_SUFFIXES = (".safetensors", ".bin", ".gguf", ".npz", ".pt", ".pth",
                   ".ckpt", ".onnx")

#: Config keys whose value names a repo you must ALSO have on disk. #196.
REQUIRES_KEYS = ("text_tokenizer", "tokenizer_name", "audio_tokenizer",
                 "codec_model", "vocoder", "base_model",
                 # A peft adapter's base, from adapter_config.json. #423.
                 "base_model_name_or_path")
#: Repo-shaped and NOT a requirement: where the config came from.
PROVENANCE_KEYS = {
    "_name_or_path": "where the config came from, not what it needs",
}
_REPO = re.compile(r"^[A-Za-z0-9][\w.-]*/[\w.-]+$")
#: A started download with no finish this long ago has no live fetch writing it.
IN_FLIGHT_SECONDS = 24 * 3600


@contextmanager
def store(conn=None):
    from harness import runs
    with runs.store(conn) as c:
        yield c


def hf_home() -> Path:
    return Path(os.environ.get("HF_HOME")
                or Path.home() / ".cache" / "huggingface")


def hub_root() -> Path:
    return hf_home() / "hub"


def gguf_root() -> Path:
    from harness import gguf
    return gguf.models_dir()


def hub_dir(repo: str) -> Path:
    """Where huggingface_hub puts `repo`, in its own spelling."""
    try:
        from huggingface_hub.file_download import repo_folder_name
        name = repo_folder_name(repo_id=repo, repo_type="model")
    except ImportError:
        name = "models--" + "--".join(repo.split("/"))
    return hub_root() / name


def _repo_from_dir(name: str) -> str:
    """Only for a hub dir no row explains, at backfill or `lh disk --record`."""
    return name[len("models--"):].replace("--", "/", 1)


def key(path) -> str:
    """A path as rows store it: parent resolved, the entry itself not followed."""
    p = Path(path).expanduser()
    return str(Path(os.path.realpath(p.parent)) / p.name)


def loadable(kind: str, path) -> bool:
    """The #399 check: config or weights present, not just a card."""
    p = Path(path)
    if kind == GGUF:
        return p.name.lower().endswith(".gguf") and p.exists()
    snaps = p / "snapshots"
    if not snaps.is_dir():
        return False
    for f in snaps.rglob("*"):
        if (f.name in LOADABLE or f.name.endswith(WEIGHT_SUFFIXES)) and f.exists():
            return True
    return False


def _measure(kind: str, path) -> tuple[int, int]:
    p = Path(path)
    if kind == GGUF:
        if p.is_symlink() or not p.is_file():
            return 0, int(p.exists())
        return p.stat().st_size, 1
    size = files = 0
    for top, _, names in os.walk(p / "blobs", followlinks=False):
        for f in names:
            full = os.path.join(top, f)
            if not os.path.islink(full):
                size += os.lstat(full).st_size
    for top, _, names in os.walk(p / "snapshots", followlinks=False):
        files += len(names)
    return size, files


def config_of(path) -> dict:
    out: dict = {}
    for name in ("adapter_config.json", "config.json"):
        for cfg in sorted(Path(path).glob(f"snapshots/*/{name}")):
            try:
                got = json.loads(cfg.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                got = {}
            out.update(got if isinstance(got, dict) else {})
            break
    return out


def requires_in(config: dict, repo: str) -> list[str]:
    out = []
    for k in REQUIRES_KEYS:
        value = config.get(k)
        if isinstance(value, str) and _REPO.match(value) and value != repo:
            out.append(value)
    return sorted(set(out))


def this_machine(conn) -> int:
    from harness import memory_store as ms
    return ms.remember_machine(conn)


def mine(conn) -> tuple:
    """This machine's id, without writing a row; one row per machine. #415."""
    from harness import runs
    return tuple(runs.here(conn))


def _in(ids) -> tuple[str, tuple]:
    ids = tuple(ids)
    if not ids:
        return "1 = 0", ()
    return f"machine_id IN ({','.join('?' * len(ids))})", ids


def _proposal(conn, name: str):
    if not name:
        return None
    row = conn.execute("SELECT id FROM proposals WHERE name = ?",
                       (name,)).fetchone()
    if row is None:
        row = conn.execute("SELECT id FROM proposals WHERE lower(name) = ?",
                           (name.lower(),)).fetchone()
    return row["id"] if row else None


def live(conn, *, repo: str = "", kind: str = "", path: str = "") -> list[dict]:
    """This machine's rows not yet removed, newest first."""
    where, args = _in(mine(conn))
    sql = f"SELECT * FROM downloads WHERE removed_at IS NULL AND {where}"
    if repo:
        sql += " AND lower(repo) = ?"
        args += (repo.lower(),)
    if kind:
        sql += " AND kind = ?"
        args += (kind,)
    if path:
        sql += " AND path = ?"
        args += (key(path),)
    return [dict(r) for r in conn.execute(sql + " ORDER BY id DESC", args)]


def start(conn, repo: str, kind: str, path, *, file: str = "",
          origin: str = FETCH, proposal: str = "") -> int:
    """A download about to begin; the row is in flight until finish()."""
    now = time.time()
    got = live(conn, kind=kind, path=path)
    if got:
        conn.execute("UPDATE downloads SET started_at = ?, finished_at = NULL, "
                     "complete = 0 WHERE id = ?", (now, got[0]["id"]))
        conn.commit()
        return got[0]["id"]
    rid = conn.execute(
        "INSERT INTO downloads (proposal_id, repo, kind, path, file, origin, "
        "started_at, machine_id) VALUES (?,?,?,?,?,?,?,?)",
        (_proposal(conn, proposal or repo), repo, kind, key(path), file,
         origin, now, this_machine(conn))).lastrowid
    conn.commit()
    return rid


def finish(conn, rid: int, path=None, *, failed: bool = False) -> dict:
    """Measure what landed and stamp the row."""
    row = dict(conn.execute("SELECT * FROM downloads WHERE id = ?",
                            (rid,)).fetchone())
    where = key(path) if path is not None else row["path"]
    size, files = _measure(row["kind"], where)
    complete = 0 if failed else int(loadable(row["kind"], where))
    needs = (requires_in(config_of(where), row["repo"])
             if row["kind"] == HUB and complete else [])
    conn.execute(
        "UPDATE downloads SET path = ?, bytes = ?, files = ?, complete = ?, "
        "requires = ?, finished_at = ? WHERE id = ?",
        (where, size, files, complete, json.dumps(needs), time.time(), rid))
    conn.commit()
    return {**row, "path": where, "bytes": size, "files": files,
            "complete": complete, "requires": json.dumps(needs)}


def record(conn, repo: str, kind: str, path, *, file: str = "",
           origin: str = FETCH, source: str = "", proposal: str = "",
           at: float | None = None) -> dict:
    """A download that already happened, measured now."""
    rid = start(conn, repo, kind, path, file=file, origin=origin,
                proposal=proposal)
    conn.execute("UPDATE downloads SET started_at = ?, source = ?, "
                 "repo = CASE WHEN repo = '' THEN ? ELSE repo END WHERE id = ?",
                 (time.time() if at is None else at, source, repo, rid))
    got = finish(conn, rid)
    if at is not None:
        conn.execute("UPDATE downloads SET finished_at = ? WHERE id = ?",
                     (at, rid))
        conn.commit()
    return got


def removed(conn, path, *, by: str, verdict_id=None, repo: str = "",
            kind: str = "", bytes_: int = 0, at: float | None = None,
            origin: str = "") -> int:
    """Stamp the live row for `path` removed; insert one if nothing recorded it."""
    at = time.time() if at is None else at
    got = live(conn, path=path)
    if got:
        for r in got:
            conn.execute(
                "UPDATE downloads SET removed_at = ?, removed_by = ?, "
                "removal_verdict_id = ?, complete = 0 WHERE id = ?",
                (at, by, verdict_id, r["id"]))
        conn.commit()
        return got[0]["id"]
    kind = kind or (GGUF if str(path).lower().endswith(".gguf") else HUB)
    rid = conn.execute(
        "INSERT INTO downloads (proposal_id, repo, kind, path, file, origin, "
        "bytes, machine_id, removed_at, removed_by, removal_verdict_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (_proposal(conn, repo), repo, kind, key(path), Path(path).name,
         origin or SCAN, int(bytes_), this_machine(conn), at, by,
         verdict_id)).lastrowid
    conn.commit()
    return rid


def _complete(conn, repo: str, kind: str = "", stat: bool = True) -> list[dict]:
    rows = [r for r in live(conn, repo=repo, kind=kind) if r["complete"]]
    return [r for r in rows if not stat or Path(r["path"]).exists()]


def have(repo: str, conn=None, *, stat: bool = True) -> bool:
    """A complete download of `repo` on this machine, still present."""
    with store(conn) as c:
        return bool(_complete(c, repo, stat=stat))


def path_of(repo: str, conn=None, kind: str = "") -> Path | None:
    """Where `repo`'s weights are: its GGUF file first, else its hub dir."""
    with store(conn) as c:
        rows = _complete(c, repo, kind)
    rows.sort(key=lambda r: (r["kind"] != GGUF, -r["id"]))
    return Path(rows[0]["path"]) if rows else None


def requires(repo: str, conn=None) -> list[str]:
    """Other repos this download's own config named, as recorded."""
    with store(conn) as c:
        rows = _complete(c, repo, HUB, stat=False)
    out = set()
    for r in rows:
        try:
            out.update(json.loads(r["requires"] or "[]"))
        except ValueError:
            continue
    return sorted(out)


def complete_hub(conn) -> list[dict]:
    """Every complete hub download on this machine, still present."""
    with store(conn) as c:
        rows = [r for r in live(c, kind=HUB) if r["complete"]]
    return [r for r in rows if Path(r["path"]).exists()]


def in_flight(row: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return (row.get("started_at") is not None and row.get("finished_at") is None
            and now - float(row["started_at"]) < IN_FLIGHT_SECONDS)


def scan(hub: Path, ggufs: Path) -> list[tuple[str, Path]]:
    """What is physically there: (kind, path), symlinked repo dirs skipped."""
    out = []
    if hub.is_dir():
        for d in sorted(hub.iterdir()):
            if d.name.startswith("models--") and d.is_dir() \
                    and not d.is_symlink():
                out.append((HUB, d))
    if ggufs.is_dir():
        for f in sorted(ggufs.iterdir()):
            if f.name.lower().endswith(".gguf"):
                out.append((GGUF, f))
    return out


def drift(conn, hub: Path | None = None, ggufs: Path | None = None) -> dict:
    """Rows whose path is gone, and paths on disk no row explains."""
    hub = Path(hub) if hub is not None else hub_root()
    ggufs = Path(ggufs) if ggufs is not None else gguf_root()
    rows = live(conn)
    gone = [r for r in rows
            if r["origin"] != PARTIAL and not os.path.lexists(r["path"])]
    known = {r["path"] for r in rows}
    unrecorded = [str(p) for _, p in scan(hub, ggufs) if key(p) not in known]
    return {"gone": gone, "unrecorded": unrecorded}


def _gguf_repo(conn, f: Path, sources: dict) -> tuple[str, str]:
    """(repo, link target) for a GGUF file: its hub row, else the gateway's map."""
    if f.is_symlink():
        target = os.path.realpath(f)
        for r in live(conn, kind=HUB):
            if target.startswith(os.path.realpath(r["path"]) + os.sep):
                return r["repo"], target
        return sources.get(f.name, ""), target
    return sources.get(f.name, ""), ""


def record_unrecorded(conn, hub: Path | None = None,
                      ggufs: Path | None = None, sources: dict | None = None,
                      origin: str = SCAN) -> dict:
    """`lh disk --record`: a row for each present path, gone rows stamped."""
    hub = Path(hub) if hub is not None else hub_root()
    ggufs = Path(ggufs) if ggufs is not None else gguf_root()
    if sources is None:
        sources = gateway_sources()
    got = drift(conn, hub, ggufs)
    for r in got["gone"]:
        removed(conn, r["path"], by="absent at " + origin)
    for kind, p in [x for x in scan(hub, ggufs) if x[0] == HUB] + \
            [x for x in scan(hub, ggufs) if x[0] == GGUF]:
        if str(p) not in got["unrecorded"]:
            continue
        if kind == HUB:
            record(conn, _repo_from_dir(p.name), HUB, p, origin=origin)
        else:
            repo, target = _gguf_repo(conn, p, sources)
            record(conn, repo, GGUF, p, file=p.name,
                   origin=LINK if target else origin, source=target)
    return {"recorded": len(got["unrecorded"]), "gone": len(got["gone"])}


def gateway_sources() -> dict:
    """source_file -> source_repo from the gateway configs."""
    from harness import disk
    out: dict = {}
    try:
        disk._aliases(disk._gateway_files(), out)
    except Exception:  # noqa: BLE001
        return {}
    return out


def snapshot_dir(path: Path) -> Path:
    return path.parent.parent if path.parent.name == "snapshots" else path


def backfill(conn, hub: Path | None = None, ggufs: Path | None = None,
             manifest: Path | None = None) -> dict:
    """Fill `downloads` once from what the store and disk already hold. Reads
    the weights dirs; never writes them."""
    from harness import paths
    hub = Path(hub) if hub is not None else hub_root()
    ggufs = Path(ggufs) if ggufs is not None else gguf_root()
    manifest = (Path(manifest) if manifest is not None
                else paths.home() / "gguf-sources.json")
    now = time.time()
    counts = {"fetch_verdicts": 0, "manifest": 0, "removals": 0, "scanned": 0}

    removals: dict = {}
    if _has_table(conn, "disk_removals"):
        for r in conn.execute("SELECT * FROM disk_removals ORDER BY id"):
            removals.setdefault(key(r["path"]), []).append(dict(r))
    stamped, done = set(), set()

    def settle(rid, row_path):
        if os.path.lexists(row_path):
            return
        gone = removals.get(key(row_path))
        if gone:
            last = max(gone, key=lambda r: r["removed_at"])
            stamped.add(last["id"])
            by, at, vid = last["source"] or "lh disk", last["removed_at"], \
                last["verdict_id"]
        else:
            by, at, vid = "absent at backfill", now, None
        conn.execute("UPDATE downloads SET removed_at = ?, removed_by = ?, "
                     "removal_verdict_id = ?, complete = 0 WHERE id = ?",
                     (at, by, vid, rid))

    def once(repo, kind, where, **kw):
        if key(where) in done:
            return
        done.add(key(where))
        # A retried migration finds this path's row, live or removed. #496.
        if conn.execute("SELECT 1 FROM downloads WHERE path = ?",
                        (key(where),)).fetchone():
            return
        got = record(conn, repo, kind, where, **kw)
        settle(got["id"], got["path"])
        return got

    for v in conn.execute(
            "SELECT v.id, v.run_path, v.decided_at, p.name FROM verdicts v "
            "JOIN proposals p ON p.id = v.proposal_id "
            "WHERE v.tier = 'fetch' AND v.run_path != '' ORDER BY v.id DESC"
            ).fetchall():
        p = Path(v["run_path"])
        kind = GGUF if p.name.lower().endswith(".gguf") else HUB
        once(v["name"], kind, p if kind == GGUF else snapshot_dir(p),
             file=p.name if kind == GGUF else "", origin=BACKFILL,
             at=float(v["decided_at"]))
        counts["fetch_verdicts"] += 1
    conn.execute("UPDATE verdicts SET run_path = '' "
                 "WHERE tier = 'fetch' AND run_path != '' AND run_id IS NULL")

    try:
        listed = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        listed = {}
    for repo, filename in sorted((listed or {}).items()):
        f = ggufs / str(filename)
        target = os.path.realpath(f) if f.is_symlink() else ""
        once(repo, GGUF, f, file=str(filename),
             origin=LINK if target else BACKFILL, source=target)
        counts["manifest"] += 1

    # A removal no row took is history: its own removed row, never a live one.
    for r in [r for rs in removals.values() for r in rs]:
        counts["removals"] += 1
        if r["id"] in stamped:
            continue
        partial = r["grp"] == "incomplete"
        repo = r["repo"] or ""
        if partial:
            owner = conn.execute(
                "SELECT repo FROM downloads WHERE path = ? ORDER BY id DESC",
                (key(Path(r["path"]).parent.parent),)).fetchone()
            repo = owner["repo"] if owner else ""
        conn.execute(
            "INSERT INTO downloads (proposal_id, repo, kind, path, file, "
            "origin, bytes, machine_id, removed_at, removed_by, "
            "removal_verdict_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_proposal(conn, repo), repo,
             GGUF if r["path"].lower().endswith(".gguf") else HUB,
             key(r["path"]), Path(r["path"]).name,
             PARTIAL if partial else BACKFILL, int(r["bytes"] or 0),
             this_machine(conn), r["removed_at"], r["source"] or "lh disk",
             r["verdict_id"]))
    if _has_table(conn, "disk_removals"):
        conn.execute("DROP TABLE disk_removals")

    counts["scanned"] = record_unrecorded(conn, hub, ggufs,
                                          origin=BACKFILL)["recorded"]
    conn.commit()
    return counts


def _has_table(conn, table: str) -> bool:
    from harness import memory_store as ms
    return bool(ms._columns(conn, table))


def summary(conn) -> dict:
    """Rows by kind, complete or not, removed or not."""
    out = {}
    for r in conn.execute(
            "SELECT kind, complete, removed_at IS NOT NULL AS gone, "
            "COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS b FROM downloads "
            "GROUP BY kind, complete, removed_at IS NOT NULL"):
        state = ("removed" if r["gone"] else
                 "complete" if r["complete"] else "incomplete")
        k = out.setdefault(r["kind"], {})
        k[state] = {"count": r["n"], "bytes": r["b"]}
    return out

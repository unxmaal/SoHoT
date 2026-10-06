"""What the weights cache holds, what uses it, and what may go. #370, #373.

The hub tree and the GGUF dir say what is physically present; the downloads
table says what each path is (#411). A path with no row is drift: reported,
never named by guessing, and never deleted.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from harness import downloads

KEEP, QUEUED, REJECTED, UNKNOWN = "keep", "queued", "rejected", "unknown"
GROUPS = (KEEP, QUEUED, REJECTED, UNKNOWN)

#: Rejected weights survive this long so a harness-fault verdict can be re-screened.
GRACE_SECONDS = 24 * 3600

REJECTIONS = ("broken", "declined")
#: Tiers that run after weights are fetched; an inspect refusal never downloaded anything.
FETCHED_TIERS = ("fetch", "screen", "measure", "adopt")
WAITING = ("queued", "screened")

#: Weights no alias names and the harness still loads. One list; grep before editing.
TOOLING = {
    "yuvalkirstain/PickScore_v1": "image adherence scorer (checks/adherence.py)",
    "laion/CLIP-ViT-H-14-laion2B-s32B-b79K": "PickScore processor",
    "xswu/HPSv2": "image adherence scorer (checks/adherence.py)",
    "litmudoc/Chatterbox-Multilingual-MLX-v2-Q8": "cloned voice presets",
    "mlx-community/S3TokenizerV2": "Chatterbox speech tokenizer",
    "mlx-community/whisper-large-v3-mlx": "multilingual stt (audio.py)",
    "microsoft/wavlm-base-plus-sv": "speaker model",
}

#: Engine specs whose weights are not named by the spec itself.
ENGINE_REPOS = {
    "mflux:flux2-klein-4b": ("black-forest-labs/FLUX.2-klein-4B",),
    "h3": ("MiniMaxAI/MiniMax-H3",),
    "acestep": ("ACE-Step/Ace-Step1.5", "ACE-Step/acestep-5Hz-lm-0.6B"),
}

UNRECORDED = "no download row; `lh disk --record` names it"


@dataclass
class Entry:
    kind: str
    path: str
    name: str
    repo: str = ""
    size: int = 0
    mtime: float = 0.0
    group: str = UNKNOWN
    why: str = ""
    outcome: str = ""
    tier: str = ""
    decided_at: float = 0.0
    verdict_id: int | None = None
    links: list = field(default_factory=list)
    download_id: int | None = None
    proposal_ids: list = field(default_factory=list)
    unrecorded: bool = False


@dataclass
class Keepers:
    repos: dict = field(default_factory=dict)
    stems: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)


@dataclass
class Inventory:
    hub: str
    gguf: str
    entries: list
    incomplete: list
    problems: list
    gone: list = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.problems


def hub_root() -> Path:
    return downloads.hub_root()


def gguf_root() -> Path:
    return downloads.gguf_root()


def _stem(filename: str) -> str:
    name = filename.lower()
    return name[:-len(".gguf")] if name.endswith(".gguf") else name


def _gateway_files() -> list[Path]:
    from harness import gateway
    found = sorted((gateway.REPO / "gateway").glob("config*.yaml"))
    extra = os.environ.get(gateway.ENV_VAR)
    if extra and Path(extra) not in found:
        found.append(Path(extra))
    return found


def _aliases(files, sources: dict | None = None) -> tuple[dict, list]:
    """alias name -> (repos, stems), and what could not be read."""
    from harness import gateway
    out, problems = {}, []
    sources = {} if sources is None else sources
    for path in files:
        data = gateway.load(path)
        entries = data.get("model_list") or []
        if not entries:
            problems.append(f"gateway config {path} has no models")
        for e in entries:
            repos, stems = set(), set()
            if e.get("source_repo"):
                repos.add(str(e["source_repo"]))
            if e.get("source_file"):
                stems.add(_stem(str(e["source_file"])))
                if e.get("source_repo"):
                    sources.setdefault(str(e["source_file"]),
                                       str(e["source_repo"]))
            model = gateway.strip_provider(
                (e.get("litellm_params") or {}).get("model", ""))
            if "/" in model:
                repos.add(model)
            elif model:
                stems.add(_stem(model))
            name = str(e.get("model_name") or "")
            got = out.setdefault(name, (set(), set()))
            got[0].update(repos)
            got[1].update(stems)
    return out, problems


def _stored(conn, spec: str) -> tuple[set, set]:
    """The repos and GGUF stems the candidate row for `spec` owns. #407, #429."""
    if conn is None or not spec:
        return set(), set()
    repos, stems = set(), set()
    for r in conn.execute(
            "SELECT p.name, d.repo, d.kind, d.file FROM candidates c "
            "JOIN proposals p ON p.id = c.proposal_id "
            "LEFT JOIN downloads d ON d.proposal_id = p.id "
            "AND d.removed_at IS NULL WHERE c.spec = ?", (spec,)).fetchall():
        repos.add(r["name"])
        if r["repo"]:
            repos.add(r["repo"])
        if r["kind"] == downloads.GGUF and r["file"]:
            stems.add(_stem(r["file"]))
    return repos, stems


def _resolve(spec: str, aliases: dict, conn=None) -> tuple[set, set]:
    """The repos and GGUF stems an engine spec or alias loads."""
    s = (spec or "").strip()
    if s in aliases:
        return set(aliases[s][0]), set(aliases[s][1])
    bare = s.split(",", 1)[0].split("@", 1)[0].lower()
    if bare.startswith("llamacpp:"):
        return set(), {_stem(bare.split(":", 1)[1])}
    head = re.split(r"[:/]", bare, maxsplit=1)[0]
    for key in (bare, head):
        if key in ENGINE_REPOS:
            return set(ENGINE_REPOS[key]), set()
    repos, stems = _stored(conn, s)
    if ":" not in s and "," not in s and "/" in s:
        # A typed default with no engine is the repo id itself.
        repos.add(s)
    return repos, stems


def keepers(conn=None, gateway_files=None, typed=None, adopted=None) -> Keepers:
    """Everything that must never be deleted, with why."""
    k = Keepers()
    aliases, k.problems = _aliases(
        _gateway_files() if gateway_files is None else gateway_files)
    if not aliases:
        k.problems.append("no gateway aliases could be read")

    def add(spec: str, why: str) -> None:
        repos, stems = _resolve(spec, aliases, conn)
        for r in repos:
            k.repos.setdefault(r.lower(), why)
        for s in stems:
            k.stems.setdefault(s, why)
        if not repos and not stems:
            k.problems.append(f"{why}: {spec!r} names no weights")

    for name in aliases:
        add(name, f"alias {name}")
    if typed is None:
        from harness import winners
        typed = winners.typed()
    for lane, spec in typed.items():
        add(spec, f"{lane} default")
    if adopted is None and conn is not None:
        from harness import adopt
        # Every machine's, not only this one's: the weights may be shared. #412.
        adopted = adopt.everywhere(conn)
    for lane, specs in (adopted or {}).items():
        for spec in sorted({specs} if isinstance(specs, str) else specs):
            add(spec, f"{lane} adopted winner")
    for repo, why in TOOLING.items():
        k.repos.setdefault(repo.lower(), f"tooling: {why}")
    return k


def latest_verdicts(conn) -> dict:
    """Each proposal's state and the verdict that set it, by name. #409."""
    rows = conn.execute(
        "SELECT p.name, p.id AS pid, v.id, p.state AS outcome, v.tier, "
        "v.decided_at FROM proposals p JOIN verdicts v "
        "ON v.id = p.state_verdict_id ORDER BY v.id").fetchall()
    return {str(r["name"]).lower(): dict(r) for r in rows}


def _du(path: Path) -> tuple[int, float]:
    size, newest = 0, 0.0
    for top, dirs, files in os.walk(path, followlinks=False):
        for f in files:
            st = os.lstat(os.path.join(top, f))
            if not os.path.islink(os.path.join(top, f)):
                size += st.st_size
            newest = max(newest, st.st_mtime)
    return size, newest


def _rows(conn) -> dict:
    """This machine's live download rows, by path."""
    if conn is None:
        return {}
    out = {}
    for r in downloads.live(conn):
        out.setdefault(r["path"], r)
    return out


def _named(e: Entry, row: dict | None) -> None:
    if row is None:
        e.unrecorded = True
        return
    e.repo, e.download_id = row["repo"] or "", row["id"]
    if row.get("proposal_id"):
        e.proposal_ids.append(row["proposal_id"])
    if e.kind == downloads.HUB and e.repo:
        e.name = e.repo


def _scan(hub: Path, ggufs: Path, rows: dict) -> tuple[list, list]:
    entries, by_dir = [], {}
    for kind, p in downloads.scan(hub, ggufs):
        if kind == downloads.HUB:
            size, mtime = _du(p)
            e = Entry("hub", str(p), p.name, "", size, mtime)
            _named(e, rows.get(downloads.key(p)))
            entries.append(e)
            by_dir[p.name] = e
    hub_real = hub.resolve() if hub.exists() else hub
    for kind, f in downloads.scan(hub, ggufs):
        if kind != downloads.GGUF:
            continue
        row = rows.get(downloads.key(f))
        if f.is_symlink():
            target = Path(os.path.realpath(f))
            try:
                top = target.relative_to(hub_real).parts[0]
            except (ValueError, IndexError):
                top = ""
            if top in by_dir:
                owner = by_dir[top]
                owner.links.append(str(f))
                if row and row.get("proposal_id"):
                    owner.proposal_ids.append(row["proposal_id"])
                continue
            st = os.lstat(f)
            e = Entry("gguf", str(f), f.name, "", 0, st.st_mtime)
        else:
            st = f.stat()
            e = Entry("gguf", str(f), f.name, "", st.st_size, st.st_mtime)
        _named(e, row)
        entries.append(e)
    incomplete = []
    if hub.is_dir():
        for blob in sorted(hub.glob("models--*/blobs/*.incomplete")):
            st = os.lstat(blob)
            incomplete.append({"path": str(blob), "size": st.st_size,
                               "mtime": st.st_mtime,
                               "dir": str(blob.parent.parent)})
    return entries, incomplete


def _proposal_ids(e: Entry) -> set:
    """The proposals this entry's download rows name. #411, #429."""
    return set(e.proposal_ids)


def _stems(e: Entry) -> list[str]:
    stems = [_stem(Path(p).name) for p in e.links]
    if e.kind == "gguf":
        stems.append(_stem(e.name))
    return stems


def _classify(e: Entry, k: Keepers, verdicts: dict, conn=None) -> None:
    by_pid = {r["pid"]: r for r in verdicts.values()}
    seen = [by_pid[i] for i in _proposal_ids(e) if i in by_pid]
    last = max(seen, key=lambda r: r["id"]) if seen else None
    if last:
        e.outcome, e.tier = last["outcome"], last["tier"]
        e.decided_at, e.verdict_id = float(last["decided_at"]), last["id"]
    why = (k.repos.get(e.repo.lower()) if e.repo else None) \
        or next((k.stems[s] for s in _stems(e) if s in k.stems), None)
    if why:
        e.group, e.why = KEEP, why
    elif e.unrecorded:
        e.group, e.why = UNKNOWN, UNRECORDED
    elif last and last["outcome"] == "measured":
        e.group, e.why = KEEP, f"measured at {last['tier']}"
    elif last and last["outcome"] in WAITING:
        e.group, e.why = QUEUED, f"{last['outcome']} at {last['tier']}"
    elif last and last["outcome"] in REJECTIONS \
            and last["tier"] in FETCHED_TIERS:
        e.group, e.why = REJECTED, f"{last['outcome']} at {last['tier']}"
    else:
        e.group = UNKNOWN
        e.why = (f"{last['outcome']} at {last['tier']}" if last
                 else "no alias, no verdict, not tooling")


def inventory(conn=None, hub: Path | None = None, ggufs: Path | None = None,
              keep: Keepers | None = None) -> Inventory:
    hub = Path(hub) if hub is not None else hub_root()
    ggufs = Path(ggufs) if ggufs is not None else gguf_root()
    problems = []
    verdicts = {}
    if conn is None:
        problems.append("no discovery store")
    else:
        verdicts = latest_verdicts(conn)
    keep = keep if keep is not None else keepers(conn)
    problems += keep.problems
    entries, incomplete = _scan(hub, ggufs, _rows(conn))
    for e in entries:
        _classify(e, keep, verdicts, conn)
    gone = downloads.drift(conn, hub, ggufs)["gone"] if conn is not None else []
    return Inventory(str(hub), str(ggufs), entries, incomplete, problems, gone)


def _inside(path: Path, root: Path) -> bool:
    """`path` sits directly in `root`, judged without following `path` itself."""
    try:
        parent = Path(os.path.realpath(path.parent))
        return root.exists() and parent == root.resolve() \
            and path.name not in ("", ".", "..")
    except OSError:
        return False


def safe_to_delete(e: Entry, now: float, wanted: str = REJECTED,
                   roots: tuple = ()) -> tuple[bool, str]:
    """The one decision `lh disk` and discovery share."""
    if e.group == KEEP:
        return False, f"kept: {e.why}"
    if e.unrecorded:
        return False, f"refused: {UNRECORDED}"
    if e.group != wanted or wanted not in (REJECTED, UNKNOWN):
        return False, f"{e.group}, not {wanted}"
    if e.group == REJECTED and now - e.decided_at < GRACE_SECONDS:
        return False, "rejected less than 24 h ago"
    root = next((Path(r) for r in roots if _inside(Path(e.path), Path(r))),
                None)
    if root is None:
        return False, f"refused: {e.path} is outside {', '.join(map(str, roots))}"
    return True, e.why


def record(conn, rows: list[dict], source: str) -> None:
    """Stamp each removed path's download row. #411."""
    if conn is None:
        return
    for r in rows:
        for p in [r["path"]] + list(r.get("links") or []):
            downloads.removed(conn, p, by=source,
                              verdict_id=r.get("verdict_id"),
                              repo=r.get("repo", ""),
                              bytes_=int(r["bytes"]) if p == r["path"] else 0,
                              at=r["at"], origin=r.get("origin", ""))


def _remove(e: Entry, hub: Path, ggufs: Path) -> list[str]:
    """Delete one entry; returns the symlinks that went with it."""
    path = Path(e.path)
    gone = []
    if e.kind == "hub":
        if path.is_symlink() or not _inside(path, hub):
            raise OSError(f"refused: {path}")
        for link in e.links:
            if Path(link).is_symlink() and _inside(Path(link), ggufs):
                os.unlink(link)
                gone.append(link)
        shutil.rmtree(path)
        return gone
    if not _inside(path, ggufs):
        raise OSError(f"refused: {path}")
    if path.is_symlink():
        os.unlink(path)
        return gone
    real = path.resolve()
    for other in ggufs.iterdir():
        if other.is_symlink() and Path(os.path.realpath(other)) == real:
            os.unlink(other)
            gone.append(str(other))
    os.unlink(path)
    return gone


def plan(inv: Inventory, now: float, wanted: str = REJECTED) -> list[Entry]:
    roots = (inv.hub, inv.gguf)
    return [e for e in inv.entries if safe_to_delete(e, now, wanted, roots)[0]]


def delete(inv: Inventory, now: float, wanted: str = REJECTED, conn=None,
           source: str = "lh disk") -> list[dict]:
    """Remove what safe_to_delete allows; refuse everything if keepers are unknown."""
    if not inv.complete:
        raise RuntimeError("refusing to delete: " + "; ".join(inv.problems))
    hub, ggufs = Path(inv.hub), Path(inv.gguf)
    removed = []
    for e in plan(inv, now, wanted):
        try:
            links = _remove(e, hub, ggufs)
        except OSError as exc:
            removed.append({"path": e.path, "error": str(exc)})
            continue
        removed.append({"path": e.path, "repo": e.repo, "group": e.group,
                        "bytes": e.size, "verdict_id": e.verdict_id,
                        "links": links, "at": time.time()})
    record(conn, [r for r in removed if "error" not in r], source)
    return removed


def clear_incomplete(inv: Inventory, conn=None, source: str = "discover",
                     now: float | None = None) -> list[dict]:
    """Partial blobs of a recorded download no live fetch is writing. #411."""
    if conn is None:
        return []
    hub = Path(inv.hub).resolve()
    rows = _rows(conn)
    removed = []
    for blob in inv.incomplete:
        path = Path(blob["path"])
        row = rows.get(downloads.key(blob["dir"]))
        if row is None or downloads.in_flight(row, now) or path.is_symlink():
            continue
        try:
            path.resolve().relative_to(hub)
        except ValueError:
            continue
        try:
            os.unlink(path)
        except OSError:
            continue
        removed.append({"path": str(path), "group": "incomplete",
                        "repo": row["repo"], "bytes": blob["size"],
                        "origin": downloads.PARTIAL, "at": time.time()})
    record(conn, removed, source)
    return removed


def clean(inv: Inventory, run_start: float, conn=None) -> dict:
    """Discovery's own cleanup: rejected past grace, and orphaned partial downloads."""
    gone = delete(inv, run_start, REJECTED, conn, source="discover")
    partial = clear_incomplete(inv, conn, now=run_start)
    ok = [r for r in gone if "error" not in r]
    return {"rejected": ok, "incomplete": partial,
            "errors": [r for r in gone if "error" in r],
            "bytes": sum(r["bytes"] for r in ok + partial)}


def sweep(run_start: float | None = None, say=print) -> dict:
    """What `lh discover --loop --run` calls first. Never raises."""
    from harness import memory_store as ms
    run_start = time.time() if run_start is None else run_start
    try:
        conn = ms.connect()
    except Exception as exc:  # noqa: BLE001
        say(f"  disk cleanup skipped: {exc}")
        return {}
    try:
        got = clean(inventory(conn), run_start, conn)
    except Exception as exc:  # noqa: BLE001
        say(f"  disk cleanup skipped: {exc}")
        return {}
    finally:
        conn.close()
    say(f"  freed {gib(got['bytes'])} GiB: {len(got['rejected'])} rejected "
        f"past 24 h, {len(got['incomplete'])} partial download(s)")
    for r in got["rejected"]:
        say(f"    {gib(r['bytes']):>7} GiB  {r['repo'] or r['path']}")
    for r in got["errors"]:
        say(f"    not removed: {r['path']}: {r['error']}")
    return got


def gib(n: int) -> str:
    return f"{n / 1024 ** 3:.1f}"


def drift(inv: Inventory) -> dict:
    """Rows whose path is gone, and paths on disk no row explains."""
    return {"gone": [{"id": r["id"], "repo": r["repo"], "path": r["path"]}
                     for r in inv.gone],
            "unrecorded": [e.path for e in inv.entries if e.unrecorded]}


def summary(inv: Inventory, now: float) -> dict:
    groups = {g: {"count": 0, "bytes": 0} for g in GROUPS}
    for e in inv.entries:
        groups[e.group]["count"] += 1
        groups[e.group]["bytes"] += e.size
    due = plan(inv, now, REJECTED)
    d = drift(inv)
    return {"hub": inv.hub, "gguf": inv.gguf, "groups": groups,
            "rejected_due": {"count": len(due),
                             "bytes": sum(e.size for e in due)},
            "incomplete": {"count": len(inv.incomplete),
                           "bytes": sum(b["size"] for b in inv.incomplete)},
            "drift": {"gone": len(d["gone"]),
                      "unrecorded": len(d["unrecorded"])},
            "problems": inv.problems}


def as_json(inv: Inventory, now: float) -> dict:
    return {**summary(inv, now), "drift_rows": drift(inv),
            "entries": [asdict(e) for e in inv.entries]}


def table(inv: Inventory, now: float) -> str:
    lines = []
    for g in GROUPS:
        rows = sorted((e for e in inv.entries if e.group == g),
                      key=lambda e: -e.size)
        total = sum(e.size for e in rows)
        lines.append(f"\n{g}  {len(rows)} entries, {gib(total)} GiB")
        for e in rows:
            age = (now - e.mtime) / 86400 if e.mtime else 0
            due = ""
            if g == REJECTED:
                ok, why = safe_to_delete(e, now, REJECTED, (inv.hub, inv.gguf))
                due = "  due" if ok else "  (<24 h)" if "24 h" in why else ""
            lines.append(f"  {gib(e.size):>7} GiB {age:6.1f}d  "
                         f"{e.name:55} {e.why}{due}")
    s = summary(inv, now)
    lines.append(f"\nrejected past 24 h: {s['rejected_due']['count']}, "
                 f"{gib(s['rejected_due']['bytes'])} GiB")
    lines.append(f"partial downloads: {s['incomplete']['count']}, "
                 f"{gib(s['incomplete']['bytes'])} GiB")
    d = drift(inv)
    lines.append(f"drift: {len(d['gone'])} recorded path(s) gone, "
                 f"{len(d['unrecorded'])} on disk with no row")
    for r in d["gone"]:
        lines.append(f"  gone        {r['repo'] or '?':40} {r['path']}")
    for p in d["unrecorded"]:
        lines.append(f"  unrecorded  {p}")
    for p in inv.problems:
        lines.append(f"deletion disabled: {p}")
    return "\n".join(lines).lstrip("\n")

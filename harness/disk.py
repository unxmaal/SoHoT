"""What the weights cache holds, what uses it, and what may go. #370, #373.

The hub tree and the GGUF dir say what is physically present; the downloads
table says what each path is (#411). A path with no row is drift: reported,
never named by guessing, and never deleted.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from harness import downloads, lanes
from harness.memory_store.schema import WAYPOINTS

KEEP, QUEUED, REJECTED, UNKNOWN = "keep", "queued", "rejected", "unknown"
GROUPS = (KEEP, QUEUED, REJECTED, UNKNOWN)

#: Weights waiting this long for a screen, or with no owner, go; fetch takes queued ones again later. #2011.
QUEUED_DEADLINE_S = 7 * 24 * 3600
#: The removed_by of an eviction past QUEUED_DEADLINE_S.
EVICTED = "discover: queued past deadline"
#: The removed_by of weights with no owner, verdict or dependent past QUEUED_DEADLINE_S.
UNOWNED = "discover: no owner past deadline"

REJECTIONS = ("broken", "declined")
#: Tiers that run after weights are fetched; an inspect refusal never downloaded anything.
FETCHED_TIERS = ("fetch", "screen", "measure", "adopt")
WAITING = WAYPOINTS

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
    "h3": ("MiniMaxAI/MiniMax-H3",),
    "acestep": ("ACE-Step/Ace-Step1.5", "ACE-Step/acestep-5Hz-lm-0.6B"),
}

#: Engines that load nothing from the hub, so their spec keeps nothing. #562.
WEIGHTLESS = ("osocr", "bm25", "pii-regex")

#: mflux preset name -> the repo it loads, as mflux's ModelConfig names it. #554.
MFLUX_REPOS = {
    "dev": "black-forest-labs/FLUX.1-dev",
    "schnell": "black-forest-labs/FLUX.1-schnell",
    "krea-dev": "black-forest-labs/FLUX.1-Krea-dev",
    "dev-kontext": "black-forest-labs/FLUX.1-Kontext-dev",
    "dev-fill": "black-forest-labs/FLUX.1-Fill-dev",
    "dev-redux": "black-forest-labs/FLUX.1-Redux-dev",
    "dev-depth": "black-forest-labs/FLUX.1-Depth-dev",
    "dev-controlnet-canny": "black-forest-labs/FLUX.1-dev",
    "schnell-controlnet-canny": "black-forest-labs/FLUX.1-schnell",
    "dev-controlnet-upscaler": "black-forest-labs/FLUX.1-dev",
    "dev-fill-catvton": "black-forest-labs/FLUX.1-Fill-dev",
    "flux2-klein-4b": "black-forest-labs/FLUX.2-klein-4B",
    "flux2-klein": "black-forest-labs/FLUX.2-klein-4B",
    "flux2-klein-9b": "black-forest-labs/FLUX.2-klein-9B",
    "z-image-turbo": "Tongyi-MAI/Z-Image-Turbo",
    "z-image": "Tongyi-MAI/Z-Image",
    "qwen-image": "Qwen/Qwen-Image-2512",
    "fibo": "briaai/FIBO",
    "krea-2": "krea/Krea-2-Turbo",
    "krea2": "krea/Krea-2-Turbo",
    "ernie-image": "baidu/ERNIE-Image",
    "ernie-image-turbo": "baidu/ERNIE-Image-Turbo",
    "lens-turbo": "Comfy-Org/Lens",
    "boogu": "Boogu/Boogu-Image-0.1-Turbo",
    "ideogram-4": "ideogram-ai/ideogram-4-fp8",
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
    #: When a retest of this rejection is due; the retest fetches again. #704, #2011.
    retest_at: float | None = None
    links: list = field(default_factory=list)
    download_id: int | None = None
    proposal_ids: list = field(default_factory=list)
    unrecorded: bool = False
    #: When its download finished, 0 when unknown. #2011.
    fetched_at: float = 0.0
    #: (name, state) of each proposal its rows name. #2011.
    waits: list = field(default_factory=list)
    #: Repos its download's config named, which it needs beside itself. #2011.
    needs: list = field(default_factory=list)


@dataclass
class Keepers:
    repos: dict = field(default_factory=dict)
    stems: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    #: lane -> why: a winner there named no weights, so all that lane's are kept. #554.
    lanes: dict = field(default_factory=dict)


@dataclass
class Inventory:
    hub: str
    gguf: str
    entries: list
    incomplete: list
    problems: list
    gone: list = field(default_factory=list)
    #: waiting_bytes() when the inventory was taken. #2011.
    waiting: int = 0

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
            "AND d.state <> 'removed' WHERE c.spec = ?", (spec,)).fetchall():
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
    if head == "mflux" and bare.partition(":")[2] in MFLUX_REPOS:
        repos.add(MFLUX_REPOS[bare.partition(":")[2]])
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

    def add(spec: str, why: str, lane: str = "") -> None:
        repos, stems = _resolve(spec, aliases, conn)
        for r in repos:
            k.repos.setdefault(r.lower(), why)
        for s in stems:
            k.stems.setdefault(s, why)
        if repos or stems or spec.partition(":")[0].strip() in WEIGHTLESS:
            return
        if lane:
            k.lanes.setdefault(lanes.canonical(lane), (
                f"{why}: {spec!r} names no weights, so every {lane} "
                f"candidate's weights are kept"))
        else:
            k.problems.append(f"{why}: {spec!r} names no weights")

    for name in aliases:
        add(name, f"alias {name}")
    if typed is None:
        from harness import winners
        typed = winners.typed()
    for lane, spec in typed.items():
        add(spec, f"{lane} default", lane)
    if adopted is None and conn is not None:
        from harness import adopt
        # Every machine's, not only this one's: the weights may be shared. #412.
        adopted = adopt.everywhere(conn)
    for lane, specs in (adopted or {}).items():
        for spec in sorted({specs} if isinstance(specs, str) else specs):
            add(spec, f"{lane} adopted winner", lane)
    for repo, why in {**TOOLING, **owned()}.items():
        k.repos.setdefault(repo.lower(), f"tooling: {why}")
    return k


def owned() -> dict:
    """Weights the harness's own code loads by a constant, so a new one is kept without editing TOOLING. #2011."""
    from harness import canary, needle
    from harness.checks import staging
    from harness.commands import vision
    out = {staging.DETECTOR_REPO: "staging detector (checks/staging.py)",
           vision.PROBE_MODEL: "vision probe (commands/vision.py)",
           needle.REPO: "needle runner (needle.py)"}
    for p in canary.PLANTS:
        for repo in (p.challenger, p.incumbent):
            if "/" in repo:
                out.setdefault(repo, f"canary plant {p.name} (canary.py)")
    return out


def _dir_repo(e: Entry) -> str:
    """org/name from a hub dir models--org--name, for an entry no row names. #2011."""
    if e.kind != "hub" or not e.name.startswith("models--"):
        return ""
    return e.name.removeprefix("models--").replace("--", "/", 1)


def latest_verdicts(conn) -> dict:
    """Each proposal's state and the verdict that set it, by name. #409."""
    rows = conn.execute(
        "SELECT p.name, p.id AS pid, p.lane, v.id, p.state AS outcome, v.tier, "
        "v.decided_at, p.next_retest_at FROM proposals p JOIN verdicts v "
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
    e.fetched_at = float(row.get("finished_at") or 0)
    try:
        e.needs = [str(r) for r in json.loads(row.get("requires") or "[]")]
    except (TypeError, ValueError):
        e.needs = []
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


def _lane_kept(e: Entry, k: Keepers, by_pid: dict) -> str | None:
    """Why a lane fallback keeps this entry; a lane we cannot read counts as every lane."""
    if not k.lanes:
        return None
    seen = {lanes.canonical((by_pid.get(i) or {}).get("lane") or "")
            for i in _proposal_ids(e)} or {""}
    hit = next((k.lanes[x] for x in sorted(seen) if x in k.lanes), None)
    if hit:
        return hit
    if "" in seen:
        return "no lane recorded while " + "; ".join(
            k.lanes[x] for x in sorted(k.lanes))
    return None


def _classify(e: Entry, k: Keepers, verdicts: dict, conn=None) -> None:
    by_pid = {r["pid"]: r for r in verdicts.values()}
    seen = [by_pid[i] for i in _proposal_ids(e) if i in by_pid]
    last = max(seen, key=lambda r: r["id"]) if seen else None
    waiting = max((r for r in seen if r["outcome"] in WAITING), key=lambda r: r["id"], default=None)
    e.waits = sorted({(r["name"], r["outcome"]) for r in seen})
    if last:
        e.outcome, e.tier = last["outcome"], last["tier"]
        e.decided_at, e.verdict_id = float(last["decided_at"]), last["id"]
        e.retest_at = last.get("next_retest_at")
    repo = e.repo or _dir_repo(e)
    why = (k.repos.get(repo.lower()) if repo else None) \
        or next((k.stems[s] for s in _stems(e) if s in k.stems), None) \
        or _lane_kept(e, k, by_pid)
    if why:
        e.group, e.why = KEEP, why
    elif e.unrecorded:
        e.group, e.why = UNKNOWN, UNRECORDED
    elif last and last["outcome"] == "measured":
        e.group, e.why = KEEP, f"measured at {last['tier']}"
    elif waiting:
        # Another proposal still waits on these weights, whatever the newest verdict says. #2011.
        e.group, e.why = QUEUED, f"{waiting['outcome']} at {waiting['tier']}"
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
    _needed(entries, conn)
    gone = downloads.drift(conn, hub, ggufs)["gone"] if conn is not None else []
    return Inventory(str(hub), str(ggufs), entries, incomplete, problems, gone, waiting_bytes(conn))


def _needed(entries: list, conn=None) -> None:
    """An entry nothing else owns follows the candidates whose config or runner needs it: kept, waiting or rejected. #2011."""
    from harness import fetching
    users: dict = {}
    for e in entries:
        if e.group == UNKNOWN or not e.repo:
            continue
        for dep in {*e.needs, *fetching.runner_bases(e.repo, conn)}:
            users.setdefault(dep.lower(), []).append(e)
    for e in entries:
        if e.group != UNKNOWN or e.unrecorded:
            continue
        mine = users.get((e.repo or _dir_repo(e)).lower(), [])
        by = next(([u for u in mine if u.group == g] for g in (KEEP, QUEUED, REJECTED)
                   if any(u.group == g for u in mine)), [])
        if by:
            e.group, e.why = by[0].group, f"needed by {by[0].repo or by[0].name}: {by[0].why}"
            e.verdict_id = e.verdict_id or by[0].verdict_id


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
        hub_gguf = e.kind == "hub" and bool(e.repo) and any(Path(e.path).rglob("*.gguf"))
        try:
            links = _remove(e, hub, ggufs)
        except OSError as exc:
            removed.append({"path": e.path, "error": str(exc)})
            continue
        removed.append({"path": e.path, "repo": e.repo, "group": e.group,
                        "bytes": e.size, "verdict_id": e.verdict_id,
                        "links": links, "at": time.time(), "hub_gguf": hub_gguf})
    gone = [r for r in removed if "error" not in r]
    record(conn, gone, source)
    _tell_router(gone, ggufs)
    return removed


def _tell_router(gone: list[dict], ggufs: Path) -> None:
    """The router lists what it saw at startup, so note each GGUF stem and GGUF hub repo deleted from under it. #780."""
    from harness import gguf
    names = [r["repo"] for r in gone if r.get("hub_gguf")]
    for r in gone:
        names += [Path(p).stem for p in [r["path"]] + list(r.get("links") or [])
                  if Path(p).suffix.lower() == ".gguf" and _inside(Path(p), ggufs)]
    if names:
        gguf.note_removed(names)


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
        if row is None or downloads.in_flight(row) or path.is_symlink():
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


def waiting_bytes(conn) -> int:
    """Bytes of this machine's live downloads whose proposal still waits for a screen; fetch's backlog. #2011."""
    if conn is None:
        return 0
    rows = {}
    for r in downloads.live(conn):
        rows.setdefault(r["path"], r)
    pids = sorted({r["proposal_id"] for r in rows.values() if r.get("proposal_id")})
    if not pids:
        return 0
    queued = {r["id"] for r in conn.execute(
        f"SELECT id FROM proposals WHERE state = 'queued' AND id IN ({', '.join('?' * len(pids))})", pids)}
    return sum(int(r["bytes"] or 0) for r in rows.values() if r.get("proposal_id") in queued)


def overdue(inv: Inventory, now: float, deadline: float | None = None) -> list[tuple[Entry, str, bool]]:
    """(entry, why, past the deadline): weights waiting for a screen that will not come, or unknown past the deadline. #2011."""
    from harness import memory
    deadline = QUEUED_DEADLINE_S if deadline is None else deadline
    out = []
    for e in inv.entries:
        if e.group == UNKNOWN and not e.unrecorded and e.fetched_at and now - e.fetched_at > deadline:
            out.append((e, f"weights removed after {(now - e.fetched_at) / 86400:.0f} d with no owner, verdict "
                           f"or candidate that needs them", True))
            continue
        if e.group != QUEUED or e.unrecorded or not e.fetched_at or not e.waits \
                or not all(state == "queued" for _, state in e.waits):
            continue
        beside = memory.held_back(e.size / 1024 ** 3)
        if beside:
            out.append((e, f"weights removed, the screen can never load them: {beside}", False))
        elif now - e.fetched_at > deadline:
            out.append((e, f"weights removed after {(now - e.fetched_at) / 86400:.0f} d waiting for a screen; "
                           f"fetch takes them again when the screen backlog has room", True))
    return out


def evict(inv: Inventory, now: float, conn=None, deadline: float | None = None) -> list[dict]:
    """Remove overdue weights, stamped EVICTED (queued, sent back to fetch) or UNOWNED. #2011."""
    if conn is None or not inv.complete:
        return []
    from harness import cuts, reasons
    from harness import memory_store as ms
    hub, ggufs = Path(inv.hub), Path(inv.gguf)
    out = []
    for e, why, late in overdue(inv, now, deadline):
        try:
            links = _remove(e, hub, ggufs)
        except OSError as exc:
            out.append({"path": e.path, "error": str(exc)})
            continue
        out.append({"path": e.path, "repo": e.repo, "group": e.group, "bytes": e.size, "verdict_id": e.verdict_id,
                    "links": links, "at": time.time(), "names": [n for n, _ in e.waits],
                    "days": (now - e.fetched_at) / 86400, "why": why, "late": late})
    gone = [r for r in out if "error" not in r]
    record(conn, [r for r in gone if r["group"] == QUEUED], EVICTED)
    record(conn, [r for r in gone if r["group"] == UNKNOWN], UNOWNED)
    for r in gone:
        for name in r["names"] if r["group"] == QUEUED else ():
            ms.decide_or_skip(conn, name, "queued", tier="fetch", reason=reasons.LIMIT, detail=r["why"][:600])
    late = sum(1 for r in gone if r["late"])
    if late:
        cuts.cut("queued_deadline", "fetched or unowned weights removed past the deadline",
                 value=(QUEUED_DEADLINE_S if deadline is None else deadline), dropped=late, conn=conn)
    _tell_router(gone, ggufs)
    return out


def clean(inv: Inventory, run_start: float, conn=None) -> dict:
    """Discovery's own cleanup: rejected weights, weights queued past the deadline, and orphaned partial downloads."""
    gone = delete(inv, run_start, REJECTED, conn, source="discover")
    late = evict(inv, run_start, conn)
    partial = clear_incomplete(inv, conn, now=run_start)
    ok = [r for r in gone if "error" not in r]
    evicted = [r for r in late if "error" not in r]
    return {"rejected": ok, "evicted": evicted, "incomplete": partial,
            "errors": [r for r in gone + late if "error" in r],
            "bytes": sum(r["bytes"] for r in ok + evicted + partial)}


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
    say(f"  freed {gib(got['bytes'])} GiB: {len(got['rejected'])} rejected, {len(got['evicted'])} queued past "
        f"the deadline or with no owner, {len(got['incomplete'])} partial download(s)")
    for r in got["rejected"]:
        say(f"    {gib(r['bytes']):>7} GiB  {r['repo'] or r['path']}")
    for r in got["evicted"]:
        say(f"    {gib(r['bytes']):>7} GiB  {r['repo'] or r['path']}  ({r['why']})")
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
            "waiting_screen": {"bytes": inv.waiting, "cap": _cap()},
            "incomplete": {"count": len(inv.incomplete),
                           "bytes": sum(b["size"] for b in inv.incomplete)},
            "drift": {"gone": len(d["gone"]),
                      "unrecorded": len(d["unrecorded"])},
            "problems": inv.problems}


def _cap() -> int:
    from harness import fetching
    return fetching.SCREEN_BACKLOG


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
                due = "  due" if ok else f"  ({why})"
            lines.append(f"  {gib(e.size):>7} GiB {age:6.1f}d  "
                         f"{e.name:55} {e.why}{due}")
    s = summary(inv, now)
    lines.append(f"\nrejected due: {s['rejected_due']['count']}, "
                 f"{gib(s['rejected_due']['bytes'])} GiB")
    lines.append(f"waiting for a screen: {gib(inv.waiting)} GiB of the {gib(_cap())} GiB fetch backlog cap")
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

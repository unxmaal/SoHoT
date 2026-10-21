"""One GGUF file per repo, for llama-server's router. See README, #295."""
from __future__ import annotations

import os
import re
from pathlib import Path

#: First match wins; otherwise the largest file under the ceiling.
PREFERRED = ("q4_k_m", "q4_k_s", "iq4_xs", "q4_0", "q5_k_m", "q5_k_s")
_SPLIT = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)
_PART = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$", re.I)
#: A single file under this fraction of the smallest split variant is not the model. #438.
STRAY = 16
#: How long a restarted router has to answer before refresh_router says it gave up. #1012.
READY_TIMEOUT_S = 120.0
#: How often a restarted router is asked whether it answers yet. #1012.
READY_POLL_S = 0.5

def models_dir() -> Path:
    """Where llama-server's router reads (scripts/serve-llamacpp.sh)."""
    raw = os.environ.get("LLAMACPP_MODELS_DIR")
    if raw:
        return Path(raw)
    hf = os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface"
    return Path(hf) / "gguf"

def _servable(f: dict) -> bool:
    name = str(f.get("rfilename", ""))
    return (name.lower().endswith(".gguf") and "/" not in name
            and not name.lower().startswith("mmproj")
            and "imatrix" not in name.lower()
            and not _SPLIT.search(name))

def shard_sets(siblings) -> dict[str, int]:
    """Total bytes of each complete split variant, keyed by its stem. #438."""
    parts: dict[str, dict[int, int]] = {}
    want: dict[str, int] = {}
    for f in siblings or []:
        name = str(f.get("rfilename", ""))
        m = _PART.match(name)
        base = name.rsplit("/", 1)[-1].lower()
        if not m or base.startswith("mmproj") or "imatrix" in base:
            continue
        parts.setdefault(m.group(1), {})[int(m.group(2))] = int(f.get("size") or 0)
        want[m.group(1)] = int(m.group(3))
    return {stem: sum(p.values()) for stem, p in parts.items()
            if len(p) == want[stem] and all(p.values())}

def _singles(siblings) -> list[tuple[str, int]]:
    """Servable single files, less any stray far smaller than a split variant."""
    files = [(str(f["rfilename"]), int(f.get("size") or 0))
             for f in siblings or [] if _servable(f)]
    sets = shard_sets(siblings)
    floor = min(sets.values()) // STRAY if sets else 0
    return [(n, s) for n, s in files if s > 0 and s >= floor]

def smallest(siblings) -> int:
    """Bytes of the cheapest variant, single file or split set, or 0 if none."""
    sizes = [s for _, s in _singles(siblings)] + list(shard_sets(siblings).values())
    return min(sizes, default=0)

def only(siblings) -> bool:
    """GGUF weights and nothing MLX or torch could load instead."""
    names = [str(f.get("rfilename", "")).lower() for f in siblings or []]
    return (any(n.endswith(".gguf") for n in names)
            and not any(n.endswith(".safetensors") for n in names))

def gguf_first(siblings) -> bool:
    """GGUF-only, or top-level GGUF beside no config.json, so mlx-lm cannot load the repo. #911."""
    top = {str(f.get("rfilename", "")).lower() for f in siblings or []}
    return only(siblings) or ("config.json" not in top and any(map(_servable, siblings or [])))

def choose(siblings, ceiling: int) -> tuple[str, int] | None:
    """The file to fetch: (name, bytes), or None if none fits."""
    fits = [(n, s) for n, s in _singles(siblings) if s <= ceiling]
    for quant in PREFERRED:
        for name, size in fits:
            if quant in name.lower():
                return name, size
    return max(fits, key=lambda f: f[1]) if fits else None


def path_of(repo: str, conn=None) -> Path | None:
    """The recorded GGUF file for `repo` on this machine, if still there. #411."""
    from harness import downloads
    return downloads.path_of(repo, conn, kind=downloads.GGUF)


def fetched(repo: str, conn=None) -> str | None:
    """The stem llama-server's router serves this repo under, if on disk."""
    path = path_of(repo, conn)
    return path.name[:-len(".gguf")] if path else None


def _hub_pick(repo: str, conn=None):
    """(hub row, snapshot dir, file name) adopt() would link for `repo`, or None. A read."""
    from harness import downloads
    from harness import inspect as ins
    with downloads.store(conn) as c:
        rows = downloads.live(c, repo=repo, kind=downloads.HUB)
    for row in rows:
        snaps = Path(row["path"]) / "snapshots"
        if not row["complete"] or not snaps.is_dir():
            continue
        for snap in sorted(snaps.iterdir()):
            files = [{"rfilename": f.name, "size": f.stat().st_size}
                     for f in snap.iterdir() if f.is_file()]
            pick = choose(files, ins.ceiling_bytes()) if gguf_first(files) else None
            if pick:
                return row, snap, pick[0]
    return None


def hub_stem(repo: str, conn=None) -> str | None:
    """The stem a GGUF-only hub download of `repo` is served under once adopted. #583."""
    got = _hub_pick(repo, conn)
    return got[2][:-len(".gguf")] if got else None


def adopt(conn, repo: str) -> str:
    """Link a whole GGUF-only hub download into the router's dir. #301.

    A write the fetch tier makes for text-lane repos only (#303, RULE #334).
    """
    from harness import downloads
    if path_of(repo, conn):
        return ""
    got = _hub_pick(repo, conn)
    if not got:
        return ""
    row, snap, name = got
    models_dir().mkdir(parents=True, exist_ok=True)
    link = models_dir() / name
    target = (snap / name).resolve()
    if not link.exists():
        link.symlink_to(target)
    downloads.record(conn, row["repo"], downloads.GGUF, link,
                     file=name, origin=downloads.LINK, source=str(target))
    return name


def adopt_pending(conn, refresh: bool = True) -> list[str]:
    """adopt() each complete text-lane hub download that has no GGUF row."""
    from harness import downloads, lanes
    out, linked = [], []
    for row in downloads.complete_hub(conn):
        got = conn.execute(
            "SELECT lane FROM proposals WHERE id = ? OR lower(name) = ?",
            (row["proposal_id"], row["repo"].lower())).fetchone()
        name = got and lanes.canonical(got["lane"] or "") in lanes.GGUF_SERVED \
            and adopt(conn, row["repo"])
        if name:
            out.append(row["repo"])
            linked.append(Path(name).stem)
    if out:
        refresh_router(expect=tuple(linked)) if refresh else note_unlisted(linked)
    return out


#: GGUF stems a day fetch linked without restarting the router, under the soh home. #1084.
UNLISTED = "router-unlisted.json"


def _unlisted_path() -> Path:
    from harness import paths
    return paths.home() / UNLISTED


def unlisted() -> list[str]:
    import json
    try:
        got = json.loads(_unlisted_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(s) for s in got] if isinstance(got, list) else []


def note_unlisted(stems) -> None:
    """Remember stems the router does not list yet, for the next sweep to restart it once. #1084."""
    import json
    got = sorted(set(unlisted()) | {s for s in stems if s})
    path = _unlisted_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(got), encoding="utf-8")


def relist() -> str:
    """Restart the router once for what day fetches left unlisted; '' when there was nothing or it answered. #1084."""
    stems = tuple(unlisted())
    if not stems:
        return ""
    why = refresh_router(expect=stems)
    if not why:
        _unlisted_path().unlink(missing_ok=True)
    return why or ""


def router_restart_argv(platform: str) -> list[str]:
    """The command that restarts the llama-server router on this platform. #319, #327."""
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    if platform == "darwin":
        return [str(scripts / "launchd.sh"), "restart", "eval"]
    import sys
    return [sys.executable, str(scripts / "with-gpu-lock"), "bash",
            str(scripts / "services.sh"), "restart", "llamacpp"]


def router_ready(expect=(), get=None) -> bool:
    """True when the router answers /health ok and lists every stem in `expect`. #1012."""
    from harness import router
    ask = get or router._get
    try:
        if (ask("/health") or {}).get("status") != "ok":
            return False
    except Exception:  # noqa: BLE001
        return False
    have = router.statuses(get) if expect else {}
    return have is not None and all(s in have for s in expect if s)


def wait_router(expect=(), timeout=None, get=None, clock=None, sleep=None) -> str:
    """"" once router_ready, else why the wait gave up after `timeout` seconds. #1012."""
    import time
    from harness import router
    timeout = READY_TIMEOUT_S if timeout is None else timeout
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    end = clock() + timeout
    while not router_ready(expect, get):
        if clock() >= end:
            listing = f" listing {', '.join(s for s in expect if s)}" if any(expect) else ""
            return (f"the router at {router.url()} did not answer /health ok{listing} "
                    f"within {timeout:g} s of its restart")
        sleep(READY_POLL_S)
    return ""


def refresh_router(expect=(), run=None, wait=None) -> str:
    """Restart the eval server so its router sees a new file, then wait until it answers. #319, #1012."""
    import subprocess
    import sys
    (run or subprocess.run)(router_restart_argv(sys.platform), check=False)
    why = (wait or wait_router)(tuple(expect))
    if why:
        print(f"  router restart: {why}; a screen now would be refused_by_gateway", file=sys.stderr)
    return why


def download(repo: str, filename: str, hf_download=None, refresh=None,
             conn=None, origin: str = "") -> str:
    from harness import downloads
    if hf_download is None:
        from huggingface_hub import hf_hub_download

        def hf_download(repo, filename, local_dir):
            return hf_hub_download(repo_id=repo, filename=filename,
                                   local_dir=local_dir)
    models_dir().mkdir(parents=True, exist_ok=True)
    with downloads.store(conn) as c:
        rid = downloads.start(c, repo, downloads.GGUF, models_dir() / filename,
                              file=filename, origin=origin or downloads.FETCH)
        try:
            where = hf_download(repo, filename, str(models_dir()))
        except BaseException:
            downloads.finish(c, rid, failed=True)
            raise
        downloads.finish(c, rid)
    refresh() if refresh else refresh_router(expect=(Path(filename).stem,))
    return str(where)


def record_existing(path, repo: str = "", refresh=None, conn=None,
                    origin: str = "") -> str:
    """Record a GGUF already on disk, writing the row download() would have. #783.

    A file placed by hand is a real case: curl, a copy, an external drive. Until
    this existed, fetch-gguf.sh was the only way to get a row, and
    harness.context.plan iterates the store, so a hand-placed file got no plan
    and no preset section. It was still advertised, because the router lists
    --models-dir directly, so it served at the [*] defaults and nothing said
    why. Measured on a 12 GB card with a 32B: the unplanned defaults reached 98
    percent of host RAM and generated 2.07 tok/s against 2.52 planned.

    NOT HASHED. The downloads table has no hash column and the fetch path does
    not hash either, so a digest here would have nowhere to go and nothing to
    compare against. Recording exactly the columns the fetch path records is
    what keeps a hand-placed file indistinguishable from a fetched one
    everywhere downstream.
    """
    from harness import downloads
    path = Path(path)
    if path.suffix.lower() != ".gguf":
        raise ValueError(f"not a gguf: {path.name}")
    if not path.is_file():
        raise FileNotFoundError(path)
    # The router reads ONE directory. A row for a file outside it would price
    # VRAM in the plan for something that can never be loaded.
    where = models_dir().resolve()
    if path.resolve().parent != where:
        raise ValueError(f"{path.name} is outside the models dir {where}")
    with downloads.store(conn) as c:
        if downloads.live(c, path=path):
            raise ValueError(f"already recorded: {path.name}")
        # repo stays empty when provenance is unknown. Inventing one would have
        # the fetch tier believe in a hub repo nobody can re-fetch from.
        downloads.record(c, repo, downloads.GGUF, path, file=path.name,
                         origin=origin or downloads.SCRIPT)
    # The file was already visible to the router; the PLAN is what is new, and
    # the preset is only read at startup.
    refresh() if refresh else refresh_router(expect=(path.stem,))
    return path.name


def _usage() -> str:
    return ("usage: python -m harness.gguf REPO FILE.gguf\n"
            "       python -m harness.gguf record PATH [REPO]")


if __name__ == "__main__":
    import sys
    from harness import downloads as _downloads
    argv = sys.argv[1:]
    if argv[:1] == ["record"]:
        if len(argv) not in (2, 3):
            sys.exit(_usage())
        print(record_existing(argv[1], repo=argv[2] if len(argv) == 3 else "",
                              origin=_downloads.SCRIPT))
    elif len(argv) == 2:
        print(download(argv[0], argv[1], origin=_downloads.SCRIPT))
    else:
        sys.exit(_usage())

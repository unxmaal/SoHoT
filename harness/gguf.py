"""One GGUF file per repo, for llama-server's router. See README, #295."""
from __future__ import annotations

import os
import re
from pathlib import Path

#: First match wins; otherwise the largest file under the ceiling.
PREFERRED = ("q4_k_m", "q4_k_s", "iq4_xs", "q4_0", "q5_k_m", "q5_k_s")
_SPLIT = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)

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

def smallest(siblings) -> int:
    """The smallest file the router could serve, or 0 if none."""
    return min((int(f.get("size") or 0) for f in siblings or []
                if _servable(f) and f.get("size")), default=0)

def only(siblings) -> bool:
    """GGUF weights and nothing MLX or torch could load instead."""
    names = [str(f.get("rfilename", "")).lower() for f in siblings or []]
    return (any(n.endswith(".gguf") for n in names)
            and not any(n.endswith(".safetensors") for n in names))

def choose(siblings, ceiling: int) -> tuple[str, int] | None:
    """The file to fetch: (name, bytes), or None if none fits."""
    fits = [(str(f["rfilename"]), int(f.get("size") or 0))
            for f in siblings or [] if _servable(f)]
    fits = [(n, s) for n, s in fits if 0 < s <= ceiling]
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


def adopt(conn, repo: str) -> str:
    """Link a whole GGUF-only hub download into the router's dir. #301.

    A write the fetch tier makes for text-lane repos only (#303, RULE #334).
    """
    from harness import downloads
    from harness import inspect as ins
    if path_of(repo, conn):
        return ""
    for row in downloads.live(conn, repo=repo, kind=downloads.HUB):
        snaps = Path(row["path"]) / "snapshots"
        if not row["complete"] or not snaps.is_dir():
            continue
        for snap in sorted(snaps.iterdir()):
            files = [{"rfilename": f.name, "size": f.stat().st_size}
                     for f in snap.iterdir() if f.is_file()]
            pick = choose(files, ins.ceiling_bytes()) if only(files) else None
            if not pick:
                continue
            models_dir().mkdir(parents=True, exist_ok=True)
            link = models_dir() / pick[0]
            target = (snap / pick[0]).resolve()
            if not link.exists():
                link.symlink_to(target)
            downloads.record(conn, row["repo"], downloads.GGUF, link,
                             file=pick[0], origin=downloads.LINK,
                             source=str(target))
            return pick[0]
    return ""


def adopt_pending(conn) -> list[str]:
    """adopt() each complete text-lane hub download that has no GGUF row."""
    from harness import downloads, lanes
    out = []
    for row in downloads.complete_hub(conn):
        got = conn.execute(
            "SELECT lane FROM proposals WHERE id = ? OR lower(name) = ?",
            (row["proposal_id"], row["repo"].lower())).fetchone()
        if got and lanes.canonical(got["lane"] or "") in lanes.TEXT_SERVED \
                and adopt(conn, row["repo"]):
            out.append(row["repo"])
    return out


def refresh_router() -> None:
    """Restart the eval server so its router sees a new file. #319."""
    import subprocess
    import sys
    if sys.platform != "darwin":
        return
    script = Path(__file__).resolve().parents[1] / "scripts" / "launchd.sh"
    subprocess.run([str(script), "restart", "eval"], check=False)


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
    (refresh or refresh_router)()
    return str(where)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        sys.exit("usage: python -m harness.gguf REPO FILE.gguf")
    from harness import downloads as _downloads
    print(download(sys.argv[1], sys.argv[2], origin=_downloads.SCRIPT))

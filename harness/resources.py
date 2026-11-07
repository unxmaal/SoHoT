"""What a queued job needs: one resource class, each with how many jobs of it run at once. #1508."""
from __future__ import annotations

#: Loads a model on this machine's GPU; one at a time.
GPU = "gpu"
#: Waits on the network: a cloud-only eval, a download.
NETWORK = "network"
#: Reads or writes much of the disk: a copy, an export.
DISK = "disk"
#: Uses CPU only.
CPU = "cpu"
#: A deploy runs alone. #1506.
DEPLOY = "deploy"
CLASSES = (GPU, NETWORK, DISK, CPU)
#: soh verbs whose whole job is a download.
DOWNLOADS = ("fetch",)


def capacity(cls: str) -> int:
    """How many jobs of `cls` this machine's worker runs at once; a deploy has the machine to itself."""
    from harness import exclusive
    return {GPU: 1, NETWORK: max(1, int(exclusive.CLOUD_SLOTS)), DISK: 1, CPU: 1}.get(cls, 1)


def check(cls: str) -> str:
    """`cls` when it is a class a job may declare; else ValueError naming them."""
    if cls not in CLASSES:
        raise ValueError(f"a job's resource is one of {', '.join(CLASSES)}, not {cls!r}")
    return cls


def _verb(argv) -> str:
    words = [w for a in argv for w in str(a).split()]
    for i, w in enumerate(words):
        if w.rsplit("/", 1)[-1] in ("soh", "lh") or w == "harness.cli":
            return next((x for x in words[i + 1:] if not x.startswith("-")), "")
    return ""


def classify(argv, kind: str = "command") -> str:
    """The class of a job that declared none: a deploy, a cloud-only eval or a download, else gpu, as every job was. #1153."""
    from harness import exclusive
    if kind == DEPLOY:
        return DEPLOY
    try:
        from evals import run
        if run.argv_lock_kind(argv or []) in exclusive.CLOUD:
            return NETWORK
    except Exception:  # noqa: BLE001 - a job the rule cannot read waits for the GPU, as every job did before
        return GPU
    return NETWORK if _verb(argv or []) in DOWNLOADS else GPU


def of(job: dict) -> str:
    """A job's class: DEPLOY for a deploy, what it declared, else what its command is classified as."""
    if job.get("kind") == DEPLOY:
        return DEPLOY
    return job.get("resource") or classify(job.get("argv") or [], job.get("kind") or "command")

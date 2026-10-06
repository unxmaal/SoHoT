"""Download queued weights in the background, durably. Issue #62.

WHY NOT the MCP server's old in-memory queue: its jobs lived in memory and died
with the process, and it existed only inside that server. A
download queue that exists only while a server happens to be running is not
automatic, which was the requirement.

The durable queue already existed and was unused for this. `memory_store` has a
non-terminal `queued` verdict; marking a candidate queued is a fact that
survives a restart, and it is already the vocabulary the loop speaks. This
module is the worker for that queue, nothing more.

ONE AT A TIME, for the same reason generation is: this machine holds one
working set, and a download competing with an eval distorts the measurement it
was queued to make possible.

NOTHING IS EXECUTED. Fetching weights is not running them.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from harness import downloads
from harness import memory_store as ms
from harness import rank
from harness import lanes, reasons, screen

GIB = 1024 ** 3
#: Never fill the volume. A download that leaves no room is a download that
#: breaks the next eval rather than enabling it.
DISK_FLOOR = 50 * GIB
#: Refuse anything larger in one go, whatever the disk says.
MAX_DOWNLOAD = 60 * GIB


class FetchError(RuntimeError):
    """The download could not be started. Never a verdict about the model."""


@dataclass
class Plan:
    repo: str
    size: int
    ok: bool
    why: str
    #: verdicts.reason for a refusal, and what would end it. #408.
    reason: str = ""
    until: str = ""


def free_bytes(path: str | Path | None = None) -> int:
    import os
    target = Path(path) if path else Path(
        os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
    while not target.exists() and target != target.parent:
        target = target.parent
    return shutil.disk_usage(target).free


def plan(repo: str, size: int, *, free: int | None = None,
         floor: int = DISK_FLOOR, cap: int = MAX_DOWNLOAD) -> Plan:
    """Whether this download may start, and why not when it may not.

    A SIZE IS REQUIRED. The inspect tier produces it, and an unknown size is
    refused rather than attempted: the whole point of inspecting before
    fetching is not to find out how big something is by downloading it.
    """
    if size <= 0:
        return Plan(repo, size, False, "no measured size; inspect it first",
                    reasons.HARNESS)
    if size > cap:
        return Plan(repo, size, False,
                    f"{size / GIB:.1f} GiB is over the {cap / GIB:.0f} GiB cap",
                    reasons.LIMIT, f"limit:download_gib>{cap / GIB:g}")
    have = free_bytes() if free is None else free
    if have - size < floor:
        return Plan(repo, size, False,
                    f"{size / GIB:.1f} GiB would leave under the "
                    f"{floor / GIB:.0f} GiB floor ({have / GIB:.0f} GiB free)",
                    reasons.MACHINE)
    return Plan(repo, size, True, f"{size / GIB:.1f} GiB, {have / GIB:.0f} GiB free")


#: Only these tiers may put something in the download queue. The JUDGE tier
#: also writes `queued`, and it judges a description: it queued a 122B model on
#: a 32 GB machine. Nothing is downloaded on the strength of prose.
FETCHABLE_TIERS = ("inspect", "fetch")
#: And only WEIGHTS are downloadable. The inspect tier queued the GitHub repos
#: it read, and this worker calls snapshot_download, which wants a HuggingFace
#: model id: every queued name 401'd. A repo is something to install and screen,
#: a weight is something to fetch, and they are not the same queue.
#:
#: THE REGISTRY ANSWERS THIS NOW, and `kind` is the fallback for rows written
#: before that column existed (#167). Applied as a hard filter it excluded 25
#: of the 28 ranked code candidates, because the sweep records `candidate` for
#: a name resolved out of prose, so the screen queued things the fetch could
#: never reach. #224.
FETCHABLE_KIND = "weights"


def have(model_id: str, conn=None) -> bool:
    """A complete download of it on this machine is recorded and present. #411."""
    return downloads.have(model_id, conn)


#: The #399 check and the #196 dependency keys live with the downloads table.
LOADABLE = downloads.LOADABLE
WEIGHT_SUFFIXES = downloads.WEIGHT_SUFFIXES
REQUIRES_KEYS = downloads.REQUIRES_KEYS
PROVENANCE_KEYS = downloads.PROVENANCE_KEYS


def requires(model_id: str, conn=None) -> list[str]:
    """Other repos this model's own config named when it was downloaded.

    A REPO BEING COMPLETE IS NOT A MODEL BEING LOADABLE. Marvis-AI's 8-bit MLX
    repo is whole and names `text_tokenizer: Marvis-AI/marvis-tts-250m-v0.2`,
    a different repo. Issue #196.
    """
    with downloads.store(conn) as c:
        got = set(downloads.requires(model_id, c))
        # An adapter needs its base before its own download names it. #423.
        try:
            parents = ms.parents_of(c, [model_id]).get(model_id, [])
        except Exception:  # noqa: BLE001
            parents = []
        got.update(p for p, kind in parents if kind == "adapter" and p != model_id)
    return sorted(got)


def missing(model_id: str, conn=None) -> list[str]:
    """Everything this model needs that is not on disk, itself included."""
    with downloads.store(conn) as c:
        wanted = [model_id] + requires(model_id, c)
        return [m for m in wanted if not have(m, c)]


def queued(conn, tiers=FETCHABLE_TIERS, kind: str = FETCHABLE_KIND,
           needs_lane: bool = True, lane: str = "") -> list[dict]:
    """Weights the inspect tier queued, best score first.

    A weight NO LANE CAN TEST is returned but never counted as fetchable:
    downloading is only justified by a measurement that follows it, and an
    automated loop would otherwise fill the disk with models that are
    unmeasurable by construction. Issue #81.
    """
    rows = conn.execute("""
        SELECT p.name, p.resolved, p.kind, p.lane, p.registry,
               -- The card's facts, so this tier can refuse an adapter or a
               -- foreign runtime before spending gigabytes on it. #414.
               p.attaches_to, p.runtime_needed,
               -- The state and the verdict that set it. #409.
               p.state AS outcome, st.tier AS tier, st.detail AS detail,
               -- The candidate's measured size, whatever verdict is newest. #211, #413.
               p.size_bytes,
               -- The judge scores REPOS; the queue holds WEIGHTS, and a weight
               -- is never judged (judging a model id in isolation is the
               -- copywriting problem the rubric exists to avoid). So a weight
               -- inherits the score of the repo that named it, through the
               -- `needs` edge. Without this every row sorted at 0 and "largest
               -- first" was whatever order the query happened to return.
               COALESCE((SELECT v2.score FROM edges e
                           JOIN verdicts v2 ON v2.proposal_id = e.src
                          WHERE e.dst = p.id AND e.relation = 'needs'
                            AND v2.score IS NOT NULL
                          ORDER BY v2.id DESC LIMIT 1), 0) AS score
        FROM proposals p LEFT JOIN verdicts st ON st.id = p.state_verdict_id
        WHERE p.state = 'queued'""").fetchall()
    def downloadable(r) -> bool:
        """snapshot_download wants a HuggingFace id. The registry says so
        outright; `kind` only has to answer for rows older than that column."""
        if r["registry"]:
            return r["registry"] != ms.GITHUB
        return not kind or r["kind"] == kind

    out = [dict(r) for r in rows
           if r["outcome"] == "queued" and r["tier"] in tiers
           and downloadable(r)
           and not have(r["resolved"] or r["name"], conn)]
    if lane:
        # A LANE-SCOPED LOOP MUST SCOPE THE STEP THAT SPENDS THE DISK. The loop
        # printed "(spending only on the image lane)" and then considered
        # whisper-tiny, wav2vec2, gpt2 and vicuna, because --lane reached the
        # queue report and not the fetch. Issue #211.
        from harness import lanes
        out = [r for r in out if lanes.serves(r.get("lane"), lane)]
    return in_rank_order(out, conn)


def in_rank_order(rows: list[dict], conn=None) -> list[dict]:
    """Fetch order is SCREEN order. The fetch exists to feed the screen.

    These were two different questions asked of one queue. This sorted by the
    judged score of the repo that named the weight; the screen sorts by the
    value of the information a screen would buy (#175), which is the ordering
    this project adopted when it retired the judge as a ranker. Measured on the
    code lane, the two top-six lists had ZERO overlap: three runs each fetched
    something and each ended with nothing to screen. Issue #224.

    Worse, every judged score in this queue is 0 -- the judge scores REPOS and
    the queue holds WEIGHTS, inherited through a `needs` edge that mostly does
    not exist -- so the old order was arbitrary among equals, which put three
    models over 12 GiB at the head of a 10 GiB budget.
    """
    from harness import rank

    # RANK THE STORE'S ROWS, NOT THESE. A fetch row carries name, lane, kind
    # and size; rank.value reads recurrence, lineage rows and the card columns,
    # which live on the judgeable row. Ranking these scored every one of them
    # identically and fell back to the alphabet, which is the ordering this
    # was replacing.
    if conn is None:
        return sorted(rows, key=lambda r: r["name"])
    from harness import memory_store as _ms

    ranked = rank.rank(_ms.judgeable(conn, limit=1_000_000),
                       serving=rank.serving(),
                       measured_lanes=rank.lanes_with_receipts(conn),
                       keep_laneless=True)
    order = {r["name"]: i for i, r in enumerate(ranked)}
    # A row rank DROPS (an adapter) sorts last rather than vanishing: this
    # queue's job is to say what it would download, and silently losing a row
    # here would read as an empty queue.
    return sorted(rows, key=lambda r: (order.get(r["name"], len(order)),
                                       r["name"]))


def download(repo: str, snapshot=None, listing=None, hf_download=None,
             text: bool = True, conn=None) -> str:
    """Weights into the shared cache. Returns the path.

    HF_HUB_OFFLINE is 1 everywhere else in this project on purpose: an eval
    that silently re-downloads a model turns a network hiccup into a model
    "failure" mid-run. Fetching is the ONE operation whose whole job is to go
    online, so it lifts the guard for the length of the call and puts it back.
    """
    import os
    was = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "0"
    constants = restore = None
    try:
        single = _gguf_pick(repo, listing, snapshot) if text else None
        if single == ():
            raise FetchError("no single GGUF file fits the ceiling")
        if single:
            from harness import gguf
            return gguf.download(repo, single[0], hf_download=hf_download,
                                 conn=conn)
        if snapshot is None:
            # The env var alone is not enough: huggingface_hub reads it ONCE at
            # import into a module constant, and harness.env has already set it
            # by then. Set both, and put both back.
            from huggingface_hub import constants
            from huggingface_hub import snapshot_download as snapshot
            restore = constants.HF_HUB_OFFLINE
            constants.HF_HUB_OFFLINE = False
        with downloads.store(conn) as c:
            rid = downloads.start(c, repo, downloads.HUB, downloads.hub_dir(repo))
            try:
                where = str(snapshot(repo_id=repo))
            except BaseException:
                downloads.finish(c, rid, failed=True)
                raise
            downloads.finish(c, rid, downloads.snapshot_dir(Path(where)))
        return where
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"{repo}: {str(exc)[:200]}") from exc
    finally:
        if constants is not None:
            constants.HF_HUB_OFFLINE = restore
        if was is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = was


def _gguf_pick(repo: str, listing, snapshot):
    """(file, bytes) for a GGUF-only repo, () if none fits, None otherwise."""
    from harness import gguf
    from harness import inspect as ins
    if listing is None:
        if snapshot is not None:
            return None
        listing = lambda r: ins.hf_model(r).get("siblings") or []  # noqa: E731
    try:
        siblings = listing(repo)
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"{repo}: listing failed: {str(exc)[:200]}") from exc
    if not gguf.only(siblings):
        return None
    return gguf.choose(siblings, ins.ceiling_bytes()) or ()


def run(conn, sizes: dict[str, int] | None = None, *, limit: int = 1, snapshot=None,
        free: int | None = None, lane: str = "",
        budget: int | None = None, listing=None,
        hf_download=None) -> list[dict]:
    """Fetch up to `limit` queued candidates, recording what happened.

    `budget` caps what ONE INVOCATION downloads in total, which is the job
    --budget-gib was documented as doing and never did: it was printed in the
    header and never passed here, so a 12 GiB budget fetched 24.6 GiB. It is a
    fact about this invocation, so exceeding it re-queues rather than settling
    anything. MAX_DOWNLOAD and DISK_FLOOR are absolute and stay in plan().
    Issue #215.

    A refused plan is recorded as `declined`, terminal, so the same oversized
    model is not re-queued every sweep. A failed download is NOT: a network
    error says nothing about the candidate. NEITHER IS A REFUSAL THAT IS ABOUT
    THIS HARNESS: "no measured size" says the store could not answer a question
    about itself, and writing that down as declined settled 16 real candidates
    permanently, including the only upgrade the image lane had. Issue #211,
    the same class as #206 a day earlier.
    """
    done = []
    fetched = 0
    spent = 0
    from harness import gguf
    gguf.adopt_pending(conn)
    for row in queued(conn, lane=lane):
        if not row.get("lane"):
            continue      # nothing here could measure it, so nothing fetches it
        # AN ADAPTER IS NOT A CANDIDATE, and this tier is where that costs
        # gigabytes. rank drops attachments so they never reach the top of the
        # queue, but rank is an ORDERING and this is a SPEND: a LoRA that is
        # merely sized would be downloaded and handed to a runner that cannot
        # load it. `declined` rather than `queued`, because unlike "no measured
        # size" this is a fact about the candidate and not about us.
        # A RUNTIME THIS MACHINE DOES NOT HAVE IS AN ANSWER, not a gap to
        # come back to. rank.unrunnable already drops these from the ordering,
        # so they never reach a fetch and never receive a verdict: the queue
        # carries them forever and every sweep re-ranks them. #254.
        #
        # Recorded WITH THE MACHINE THAT REFUSED, because the store is shared
        # and the same weights are ordinary on the box with the card. A reader
        # elsewhere sees a fact about this machine rather than about the model.
        needs = rank.unrunnable(row, None)
        if needs:
            # verdicts.machine_id says where; the detail no longer does. #415.
            why = (f"{needs}: this machine has no runtime "
                   f"that can load these weights")
            # AND WHAT WOULD END THE WAIT, as a predicate. `needs-cuda` is
            # `unrunnable`'s own spelling, so the condition derives from it
            # rather than being a second list to keep in step. Without this
            # the row is a dead end: 34 rows in the real store were declined
            # here and runnable on the box with the card, and nothing could
            # find them. Issue #266.
            ms.decide_or_skip(conn, row["name"], "declined", tier="fetch", detail=why,
                              reason=reasons.MACHINE,
                              until=f"runtime:{needs.removeprefix('needs-')}")
            done.append({"repo": row["name"], "ok": False, "why": why})
            continue
        # A LANE HAVING A RUNNER IS NOT A RUNNER TAKING THIS MODEL, and this
        # tier is where the difference costs gigabytes. Both image candidates
        # in the first scheduled sweep were downloaded, handed to evals.run,
        # refused for "no cases of a modality it can run", and re-queued --
        # correctly, since that refusal is about the harness. So they came
        # back on the next sweep and would have forever. `queued`, not
        # `declined`: the candidate did nothing wrong and an engine entry
        # would make it runnable, so it is reported to a person instead.
        attachment = row.get("attaches_to") or ""
        gap = screen.runner_gap(row.get("lane") or "", row["name"], attachment,
                                conn=conn)
        if gap:
            why = f"{gap}: no runner in the {row['lane']} lane can load it"
            ms.decide_or_skip(conn, row["name"], "queued", tier="fetch", detail=why,
                              reason=reasons.HARNESS)
            done.append({"repo": row["name"], "ok": False, "why": why})
            continue
        if attachment and not screen.takes_attachment(row.get("lane") or "", attachment):
            why = (f"{attachment} in its own card: this attaches to a model "
                   f"rather than being one, and no lane can run it alone")
            ms.decide_or_skip(conn, row["name"], "declined", tier="fetch", detail=why,
                              reason=reasons.CANDIDATE)
            done.append({"repo": row["name"], "ok": False, "why": why})
            continue
        # `limit` bounds DOWNLOADS, not decisions. Counting refusals against it
        # let one unsized entry at the head of the queue consume the whole
        # budget, so nothing was ever fetched.
        if fetched >= limit:
            break
        name = row["resolved"] or row["name"]
        # Each row's own measured size; an override map covering only the
        # first `limit` rows left the rest at 0 for 22 sweeps. #292.
        size = (sizes or {}).get(name) or int(row.get("size_bytes") or 0)
        if budget is not None and size > 0 and spent + size > budget:
            why = (f"{size / GIB:.1f} GiB would take this run past its "
                   f"{budget / GIB:.0f} GiB budget ({spent / GIB:.1f} GiB "
                   f"already fetched)")
            ms.decide_or_skip(conn, row["name"], "queued", tier="fetch", detail=why,
                              reason=reasons.LIMIT)
            done.append({"repo": name, "ok": False, "why": why})
            continue
        p = plan(name, size, free=free)
        if not p.ok:
            # Our own gap is not an answer about the candidate. #211, #408.
            outcome = "queued" if p.reason == reasons.HARNESS else "declined"
            ms.decide_or_skip(conn, row["name"], outcome, tier="fetch", detail=p.why,
                              reason=p.reason, until=p.until)
            done.append({"repo": name, "ok": False, "why": p.why})
            continue
        try:
            text = lanes.canonical(row.get("lane") or "") in lanes.TEXT_SERVED
            if listing is not None or hf_download is not None or not text:
                where = download(name, snapshot=snapshot, listing=listing,
                                 hf_download=hf_download, text=text, conn=conn)
            else:
                where = download(name, snapshot=snapshot, conn=conn)
        except FetchError as exc:
            done.append({"repo": name, "ok": False, "why": str(exc)})
            continue
        fetched += 1
        spent += size
        if text:
            # A whole GGUF-only repo is served through the router. #301, #303.
            from harness import gguf
            gguf.adopt(conn, name)
        # WHAT IT NEEDS BESIDE ITSELF, as its config recorded it on landing.
        # A tokenizer in another repo makes a whole download unloadable. #196.
        for dep in requires(name, conn):
            if have(dep, conn):
                continue
            try:
                download(dep, snapshot=snapshot, conn=conn)
                done.append({"repo": dep, "ok": True,
                             "why": f"needed by {name}"})
            except FetchError as exc:
                done.append({"repo": dep, "ok": False,
                             "why": f"needed by {name}: {exc}"})
        # Where it landed is a downloads row, not this verdict's run_path. #411.
        ms.decide_or_skip(conn, row["name"], "queued", tier="fetch",
                          detail="downloaded", reason=reasons.CANDIDATE)
        done.append({"repo": name, "ok": True, "why": where})
    return done

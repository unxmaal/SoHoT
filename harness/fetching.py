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
import time
from dataclasses import dataclass
from pathlib import Path

from harness import downloads
from harness import memory_store as ms
from harness import rank
from harness import lanes, reasons, screen, variants

GIB = 1024 ** 3
_BUDGET_WAIT = "limit:download_budget_gib>"


def budget_gib(gib=None) -> float:
    """The run's budget in GiB: what it names, else the registered download_budget. #704."""
    if gib:
        return float(gib)
    from harness import knobs
    return float(knobs.KNOBS["download_budget"].default())


def budget_allows(until, budget: int | None) -> bool:
    """False when a row waits for a bigger download budget than `budget` bytes. #704."""
    if budget is None or not (until or "").startswith(_BUDGET_WAIT):
        return True
    from harness.memory_store import revisit
    return revisit.until_met(until, {"limits": {"download_budget_gib": budget / GIB}})
#: Never fill the volume. A download that leaves no room is a download that
#: breaks the next eval rather than enabling it.
DISK_FLOOR = 50 * GIB
#: Refuse anything larger in one go, whatever the disk says.
MAX_DOWNLOAD = 60 * GIB


class FetchError(RuntimeError):
    """The download could not be started. Never a verdict about the model."""


class FetchDeferred(FetchError):
    """The registry rate-limited us: the rest of this tier waits for the next sweep. #675."""


class Unloadable(FetchError):
    """The listing holds no weights a runner here loads; `formats` names the ones it has. #798."""

    def __init__(self, why: str, formats=()):
        super().__init__(why)
        self.formats = tuple(formats)


#: Weight formats some registered runner loads: mlx/transformers/diffusers, llama.cpp, mlx whisper, kokoro.
RUNNER_FORMATS = (".safetensors", ".gguf", ".bin", ".npz", ".onnx")
#: until for weights only in formats no runner loads; met once RUNNER_FORMATS takes one. #798.
FORMAT_WAIT = "format:"


def lane_formats(lane: str = "", patterns=()) -> tuple[str, ...]:
    """The RUNNER_FORMATS a runner of `lane` loads: GGUF only on llama.cpp's lanes, an opener's only what its patterns match. #1040."""
    got = RUNNER_FORMATS
    if lane and lanes.canonical(lane) not in lanes.GGUF_SERVED:
        got = tuple(f for f in got if f != ".gguf")
    if patterns:
        got = tuple(f for f in got if variants.matches("w" + f, patterns))
    return got


def _lane_patterns(lane: str, runtimes=None) -> tuple[str, ...]:
    if runtimes is None:
        from harness import machine
        runtimes = machine.detect().runtimes
    return variants.opens(lane, runtimes=runtimes)


def foreign_formats(siblings, lane: str = "", patterns=()) -> list[str]:
    """Weight formats in the listing when none of it is one the lane's runner loads, else []."""
    names = [str(s.get("rfilename", "")).lower() for s in siblings or []]
    if any(n.endswith(lane_formats(lane, patterns)) for n in names):
        return []
    return sorted({Path(n).suffix for n in names if n.endswith(downloads.WEIGHT_SUFFIXES)})


def format_waits(until, lane: str = "", runtimes=None) -> bool:
    """True while a row waits on a runner for formats its lane's runners still lack."""
    if not (until or "").startswith(FORMAT_WAIT):
        return False
    have = lane_formats(lane, _lane_patterns(lane, runtimes) if lane else ())
    return not any(f in have for f in until.removeprefix(FORMAT_WAIT).split("|"))


#: why_not reasons, and the ones fetch skips on without trying or writing anything. #925.
BACKPRESSURE, BUDGET, FORMAT, NO_LANE, UNINSPECTED = "backpressure", "budget", "format", "no lane", "uninspected"
OVER_BUDGET, FAILED = "over budget", "last download failed"
#: The fetch's own recorded refusal (a runner gap, a budget, a base it waits on), read back by the funnel. #1084.
SKIPPED = "fetch skipped"
#: The detail of the fetch verdict that records a download, the one fetch verdict that is not a skip.
DOWNLOADED = "downloaded"
SILENT = (BACKPRESSURE, BUDGET, FORMAT, NO_LANE, UNINSPECTED)


def held(backlog: int, top: int) -> tuple[str, str] | None:
    """The loop's backpressure: enough already on disk waits for a screen, so nothing is fetched. #396."""
    if top and backlog >= top:
        return BACKPRESSURE, (f"{backlog} candidate(s) already on disk wait for a screen, "
                              f"and this run screens {top}")
    return None


def over_budget(size: int, budget: int | None, spent: int = 0) -> bool:
    """A measured size that would take this run past its budget. #215."""
    return budget is not None and size > 0 and spent + size > budget


def why_not(row: dict, *, budget: int | None = None, backlog: int = 0,
            top: int = 0) -> tuple[str, str] | None:
    """Why fetch would not download this queued row now, as (reason, detail), or None. #925."""
    got = held(backlog, top)
    if got:
        return got
    until = row.get("until") or ""
    if not budget_allows(until, budget):
        return BUDGET, f"waits for a download budget over {until.removeprefix(_BUDGET_WAIT)} GiB"
    if format_waits(until, row.get("lane") or ""):
        return FORMAT, f"waits for a runner that loads {until.removeprefix(FORMAT_WAIT).replace('|', ', ')}"
    if not row.get("lane"):
        return NO_LANE, "nothing here could measure it, so nothing fetches it"
    if not row.get("inspected"):
        return UNINSPECTED, "inspect has not answered since it was queued or reopened"
    size = int(row.get("size_bytes") or 0)
    if over_budget(size, budget):
        return OVER_BUDGET, f"{size / GIB:.1f} GiB is over the {budget / GIB:.0f} GiB budget of a whole run"
    if row.get("failed_at"):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["failed_at"]))
        return FAILED, f"its last download, at {when}, failed and left nothing; fetch tries again"
    return None


def format_wanted(conn, lane: str = "") -> list[dict]:
    """Queued candidates waiting on a runner for their weight format, for the runners-wanted report."""
    rows = conn.execute("""
        SELECT p.name, p.lane, st.detail, st.until FROM proposals p
          JOIN verdicts st ON st.id = p.state_verdict_id
         WHERE p.state = 'queued' AND st.tier IN ('fetch', 'inspect') AND st.until LIKE ?""",
                        (FORMAT_WAIT + "%",)).fetchall()
    return [{"name": r["name"], "lane": r["lane"], "why_not": r["detail"]} for r in rows
            if format_waits(r["until"], r["lane"] or "") and (not lane or lanes.serves(r["lane"], lane))]


def weights_gap(siblings, lane: str = "", patterns=()) -> str:
    """Why nothing in this listing is weights a runner of the lane here loads, or "". #798, #1040."""
    names = [str(s.get("rfilename", "")).lower() for s in siblings or []]
    have = lane_formats(lane, patterns)
    if any(n.endswith(have) for n in names):
        return ""
    other = foreign_formats(siblings, lane, patterns)
    if other:
        whose = f"{lanes.canonical(lane)} runner" if lane else "runner"
        return (f"runners wanted: its weights are {', '.join(other)}, and no {whose} here "
                f"loads that format (only {', '.join(have)})")
    return f"no weights: none of its {len(names)} file(s) is a weight file"


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


def runner_bases(model_id: str) -> list[str]:
    """Base weights the candidate's runner loads beside it, which its own config never names. #632."""
    from evals.runners.omnisvg import MODELS
    return [base for base, repo in MODELS.values() if repo == model_id]


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
    got.update(runner_bases(model_id))
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
               p.attaches_to, p.runtime_needed, p.model_type, p.library, p.card_tags,
               -- The state and the verdict that set it. #409.
               p.state AS outcome, st.tier AS tier, st.detail AS detail, st.until AS until,
               -- The candidate's measured size, whatever verdict is newest. #211, #413.
               p.size_bytes,
               -- When its newest fetch download finished incomplete, none complete since. #925.
               (SELECT d.finished_at FROM downloads d
                 WHERE d.proposal_id = p.id AND d.origin = 'fetch' AND d.removed_at IS NULL
                 ORDER BY d.id DESC LIMIT 1) AS last_fetch_at,
               (SELECT d.complete FROM downloads d
                 WHERE d.proposal_id = p.id AND d.origin = 'fetch' AND d.removed_at IS NULL
                 ORDER BY d.id DESC LIMIT 1) AS last_fetch_complete,
               -- Inspect has answered since the last reopen; a 429 writes nothing. #798.
               COALESCE((SELECT vi.tier = 'inspect' AND vi.outcome = 'queued'
                                AND vi.reason NOT IN (:reopened, :harness)
                           FROM verdicts vi
                          WHERE vi.proposal_id = p.id
                            AND (vi.tier = 'inspect' OR vi.reason = :reopened)
                          ORDER BY vi.id DESC LIMIT 1), 0) AS inspected,
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
        WHERE p.state = 'queued'""",
                        {"reopened": reasons.REOPENED, "harness": reasons.HARNESS}).fetchall()
    def downloadable(r) -> bool:
        """snapshot_download wants a HuggingFace id. The registry says so
        outright; `kind` only has to answer for rows older than that column."""
        if r["registry"]:
            return r["registry"] != ms.GITHUB
        return not kind or r["kind"] == kind

    out = [{**dict(r), "failed_at": r["last_fetch_at"] if r["last_fetch_at"] and not r["last_fetch_complete"]
            else None} for r in rows
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
    return by_lane_turns(in_rank_order(out, conn), conn)


def by_lane_turns(rows: list[dict], conn=None) -> list[dict]:
    """Rank order taken a lane at a time: every lane's #1 before any lane's #2; a parent rides in its child's lane. #1084."""
    names = [r["name"] for r in rows]
    child_lane: dict[str, str] = {}
    if conn is not None and names:
        try:
            parents = ms.parents_of(conn, names)
        except Exception:  # noqa: BLE001
            parents = {}
        for r in rows:
            for parent, _kind in parents.get(r["name"], []):
                child_lane.setdefault(parent, lanes.canonical(r.get("lane") or ""))
    queues: dict[str, list[dict]] = {}
    for r in rows:
        key = child_lane.get(r["name"]) or child_lane.get(r.get("resolved") or "") \
            or lanes.canonical(r.get("lane") or "")
        queues.setdefault(key, []).append(r)
    at = {id(r): i for i, r in enumerate(rows)}
    out, turn = [], 0
    while len(out) < len(rows):
        out += sorted((q[turn] for q in queues.values() if turn < len(q)), key=lambda r: at[id(r)])
        turn += 1
    return out


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
                       keep_laneless=True, conn=conn)
    order = {r["name"]: i for i, r in enumerate(ranked)}
    # A row rank DROPS (an adapter) sorts last rather than vanishing: this
    # queue's job is to say what it would download, and silently losing a row
    # here would read as an empty queue.
    return sorted(rows, key=lambda r: (order.get(r["name"], len(order)),
                                       r["name"]))


def download(repo: str, snapshot=None, listing=None, hf_download=None,
             text: bool = True, conn=None, require_weights: bool = False,
             model_type: str = "", lane: str = "", card=None, refresh: bool = True) -> str:
    """Weights into the shared cache. Returns the path.

    HF_HUB_OFFLINE is 1 everywhere else in this project on purpose: an eval
    that silently re-downloads a model turns a network hiccup into a model
    "failure" mid-run. Fetching is the ONE operation whose whole job is to go
    online, so it lifts the guard for the length of the call and puts it back.
    """
    from harness import env
    with env.online():
        return _download(repo, snapshot, listing, hf_download, text, conn, require_weights,
                         model_type, lane, card, refresh)


def _download(repo, snapshot, listing, hf_download, text, conn, require_weights,
              model_type="", lane="", card=None, refresh=True) -> str:
    try:
        allow = None
        if require_weights and (listing is not None or snapshot is None):
            siblings = _siblings(repo, listing or _listing)
            # The files the lane's runner opens, not a variant some other runner loads. #1040.
            patterns = _patterns(repo, lane, card)
            gap = weights_gap(siblings, lane, patterns)
            if gap:
                raise Unloadable(gap, foreign_formats(siblings, lane, patterns))
            listing = lambda _repo, s=siblings: s  # noqa: E731
            chosen = _chosen(siblings, model_type, lane, patterns)
            allow = variants.download_files(siblings, chosen, patterns) if chosen else None
        single = _gguf_pick(repo, listing, snapshot, model_type) if text else None
        if single == ():
            raise FetchError("no single GGUF file fits the ceiling")
        if single:
            from harness import gguf
            # A day fetch leaves the router alone; the night's screen restarts it. #1084.
            return gguf.download(repo, single[0], hf_download=hf_download, conn=conn,
                                 refresh=None if refresh else (lambda: gguf.note_unlisted((Path(single[0]).stem,))))
        if snapshot is None:
            from huggingface_hub import snapshot_download as snapshot
        with downloads.store(conn) as c:
            rid = downloads.start(c, repo, downloads.HUB, downloads.hub_dir(repo))
            try:
                # Only the variant inspect sized, not every copy the repo holds. #947.
                where = str(snapshot(repo_id=repo, allow_patterns=allow) if allow
                            else snapshot(repo_id=repo))
            except BaseException:
                downloads.finish(c, rid, failed=True)
                raise
            downloads.finish(c, rid, downloads.snapshot_dir(Path(where)))
        return where
    except FetchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FetchError(str(exc)[:200]) from exc


def _listing(repo: str) -> list:
    """The registry's file list for `repo`, waiting out a 429 as the feeds do. #630, #675."""
    from harness import inspect as ins
    from harness import ratelimit
    return ratelimit.get_json(ins.MODEL_URL.format(model_id=repo)).get("siblings") or []


def _siblings(repo: str, listing) -> list:
    """The listing, a 429 as FetchDeferred and any other failure as FetchError. #675."""
    from harness import ratelimit
    try:
        return listing(repo)
    except ratelimit.RateLimited as exc:
        raise FetchDeferred(f"listing rate-limited (HTTP 429 after {ratelimit.ATTEMPTS} attempts); "
                            f"the rest of this tier waits for the next sweep") from exc
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"listing failed: {_reason(exc)}") from exc


def _patterns(repo: str, lane: str, card=None) -> tuple[str, ...]:
    from harness import machine
    return variants.opens(lane, repo, card, machine.detect().runtimes)


def _chosen(siblings, model_type: str = "", lane: str = "", patterns=()):
    """The variant inspect sizes this listing by on this machine, for the lane's runner. #947, #1040."""
    from harness import inspect as ins
    from harness import machine
    here = machine.detect()
    return variants.pick(variants.runnable(siblings, ins.ceiling_bytes(), model_type, lane, patterns),
                         has=lambda rt: not here.refuses(rt))


def _gguf_pick(repo: str, listing, snapshot, model_type: str = ""):
    """(file, bytes) for a GGUF-only repo or one whose chosen variant is a GGUF, () if none fits, None otherwise."""
    from harness import gguf
    from harness import inspect as ins
    if listing is None:
        if snapshot is not None:
            return None
        listing = _listing
    siblings = _siblings(repo, listing)
    if gguf.only(siblings):
        return gguf.choose(siblings, ins.ceiling_bytes()) or ()
    chosen = _chosen(siblings, model_type)
    if chosen and chosen.format == variants.GGUF:
        return gguf.choose(siblings, ins.ceiling_bytes()) or ()
    return None


def _reason(exc: Exception) -> str:
    """An HTTP failure as its status, since the exception text repeats the URL and so the repo id. #675."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else str(exc)[:200]


def _fetch_needs(name: str, needs: list[str], *, bases: list[str], sizes: dict, sizer,
                 budget: int | None, spent: int, free: int | None, floor: int, fetch):
    """Download what `name` needs beside itself: (done, bytes spent, (reason, why) of the first base not fetched)."""
    done: list[dict] = []
    spent_now = 0
    waiting: tuple[str, str] | None = None
    for dep in needs:
        if dep not in bases:
            try:
                fetch(dep)
            except FetchDeferred as exc:
                done.append({"repo": dep, "ok": False, "why": f"needed by {name}: {exc}", "deferred": True})
                return done, spent_now, waiting
            except FetchError as exc:
                done.append({"repo": dep, "ok": False, "why": f"needed by {name}: {exc}"})
            else:
                done.append({"repo": dep, "ok": True, "why": f"needed by {name}"})
            continue
        size = (sizes or {}).get(dep) or sizer(dep) or -1
        if budget is not None and size > 0 and spent + spent_now + size > budget:
            why = (f"{dep}, the base its runner needs, is {size / GIB:.1f} GiB and would take "
                   f"this run past its {budget / GIB:.0f} GiB budget")
            done.append({"repo": dep, "ok": False, "why": why})
            waiting = waiting or (reasons.LIMIT, why)
            continue
        p = plan(dep, size, free=free, floor=floor)
        if not p.ok:
            why = f"{dep}, the base its runner needs: {p.why}"
            done.append({"repo": dep, "ok": False, "why": why})
            waiting = waiting or (p.reason, why)
            continue
        try:
            fetch(dep)
        except FetchError as exc:
            why = f"{dep}, the base its runner needs: {exc}"
            done.append({"repo": dep, "ok": False, "why": why,
                         **({"deferred": True} if isinstance(exc, FetchDeferred) else {})})
            waiting = waiting or (reasons.HARNESS, why)
            if isinstance(exc, FetchDeferred):
                return done, spent_now, waiting
        else:
            spent_now += size
            done.append({"repo": dep, "ok": True, "why": f"base weights for {name}"})
    return done, spent_now, waiting


def _on_disk_waiting(conn, lane: str = "") -> list[str]:
    """Queued candidates already downloaded whose runner base is still missing. #632."""
    out = []
    for r in conn.execute("SELECT name, resolved, lane FROM proposals WHERE state = 'queued'"):
        name = r["resolved"] or r["name"]
        if lane and not lanes.serves(r["lane"], lane):
            continue
        if runner_bases(name) and have(name, conn) and missing(name, conn):
            out.append(name)
    return out


def run(conn, sizes: dict[str, int] | None = None, *, limit: int = 1, snapshot=None,
        free: int | None = None, lane: str = "",
        budget: int | None = None, listing=None,
        hf_download=None, floor: int = DISK_FLOOR, sizer=None,
        refresh: bool = True, stop_at: float | None = None, clock=time.time) -> list[dict]:
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
    the same class as #206 a day earlier. Nor is a disk below the floor. #528.
    """
    done = []
    fetched = 0
    spent = 0
    from harness import gguf
    gguf.adopt_pending(conn, refresh=refresh)
    if sizer is None:
        from harness import inspect as ins
        sizer = ins.hf_size

    def needs_of(name):
        """Bytes spent on what `name` needs, None when the registry deferred the tier."""
        got, cost, waiting = _fetch_needs(
            name, [m for m in requires(name, conn) if not have(m, conn)],
            bases=runner_bases(name), sizes=sizes or {}, sizer=sizer, budget=budget,
            spent=spent, free=free, floor=floor,
            fetch=lambda dep: download(dep, snapshot=snapshot, conn=conn, refresh=refresh))
        done.extend(got)
        if waiting:
            reason, why = waiting
            ms.decide_or_skip(conn, name, "queued", tier="fetch", detail=f"waiting on {why}",
                              reason=reason)
        return None if any(d.get("deferred") for d in got) else cost

    # A candidate already on disk can still be missing the base its runner loads. #632.
    for name in _on_disk_waiting(conn, lane):
        cost = needs_of(name)
        if cost is None:
            return done
        spent += cost
    for row in queued(conn, lane=lane):
        # Budget (#704), format (#798), no lane, and a reopen inspect has not answered (#798).
        why = why_not(row, budget=budget)
        if why and why[0] in SILENT:
            if why[0] == UNINSPECTED:
                done.append({"repo": row["resolved"] or row["name"], "ok": False, "why": why[1]})
            continue
        # AN ADAPTER IS NOT A CANDIDATE, and this tier is where that costs
        # gigabytes. rank drops attachments so they never reach the top of the
        # queue, but rank is an ORDERING and this is a SPEND: a LoRA that is
        # merely sized would be downloaded and handed to a runner that cannot
        # load it. `declined` rather than `queued`, because unlike "no measured
        # size" this is a fact about the candidate and not about us.
        attachment = row.get("attaches_to") or ""
        # An attachment is one on every machine, so it is decided before this machine's runtimes. #1039.
        if attachment and not screen.takes_attachment(row.get("lane") or "", attachment):
            why = (f"{attachment} in its own card: this attaches to a model "
                   f"rather than being one, and no lane can run it alone")
            ms.decide_or_skip(conn, row["name"], "declined", tier="fetch", detail=why,
                              reason=reasons.CANDIDATE)
            done.append({"repo": row["name"], "ok": False, "why": why})
            continue
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
        gap = screen.runner_gap(row.get("lane") or "", row["name"], attachment,
                                conn=conn)
        if gap:
            why = f"{gap}: no runner in the {row['lane']} lane can load it"
            ms.decide_or_skip(conn, row["name"], "queued", tier="fetch", detail=why,
                              reason=reasons.HARNESS)
            done.append({"repo": row["name"], "ok": False, "why": why})
            continue
        from harness import ds4
        if ds4.recognised(row["name"]):
            # A ds4 file is one very large download; a person starts it. #611.
            spec = screen.candidate_for(row.get("lane") or "", row["name"], conn=conn)
            stem = spec.partition(",")[0].removeprefix(ds4.PREFIX)
            why = (f"a ds4 model is fetched by hand: uv run python -m harness.ds4 fetch "
                   f"{row['name']} {stem}.gguf")
            ms.decide_or_skip(conn, row["name"], "queued", tier="fetch", detail=why,
                              reason=reasons.LIMIT)
            done.append({"repo": row["name"], "ok": False, "why": why})
            continue
        # `limit` bounds DOWNLOADS, not decisions. Counting refusals against it
        # let one unsized entry at the head of the queue consume the whole
        # budget, so nothing was ever fetched.
        if fetched >= limit:
            break
        if stop_at is not None and clock() >= stop_at:
            done.append({"repo": row["resolved"] or row["name"], "ok": False,
                         "why": "this fetch's window has closed; the next one takes it"})
            break
        name = row["resolved"] or row["name"]
        # Each row's own measured size; an override map covering only the
        # first `limit` rows left the rest at 0 for 22 sweeps. #292.
        size = (sizes or {}).get(name) or int(row.get("size_bytes") or 0)
        if over_budget(size, budget, spent):
            why = (f"{size / GIB:.1f} GiB would take this run past its "
                   f"{budget / GIB:.0f} GiB budget ({spent / GIB:.1f} GiB "
                   f"already fetched)")
            # Bigger than the whole budget, no sweep at this budget ever takes it. #704.
            until = f"limit:download_budget_gib>{budget / GIB:g}" if size > budget else ""
            ms.decide_or_skip(conn, row["name"], "queued", tier="fetch", detail=why,
                              reason=reasons.LIMIT, until=until)
            done.append({"repo": name, "ok": False, "why": why})
            continue
        p = plan(name, size, free=free, floor=floor)
        if not p.ok:
            # Our own gap, or a disk that will be freed, is not an answer about the candidate. #211, #408, #528.
            outcome = "queued" if p.reason in (reasons.HARNESS, reasons.MACHINE) else "declined"
            ms.decide_or_skip(conn, row["name"], outcome, tier="fetch", detail=p.why,
                              reason=p.reason, until=p.until)
            done.append({"repo": name, "ok": False, "why": p.why})
            continue
        try:
            text = lanes.canonical(row.get("lane") or "") in lanes.GGUF_SERVED
            if listing is not None or hf_download is not None or not text:
                where = download(name, snapshot=snapshot, listing=listing,
                                 hf_download=hf_download, text=text, conn=conn,
                                 require_weights=True, model_type=row.get("model_type") or "",
                                 lane=row.get("lane") or "", card=row, refresh=refresh)
            else:
                where = download(name, snapshot=snapshot, conn=conn, require_weights=True,
                                 model_type=row.get("model_type") or "",
                                 lane=row.get("lane") or "", card=row, refresh=refresh)
        except FetchDeferred as exc:
            done.append({"repo": name, "ok": False, "why": str(exc), "deferred": True})
            break
        except Unloadable as exc:
            # Foreign formats wait on an engine entry, a person's call (runners wanted); no weights is final.
            if exc.formats:
                ms.decide_or_skip(conn, row["name"], "queued", tier="fetch", detail=str(exc),
                                  reason=reasons.HARNESS,
                                  until=FORMAT_WAIT + "|".join(exc.formats))
            else:
                ms.decide_or_skip(conn, row["name"], "declined", tier="fetch", detail=str(exc),
                                  reason=reasons.CANDIDATE)
            done.append({"repo": name, "ok": False, "why": str(exc)})
            continue
        except FetchError as exc:
            done.append({"repo": name, "ok": False, "why": str(exc)})
            continue
        fetched += 1
        spent += size
        if text:
            # A whole GGUF-only repo is served through the router. #301, #303.
            from harness import gguf
            linked = gguf.adopt(conn, name)
            if linked and not refresh:
                gguf.note_unlisted((Path(linked).stem,))
            elif linked:
                # The router lists a new file only after a restart, and the screen tier comes next. #1012.
                gguf.refresh_router(expect=(Path(linked).stem,))
        # WHAT IT NEEDS BESIDE ITSELF, as its config recorded it on landing.
        # A tokenizer in another repo makes a whole download unloadable. #196.
        # Where it landed is a downloads row, not this verdict's run_path. #411.
        ms.decide_or_skip(conn, row["name"], "queued", tier="fetch",
                          detail=DOWNLOADED, reason=reasons.CANDIDATE)
        # What it needs beside itself: what its config named on landing (#196) and its runner's base (#632).
        cost = needs_of(name)
        done.append({"repo": name, "ok": True, "why": where})
        if cost is None:
            break
        spent += cost
    return done

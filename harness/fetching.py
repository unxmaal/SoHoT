"""Weights for the test about to run them, fetched as it starts and removed when it ends. #62, #2015."""
from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from harness import cuts, download_state, downloads, knobs
from harness import memory_store as ms
from harness import rank
from harness import lanes, reasons, refetch, screen, variants

GIB = 1024 ** 3
#: Room a download leaves above the deploy's own floor (env.HF_MIN_FREE_GB), so discovery never blocks a deploy. #2011.
FLOOR_MARGIN = 30 * GIB
#: Refuse anything larger in one go, whatever the disk says.
MAX_DOWNLOAD = 60 * GIB


class FetchError(RuntimeError):
    """The download could not be started. Never a verdict about the model."""


class FetchDeferred(FetchError):
    """The registry rate-limited us: the rest of this tier waits for the next sweep. #675."""


class NoRoom(FetchError):
    """What the download would really take leaves the volume under the floor; a fact about this disk. #2011."""


class Refetch(FetchError):
    """The repo landed within the refetch window and no verdict was written since. #2161."""


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
FORMAT, NO_LANE, UNINSPECTED, FAILED = "format", "no lane", "uninspected", "last download failed"
#: The fetch's own recorded refusal (a runner gap, a base it waits on), read back by the funnel. #1084.
SKIPPED = "fetch skipped"
#: The event of the fetch verdict that records a download, the one fetch verdict that is not a skip. #1878.
DOWNLOADED = refetch.LANDED_EVENT
#: That verdict's detail, display only; an older release still reads it. #1878.
DOWNLOADED_DETAIL = "downloaded"
SILENT = (FORMAT, NO_LANE, UNINSPECTED)


def why_not(row: dict) -> tuple[str, str] | None:
    """Why fetch would not download this queued row now, as (reason, detail), or None. #925."""
    until = row.get("until") or ""
    if format_waits(until, row.get("lane") or ""):
        return FORMAT, f"waits for a runner that loads {until.removeprefix(FORMAT_WAIT).replace('|', ', ')}"
    if not row.get("lane"):
        return NO_LANE, "nothing here could measure it, so nothing fetches it"
    if not row.get("inspected"):
        return UNINSPECTED, "inspect has not answered since it was queued or reopened"
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
    from harness import env
    target = Path(path) if path else env.weights_home()
    while not target.exists() and target != target.parent:
        target = target.parent
    return shutil.disk_usage(target).free


def disk_floor(environ=None) -> int:
    """Bytes a download must leave free: the deploy's HF_MIN_FREE_GB plus FLOOR_MARGIN, read now. #2011."""
    from harness import env
    return env.min_free_gb(environ) * GIB + FLOOR_MARGIN


def no_room(what: str, size: int, *, free: int | None = None, floor: int | None = None) -> str:
    """Why `size` more bytes would take the weights volume under the floor, or ''; a refusal is a cut. #2011."""
    floor = disk_floor() if floor is None else floor
    have = free_bytes() if free is None else free
    if have - size >= floor:
        return ""
    cuts.cut("disk_floor", f"{what}: download refused at the disk floor", value=floor, kept=0, dropped=1)
    return (f"{size / GIB:.1f} GiB would leave under the {floor / GIB:.0f} GiB floor "
            f"({have / GIB:.0f} GiB free)")


def plan(repo: str, size: int, *, free: int | None = None,
         floor: int | None = None, cap: int = MAX_DOWNLOAD) -> Plan:
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
                    reasons.LIMIT, f"limit:{knobs.limit('download_gib', cap / GIB, 'GiB')}")
    have = free_bytes() if free is None else free
    why = no_room(repo, size, free=have, floor=floor)
    if why:
        return Plan(repo, size, False, why, reasons.MACHINE)
    return Plan(repo, size, True, f"{size / GIB:.1f} GiB, {have / GIB:.0f} GiB free")


#: Only these tiers may put something in the download queue; a screen's own requeue is one. The JUDGE tier
#: also writes `queued`, and it judges a description: it queued a 122B model on
#: a 32 GB machine. Nothing is downloaded on the strength of prose.
FETCHABLE_TIERS = ("inspect", "fetch", "screen")
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


def runner_bases(model_id: str, conn=None) -> list[str]:
    """Repos the candidate's runner loads beside it, which its own config never names: OmniSVG's base (#632), an mflux family's (#1546)."""
    from evals.runners.omnisvg import MODELS
    from harness import engines
    got = [base for base, repo in MODELS.values() if repo == model_id]
    lane, model_type = _filed(model_id, conn)
    if not lane or lanes.serves(lane, "image"):
        got += [r for r in engines.mflux_needs(model_id) if r not in got]
    # mlx-audio loads a model's codec or tokenizer from a repo of its own (MOSS-TTS). #2012.
    if lane and lanes.serves(lane, "tts"):
        got += [r for r in engines.audio_needs(model_id, model_type) if r not in got]
    return got


def _filed(model_id: str, conn) -> tuple[str, str]:
    """(lane, model_type) the store holds for it, ("", "") when it holds none."""
    if conn is None:
        return "", ""
    try:
        row = conn.execute("SELECT lane, model_type FROM proposals WHERE name = ? OR resolved = ? ORDER BY id LIMIT 1",
                           (model_id, model_id)).fetchone()
    except Exception:  # noqa: BLE001
        return "", ""
    return ((row["lane"] or ""), (row["model_type"] or "")) if row else ("", "")


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
        adapted = [p for p, kind in parents if kind == "adapter" and p != model_id]
        if adapted and loads_its_base(model_id, c):
            got.update(adapted)
        got.update(runner_bases(model_id, c))
    return sorted(got)


def loads_its_base(model_id: str, conn) -> bool:
    """Whether the runner loads an adapter's lineage parent beside it: for a GGUF, only a LoRA GGUF does. #1091."""
    from harness import context, gguf
    path = gguf.path_of(model_id, conn)
    try:
        kind = str(context.read_meta(path).get("general.type") or "") if path is not None else ""
    except (OSError, ValueError):
        kind = ""
    if kind:
        return kind.lower() == "adapter"
    row = conn.execute("SELECT attaches_to, library, card_tags FROM proposals WHERE name = ?", (model_id,)).fetchone()
    try:
        tags = [str(t).lower() for t in json.loads(row["card_tags"] or "[]")] if row else []
    except (TypeError, ValueError):
        tags = []
    if path is None and not (model_id.lower().endswith("gguf") or "gguf" in tags
                             or (row and (row["library"] or "").lower() == "gguf")):
        return True
    return bool(row) and (row["attaches_to"] or "").lower() in screen.ADAPTER_KINDS


def missing(model_id: str, conn=None) -> list[str]:
    """Everything this model needs that is not on disk, itself included."""
    with downloads.store(conn) as c:
        wanted = [model_id] + requires(model_id, c)
        return [m for m in wanted if not have(m, c)]


def queued(conn, tiers=FETCHABLE_TIERS, kind: str = FETCHABLE_KIND,
           needs_lane: bool = True, lane: str = "", name: str = "") -> list[dict]:
    """Weights queued and not on disk, in the order the screen fetches them; `name` alone, unranked. #81, #2015.

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
                 WHERE d.proposal_id = p.id AND d.origin = 'fetch' AND d.state <> 'removed'
                 ORDER BY d.id DESC LIMIT 1) AS last_fetch_at,
               -- A stood-down download is no failure, so only 'incomplete' reads as one. #1734.
               (SELECT d.state FROM downloads d
                 WHERE d.proposal_id = p.id AND d.origin = 'fetch' AND d.state <> 'removed'
                 ORDER BY d.id DESC LIMIT 1) AS last_fetch_state,
               -- Inspect has answered since the last reopen; a 429 writes nothing. #798.
               COALESCE((SELECT CASE WHEN vi.tier = 'inspect' AND vi.outcome = 'queued'
                                AND vi.reason NOT IN (:reopened, :harness) THEN 1 ELSE 0 END
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
        WHERE p.state = 'queued'""" + (" AND (p.name = :name OR p.resolved = :name)" if name else ""),
                        {"reopened": reasons.REOPENED, "harness": reasons.HARNESS, "name": name}).fetchall()
    def downloadable(r) -> bool:
        """snapshot_download wants a HuggingFace id. The registry says so
        outright; `kind` only has to answer for rows older than that column."""
        if r["registry"]:
            return r["registry"] != ms.GITHUB
        return not kind or r["kind"] == kind

    out = [{**dict(r), "failed_at": r["last_fetch_at"] if r["last_fetch_state"] == download_state.INCOMPLETE
            else None} for r in rows
           if r["outcome"] == "queued" and r["tier"] in tiers
           and downloadable(r)
           and not have(r["resolved"] or r["name"], conn)]
    if name:
        return out
    if lane:
        # A LANE-SCOPED LOOP MUST SCOPE THE STEP THAT SPENDS THE DISK. The loop
        # printed "(spending only on the image lane)" and then considered
        # whisper-tiny, wav2vec2, gpt2 and vicuna, because --lane reached the
        # queue report and not the fetch. Issue #211.
        from harness import lanes
        out = [r for r in out if lanes.serves(r.get("lane"), lane)]
    return by_lane_turns(in_rank_order(out, conn), conn)


def row(conn, name: str) -> dict | None:
    """The fetch queue's row for `name` when a screen may fetch it now, else None. #2015."""
    return next(iter(queued(conn, name=name)), None)


def by_lane_turns(rows: list[dict], conn=None) -> list[dict]:
    """Rank order taken a lane at a time: every lane's #1 before any lane's #2, work lanes first; a parent rides in its child's lane. #1084, #2033."""
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
    # Within a turn the work lanes go first, then rank order. #2033.
    work = {id(r): (lanes.WORK.index(k) if k in lanes.WORK else len(lanes.WORK)) for k, q in queues.items() for r in q}
    out, turn = [], 0
    while len(out) < len(rows):
        out += sorted((q[turn] for q in queues.values() if turn < len(q)), key=lambda r: (work[id(r)], at[id(r)]))
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

    judged = cuts.filled(_ms.judgeable(conn, limit=1_000_000), 1_000_000,
                         "harness/fetching.py:in_rank_order->_ms.judgeable(limit)",
                         "fetch order ranked a full page of judgeable rows", conn=conn)
    ranked = rank.rank(judged,
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
             model_type: str = "", lane: str = "", card=None, refresh: bool = True,
             free: int | None = None, floor: int | None = None) -> str:
    """Weights into the shared cache. Returns the path.

    HF_HUB_OFFLINE is 1 everywhere else in this project on purpose: an eval
    that silently re-downloads a model turns a network hiccup into a model
    "failure" mid-run. Fetching is the ONE operation whose whole job is to go
    online, so it lifts the guard for the length of the call and puts it back.
    """
    from harness import env
    with env.online():
        return _download(repo, snapshot, listing, hf_download, text, conn, require_weights,
                         model_type, lane, card, refresh, free, floor)


def _taken(siblings, allow) -> int:
    """Bytes a snapshot with this allow list takes from this listing. #2011."""
    return variants.files_bytes(siblings, allow)


def _room_for(repo: str, size: int, free, floor) -> None:
    why = no_room(repo, size, free=free, floor=floor)
    if why:
        raise NoRoom(f"its download would take {why}")


def _download(repo, snapshot, listing, hf_download, text, conn, require_weights,
              model_type="", lane="", card=None, refresh=True, free=None, floor=None) -> str:
    try:
        allow, taken = None, None
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
            taken = _taken(siblings, allow)
        single = _gguf_pick(repo, listing, snapshot, model_type, conn) if text else None
        if single == ():
            raise FetchError("no single GGUF file fits the ceiling")
        # The bytes the download really takes, not the variant inspect sized. #2011.
        if not single and taken is not None:
            _room_for(repo, taken, free, floor)
        if single:
            _room_for(repo, int(single[1] or 0), free, floor)
            from harness import gguf
            try:
                # A fetch told to hold the router leaves it alone; the next screen restarts it once. #1084.
                return gguf.download(repo, single[0], hf_download=hf_download, conn=conn,
                                     refresh=None if refresh else (lambda: gguf.note_unlisted((Path(single[0]).stem,))))
            except gguf.Auxiliary as exc:
                # The file that fits is a drafter, MTP head or shard; fetching it again would land the same one. #1674.
                raise Unloadable(str(exc)) from exc
        if snapshot is None:
            from huggingface_hub import snapshot_download as snapshot
        with downloads.store(conn) as c:
            rid = downloads.start(c, repo, downloads.HUB, downloads.hub_dir(repo), reason=download_state.REFETCH)
            try:
                # Only the variant inspect sized, not every copy the repo holds. #947.
                with downloads.landing(downloads.hub_dir(repo), what=repo):
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


def _gguf_pick(repo: str, listing, snapshot, model_type: str = "", conn=None):
    """(file, bytes) for a GGUF-only repo or one whose chosen variant is a GGUF, () if none fits, None otherwise."""
    from harness import gguf
    if listing is None:
        if snapshot is not None:
            return None
        listing = _listing
    siblings = _siblings(repo, listing)
    if gguf.only(siblings):
        return _choose_unheld(repo, siblings, conn)
    chosen = _chosen(siblings, model_type)
    if chosen and chosen.format == variants.GGUF:
        return _choose_unheld(repo, siblings, conn)
    return None


def _choose_unheld(repo: str, siblings, conn):
    """gguf.choose over the files this machine has not already set aside; Unloadable when only set-aside ones fit. #1989."""
    import sys
    from harness import gguf
    from harness import inspect as ins
    held = []
    while pick := gguf.choose(siblings, ins.ceiling_bytes()):
        copy = gguf.held_aside(repo, pick[0], pick[1], conn)
        if copy is None:
            return pick
        print(f"  gguf: {repo}: not fetching {pick[0]}: already set aside at {copy}; "
              f"scripts/fetch-gguf.sh {repo} {pick[0]} fetches it by hand", file=sys.stderr)
        held.append(f"{pick[0]} (set aside at {copy})")
        siblings = [f for f in siblings if f.get("rfilename") != pick[0]]
    if held:
        raise Unloadable(f"every GGUF that fits is already set aside, not fetched again: {', '.join(held)}")
    return ()


def _reason(exc: Exception) -> str:
    """An HTTP failure as its status, since the exception text repeats the URL and so the repo id. #675."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else str(exc)[:200]


def _fetch_needs(name: str, needs: list[str], *, bases: list[str], sizer, free: int | None, floor: int, fetch):
    """Download what `name` needs beside itself, each under the floor: (done, bytes spent, first wait). #1091."""
    done: list[dict] = []
    spent_now = 0
    waiting: tuple[str, str] | None = None
    for dep in needs:
        what = f"{dep}, the base its runner needs" if dep in bases else f"{dep}, needed by {name}"
        size = sizer(dep) or -1
        p = plan(dep, size, free=free, floor=floor)
        if not p.ok:
            why = f"{what}: {p.why}"
            done.append({"repo": dep, "ok": False, "why": why})
            waiting = waiting or (p.reason, why)
            continue
        try:
            fetch(dep)
        except FetchError as exc:
            why = f"{what}: {exc}"
            done.append({"repo": dep, "ok": False, "why": why,
                         **({"deferred": True} if isinstance(exc, FetchDeferred) else {})})
            waiting = waiting or (reasons.HARNESS, why)
            if isinstance(exc, FetchDeferred):
                return done, spent_now, waiting
        else:
            spent_now += size
            done.append({"repo": dep, "ok": True, "bytes": size,
                         "why": f"base weights for {name}" if dep in bases else f"needed by {name}"})
    return done, spent_now, waiting


def _refused(conn, row: dict, outcome: str, why: str, *, reason: str, until: str = "") -> dict:
    ms.decide_or_skip(conn, row["name"], outcome, tier="fetch", detail=why[:600], reason=reason, until=until)
    return {"repo": row["resolved"] or row["name"], "ok": False, "why": why}


def _refusal(conn, row: dict) -> dict | None:
    """The refusal a candidate gets before any byte is fetched, recorded, or None when it may be fetched. #81, #254, #2015."""
    name = row["resolved"] or row["name"]
    why = why_not(row)
    if why and why[0] in SILENT:
        return {"repo": name, "ok": False, "why": why[1]}
    # AN ADAPTER IS NOT A CANDIDATE, and this tier is where that costs gigabytes. #414.
    attachment = row.get("attaches_to") or ""
    # An attachment is one on every machine, so it is decided before this machine's runtimes. #1039.
    if attachment and not screen.takes_attachment(row.get("lane") or "", attachment):
        return _refused(conn, row, "declined", f"{attachment} in its own card: this attaches to a model rather than "
                        f"being one, and no lane can run it alone", reason=reasons.CANDIDATE)
    # A lane discovery never screens loads its own weights when a person runs it. #1282.
    if lanes.canonical(row.get("lane") or "") in lanes.BY_HAND:
        return _refused(conn, row, "queued", screen.by_hand(row["lane"], row["name"], card=row), reason=reasons.HARNESS)
    # A runtime this machine lacks is an answer about this machine, with what would end the wait. #254, #266, #415.
    needs = rank.unrunnable(row, None)
    if needs:
        return _refused(conn, row, "declined", f"{needs}: this machine has no runtime that can load these weights",
                        reason=reasons.MACHINE, until=f"runtime:{needs.removeprefix('needs-')}")
    # A lane having a runner is not a runner taking this model; an engine entry would make it runnable. #213.
    gap = screen.runner_gap(row.get("lane") or "", row["name"], attachment, conn=conn)
    if gap:
        return _refused(conn, row, "queued", f"{gap}: no runner in the {row['lane']} lane can load it",
                        reason=reasons.HARNESS)
    from harness import ds4
    if ds4.recognised(row["name"]):
        # A ds4 file is one very large download; a person starts it. #611.
        spec = screen.candidate_for(row.get("lane") or "", row["name"], conn=conn)
        stem = spec.partition(",")[0].removeprefix(ds4.PREFIX)
        return _refused(conn, row, "queued", f"a ds4 model is fetched by hand: uv run python -m harness.ds4 fetch "
                        f"{row['name']} {stem}.gguf", reason=reasons.LIMIT)
    return None


def _budget(conn, repo: str, via: str, owner: str = "") -> None:
    """Raise Refetch when `repo` landed within the window and no verdict was written since. #2161."""
    why = refetch.refusal(conn, repo, via, owner)
    if why:
        raise Refetch(why)


def _land(conn, name: str, card: dict, *, snapshot=None, listing=None, hf_download=None, free=None, floor=None,
          refresh: bool = True, via: str = "fetch") -> str:
    """Download `name` the way its lane's runner loads it and tell the router of a new GGUF; the path. #2015."""
    _budget(conn, name, via)
    refetch.clear(name)
    text = lanes.canonical(card.get("lane") or "") in lanes.GGUF_SERVED
    where = download(name, snapshot=snapshot, listing=listing, hf_download=hf_download, text=text, conn=conn,
                     require_weights=True, model_type=card.get("model_type") or "", lane=card.get("lane") or "",
                     card=card, refresh=refresh, free=free, floor=floor)
    if text:
        # A whole GGUF-only repo is served through the router, which lists a new file only after a restart. #301, #1012.
        from harness import gguf
        linked = gguf.adopt(conn, name)
        if linked and not refresh:
            gguf.note_unlisted((Path(linked).stem,))
        elif linked:
            gguf.refresh_router(expect=(Path(linked).stem,))
    return where


def _needs(conn, name: str, *, free, floor, snapshot=None, refresh: bool = True, sizer=None):
    """Fetch what `name` loads beside itself: (done, bytes, first wait). #196, #632, #1091."""
    if sizer is None:
        from harness import inspect as ins
        sizer = ins.hf_size

    def fetch(dep: str) -> str:
        _budget(conn, dep, f"{name}'s dependency", name)
        refetch.clear(dep)
        return download(dep, snapshot=snapshot, conn=conn, refresh=refresh)
    return _fetch_needs(name, [m for m in requires(name, conn) if not have(m, conn)],
                        bases=runner_bases(name, conn), sizer=sizer, free=free, floor=floor, fetch=fetch)


def dependency_gap(conn, target: str, *, free=None, floor=None, sizer=None) -> tuple[Plan, str] | None:
    """The first dependency `target` will need, known before it is downloaded, that may not be: its plan and why. #2161."""
    if sizer is None:
        from harness import inspect as ins
        sizer = ins.hf_size
    floor = disk_floor() if floor is None else floor
    bases = runner_bases(target, conn)
    for dep in sorted(set(requires(target, conn)) | set(downloads.recorded_requires(target, conn))):
        if dep == target or have(dep, conn):
            continue
        p = plan(dep, sizer(dep) or -1, free=free, floor=floor)
        if not p.ok:
            what = f"{dep}, the base its runner needs" if dep in bases else f"{dep}, needed by {target}"
            return p, f"{what}: {p.why}"
    return None


def for_test(conn, row: dict, *, snapshot=None, listing=None, hf_download=None, free: int | None = None,
             floor: int | None = None, sizer=None, refresh: bool = True) -> dict:
    """Fetch one candidate the screen is about to run, a refusal recorded at the fetch tier; what happened. #2015.

    THE TEST FETCHES WHAT IT RUNS. Nothing downloads a candidate ahead of the
    screen that runs it, and the screen removes it again when it is done
    unless the measure step that follows in the same sweep takes it.
    """
    refused = _refusal(conn, row)
    if refused:
        return refused
    name = row["resolved"] or row["name"]
    floor = disk_floor() if floor is None else floor
    size = int(row.get("size_bytes") or 0)
    p = plan(name, size, free=free, floor=floor)
    if not p.ok:
        # Our own gap, or a disk that will be freed, is not an answer about the candidate. #211, #408, #528.
        outcome = "queued" if p.reason in (reasons.HARNESS, reasons.MACHINE) else "declined"
        return _refused(conn, row, outcome, p.why, reason=p.reason, until=p.until)
    # What it will need beside itself is checked before a byte of it is fetched. #2161.
    gap = dependency_gap(conn, name, free=free, floor=floor, sizer=sizer)
    if gap:
        outcome = "queued" if gap[0].reason in (reasons.HARNESS, reasons.MACHINE) else "declined"
        return _refused(conn, row, outcome, gap[1], reason=gap[0].reason, until=gap[0].until)
    try:
        where = _land(conn, name, row, snapshot=snapshot, listing=listing, hf_download=hf_download,
                      free=free, floor=floor, refresh=refresh, via="the screen")
    except FetchDeferred as exc:
        return {"repo": name, "ok": False, "why": str(exc), "deferred": True}
    except Unloadable as exc:
        # Foreign formats wait on an engine entry, a person's call (runners wanted); no weights is final.
        if exc.formats:
            return _refused(conn, row, "queued", str(exc), reason=reasons.HARNESS,
                            until=FORMAT_WAIT + "|".join(exc.formats))
        return _refused(conn, row, "declined", str(exc), reason=reasons.CANDIDATE)
    except NoRoom as exc:
        return _refused(conn, row, "queued", str(exc), reason=reasons.MACHINE)
    except FetchError as exc:
        return {"repo": name, "ok": False, "why": str(exc)}
    # Where it landed is a downloads row, not this verdict's run_path. #411.
    ms.decide_or_skip(conn, row["name"], "queued", tier="fetch", detail=DOWNLOADED_DETAIL, reason=reasons.CANDIDATE,
                      event=DOWNLOADED)
    done, cost, waiting = _needs(conn, name, free=free, floor=floor, snapshot=snapshot, refresh=refresh, sizer=sizer)
    if waiting:
        reason, why = waiting
        ms.decide_or_skip(conn, row["name"], "queued", tier="fetch", detail=f"{refetch.WAITING}{why}"[:600], reason=reason,
                          event=refetch.WAITING_EVENT)
        return {"repo": name, "ok": False, "why": f"{refetch.WAITING}{why}", "needs": done,
                **({"deferred": True} if any(d.get("deferred") for d in done) else {})}
    return {"repo": name, "ok": True, "bytes": size + cost, "why": where, "needs": done}


def card(conn, name: str) -> dict:
    """The proposal's card facts a download picks its files by, {} when the store has none. #2015."""
    got = conn.execute("SELECT name, resolved, lane, model_type, attaches_to, runtime_needed, library, card_tags, "
                       "size_bytes FROM proposals WHERE name = ? OR resolved = ? ORDER BY id LIMIT 1",
                       (name, name)).fetchone()
    return dict(got) if got else {}


def _decline(conn, name: str, p: Plan, why: str, tier: str) -> None:
    """The verdict of a candidate whose dependency cannot be fetched, so no sweep picks it again until its until is met. #2161."""
    outcome = "queued" if p.reason in (reasons.HARNESS, reasons.MACHINE) else "declined"
    try:
        ms.decide_or_skip(conn, name, outcome, tier=tier, detail=why[:600], reason=p.reason, until=p.until)
    except KeyError as exc:
        print(f"  {name}: not recorded: {exc}", flush=True)


def ensure(conn, name: str, *, snapshot=None, listing=None, hf_download=None, free: int | None = None,
           floor: int | None = None, sizer=None, refresh: bool = True, via: str = "measure", tier: str = "measure") -> str:
    """Fetch what a measurement of `name` loads and is not on disk, under the floor: why it could not, or "". #2015, #2161."""
    from harness import methods
    target = methods.weights_of(name) if methods.is_method(name) else name
    if not target or not missing(target, conn):
        return ""
    floor = disk_floor() if floor is None else floor
    # Its dependencies are checked before a byte of it is fetched, and a refusal is a verdict. #2161.
    gap = dependency_gap(conn, target, free=free, floor=floor, sizer=sizer)
    if gap:
        _decline(conn, name, gap[0], gap[1], tier)
        return gap[1]
    if not have(target, conn):
        facts = card(conn, target)
        p = plan(target, int(facts.get("size_bytes") or 0), free=free, floor=floor)
        if not p.ok:
            return f"{target}: {p.why}"
        try:
            _land(conn, target, facts, snapshot=snapshot, listing=listing, hf_download=hf_download,
                  free=free, floor=floor, refresh=refresh, via=via)
        except FetchError as exc:
            return f"{target}: {exc}"
    _, _, waiting = _needs(conn, target, free=free, floor=floor, snapshot=snapshot, refresh=refresh, sizer=sizer)
    return waiting[1] if waiting else ""

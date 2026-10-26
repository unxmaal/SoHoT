"""A candidate's family is its lineage root: paired losses demote the rest of a family in a lane (#1100), and a family unmeasured there gets a reserved measure slot (#1111)."""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field

from harness import lanes

DAY = 86400.0
#: Distinct members of one family that lost a paired comparison in a lane, since its last win there, before the rest rank lower.
LOSSES_TO_DEMOTE = 2
#: What a demoted family's remaining members lose in rank.value.
DEMOTION = -3.0
#: Days a lane's paired comparison of a family counts as recent, for the diversity slot.
WINDOW_DAYS = 30.0
#: Measure slots per sweep held for a family with no recent paired comparison in its lane.
SLOTS = 1
#: Lineage hops followed to a root; a cycle or a longer chain stops there.
HOPS = 8
#: A parent more than this many times larger or smaller than its child is a card error, and the chain stops before it.
SIZE_RATIO = 2.0

#: Name words that say a model was trained for a lane: such a member is exempt from its family's demotion there.
LANE_TRAINING = {"code": ("coder", "code", "codestral", "devstral", "swe"), "web": ("web", "html", "webdev"),
                 "svg": ("svg",), "agent": ("agent", "agentic", "toolcall"), "decide": ("decider",),
                 "ocr": ("ocr",), "stt": ("asr", "stt"), "tts": ("tts",)}
_WORDS = re.compile(r"[a-z0-9]+")


def key(name: str) -> str:
    """A root's family key: its basename, lowercased, less a format suffix and a -base suffix."""
    from harness.quants import FORMAT_SUFFIX
    base = (name or "").strip().rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    base = FORMAT_SUFFIX.sub("", base).lower()
    return base[:-5] if base.endswith("-base") and len(base) > 5 else base


def graph(conn) -> dict[str, list[str]]:
    """name -> its lineage parents, lowercased, in the order inspect wrote them."""
    out: dict[str, list[str]] = {}
    for r in conn.execute("SELECT p.name, l.parent FROM lineage l JOIN proposals p ON p.id = l.proposal_id "
                          "ORDER BY l.id"):
        got = out.setdefault(str(r[0]).strip().lower(), [])
        parent = str(r[1]).strip().lower()
        if parent and parent not in got:
            got.append(parent)
    return out


def root(name: str, parents_of: dict, parents=()) -> str:
    """The end of `name`'s first-parent lineage chain; `name` itself when no lineage is known."""
    cur = (name or "").strip().lower()
    ups = parents_of.get(cur) or [str(p[0] if isinstance(p, (tuple, list)) else p).strip().lower()
                                  for p in parents if p]
    seen = {cur}
    while ups and ups[0] not in seen and len(seen) <= HOPS and _same_size(cur, ups[0]):
        cur = ups[0]
        seen.add(cur)
        ups = parents_of.get(cur) or []
    if ups and ups[0] not in seen and len(seen) > HOPS and _same_size(cur, ups[0]):
        from harness import cuts
        cuts.cut("family_hops", f"lineage of {name} past the hops")
    return cur


def _same_size(child: str, parent: str) -> bool:
    from harness.rank import params_b
    a, b = params_b(child), params_b(parent)
    return not (a and b) or max(a, b) / min(a, b) <= SIZE_RATIO


def base_form(name: str, root_key: str) -> bool:
    """Whether `name` is the root's own weights in some format: Qwen/X, unsloth/X-GGUF, bartowski/Qwen_X-GGUF."""
    own = key(name)
    return bool(root_key) and (own == root_key or own.endswith("_" + root_key))


def exempt(name: str, lane: str) -> str:
    """The word in `name` naming training for `lane`, else ''."""
    words = set(_WORDS.findall((name or "").rsplit("/", 1)[-1].rsplit(":", 1)[-1].lower()))
    return next((w for w in LANE_TRAINING.get(lanes.canonical(lane), ()) if w in words), "")


def _lane(detail: str, fallback: str) -> str:
    head = (detail or "").split(":", 1)[0].strip().lower()
    return head if lanes.known(head) else lanes.canonical(fallback)


@dataclass
class Family:
    lane: str
    key: str
    root: str
    #: Members that lost since the family's last win in the lane, in order.
    lost: list = field(default_factory=list)
    verdicts: int = 0
    won: str = ""
    won_at: float | None = None
    last_compared: float = 0.0
    demoted: bool = False


@dataclass
class Standing:
    """Every family's paired record per lane, and the lineage its members' roots come from."""
    parents_of: dict = field(default_factory=dict)
    families: dict = field(default_factory=dict)
    losses_to_demote: int = LOSSES_TO_DEMOTE

    def key_of(self, row) -> str:
        name = row.get("name", "") if isinstance(row, dict) else str(row)
        parents = row.get("parents") or () if isinstance(row, dict) else ()
        return key(root(name, self.parents_of, parents))

    def of(self, row, lane: str) -> Family | None:
        return self.families.get((lanes.canonical(lane), self.key_of(row)))

    def demotion(self, row, lane: str) -> tuple[float, str]:
        """(score, why) the family term gives `row` in `lane`: DEMOTION once demoted, 0 with a reason when exempt."""
        name = row.get("name", "")
        fam = None if _method(name) else self.of(row, lane)
        if fam is None or not fam.demoted or name.lower() in {n.lower() for n in fam.lost}:
            return 0.0, ""
        if base_form(name, fam.key) and not any(base_form(n, fam.key) for n in fam.lost):
            # Its derivatives lost; no form of the base itself did, so its question is open. #1288.
            return 0.0, f"the {fam.key} base itself has no paired loss in {fam.lane}, only its derivatives"
        word = exempt(name, lane)
        if word:
            return 0.0, (f"exempt from the {fam.key} family demotion in {fam.lane}: "
                         f"its name says {lane} training ({word})")
        return DEMOTION, (f"{len(fam.lost)} of the {fam.key} family lost at the paired gate in {fam.lane} "
                          f"since its last win, so the rest rank lower")

    def compared_since(self, row, lane: str, since: float) -> bool:
        fam = self.of(row, lane)
        return fam is not None and fam.last_compared >= since

    def demoted(self) -> list[Family]:
        return sorted((f for f in self.families.values() if f.demoted), key=lambda f: (f.lane, -len(f.lost), f.key))


def _method(name: str) -> bool:
    """A method crossing is the incumbent run another way, never a family of its own."""
    from harness import methods
    return methods.is_method(name)


def standing(conn, losses_to_demote: int | None = None) -> Standing:
    """Paired outcomes per family and lane from the store's adopt verdicts; empty when there is no store to read."""
    from harness import adopt, reasons
    need = LOSSES_TO_DEMOTE if losses_to_demote is None else int(losses_to_demote)
    if conn is None:
        return Standing(losses_to_demote=need)
    try:
        parents_of = graph(conn)
        rows = conn.execute(
            "SELECT v.decided_at, v.outcome, v.detail, p.name, p.lane FROM verdicts v "
            "JOIN proposals p ON p.id = v.proposal_id WHERE v.tier = ? AND v.reason = ? "
            "AND v.outcome IN ('measured', 'declined') ORDER BY v.decided_at, v.id",
            (adopt.TIER, reasons.CANDIDATE)).fetchall()
    except (AttributeError, sqlite3.Error):
        # An order hint never fails the ranking or the sweep; no record is the answer.
        return Standing(losses_to_demote=need)
    out = Standing(parents_of=parents_of, losses_to_demote=need)
    for at, outcome, detail, name, lane in rows:
        if _method(name):
            continue
        lane = _lane(detail, lane)
        k = key(root(name, parents_of))
        fam = out.families.setdefault((lane, k), Family(lane, k, root(name, parents_of)))
        fam.verdicts += 1
        fam.last_compared = max(fam.last_compared, float(at or 0))
        if outcome == "measured":
            fam.lost, fam.won, fam.won_at = [], name, float(at or 0)
        elif name not in fam.lost:
            fam.lost.append(name)
    for fam in out.families.values():
        fam.demoted = need > 0 and len(fam.lost) >= need
    return out


def measure_order(rows, st: Standing) -> list[dict]:
    """The measure queue with a demoted family's members after the rest, each part in its own order."""
    rows = list(rows)
    low = [bool(st.demotion(r, r.get("lane", ""))[0]) for r in rows]
    return [r for r, d in zip(rows, low) if not d] + [r for r, d in zip(rows, low) if d]


def reserve(rows, st: Standing, *, now: float | None = None, slots: int | None = None,
            window_days: float | None = None, fits=None) -> tuple[list[dict], list[dict], list[str]]:
    """(queue, picks, lines): up to `slots` of the highest-placed rows whose family has no paired comparison in
    its lane within the window, moved to the head; a pick that does not fit gives its slot back, and says so."""
    now = time.time() if now is None else now
    slots = SLOTS if slots is None else int(slots)
    days = WINDOW_DAYS if window_days is None else float(window_days)
    rows, picks, lines, families = list(rows), [], [], set()
    if slots <= 0:
        return rows, [], [f"diversity: {slots} slot(s) reserved, so none is held"]
    since = now - days * DAY
    for r in rows:
        if len(picks) >= slots:
            break
        lane = lanes.canonical(r.get("lane"))
        k = st.key_of(r)
        fam = st.of(r, lane)
        if _method(r.get("name", "")) or (lane, k) in families or (fam and fam.demoted) \
                or st.compared_since(r, lane, since):
            continue
        ok, why = fits(r) if fits else (True, "")
        if not ok:
            lines.append(f"diversity: {r.get('name', '')} ({k}) does not fit: {why}")
            continue
        families.add((lane, k))
        last = (f"last compared {(now - fam.last_compared) / DAY:.0f} days ago" if fam and fam.last_compared
                else "never compared")
        picks.append({"name": r.get("name", ""), "lane": lane, "family": k, "why": f"{k} in {lane}: {last}"})
        lines.append(f"diversity: {r.get('name', '')} takes a reserved slot, family {k} in {lane} "
                     f"has no paired comparison in {days:g} days ({last})")
    if len(picks) < slots:
        lines.append(f"diversity: {slots - len(picks)} reserved slot(s) return to the normal queue: no other "
                     f"candidate of a family unmeasured in {days:g} days fits")
    chosen = {p["name"] for p in picks}
    return [r for r in rows if r.get("name") in chosen] + [r for r in rows if r.get("name") not in chosen], picks, lines


def plan(rows, st: Standing, n: int, **kw) -> list[dict]:
    """The first `n` measurements of a sweep: demoted families last, then the reserved slots at the head."""
    queue, _, _ = reserve(measure_order(rows, st), st, **kw)
    return queue[:max(int(n), 0)]

"""Owner blind A/B picks on perceptual lanes: a holdout win waits for the owner's picks before it is adopted (#2183)."""
from __future__ import annotations

import json
import mimetypes
import random
import secrets
import time
from dataclasses import asdict, replace
from pathlib import Path

from harness import lanes, reasons

#: Blind pairs the owner is shown for one held win. #2183.
PAIRS = 6
#: Pairs of those the challenger must win outright, and more than the incumbent wins, to be adopted. #2183.
NEEDED = 4

WAITING, ADOPTED, DECLINED = "waiting", "adopted", "declined"
CHOICES = ("left", "right", "none")
SIDES = ("left", "right")
#: verdict.evidence key set once the picks are in, so the gate lets the verdict through.
PICKED = "owner_picked"
#: The status.json and cond key prefix of an item.
KEY = "picks-"


def kind_of(path: str) -> str:
    """image, audio or video, by the file's type; '' for anything a page cannot play."""
    mime = mimetypes.guess_type(str(path))[0] or ""
    return mime.split("/")[0] if mime.split("/")[0] in ("image", "audio", "video") else ""


def _names(conn, verdict, spec: str) -> dict[str, str]:
    """Each name a results row may carry for the incumbent and the challenger -> 'inc' or 'chal'."""
    from harness import candidates
    names = {verdict.incumbent: "inc", verdict.challenger: "chal"}
    row = candidates.get(conn, spec) if spec else None
    if row:
        names.setdefault(row["receipt_key"], "chal")
    return {k: v for k, v in names.items() if k}


def pairs_for(conn, runs: list, names: dict[str, str], n: int, rng: random.Random) -> list[dict]:
    """Up to `n` pairs of the two sides' stored outputs on one case, each side placed by a coin flip. Regenerates nothing."""
    if not runs:
        return []
    marks = ",".join("?" * len(runs))
    have: dict[str, dict[str, str]] = {}
    for r in conn.execute(f"SELECT case_id, candidate, artifact_path FROM results WHERE run_id IN ({marks}) "
                          f"AND artifact_path IS NOT NULL ORDER BY run_id, seq", [int(x) for x in runs]):
        side, path = names.get(r["candidate"]), str(r["artifact_path"] or "")
        if side and kind_of(path) and Path(path).is_file():
            have.setdefault(r["case_id"], {}).setdefault(side, path)
    cases = sorted(c for c, sides in have.items() if len(sides) == 2)
    if len(cases) > n:
        from harness import cuts
        cuts.cut("owner_picks_pairs", f"{len(cases)} cases have both outputs; {n} blind pairs are shown", value=n,
                 kept=n, dropped=len(cases) - n, conn=conn)
    out = []
    for case in rng.sample(cases, min(n, len(cases))):
        flip = rng.random() < 0.5
        inc, chal = have[case]["inc"], have[case]["chal"]
        left, right = (chal, inc) if flip else (inc, chal)
        out.append({"case": case, "left": left, "right": right, "left_is": "chal" if flip else "inc", "pick": ""})
    return out


def waiting(conn) -> list[dict]:
    return [_item(r) for r in conn.execute("SELECT * FROM owner_picks WHERE state = ? ORDER BY id", (WAITING,))]


def get(conn, pid: int) -> dict | None:
    r = conn.execute("SELECT * FROM owner_picks WHERE id = ?", (int(pid),)).fetchone()
    return _item(r) if r else None


def _item(r) -> dict:
    return {**dict(r), "pairs": json.loads(r["pairs"] or "[]"), "held": json.loads(r["held"] or "{}")}


def waiting_for(conn, lane: str, challenger: str) -> dict | None:
    for it in waiting(conn):
        if it["lane"] == lanes.canonical(lane) and challenger in (it["challenger"], it["spec"], it["proposal"]):
            return it
    return None


def gate(conn, verdict, spec: str, run_id=None, seed: int | None = None):
    """(verdict to record, item to open or None): a perceptual lane's measured win waits for the owner; everything else passes."""
    from harness import adopt
    if not (verdict.adopt and verdict.how == adopt.MEASURED and lanes.perceptual(verdict.lane)
            and not verdict.evidence.get(PICKED)):
        return verdict, None
    if waiting_for(conn, verdict.lane, spec or verdict.challenger):
        return _awaiting(verdict, "an earlier win of it already waits for the owner's picks"), None
    runs = [x for x in [run_id, *(verdict.evidence.get("pick_runs") or [])] if x is not None]
    rng = random.Random(secrets.randbits(64) if seed is None else seed)
    pairs = pairs_for(conn, list(dict.fromkeys(runs)), _names(conn, verdict, spec), PAIRS, rng)
    if not pairs:
        return replace(verdict, adopt=False, failure_class=reasons.HARNESS_ERROR,
                       why=f"won the gate, but no stored output of both sides exists to show the owner ({verdict.why})"), None
    held = asdict(verdict)
    return _awaiting(verdict, f"{len(pairs)} blind pair(s) wait for the owner's picks"), {
        "lane": lanes.canonical(verdict.lane), "incumbent": verdict.incumbent, "challenger": verdict.challenger,
        "spec": spec or verdict.challenger, "run_id": run_id, "pairs": pairs, "held": held}


def _awaiting(verdict, said: str):
    return replace(verdict, adopt=False, failure_class=reasons.AWAITING_OWNER, why=f"won the gate; {said} ({verdict.why})")


def open_item(conn, vid: int, item: dict, proposal: str = "") -> int:
    """Write the waiting item beside the held verdict `vid`, uncommitted."""
    cur = conn.execute(
        "INSERT INTO owner_picks (verdict_id, lane, incumbent, challenger, spec, proposal, run_id, state, pairs, held, opened_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (vid, item["lane"], item["incumbent"], item["challenger"], item["spec"], proposal or item["spec"], item["run_id"],
         WAITING, json.dumps(item["pairs"]), json.dumps(item["held"], default=str), time.time()))
    return int(cur.lastrowid)


def pinned_specs(conn) -> list[tuple[str, str]]:
    """(lane, spec) of each challenger whose weights stay while the owner has not picked."""
    return [(it["lane"], it["spec"]) for it in waiting(conn)]


def holds_weights(conn, name: str) -> bool:
    return any(name in (it["proposal"], it["spec"], it["challenger"]) for it in waiting(conn))


def tally(pairs: list[dict]) -> dict:
    """Wins for the challenger and the incumbent and the pairs left open or without preference."""
    out = {"chal": 0, "inc": 0, "none": 0, "open": 0}
    for p in pairs:
        if not p["pick"]:
            out["open"] += 1
        elif p["pick"] == "none":
            out["none"] += 1
        else:
            out[p["left_is"] if p["pick"] == "left" else ("inc" if p["left_is"] == "chal" else "chal")] += 1
    return out


def preferred(pairs: list[dict], needed: int | None = None) -> bool:
    """The challenger takes at least `needed` of the pairs (all of them when fewer were shown) and more than the incumbent; ties count for neither."""
    t = tally(pairs)
    return t["chal"] >= min(NEEDED if needed is None else needed, len(pairs)) and t["chal"] > t["inc"]


def pick(conn, pid: int, n: int, choice: str) -> tuple[dict, str]:
    """Record the owner's choice on pair `n`; once every pair has one, adopt or decline by them. (item, what happened)."""
    it = get(conn, pid)
    if it is None or it["state"] != WAITING:
        raise ValueError(f"no waiting picks item {pid}")
    if choice not in CHOICES:
        raise ValueError(f"a pick is one of {', '.join(CHOICES)}")
    if not 0 <= int(n) < len(it["pairs"]):
        raise ValueError(f"item {pid} has no pair {n}")
    it["pairs"][int(n)]["pick"] = choice
    conn.execute("UPDATE owner_picks SET pairs = ? WHERE id = ? AND state = ?", (json.dumps(it["pairs"]), int(pid), WAITING))
    conn.commit()
    left = tally(it["pairs"])["open"]
    if left:
        return it, f"pair {int(n) + 1} picked; {left} left"
    return it, resolve(conn, it)


def resolve(conn, it: dict) -> str:
    """Adopt or decline the held win by the picks, recording them on the verdict."""
    from harness import adopt, test_weights
    held = {**it["held"], "alpha_cut": tuple(it["held"].get("alpha_cut") or ())}
    verdict = adopt.Verdict(**held)
    t = tally(it["pairs"])
    won = preferred(it["pairs"])
    summary = {"chal": t["chal"], "inc": t["inc"], "none": t["none"], "needed": min(NEEDED, len(it["pairs"])),
               "pairs": [{"case": p["case"], "pick": p["pick"], "winner": _winner(p)} for p in it["pairs"]]}
    said = f"the owner preferred it in {t['chal']} of {len(it['pairs'])} blind pairs, the incumbent in {t['inc']}, {t['none']} no preference"
    evidence = {**verdict.evidence, PICKED: summary}
    if won:
        out = replace(verdict, adopt=True, failure_class="", evidence=evidence, why=f"{verdict.why}; {said}")
    else:
        out = replace(verdict, adopt=False, failure_class=reasons.OWNER_DECLINED, evidence=evidence,
                      why=f"won the gate, but {said}")
    if not won and t["chal"] > t["inc"]:
        from harness import cuts
        cuts.cut("owner_picks_needed", f"{it['spec']}: {t['chal']} blind pairs for it of {len(it['pairs'])}, short of {summary['needed']}",
                 value=summary["needed"], kept=0, dropped=1, conn=conn)
    adopt.record(conn, out, spec=it["spec"], run_id=it["run_id"])
    conn.execute("UPDATE owner_picks SET state = ?, decided_at = ? WHERE id = ? AND state = ?",
                 (ADOPTED if won else DECLINED, time.time(), it["id"], WAITING))
    conn.commit()
    if not won:
        test_weights.release(it["proposal"])
    return f"{'ADOPTED' if won else 'declined'} {it['spec']} over {it['incumbent']}: {said}"


def _winner(p: dict) -> str:
    if p["pick"] not in SIDES:
        return "none"
    return p["left_is"] if p["pick"] == "left" else ("inc" if p["left_is"] == "chal" else "chal")


def media(conn, pid: int, n: int, side: str) -> tuple[Path, str] | None:
    """The stored file of one side of one pair of a waiting item and its media type; only what the item holds."""
    it = get(conn, pid)
    if it is None or it["state"] != WAITING or side not in SIDES or not 0 <= n < len(it["pairs"]):
        return None
    path = Path(it["pairs"][n][side])
    return (path, mimetypes.guess_type(str(path))[0] or "application/octet-stream") if path.is_file() else None


def view(conn) -> list[dict]:
    """The waiting items as the status page shows them: no model name, no spec, nothing that says which side is which."""
    out = []
    for it in waiting(conn):
        pairs = [{"n": i, "kind": kind_of(p["left"]), "picked": p["pick"], "left": f"status/pick-media/{it['id']}/{i}/left",
                  "right": f"status/pick-media/{it['id']}/{i}/right"} for i, p in enumerate(it["pairs"])]
        out.append({"id": it["id"], "lane": it["lane"], "since": it["opened_at"], "pairs": pairs,
                    "open": sum(1 for p in pairs if not p["picked"])})
    return out


def read(conn, now: float | None = None) -> dict:
    """The status section: {'items': view(conn)}; with no store, an error the band names."""
    if conn is None:
        return {"items": [], "why": "store down: picks not read"}
    return {"items": view(conn)}

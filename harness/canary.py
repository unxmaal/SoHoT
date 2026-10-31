"""The night canary: planted candidates with known verdicts, run for real under an isolated home. #919."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from harness import paths, reasons

#: `soh morning` calls the canary stale when its newest receipt is older than this.
STALE_DAYS = 8
#: How long the canary waits for the live discovery loop to finish before giving up for the week.
WAIT_H = 3.0
POLL_S = 300.0
#: The GPU lock's declared deadline per plant, so a watchdog can tell a stuck canary from a slow one.
PLANT_DEADLINE_S = 2 * 3600.0
SOURCE = "canary"


@dataclass(frozen=True)
class Plant:
    name: str
    lane: str
    challenger: str
    #: (outcome, tier, reason) of the plant's final verdict; an empty reason is not checked.
    expect: tuple
    #: "" serves the lane's typed constant; otherwise adopted by hand in the isolated store first.
    incumbent: str = ""
    #: "adopt" runs the loop's spend; "screen" stops after the screen, so nothing is measured.
    through: str = "adopt"
    #: A PRECONDITIONS key: what must hold on this machine for the expectation to be fixed. #1006.
    requires: str = ""


#: requires -> (what must hold, the runtime it is judged against, failure classes that say it does not).
PRECONDITIONS = {
    "loads": ("the GGUF loads under this llama.cpp build", "llama.cpp",
              (reasons.LOAD_FAILED_FILE, reasons.LOAD_FAILED_RUNTIME)),
}


PLANTS = (
    # The 133-clip holdout separates tdt-1.1b from tdt-0.6b-v3 (12 gained, 2 lost) but not v2 from v3 (7, 3). #1007.
    Plant("stt-known-worse", "stt", "mlx-community/parakeet-tdt-0.6b-v3",
          ("declined", "adopt", "candidate"), incumbent="mlx-community/parakeet-tdt-1.1b"),
    Plant("stt-known-better", "stt", "mlx-community/parakeet-tdt-1.1b",
          ("measured", "adopt", ""), incumbent="mlx-community/parakeet-tdt-0.6b-v3"),
    Plant("gguf-first", "code", "HauhauCS/Nemotron3-Nano-4B-Uncensored-HauhauCS-Aggressive",
          ("screened", "screen", ""), through="screen", requires="loads"),
)


@dataclass(frozen=True)
class Replay:
    """A stored known pair replayed through adopt.decide and confirm: no GPU, no isolated home, no store write. #1294."""
    name: str
    lane: str
    #: Receipt keys, as the results table names the candidates.
    incumbent: str
    challenger: str
    #: (the incumbent's measure run, the challenger's); the same run when both ran in one.
    runs: tuple
    #: (outcome, reason) the gate must reach; an empty reason is not checked.
    expect: tuple


REPLAYS = (
    # Opus against Ornith on one shared exam, scores in the issue. #1294.
    Replay("repo-known-better", "repo", "llamacpp:Ornith-1.5-35B-Q4_K_M", "claude-code:claude-opus-5-5",
           (571, 572), ("measured", "")),
    Replay("repo-known-worse", "repo", "claude-code:claude-opus-5-5", "llamacpp:Ornith-1.5-35B-Q4_K_M",
           (572, 571), ("declined", "candidate")),
    # Ornith against the smallest LFM in one run, the newest code run the gate separates both ways.
    Replay("code-known-better", "code", "LiquidAI/LFM2.5-350M", "llamacpp:Ornith-1.5-35B-Q4_K_M",
           (378, 378), ("measured", "")),
    Replay("code-known-worse", "code", "llamacpp:Ornith-1.5-35B-Q4_K_M", "LiquidAI/LFM2.5-350M",
           (378, 378), ("declined", "candidate")),
)


def _stored_rows(conn, run_id: int, key: str, lane: str) -> list[dict]:
    return [{"case_id": r[0], "candidate": r[1], "passed": bool(r[2]), "metrics": json.loads(r[3] or "{}"),
             "seconds": r[4], "peak_kb": r[5], "failure_class": r[6] or "", "repeat_index": r[7]}
            for r in conn.execute(
                "SELECT x.case_id, x.candidate, x.passed, x.metrics, x.seconds, x.peak_kb, x.failure_class, "
                "x.repeat_index FROM results x JOIN runs u ON u.id = x.run_id "
                "WHERE u.id = ? AND u.lane = ? AND u.tier = 'measure' AND x.candidate = ? ORDER BY x.seq",
                (int(run_id), lane, key))]


def _replay_invalid(conn, r: Replay, rows: list[dict], split) -> str:
    """Why the stored data no longer holds the plant's known answer, else ""; never judged on the gate's answer."""
    from harness import holdout
    for run_id, key in zip(r.runs, (r.incumbent, r.challenger)):
        if not any(x["candidate"] == key for x in rows):
            return f"no rows for {key} in {r.lane} measure run {run_id}"
    digests = {d for (d,) in conn.execute(
        f"SELECT cases_digest FROM runs WHERE id IN ({','.join('?' * len(set(r.runs)))})", tuple(set(r.runs)))}
    if len(digests) != 1 or "" in digests:
        return f"runs {r.runs[0]} and {r.runs[1]} ran different exams ({', '.join(sorted(digests)) or 'none'})"
    shared = ({holdout.base_id(x["case_id"]) for x in rows if x["candidate"] == r.incumbent}
              & {holdout.base_id(x["case_id"]) for x in rows if x["candidate"] == r.challenger})
    on = {side: len(shared & set(getattr(split, side))) for side in ("holdout", "dev")}
    if on["holdout"] < holdout.MIN_HOLDOUT or on["dev"] < holdout.MIN_DEV:
        return (f"today's {r.lane} split leaves {on['holdout']} of the stored cases on the holdout and "
                f"{on['dev']} on dev, under {holdout.MIN_HOLDOUT} and {holdout.MIN_DEV}")
    return ""


def replay(conn, r: Replay, split=None) -> dict:
    """The adopt gate's answer on the plant's stored rows, as `soh measure` asks it, against the known one."""
    from harness import adopt, holdout
    split = holdout.for_lane(r.lane) if split is None else split
    want, want_reason = r.expect
    base = {"plant": r.name, "lane": r.lane, "incumbent": r.incumbent, "challenger": r.challenger,
            "runs": list(r.runs), "expected": [want, adopt.TIER, want_reason], "replay": True, "rcs": []}
    rows = [x for run_id, key in zip(r.runs, (r.incumbent, r.challenger)) for x in _stored_rows(conn, run_id, key, r.lane)]
    bad = _replay_invalid(conn, r, rows, split)
    if bad:
        return {**base, "observed": {}, "invalid": bad, "ok": False}
    v = adopt.decide(r.lane, adopt._summary(rows, r.incumbent), adopt._summary(rows, r.challenger), rows,
                     split=split)
    v = adopt.confirm(v, rows, split)
    outcome, reason = adopt.outcome_of(v)
    got = {"outcome": outcome, "tier": adopt.TIER, "reason": reason, "why": v.why, "id": None}
    ok = outcome == want and (not want_reason or reason == want_reason)
    return {**base, "observed": got, "invalid": "", "ok": ok}


def replay_all(replays) -> list[dict]:
    """Every replay on the live store's stored rows, opened read-only."""
    live = paths.home() / "discovery.db"
    if not replays:
        return []
    if not live.is_file():
        return [{"plant": r.name, "lane": r.lane, "replay": True, "observed": {}, "rcs": [], "ok": False,
                 "expected": [*r.expect[:1], "adopt", r.expect[1]], "invalid": f"no store at {live}"}
                for r in replays]
    conn = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    try:
        return [replay(conn, r) for r in replays]
    finally:
        conn.close()


def unsafe(plant: Plant) -> str:
    """Why a plant cannot run in isolation, else "": an adoption in a gateway text lane restarts the live gateway."""
    from harness import gateway
    if plant.through not in ("adopt", "screen"):
        return f"{plant.name}: through must be adopt or screen, not {plant.through!r}"
    if plant.requires and plant.requires not in PRECONDITIONS:
        return f"{plant.name}: no precondition named {plant.requires!r}"
    if plant.through == "adopt" and plant.lane in gateway.TEXT_LANES:
        return (f"{plant.name}: an adoption in the {plant.lane} lane re-points the live gateway; "
                f"plant it through the screen only")
    return ""


def receipts() -> Path:
    return paths.home() / "canary"


def steps(plant: Plant) -> list[list[str]]:
    """The `soh` commands the plant's isolated home runs, in order: the real inspect, then the spend."""
    out = [["discover", "--inspect", "--from-store", "--run", "--lane", plant.lane, "--top", "1"]]
    if plant.through == "screen":
        return out + [["fetch", "--run", "--limit", "1"],
                      ["discover", "--screen", "--run", "--lane", plant.lane, "--top", "1"]]
    return out + [["canary", "spend", "--lane", plant.lane, "--top", "1"]]


def seed(conn, plant: Plant) -> None:
    """A sighting of the challenger, as a sweep leaves one, and the plant's incumbent adopted by hand."""
    from harness import adopt, screen, winners
    from harness import memory_store as ms
    ms.record(conn, ms.Seen(name=plant.challenger, source=SOURCE, url="", relevance=0,
                            kind="candidate", registry=ms.HUGGINGFACE, lane=plant.lane,
                            resolved=plant.challenger, why=f"planted by soh canary: {plant.name}"))
    typed = winners.typed().get(plant.lane, "")
    if plant.incumbent and plant.incumbent != typed:
        spec = screen.candidate_for(plant.lane, plant.incumbent)
        adopt.record(conn, adopt.Verdict(plant.lane, typed, spec, True,
                                         f"the canary's planted incumbent for {plant.name}",
                                         adopt.BY_HAND, forced=True), spec=spec)
    conn.commit()


def observe(conn, plant: Plant) -> dict:
    """The plant's final verdict in its isolated store, and what the lane serves afterwards."""
    from harness import adopt, winners
    row = conn.execute(
        "SELECT v.id, v.outcome, v.tier, v.reason, v.detail, v.failure_class FROM proposals p "
        "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (plant.challenger,)).fetchone()
    got = dict(row) if row else {"id": None, "outcome": "", "tier": "", "reason": "", "detail": "", "failure_class": ""}
    got["serves"] = adopt.default_for(plant.lane, winners.typed().get(plant.lane, ""), conn=conn)
    return got


def matches(plant: Plant, got: dict) -> bool:
    outcome, tier, reason = plant.expect
    if (got.get("outcome"), got.get("tier")) != (outcome, tier) or (reason and got.get("reason") != reason):
        return False
    if tier != "adopt":
        return True
    from harness import screen
    serves = got.get("serves") in (plant.challenger, screen.candidate_for(plant.lane, plant.challenger))
    return serves == (outcome == "measured")


def runtime_version(plant: Plant) -> str:
    from harness import memory_store as ms
    if not plant.requires:
        return ""
    return str(ms.this_machine().get("versions", {}).get(PRECONDITIONS[plant.requires][1]) or "")


def violated(plant: Plant, got: dict, version: str) -> str:
    """Why the plant's own run shows its precondition does not hold here, else ""."""
    if not plant.requires:
        return ""
    what, runtime, classes = PRECONDITIONS[plant.requires]
    if got.get("failure_class") not in classes:
        return ""
    return f"{what} does not hold ({runtime} {version or '?'}): {(got.get('detail') or '')[:300]}"


def still_invalid(plant: Plant, prior: dict | None, version: str) -> str:
    """The invalidity a previous receipt found for this plant, while the runtime it was judged on is unchanged."""
    for p in (prior or {}).get("plants") or []:
        if p.get("plant") == plant.name and p.get("invalid") and version and p.get("version") == version:
            return p["invalid"]
    return ""


def leaked(live: Path, names, since: float) -> int:
    """Verdicts on the plants' names the live store took since the canary started; read-only."""
    if not live.is_file():
        return 0
    names = list(names)
    if not names:
        return 0
    conn = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    try:
        return conn.execute(
            f"SELECT count(*) FROM verdicts WHERE decided_at > ? AND proposal_id IN "
            f"(SELECT id FROM proposals WHERE name IN ({','.join('?' * len(names))}))",
            (since, *names)).fetchone()[0]
    finally:
        conn.close()


def child_env(home: Path) -> dict:
    """The isolated home, under the GPU lock the canary already holds on the live one, whose services it uses."""
    from harness import exclusive, load_log
    serving = os.environ.get(load_log.SERVING_ENV) or str(paths.home())
    return {**os.environ, paths.ENV_VAR: str(home), exclusive.HELD_ENV: "1", load_log.SERVING_ENV: serving}


def run_plant(plant: Plant, home: Path, run=subprocess.run, say=print, prior: dict | None = None) -> dict:
    """Seed `home`, run the plant's steps in it, and read back what it decided."""
    from harness import memory_store as ms
    if paths.is_live(home / "discovery.db") or home.resolve() == paths.home().resolve():
        raise RuntimeError(f"{home} is the live home; the canary runs only in an isolated one")
    version = runtime_version(plant)
    base = {"plant": plant.name, "lane": plant.lane, "challenger": plant.challenger,
            "expected": list(plant.expect), "home": str(home), "version": version}
    known = still_invalid(plant, prior, version)
    if known:
        say(f"  {plant.name}: not planted, still invalid on this machine")
        return {**base, "observed": {}, "rcs": [], "invalid": known, "ok": False}
    home.mkdir(parents=True, exist_ok=True)
    conn = ms.connect(home / "discovery.db")
    try:
        seed(conn, plant)
    finally:
        conn.close()
    rcs = []
    for argv in steps(plant):
        say(f"  {plant.name}: soh {' '.join(argv)}")
        with open(home / "canary.log", "a", encoding="utf-8") as log:
            rcs.append(run([sys.executable, "-m", "harness.cli", *argv], env=child_env(home),
                           cwd=str(paths.REPO), stdout=log, stderr=subprocess.STDOUT).returncode)
    conn = ms.connect(home / "discovery.db")
    try:
        got = observe(conn, plant)
    finally:
        conn.close()
    bad = violated(plant, got, version)
    return {**base, "observed": got, "rcs": rcs, "invalid": bad, "ok": not bad and matches(plant, got)}


def loop_running() -> bool:
    from harness import heartbeat
    beat = heartbeat.summary()
    return bool(beat) and beat.get("status") == "running"


def run(plants=PLANTS, run=subprocess.run, now=time.time, sleep=time.sleep, wait_h: float = WAIT_H,
        say=print, replays=()) -> dict:
    """Every replay on stored rows, then every plant in its own isolated home after the live loop finishes; one receipt."""
    from harness import exclusive
    bad = [why for why in map(unsafe, plants) if why]
    if bad:
        raise ValueError("; ".join(bad))
    first = now()
    out = replay_all(replays)
    deadline = first + wait_h * 3600
    while plants and loop_running():
        if now() >= deadline:
            from harness import cuts
            cuts.cut("canary_wait_h", "the canary's plants: the discovery loop was still running", value=wait_h,
                     kept=0, dropped=len(plants))
            return write({"started": first, "finished": now(), "plants": out, "leaked": 0, "ok": False,
                          "skipped": f"the discovery loop was still running after {wait_h:g} h"})
        say("  the discovery loop is running; waiting for it to finish")
        sleep(POLL_S)
    started = now()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(started))
    prior = latest()
    if plants:
        with exclusive.held("eval", announce=say, deadline_s=PLANT_DEADLINE_S * len(plants)):
            for plant in plants:
                out.append(run_plant(plant, receipts() / "homes" / stamp / plant.name, run=run, say=say,
                                     prior=prior))
    n = leaked(paths.home() / "discovery.db", [p.challenger for p in plants], started)
    return write({"started": started, "finished": now(), "plants": out, "leaked": n,
                  "ok": bool(out) and all(p["ok"] for p in out) and n == 0})


def write(receipt: dict) -> dict:
    d = receipts()
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(receipt["started"]))
    path = d / f"canary-{stamp}.json"
    path.write_text(json.dumps(receipt, indent=1, sort_keys=True), encoding="utf-8")
    receipt["path"] = str(path)
    return receipt


def latest() -> dict | None:
    """The newest receipt, by its own start time, or None."""
    best = None
    for f in sorted(receipts().glob("canary-*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if best is None or float(r.get("started") or 0) >= float(best.get("started") or 0):
            best = r
    return best


def morning_line(now: float | None = None) -> str:
    """One line for `soh morning` when the canary needs a person, else ""."""
    now = time.time() if now is None else now
    r = latest()
    if r is not None and now - float(r.get("started") or 0) > STALE_DAYS * 86400:
        from harness import cuts
        cuts.cut("canary_stale_days", "the newest canary receipt, too old to vouch for the loop", kept=0, dropped=1)
    if r is None or now - float(r.get("started") or 0) > STALE_DAYS * 86400:
        return f"the canary has no receipt newer than {STALE_DAYS} days"
    wrong = [p["plant"] for p in r.get("plants") or [] if not p.get("ok") and not p.get("invalid")]
    invalid = [p["plant"] for p in r.get("plants") or [] if p.get("invalid")]
    if r.get("skipped"):
        return f"the canary did not run: {r['skipped']}"
    if wrong:
        return f"the canary's plants missed their expected verdicts: {', '.join(wrong)}"
    if invalid:
        return f"the canary's plants are invalid on this machine and need replacing: {', '.join(invalid)}"
    if r.get("leaked"):
        return f"the canary leaked {r['leaked']} verdict(s) into the live store"
    return ""


def separable(conn, plant: Plant) -> dict:
    """Whether the adopt gate, on the newest stored run holding both candidates, gives the plant's expected answer."""
    from harness import adopt, screen
    if plant.through != "adopt":
        return {"plant": plant.name, "ok": True, "why": "screened only, nothing to separate"}
    inc, ch = (screen.candidate_for(plant.lane, n) for n in (plant.incumbent, plant.challenger))
    run_row = conn.execute(
        "SELECT r.run_id FROM results r JOIN candidates c ON c.id = r.candidate_id "
        "JOIN runs u ON u.id = r.run_id WHERE c.spec IN (?, ?) AND u.tier = 'measure' "
        "GROUP BY r.run_id HAVING count(DISTINCT c.spec) = 2 ORDER BY u.generated_at DESC, r.run_id DESC LIMIT 1",
        (inc, ch)).fetchone()
    if not run_row:
        return {"plant": plant.name, "ok": False, "why": f"no stored measure run holds both {inc} and {ch}"}
    rows = [{"case_id": r[0], "candidate": r[1], "passed": bool(r[2]), "metrics": json.loads(r[3] or "{}"),
             "seconds": r[4], "repeat_index": r[5]} for r in conn.execute(
        "SELECT r.case_id, c.spec, r.passed, r.metrics, r.seconds, r.repeat_index FROM results r "
        "JOIN candidates c ON c.id = r.candidate_id WHERE r.run_id = ? AND c.spec IN (?, ?)",
        (run_row[0], inc, ch))]
    v = adopt.decide(plant.lane, adopt._summary(rows, inc), adopt._summary(rows, ch), rows)
    outcome, reason = adopt.outcome_of(v)
    want, _, want_reason = plant.expect
    ok = outcome == want and (not want_reason or reason == want_reason)
    return {"plant": plant.name, "run_id": run_row[0], "ok": ok, "why": f"{outcome}/{reason}: {v.why}"}


def plant_rows() -> list[dict]:
    return [{**asdict(p), "steps": [" ".join(s) for s in steps(p)], "unsafe": unsafe(p)} for p in PLANTS]

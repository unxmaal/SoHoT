"""Re-point the sohot-<lane> aliases after an adoption without cutting off a request. #483.

LiteLLM 1.100.0's /model/new, /model/update and /model/delete refuse without a
Postgres database (prisma_client) and STORE_MODEL_IN_DB, so the gateway cannot
take a new alias live. The switch is a restart, deferred until the gateway has
had nothing in flight for `idle_s`, read from its own /health/backlog counter
(InFlightRequestsMiddleware, which counts every HTTP request including a stream
until its last byte, and the probe itself). After `max_wait_s` it restarts anyway
and says so. Each switch is a gateway_switches row.

A switch counts only once the restarted gateway serves every moved alias on the
new config (/model/info). A restart that fails or never serves it is a `failed`
row with its reason, retried after a backoff up to RETRIES times; then the old
served config is put back and restarted, so the last good switch stays current
and the next switch() sees the difference and tries again. #522.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from harness import cuts

PROBE_TIMEOUT_S = 5.0

IDLE_S = 60.0
MAX_WAIT_S = 20 * 60.0


def _longest_request_s() -> float:
    from harness import completion
    return max(completion.timeout_for(b) for rungs in completion.LADDER.values() for b in rungs)


#: How long a drain waits for in-flight requests: the longest timeout any eval rung allows, plus a margin. #703.
DRAIN_S = _longest_request_s() + 5 * 60.0
DRAIN_FILE = "gateway.draining"
#: What the gateway answers with its 503 while draining; reasons reads it as refused_by_gateway.
DRAINING = "the gateway is draining"
POLL_S = 2.0
RETRIES = 3
BACKOFF_S = 30.0
SERVE_WAIT_S = 120.0
SWITCHED, FAILED = "switched", "failed"
#: Times the worker starts again a switch whose process died, per adoption request, before it alerts instead. #1899.
RESPAWNS = 1


def headers() -> dict:
    """The gateway key for a management call, from the one key source (#482)."""
    from harness import gateway_key
    return gateway_key.headers()


def in_flight(base: str) -> int | None:
    """Requests in flight on the gateway besides this probe; None when it will not say."""
    import httpx

    from harness import completion
    try:
        r = completion.http().get(f"{base.rstrip('/')}/health/backlog", headers=headers(), timeout=PROBE_TIMEOUT_S)
    except httpx.ConnectError:
        return 0
    except httpx.HTTPError as exc:
        if cuts.timed_out(exc):
            cuts.cut("gateway_probe_timeout", "/health/backlog gave no answer in time",
                     kept=0, dropped=1)
        return None
    if r.status_code != 200:
        return None
    try:
        got = int(r.json()["in_flight_requests"])
    except (ValueError, KeyError, TypeError):
        return None
    return max(got - 1, 0)


def _drain_path(node: str = ""):
    from harness import paths
    return paths.home() / "nodes" / f"{node}.draining" if node else paths.home() / DRAIN_FILE


def start_drain(until: float | None = None, node: str = "") -> None:
    """Ask the gateway to refuse new requests, or to send none to NODE, until `until` (epoch seconds), so a dead caller cannot wedge it."""
    until = time.time() + DRAIN_S + SERVE_WAIT_S if until is None else until
    _drain_path(node).parent.mkdir(parents=True, exist_ok=True)
    _drain_path(node).write_text(repr(float(until)), encoding="utf-8")


def stop_drain(node: str = "") -> None:
    _drain_path(node).unlink(missing_ok=True)


def draining(now: float | None = None, node: str = "") -> bool:
    """Whether the gateway should refuse a new request because a switch is draining it, or keep it off a draining NODE. #1815."""
    try:
        until = float(_drain_path(node).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (time.time() if now is None else now) < until


def _drain(base, drain_s, poll_s, clock, sleep, log) -> tuple[str, int | None]:
    """Refuse new requests and wait for the ones in flight, up to drain_s."""
    start_drain(time.time() + drain_s + SERVE_WAIT_S)
    start = clock()
    while True:
        busy = in_flight(base)
        if busy == 0:
            return "drained", busy
        if clock() - start >= drain_s:
            if log:
                log(f"gateway still busy after a {drain_s:.0f}s drain "
                    f"(in flight: {'unknown' if busy is None else busy}); restarting anyway")
            return "forced", busy
        sleep(poll_s)


def wait_then_restart(base: str, restart, idle_s: float = IDLE_S,
                      max_wait_s: float = MAX_WAIT_S, poll_s: float = POLL_S,
                      clock=time.time, sleep=time.sleep, log=None,
                      drain_s: float = DRAIN_S) -> dict:
    """Restart once nothing has been in flight for idle_s; past max_wait_s, drain for up to drain_s first."""
    start = clock()
    quiet_since = None
    while True:
        now = clock()
        busy = in_flight(base)
        if busy == 0:
            quiet_since = now if quiet_since is None else quiet_since
            if now - quiet_since >= idle_s:
                how = "idle"
                break
        else:
            quiet_since = None
        if now - start >= max_wait_s:
            how = "forced"
            if drain_s > 0:
                if log:
                    log(f"gateway not quiet after {max_wait_s:.0f}s; refusing new requests "
                        f"and draining the ones in flight")
                how, busy = _drain(base, drain_s, poll_s, clock, sleep, log)
            elif log:
                log(f"gateway not quiet after {max_wait_s:.0f}s "
                    f"(in flight: {'unknown' if busy is None else busy}); restarting anyway")
            break
        sleep(poll_s)
    try:
        restart()
    finally:
        stop_drain()
    return {"how": how, "in_flight": busy, "switched_at": clock()}


def _aliases(cfg: dict) -> dict:
    """{lane: litellm_params} for each sohot-<lane> alias in a config."""
    from harness import gateway
    names = {gateway.LANE_ALIAS.format(lane): lane for lane in gateway.TEXT_LANES}
    return {names[e.get("model_name")]: dict(e.get("litellm_params") or {})
            for e in cfg.get("model_list") or [] if e.get("model_name") in names}


def switches(conn) -> list[dict]:
    """Every alias switch that took, oldest first."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM gateway_switches WHERE outcome = ? ORDER BY id", (SWITCHED,)).fetchall()]


def failures(conn) -> list[dict]:
    """Every switch attempt that did not take, oldest first. #522."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM gateway_switches WHERE outcome = ? ORDER BY id", (FAILED,)).fetchall()]


def unresolved(conn) -> list[dict]:
    """Per lane, the failures since its last good switch: what `soh report` must show. #522."""
    out = {}
    for r in conn.execute("SELECT * FROM gateway_switches ORDER BY id").fetchall():
        if r["outcome"] == SWITCHED:
            out.pop(r["lane"], None)
        else:
            row = out.setdefault(r["lane"], {"lane": r["lane"], "attempts": 0})
            row.update(new_spec=r["new_spec"], reason=r["reason"], at=r["switched_at"])
            row["attempts"] += 1
    return list(out.values())


def _old_spec(conn, lane: str, params: dict) -> str:
    """What the alias served: the last switch that took, else the upstream model it named."""
    row = conn.execute("SELECT new_spec FROM gateway_switches WHERE lane = ? AND outcome = ? "
                       "ORDER BY id DESC LIMIT 1", (lane, SWITCHED)).fetchone()
    return row["new_spec"] if row else str(params.get("model") or "")


def _launchd_restart() -> bool:
    from harness import gateway
    return subprocess.call([str(gateway.REPO / "scripts" / "launchd.sh"), "restart", "gateway"]) == 0


#: How each platform restarts its gateway service; a platform missing here cannot switch. #703.
RESTARTERS = {"darwin": _launchd_restart}


def can_restart() -> bool:
    return sys.platform in RESTARTERS


def restart_service() -> bool:
    """Restart the gateway service; the caller already holds the machine lock."""
    if not can_restart():
        raise RuntimeError(f"no restart method on {sys.platform}")
    from harness import monitor
    if not monitor.live_home():
        raise RuntimeError(monitor.off_live("restarting the gateway"))
    return RESTARTERS[sys.platform]()


def not_serving(base: str, want: dict) -> str:
    """'' when the gateway serves every alias in `want` ({alias: model}) as given, else why not."""
    import httpx

    from harness import completion
    try:
        r = completion.http().get(f"{base.rstrip('/')}/model/info", headers=headers(), timeout=PROBE_TIMEOUT_S)
    except httpx.HTTPError as exc:
        if cuts.timed_out(exc):
            cuts.cut("gateway_probe_timeout", "/model/info gave no answer in time",
                     kept=0, dropped=1)
        return f"the gateway did not answer /model/info: {exc}"
    if r.status_code != 200:
        return f"/model/info answered HTTP {r.status_code}"
    try:
        served = {e.get("model_name"): (e.get("litellm_params") or {}).get("model")
                  for e in r.json().get("data") or []}
    except (ValueError, AttributeError):
        return "/model/info answered something that is not its JSON"
    wrong = [f"{alias} serves {served.get(alias)!r}, not {model!r}"
             for alias, model in sorted(want.items()) if served.get(alias) != model]
    return "; ".join(wrong)


def _await_serving(base, want, clock, sleep, poll_s) -> str:
    deadline = clock() + SERVE_WAIT_S
    while True:
        why = not_serving(base, want)
        late = clock() >= deadline
        if why and late:
            cuts.cut("harness/gateway_switch.py:SERVE_WAIT_S", f"the restarted gateway still did not serve: {why}",
                     kept=0, dropped=1)
        if not why or late:
            return why
        sleep(poll_s)


def switch(base: str | None = None, restart=restart_service, requested_at=None,
           idle_s: float = IDLE_S, max_wait_s: float = MAX_WAIT_S,
           poll_s: float = POLL_S, clock=time.time, sleep=time.sleep,
           log=None, config=None, drain_s: float = DRAIN_S, advance=None) -> list[dict]:
    """Regenerate the served config and restart once quiet, if any lane alias moved; `advance` moves its state row."""
    import json
    from harness import adopt, gateway
    from harness import gateway_switch_state as st
    from harness.completion import DEFAULT_GATEWAY
    base = base or DEFAULT_GATEWAY
    advance = advance or (lambda *a, **k: None)
    requested_at = clock() if requested_at is None else requested_at
    path = gateway.served_path(config)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    old = _aliases(gateway.load(path))
    if _aliases(gateway.served(config)) == old:
        advance(st.REQUESTED, st.SERVING, st.UNCHANGED)
        return []
    if restart is restart_service and not can_restart():
        defaults, new = adopt.lane_defaults(), _aliases(gateway.served(config))
        moved = {lane: (defaults.get(lane, ""), new[lane].get("model"))
                 for lane in new if new[lane] != old.get(lane)}
        _record(moved, old, {"how": "none", "in_flight": None, "switched_at": clock()},
                requested_at, FAILED, f"no restart method on {sys.platform}", log)
        advance(st.REQUESTED, st.FAILED, st.NO_RESTART)
        return []
    moved = {}
    for attempt in range(RETRIES):
        if attempt:
            sleep(BACKOFF_S * 2 ** (attempt - 1))
        restarted = {}

        def regenerate_and_restart(attempt=attempt):
            if attempt:
                advance(st.RESTARTING, st.WRITING, st.RETRY)
            else:
                advance(st.REQUESTED, st.WRITING, st.QUIET, before=before)
            defaults = adopt.lane_defaults()
            gateway.write_served(config, defaults)
            new = _aliases(gateway.load(path))
            moved.clear()
            moved.update({lane: (defaults.get(lane, ""), new[lane].get("model"))
                          for lane in new if new[lane] != old.get(lane)})
            advance(st.WRITING, st.RESTARTING, st.WRITTEN, target=path.read_text(encoding="utf-8"),
                    moved=json.dumps(moved, sort_keys=True))
            try:
                restarted["ok"] = restart() is not False
            except Exception as exc:  # noqa: BLE001
                restarted["ok"], restarted["why"] = False, f"{type(exc).__name__}: {exc}"

        got = wait_then_restart(base, regenerate_and_restart, idle_s, max_wait_s,
                                poll_s, clock, sleep, log, drain_s)
        if restarted.get("ok"):
            want = {gateway.LANE_ALIAS.format(lane): model for lane, (_, model) in moved.items()}
            why = _await_serving(base, want, clock, sleep, poll_s)
        else:
            why = "the gateway restart failed" + (f": {restarted['why']}" if restarted.get("why") else "")
        if not why:
            rows = _record(moved, old, got, requested_at, SWITCHED, "", log)
            advance(st.RESTARTING, st.SERVING, st.SERVED)
            return rows
        _record(moved, old, {**got, "switched_at": clock()}, requested_at, FAILED, why, log)
    cuts.cut("harness/gateway_switch.py:RETRIES", f"the switch gave up after {RETRIES} attempts and restores the old config",
             kept=0, dropped=len(moved))
    if before is not None:
        path.write_text(before, encoding="utf-8")
        try:
            back = restart() is not False
        except Exception as exc:  # noqa: BLE001
            back = False
            if log:
                log(f"restoring the old config: {type(exc).__name__}: {exc}")
        if log:
            log("the old config is restored" + ("" if back else ", but its restart failed too"))
    advance(st.RESTARTING, st.FAILED, st.GAVE_UP)
    return []


def _record(moved, old, got, requested_at, outcome, reason, log) -> list[dict]:
    from harness import memory_store as ms
    rows = []
    conn = ms.connect()
    try:
        for lane, (spec, _) in moved.items():
            row = {"lane": lane, "old_spec": _old_spec(conn, lane, old.get(lane, {})),
                   "new_spec": spec, "how": got["how"], "requested_at": requested_at,
                   "switched_at": got["switched_at"], "in_flight": got["in_flight"],
                   "outcome": outcome, "reason": reason}
            conn.execute("INSERT INTO gateway_switches (lane, old_spec, new_spec, how, "
                         "requested_at, switched_at, in_flight, outcome, reason) VALUES "
                         "(:lane, :old_spec, :new_spec, :how, :requested_at, "
                         ":switched_at, :in_flight, :outcome, :reason)", row)
            rows.append(row)
            if log:
                verb = "->" if outcome == SWITCHED else "did not take:"
                log(f"sohot-{lane}: {row['old_spec']} {verb} {spec} ({reason or got['how']})")
        conn.commit()
    finally:
        conn.close()
    return rows


def _gone_record(row, moved, old, outcome, reason, log) -> list[dict]:
    got = {"how": "reconciled", "in_flight": None, "switched_at": time.time()}
    return _record(moved, old, got, row["requested_at"] or got["switched_at"], outcome, reason, log)


def settle(conn, row: dict, why: str, serving=None, log=None) -> str:
    """End a switch whose process died or raised: finished if the gateway serves its target, else the old served config is put back."""
    import json
    from pathlib import Path

    import yaml

    from harness import gateway, gateway_respawn
    from harness import gateway_switch_state as st
    stop_drain()
    frm, rid = row["state"], row["id"]
    if frm == st.REQUESTED:
        settled = gateway_respawn.late(conn, rid) if why == st.DIED else None
        st.move(conn, rid, frm, st.FAILED, why if settled is None else st.LATE,
                detail=f"the switch process {why} before it wrote anything"
                       + ("" if settled is None else f", a late claim after switch {settled} settled it unclaimed"))
        return st.FAILED
    path = Path(row["config"])
    current = path.read_text(encoding="utf-8") if path.exists() else None
    before, target = row["before"], row["target"]
    moved = {lane: tuple(v) for lane, v in json.loads(row["moved"] or "{}").items()}
    old = _aliases(yaml.safe_load(before) or {}) if before else {}
    if frm == st.RESTARTING and current == target and moved:
        if serving is None:
            from harness.completion import DEFAULT_GATEWAY

            def serving(want):
                return not_serving(DEFAULT_GATEWAY, want)
        if not serving({gateway.LANE_ALIAS.format(lane): model for lane, (_, model) in moved.items()}):
            if st.move(conn, rid, frm, st.SERVING, st.FINISHED,
                       detail=f"the switch process {why}; the gateway already serves its target"):
                _gone_record(row, moved, old, SWITCHED, "", log)
            return st.SERVING
    if frm == st.RESTARTING and current not in (before, target):
        st.move(conn, rid, frm, st.FAILED, st.SUPERSEDED,
                detail=f"the switch process {why}; another writer changed the served config since")
        return st.FAILED
    if before is not None and current != before:
        path.write_text(before, encoding="utf-8")
    note = f"the switch process {why} while {frm}; the old served config is back for the next switch"
    if st.move(conn, rid, frm, st.FAILED, why, detail=note) and moved:
        _gone_record(row, moved, old, FAILED, note, log)
    if log:
        log(f"switch {rid}: {note}")
    return st.FAILED


def reconcile(conn, alive=None, serving=None, log=None) -> dict | None:
    """The in-flight switch, settled first if its process is gone; None when no switch holds the slot."""
    from harness import gateway_switch_state as st
    row = st.live(conn)
    if row is None:
        return None
    if (alive or st.alive)(row) is False:
        settle(conn, row, st.DIED, serving, log)
        return st.get(conn, row["id"])
    return row


def respawn(requested_at: float) -> None:
    """Start a dead switch's adoption again, marked until it claims its row; only from the live home, since a detached switch restarts this machine's gateway."""
    from harness import gateway_respawn, monitor, paths
    from harness import memory_store as ms
    if not monitor.live_home():
        raise OSError(f"{paths.home()} is not the live home, so it starts no gateway switch")
    conn = ms.connect()
    try:
        after = gateway_respawn.newest(conn)
    finally:
        conn.close()
    spawned_at = time.time()
    gateway_respawn.mark(requested_at, after, spawned_at)
    try:
        proc = spawn(requested_at=requested_at)
    except BaseException:
        gateway_respawn.clear()
        raise
    if getattr(proc, "pid", None):
        gateway_respawn.mark(requested_at, after, spawned_at, proc.pid)
    else:
        gateway_respawn.clear()


def _alert(message: str) -> None:
    from harness import gateway_switch_state as st
    from harness import monitor
    monitor.alert("service", {"MONIT_SERVICE": "gateway-switch", "MONIT_EVENT": st.GAVE_UP,
                              "MONIT_DESCRIPTION": message})


def _gave_up(row: dict, deaths: int) -> str:
    from harness import gateway_switch_state as st
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["requested_at"])) if row["requested_at"] else "?"
    return (f"the gateway alias switch for the adoption requested at {when} died {deaths} times (last: switch "
            f"{row['id']}, while {row['state']}); the worker started it again {deaths - 1} time(s) and stops now. "
            f"The gateway serves the old aliases until the next adoption, or until `python -m harness.gateway_switch` "
            f"is run by hand from the deploy checkout"
            + ("; its process was still running, and a claim it makes later is refused"
               if row.get("reason") == st.UNCLAIMED else ""))


def repair(alive=None, serving=None, start=None, alert=None, config=None, log=None, now=None,
           same=None) -> dict | None:
    """The worker's pass: settle a switch whose process is gone, or a respawn that never claimed its row, and start it again, RESPAWNS times per adoption, then alert; None when there is nothing to settle here. #1899, #1904."""
    from harness import cuts, gateway_respawn, paths
    from harness import gateway_switch_state as st
    from harness import memory_store as ms
    if paths.role() != paths.SCHEDULER:
        return None
    conn = ms.connect()
    try:
        row = st.live(conn)
        if row is None:
            after = gateway_respawn.unclaimed(conn, now=now, same=same, log=log)
            if after is None:
                return None
            row = {**after, "state": "starting"}
        elif (alive or st.alive)(row) is not False:
            return None
        else:
            settle(conn, row, st.DIED, serving, log)
            after = st.get(conn, row["id"])
        deaths = st.deaths(conn, row["requested_at"]) if row["requested_at"] is not None else RESPAWNS + 1
    finally:
        conn.close()
    out = {"switch": row["id"], "state": after["state"], "reason": after["reason"], "respawned": False, "alerted": ""}
    if after["state"] != st.FAILED or after["reason"] not in (st.DIED, st.UNCLAIMED) or not pending(config):
        return out
    if deaths > RESPAWNS:
        out["alerted"] = _gave_up(row, deaths)
        cuts.cut("harness/gateway_switch.py:RESPAWNS", f"switch {row['id']} not started again", kept=0, dropped=1)
        (alert or _alert)(out["alerted"])
        return out
    try:
        (start or respawn)(row["requested_at"])
    except OSError as exc:
        out["alerted"] = (f"the gateway alias switch {row['id']} died and could not be started again ({exc}); the "
                          f"gateway serves the old aliases until the next adoption")
        (alert or _alert)(out["alerted"])
        return out
    out["respawned"] = True
    return out


def turn() -> dict | None:
    """repair, from the worker's turn: logged rather than raised, so a repair error never stops the worker. #1899."""
    stamp = time.strftime("%H:%M:%S")
    try:
        got = repair()
    except Exception as exc:  # noqa: BLE001 - on any store
        print(f"{stamp} gateway switch repair failed: {exc}", flush=True)
        return None
    if got is not None:
        print(f"{stamp} gateway switch {got['switch']} settled {got['state']} ({got['reason']})"
              + ("; started again" if got["respawned"] else "")
              + (f"; alerted: {got['alerted']}" if got["alerted"] else ""), flush=True)
    return got


def view(conn, config=None, alive=None) -> dict:
    """How the gateway switch stands, read-only: the live switch's state or orphaned; with none, serving or stale against the adoptions."""
    from harness import adopt, gateway
    from harness import gateway_switch_state as st
    row = st.live(conn)
    if row is not None:
        gone = (alive or st.alive)(row) is False
        return {"state": st.ORPHANED if gone else row["state"], "switch": row["id"],
                "why": (f"switch {row['id']} is {row['state']} but its process is gone" if gone
                        else f"switch {row['id']} is {row['state']} ({row['reason']})")}
    path = gateway.served_path(config)
    if not path.exists():
        return {"state": st.UNWRITTEN, "switch": None, "why": f"no served config at {path}"}
    have = _aliases(gateway.load(path))
    want = _aliases(gateway.served(config, adopt.lane_defaults(conn)))
    off = sorted(lane for lane in set(have) | set(want) if have.get(lane) != want.get(lane))
    if off:
        return {"state": st.STALE, "switch": None,
                "why": f"the served config does not name what {', '.join(off)} adopted, and no switch is in flight"}
    return {"state": st.SERVING, "switch": None, "why": ""}


def waiter(requested_at: float) -> tuple[list[str], dict]:
    """The detached switch's argv and env, without the caller's hold on the machine lock."""
    from harness import exclusive
    env = {k: v for k, v in os.environ.items() if k != exclusive.HELD_ENV}
    return ([sys.executable, "-m", "harness.gateway_switch",
             "--requested-at", repr(float(requested_at))], env)


def spawn(requested_at: float | None = None, popen=None, alive=None):
    """Start the switch detached, after settling a dead one, and return its process; none when a live switch holds the slot, as it re-reads on settling."""
    import subprocess
    from harness import gateway, paths
    from harness import gateway_switch_state as st
    from harness import memory_store as ms
    from harness import monitor
    if not monitor.live_home():
        print(f"gateway switch not started: {monitor.off_live('restarting the gateway')}", file=sys.stderr)
        return None
    if not can_restart():
        # Recorded as a failed switch, so report and judge do not read the lane as served. #703.
        switch(requested_at=requested_at)
        return None
    conn = ms.connect()
    try:
        row = reconcile(conn, alive=alive)
    finally:
        conn.close()
    if row is not None and row["state"] in st.LIVE:
        return None
    argv, env = waiter(time.time() if requested_at is None else requested_at)
    log = open(paths.logs() / "gateway-switch.log", "a", encoding="utf-8")
    try:
        return (popen or subprocess.Popen)(argv, env=env, cwd=str(gateway.REPO),
                                    stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        log.close()


def deadline_s(max_wait_s: float, drain_s: float) -> float:
    """The longest a switch may hold the machine: every attempt's wait, drain and serve check, and the backoffs between. #775."""
    return (RETRIES * (max_wait_s + drain_s + SERVE_WAIT_S)
            + sum(BACKOFF_S * 2 ** (attempt - 1) for attempt in range(1, RETRIES)))


def main(argv=None) -> int:
    from harness import exclusive
    from harness import gateway_switch_state as st
    p = argparse.ArgumentParser(prog="python -m harness.gateway_switch")
    p.add_argument("--requested-at", type=float, default=None)
    p.add_argument("--idle-s", type=float, default=IDLE_S)
    p.add_argument("--max-wait-s", type=float, default=MAX_WAIT_S)
    a = p.parse_args(argv)

    def log(msg):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} gateway-switch: {msg}",
              file=sys.stderr, flush=True)

    requested_at = a.requested_at
    try:
        # A switch that served re-reads the adoptions: one made while it held the slot lost its own claim.
        while run(requested_at, a.idle_s, a.max_wait_s, log) == st.SERVING and pending():
            requested_at = None
    except exclusive.StoreDown as exc:
        log(str(exc))
        return 1
    return 0


def pending(config=None) -> bool:
    """Whether the served config's lane aliases differ from what the adoptions say now."""
    from harness import gateway
    return _aliases(gateway.served(config)) != _aliases(gateway.load(gateway.served_path(config)))


def _advance(rid):
    from harness import gateway_switch_state as st
    from harness import memory_store as ms

    def advance(frm, to, reason, **cols):
        conn = ms.connect()
        try:
            if not st.move(conn, rid, frm, to, reason, **cols):
                raise st.Lost(f"switch {rid} is no longer {frm}: another writer settled it")
        finally:
            conn.close()
    return advance


def run(requested_at, idle_s, max_wait_s, log, held=None, alive=None, ident=None, switch_fn=None,
        base=None) -> str:
    """Claim the one in-flight slot, switch under the machine lock, and return the state the switch ended in ('' when it lost the claim)."""
    from harness import exclusive, gateway, gateway_respawn
    from harness import gateway_switch_state as st
    from harness import memory_store as ms
    from harness.completion import DEFAULT_GATEWAY

    def serving(want):
        return not_serving(base or DEFAULT_GATEWAY, want)
    conn = ms.connect()
    try:
        reconcile(conn, alive=alive, serving=serving, log=log)
        try:
            rid = st.claim(conn, requested_at=time.time() if requested_at is None else requested_at,
                           config=str(gateway.served_path()), **(ident or st.me()))
        except st.Lost as exc:
            log(f"{exc}; it re-reads the adoptions once it settles")
            return ""
        settled = gateway_respawn.late(conn, rid)
        if settled is not None:
            why = (f"switch {settled} already settled this respawn unclaimed (gateway_respawn_claim), so its late "
                   f"claim is refused")
            st.move(conn, rid, st.REQUESTED, st.FAILED, st.LATE, detail=why)
            log(f"switch {rid}: {why}")
            return st.FAILED
    finally:
        conn.close()
    try:
        # After any run that loads models, so a restart never lands mid-measurement. #319.
        with (held or exclusive.held)("external", announce=log, deadline_s=deadline_s(max_wait_s, DRAIN_S)):
            (switch_fn or switch)(base=base, requested_at=requested_at, idle_s=idle_s, max_wait_s=max_wait_s,
                                  log=log, advance=_advance(rid))
    except st.Lost as exc:
        log(str(exc))
        return ""
    except BaseException as exc:
        conn = ms.connect()
        try:
            row = st.get(conn, rid)
            if row and row["state"] in st.LIVE:
                settle(conn, row, st.RAISED, serving, log)
        except Exception as inner:  # noqa: BLE001
            log(f"switch {rid} raised {type(exc).__name__} and could not be settled: {inner}")
        finally:
            conn.close()
        raise
    conn = ms.connect()
    try:
        return st.get(conn, rid)["state"]
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

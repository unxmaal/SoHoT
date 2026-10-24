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


def headers() -> dict:
    """The gateway key for a management call, from the one key source (#482)."""
    from harness import gateway_key
    return gateway_key.headers()


def in_flight(base: str) -> int | None:
    """Requests in flight on the gateway besides this probe; None when it will not say."""
    import httpx
    try:
        r = httpx.get(f"{base.rstrip('/')}/health/backlog", headers=headers(),
                      timeout=5.0)
    except httpx.ConnectError:
        return 0
    except httpx.HTTPError as exc:
        if cuts.timed_out(exc):
            cuts.cut("harness/gateway_switch.py:in_flight->httpx.get(timeout)", "/health/backlog gave no answer in time",
                     kept=0, dropped=1)
        return None
    if r.status_code != 200:
        return None
    try:
        got = int(r.json()["in_flight_requests"])
    except (ValueError, KeyError, TypeError):
        return None
    return max(got - 1, 0)


def _drain_path():
    from harness import paths
    return paths.home() / DRAIN_FILE


def start_drain(until: float | None = None) -> None:
    """Ask the gateway to refuse new requests until `until` (epoch seconds), so a dead switch cannot wedge it."""
    until = time.time() + DRAIN_S + SERVE_WAIT_S if until is None else until
    _drain_path().write_text(repr(float(until)), encoding="utf-8")


def stop_drain() -> None:
    _drain_path().unlink(missing_ok=True)


def draining(now: float | None = None) -> bool:
    """Whether the gateway should refuse a new request because a switch is draining it."""
    try:
        until = float(_drain_path().read_text(encoding="utf-8"))
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
    return RESTARTERS[sys.platform]()


def not_serving(base: str, want: dict) -> str:
    """'' when the gateway serves every alias in `want` ({alias: model}) as given, else why not."""
    import httpx
    try:
        r = httpx.get(f"{base.rstrip('/')}/model/info", headers=headers(), timeout=5.0)
    except httpx.HTTPError as exc:
        if cuts.timed_out(exc):
            cuts.cut("harness/gateway_switch.py:not_serving->httpx.get(timeout)", "/model/info gave no answer in time",
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
           log=None, config=None, drain_s: float = DRAIN_S) -> list[dict]:
    """Regenerate the served config and restart once quiet, if any lane alias moved."""
    from harness import adopt, gateway
    from harness.completion import DEFAULT_GATEWAY
    base = base or DEFAULT_GATEWAY
    requested_at = clock() if requested_at is None else requested_at
    path = gateway.served_path(config)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    old = _aliases(gateway.load(path))
    if _aliases(gateway.served(config)) == old:
        return []
    if restart is restart_service and not can_restart():
        defaults, new = adopt.lane_defaults(), _aliases(gateway.served(config))
        moved = {lane: (defaults.get(lane, ""), new[lane].get("model"))
                 for lane in new if new[lane] != old.get(lane)}
        _record(moved, old, {"how": "none", "in_flight": None, "switched_at": clock()},
                requested_at, FAILED, f"no restart method on {sys.platform}", log)
        return []
    moved = {}
    for attempt in range(RETRIES):
        if attempt:
            sleep(BACKOFF_S * 2 ** (attempt - 1))
        restarted = {}

        def regenerate_and_restart():
            defaults = adopt.lane_defaults()
            gateway.write_served(config, defaults)
            new = _aliases(gateway.load(path))
            moved.clear()
            moved.update({lane: (defaults.get(lane, ""), new[lane].get("model"))
                          for lane in new if new[lane] != old.get(lane)})
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
            return _record(moved, old, got, requested_at, SWITCHED, "", log)
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


def waiter(requested_at: float) -> tuple[list[str], dict]:
    """The detached switch's argv and env, without the caller's hold on the machine lock."""
    from harness import exclusive
    env = {k: v for k, v in os.environ.items() if k != exclusive.HELD_ENV}
    return ([sys.executable, "-m", "harness.gateway_switch",
             "--requested-at", repr(float(requested_at))], env)


def spawn(requested_at: float | None = None, popen=None) -> None:
    """Start the switch detached: it may wait hours for a run to free the machine lock."""
    import subprocess
    from harness import gateway, paths
    if not can_restart():
        # Recorded as a failed switch, so report and judge do not read the lane as served. #703.
        switch(requested_at=requested_at)
        return
    argv, env = waiter(time.time() if requested_at is None else requested_at)
    log = open(paths.logs() / "gateway-switch.log", "a", encoding="utf-8")
    try:
        (popen or subprocess.Popen)(argv, env=env, cwd=str(gateway.REPO),
                                    stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        log.close()


def main(argv=None) -> int:
    from harness import exclusive
    p = argparse.ArgumentParser(prog="python -m harness.gateway_switch")
    p.add_argument("--requested-at", type=float, default=None)
    p.add_argument("--idle-s", type=float, default=IDLE_S)
    p.add_argument("--max-wait-s", type=float, default=MAX_WAIT_S)
    a = p.parse_args(argv)

    def log(msg):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} gateway-switch: {msg}",
              file=sys.stderr, flush=True)

    # After any run that loads models, so a restart never lands mid-measurement. #319.
    with exclusive.held("external", announce=log):
        switch(requested_at=a.requested_at, idle_s=a.idle_s,
               max_wait_s=a.max_wait_s, log=log)
    return 0


if __name__ == "__main__":
    sys.exit(main())

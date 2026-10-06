"""Re-point the sohot-<lane> aliases after an adoption without cutting off a request. #483.

LiteLLM 1.100.0's /model/new, /model/update and /model/delete refuse without a
Postgres database (prisma_client) and STORE_MODEL_IN_DB, so the gateway cannot
take a new alias live. The switch is a restart, deferred until the gateway has
had nothing in flight for `idle_s`, read from its own /health/backlog counter
(InFlightRequestsMiddleware, which counts every HTTP request including a stream
until its last byte, and the probe itself). After `max_wait_s` it restarts anyway
and says so. Each switch is a gateway_switches row.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

KEY_ENV = "LITELLM_MASTER_KEY"
IDLE_S = 60.0
MAX_WAIT_S = 20 * 60.0
POLL_S = 2.0


def headers() -> dict:
    """The gateway key for a management call; the one place it is sent from."""
    key = os.environ.get(KEY_ENV, "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def in_flight(base: str) -> int | None:
    """Requests in flight on the gateway besides this probe; None when it will not say."""
    import httpx
    try:
        r = httpx.get(f"{base.rstrip('/')}/health/backlog", headers=headers(),
                      timeout=5.0)
    except httpx.ConnectError:
        return 0
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        got = int(r.json()["in_flight_requests"])
    except (ValueError, KeyError, TypeError):
        return None
    return max(got - 1, 0)


def wait_then_restart(base: str, restart, idle_s: float = IDLE_S,
                      max_wait_s: float = MAX_WAIT_S, poll_s: float = POLL_S,
                      clock=time.time, sleep=time.sleep, log=None) -> dict:
    """Restart once nothing has been in flight for idle_s, or at max_wait_s regardless."""
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
            if log:
                log(f"gateway not quiet after {max_wait_s:.0f}s "
                    f"(in flight: {'unknown' if busy is None else busy}); restarting anyway")
            break
        sleep(poll_s)
    restart()
    return {"how": how, "in_flight": busy, "switched_at": clock()}


def _aliases(cfg: dict) -> dict:
    """{lane: litellm_params} for each sohot-<lane> alias in a config."""
    from harness import gateway
    names = {gateway.LANE_ALIAS.format(lane): lane for lane in gateway.TEXT_LANES}
    return {names[e.get("model_name")]: dict(e.get("litellm_params") or {})
            for e in cfg.get("model_list") or [] if e.get("model_name") in names}


def switches(conn) -> list[dict]:
    """Every recorded alias switch, oldest first."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM gateway_switches ORDER BY id").fetchall()]


def _old_spec(conn, lane: str, params: dict) -> str:
    """What the alias served: the last switch's spec, else the upstream model it named."""
    row = conn.execute("SELECT new_spec FROM gateway_switches WHERE lane = ? "
                       "ORDER BY id DESC LIMIT 1", (lane,)).fetchone()
    return row["new_spec"] if row else str(params.get("model") or "")


def restart_service() -> None:
    """Restart the gateway's launchd service; the caller already holds the machine lock."""
    import subprocess
    from harness import gateway
    if sys.platform == "darwin":
        subprocess.call([str(gateway.REPO / "scripts" / "launchd.sh"), "restart", "gateway"])


def switch(base: str | None = None, restart=restart_service, requested_at=None,
           idle_s: float = IDLE_S, max_wait_s: float = MAX_WAIT_S,
           poll_s: float = POLL_S, clock=time.time, sleep=time.sleep,
           log=None, config=None) -> list[dict]:
    """Regenerate the served config and restart once quiet, if any lane alias moved."""
    from harness import adopt, gateway
    from harness import memory_store as ms
    from harness.completion import DEFAULT_GATEWAY
    base = base or DEFAULT_GATEWAY
    requested_at = clock() if requested_at is None else requested_at
    old = _aliases(gateway.load(gateway.served_path(config)))
    if _aliases(gateway.served(config)) == old:
        return []
    moved = {}

    def regenerate_and_restart():
        defaults = adopt.lane_defaults()
        gateway.write_served(config, defaults)
        new = _aliases(gateway.load(gateway.served_path(config)))
        moved.update({lane: defaults.get(lane, "") for lane in new
                      if new[lane] != old.get(lane)})
        restart()

    got = wait_then_restart(base, regenerate_and_restart, idle_s, max_wait_s,
                            poll_s, clock, sleep, log)
    rows = []
    conn = ms.connect()
    try:
        for lane, spec in moved.items():
            row = {"lane": lane, "old_spec": _old_spec(conn, lane, old.get(lane, {})),
                   "new_spec": spec, "how": got["how"], "requested_at": requested_at,
                   "switched_at": got["switched_at"], "in_flight": got["in_flight"]}
            conn.execute("INSERT INTO gateway_switches (lane, old_spec, new_spec, how, "
                         "requested_at, switched_at, in_flight) VALUES "
                         "(:lane, :old_spec, :new_spec, :how, :requested_at, "
                         ":switched_at, :in_flight)", row)
            rows.append(row)
            if log:
                log(f"sohot-{lane}: {row['old_spec']} -> {spec} ({got['how']})")
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
    if sys.platform != "darwin":
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

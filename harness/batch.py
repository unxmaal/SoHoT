"""One batch at a time on a serving deployment, held as a store lease by the gateway in front of it. #769."""
from __future__ import annotations

import ipaddress
import os
import secrets
import socket
import time

#: The batch this process and its children run under; set by exclusive.held.
ENV = "SOHOT_BATCH"
#: The request header that names a request's batch to the serving gateway.
HEADER = "x-sohot-batch"
#: What a gateway answers with its 503 while another batch holds the deployment; reasons reads it as refused_by_gateway.
BUSY = "the serving machine is busy with another batch"
PREFIX = "batch:"
#: How long a batch lease outlives its holder's last request or renewal.
TTL_S = 120.0
#: How long one request waits out a busy deployment before it gives up.
BUSY_WAIT_S = 2 * 3600.0
#: How often a request refused as busy asks again.
BUSY_POLL_S = 5.0


def current(environ=None) -> str:
    return ((os.environ if environ is None else environ).get(ENV) or "").strip()


def new_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(3)}"


def name(deployment: str) -> str:
    return PREFIX + (deployment or "")


def here() -> str:
    """This machine's identity as its gateway keys a local deployment: served_model.this_machine."""
    try:
        from evals import environment
        return environment.identity()["fingerprint"]
    except Exception:  # noqa: BLE001
        return ""


def from_gateway(batch: str) -> dict:
    """The holder a gateway records for a batch it saw only as a header."""
    return {"batch": batch, "machine_id": PREFIX + batch, "pid": None}


def claim(conn, deployment: str, batch: str, who: dict | None = None, ttl_s: float | None = None,
          now: float | None = None, alive=None) -> dict:
    """{} once `batch` holds `deployment` (taken or renewed), else the holder that kept it."""
    from harness import lease
    ttl_s = TTL_S if ttl_s is None else ttl_s
    who = {**(who or from_gateway(batch)), "batch": batch}
    got = lease.take(conn, name(deployment), who, ttl_s, now=now, alive=alive)
    if not got or got.get("batch") != batch:
        return got
    kept = {k: v for k, v in got.items() if k not in ("since", "expires")}
    if lease.renew(conn, name(deployment), kept, ttl_s, now=now):
        return {}
    return lease.holder(conn, name(deployment))


def let_go(conn, deployment: str, batch: str) -> bool:
    """Drop the lease on `deployment` if `batch` holds it, whoever recorded it last."""
    from harness import lease
    got = lease.holder(conn, name(deployment))
    if got.get("batch") != batch:
        conn.commit()
        return False
    return lease.release(conn, name(deployment), got)


def describe(holder: dict) -> str:
    return f"batch {holder.get('batch') or 'unknown'}"


def _local_address(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
        except (OSError, ValueError):
            return False
    if ip.is_loopback or ip.is_unspecified:
        return True
    family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    # Only an address one of this host's interfaces holds can be bound.
    with socket.socket(family, socket.SOCK_DGRAM) as s:
        try:
            s.bind((str(ip), 0))
            return True
        except OSError:
            return False


def is_here(url: str) -> bool:
    """Whether a gateway URL is served by this machine."""
    from urllib.parse import urlsplit

    from harness.machine import LOOPBACK
    host = urlsplit(url or "").hostname or ""
    return not host or host in LOOPBACK or _local_address(host)

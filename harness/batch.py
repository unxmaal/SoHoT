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
    """This machine's identity as its gateway keys a local deployment, from the process's cached probe."""
    try:
        from harness import memory_store as ms
        return ms.this_machine()["fingerprint"]
    except Exception:  # noqa: BLE001
        return ""


def origin(batch: str) -> int | None:
    """The pid a batch id of this host names (new_id's host-pid-token), else None. #1231."""
    host, _, rest = (batch or "").rpartition("-")[0].rpartition("-")
    if not host or host != socket.gethostname() or not rest.isdigit():
        return None
    return int(rest)


def from_gateway(batch: str, local: bool = False) -> dict:
    """The holder a gateway records for a batch it saw only as a header; a local one names its pid. #1231."""
    pid = origin(batch) if local else None
    return {"batch": batch, "machine_id": PREFIX + batch, "pid": None,
            **({"local_pid": pid} if pid else {})}


def ended(holder: dict, alive) -> bool:
    """Whether a gateway-recorded local batch's process has exited. #1231."""
    pid = holder.get("local_pid")
    return bool(pid) and not alive(int(pid))


def claim(conn, deployment: str, batch: str, who: dict | None = None, ttl_s: float | None = None,
          now: float | None = None, alive=None) -> dict:
    """{} once `batch` holds `deployment` (taken or renewed), else the holder that kept it."""
    from harness import lease
    ttl_s = TTL_S if ttl_s is None else ttl_s
    who = {**(who or from_gateway(batch)), "batch": batch}
    stale = (lambda holder: ended(holder, alive)) if alive else None
    got = lease.take(conn, name(deployment), who, ttl_s, now=now, alive=alive, stale=stale)
    if not got or got.get("batch") != batch:
        return got
    return {} if keep(conn, deployment, batch, ttl_s, now=now, holder=got) else lease.holder(
        conn, name(deployment))


def keep(conn, deployment: str, batch: str, ttl_s: float | None = None, now: float | None = None,
         holder: dict | None = None) -> bool:
    """Renew `deployment` for `batch` only while it still holds it; never takes a free one. #1231."""
    from harness import lease
    got = lease.holder(conn, name(deployment)) if holder is None else holder
    if got.get("batch") != batch:
        conn.commit()
        return False
    kept = {k: v for k, v in got.items() if k not in ("since", "expires")}
    return lease.renew(conn, name(deployment), kept, TTL_S if ttl_s is None else ttl_s, now=now)


def let_go_all(conn, batch: str) -> int:
    """Drop every deployment's lease `batch` holds, the gateway's node and upstream keys too. #1231."""
    from harness import lease
    rows = conn.execute("SELECT key FROM meta WHERE key LIKE ?", (lease.PREFIX + PREFIX + "%",)).fetchall()
    conn.commit()
    return sum(let_go(conn, row["key"][len(lease.PREFIX + PREFIX):], batch) for row in rows)


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

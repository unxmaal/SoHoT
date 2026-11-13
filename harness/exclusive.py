"""One large working set at a time, across processes. Issue #137.

An in-process queue (the MCP server's, retired in #353) guarded only its own
caller and left `lh` free to collide with itself. Every `lh` invocation is a
new process, so serialising them needs the operating system.

MEASURED, NOT ASSUMED. 2026-09-12 on the M2 Pro: `lh image` started while
`lh video` held the GPU. Both went straight at it, Metal returned
kIOGPUCommandBufferCallbackErrorTimeout, swap reached 8.0 GB of 9.2, and both
jobs were killed with no artifact. That is ERROR #33 and assumption C4.

The lock is this machine's gpu lease in the store, plus the generation.lock flock other projects' lockf shares. #1619.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

from harness.atomic_file import replace
from harness import stale_temp
from harness import paths

#: What holds the lock, for a waiter to report. Best-effort and advisory: the
#: LOCK is the truth, this is only how a waiter says what it is waiting behind.
HOLDER = "generation.holder"
LOCK = "generation.lock"
#: Written at the first gpu refusal while the store is down, removed at the next store connect. #1648.
REFUSED = "gpu.refused"

#: Which lanes need the whole machine, declared once rather than tested for at
#: each call site.
#:
#: THE ABSENT ONES ARE THE DELIBERATE PART. svg, web, code and extract go to
#: mlx_lm.server, which already serialises through a single queue of its own;
#: say and hear go to a small resident audio service. Making `lh extract` --
#: one run of one prompt at 0.96s, M2 Pro, 2026-09-12, never repeated -- wait
#: behind a 40-minute video would be a downgrade wearing the clothes of
#: enforcement. The argument does not rest on that number: two orders of
#: magnitude is the claim, and a re-measurement would have to find seconds
#: rather than milliseconds to change it. The resource protected here is a
#: large LOCAL working set, not the machine.
EXCLUSIVE = {"image", "video"}
#: Batch runs that load models on any engine, and other projects through
#: scripts/with-gpu-lock. A lane prompt is not one of these. #314.
BATCH = {"eval", "ramp", "external", "chaos", "install"}
#: Kinds that run under the flock alone when the store is down: install, deploy and unit restarts are repairs. #1648, #1667.
REPAIR = {"install"}
#: Batch kinds that reach their models through the gateway, so they load the serving machine, not this one. #769.
GATEWAY_BATCH = {"eval"}
#: Batch kinds that load no model anywhere this machine serves: an eval whose every candidate is hosted. #1135.
CLOUD = {"cloud-eval"}
#: Cloud-only evals that run at once; their graders still use this machine's CPU and disk. #1135.
CLOUD_SLOTS = 2
#: Set while a cloud slot is held, so a child eval does not take a second one.
CLOUD_HELD_ENV = "LH_CLOUD_LOCK_HELD"
#: Batch kinds whose every model a node serves: they hold the node's gpu lease, never this machine's. #778, #1689.
NODE = {"node-eval"}
#: Set to the node's name while its lease is held, so a child does not take it again and an eval yields to its serving.
NODE_HELD_ENV = "LH_NODE_LOCK_HELD"
#: Set while held, so a child that also asks (a helper running `lh ...`)
#: does not deadlock against its own parent.
HELD_ENV = "LH_GPU_LOCK_HELD"
#: The id of the gpu lease HELD_ENV stands for, so a child re-checks it is still in force. #1732.
LEASE_ENV = "LH_GPU_LEASE_ID"

#: The gpu lease row is the one record of who holds this machine's GPU; the states it can be in. #1732.
FREE, RESERVED, LOADING, LAPSED, ABANDONED = "free", "reserved", "loading", "lapsed", "abandoned"
#: Each legal move of a gpu lease row, (from, to) -> the writers that may make it; _move refuses any other. #1732.
MOVES = {
    (FREE, RESERVED): {"workqueue"},
    (FREE, LOADING): {"take"},
    (RESERVED, RESERVED): {"workqueue"},
    (RESERVED, LOADING): {"own"},
    (LOADING, RESERVED): {"own"},
    (LOADING, LOADING): {"beat"},
    (RESERVED, FREE): {"workqueue"},
    (LOADING, FREE): {"release"},
    (LAPSED, FREE): {"release", "workqueue"},
    (ABANDONED, FREE): {"reap", "release", "workqueue"},
    (RESERVED, LAPSED): {"clock"},
    (LOADING, LAPSED): {"clock"},
    (RESERVED, ABANDONED): {"death"},
    (LOADING, ABANDONED): {"death"},
    (LAPSED, ABANDONED): {"death"},
}

#: How often a waiter re-reads the holder to refresh what it reports.
POLL_SECONDS = 0.5
#: Seconds held() waits for the GPU in all before it gives up with WaitExpired. #1763.
GPU_WAIT_S = 28800.0


def _venv_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _imports_psycopg(python: Path) -> bool:
    import subprocess
    return subprocess.run([str(python), "-I", "-c", "import psycopg"], capture_output=True).returncode == 0


def store_python(repo: Path, can_import=_imports_psycopg) -> str | None:
    """A venv interpreter that can open this home's Postgres store when this one cannot; None when this one can. #1586."""
    import importlib.util

    from harness import store
    if os.environ.get(HELD_ENV) == "1" or store.backend() != store.POSTGRES or importlib.util.find_spec("psycopg"):
        return None
    tried = [sys.executable]
    try:
        deploy = paths.deploy_checkout()
    except Exception:  # noqa: BLE001 - the repo's own venv is still a candidate
        deploy = None
    for root in (repo, deploy):
        python = _venv_python(Path(root)) if root else None
        if python is None or not python.exists() or str(python) in tried:
            continue
        tried.append(str(python))
        if can_import(python):
            return str(python)
    raise RuntimeError(f"the store is Postgres and no interpreter tried can import psycopg ({', '.join(tried)}); "
                       "uv sync --group cluster")


def _dir() -> Path:
    d = paths.home() / "queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock_path() -> Path:
    return _dir() / LOCK


def holder_path() -> Path:
    """The holder record, in the machine's home beside its generation.lock, whichever home this process writes. #1732."""
    return _on_machine(_dir) / HOLDER


def cloud_lock_path(slot: int) -> Path:
    return _dir() / f"cloud.{slot}.lock"


def cloud_holder_path(slot: int) -> Path:
    return _dir() / f"cloud.{slot}.holder"


def _read(path: Path) -> dict:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def holder() -> dict:
    """Who has it, or {}. Never raises: a waiter reporting nothing is fine,
    a waiter crashing because the holder exited mid-read is not."""
    return _read(holder_path())


def _on_machine(fn):
    """fn() with home() at the machine's home, where its generation.lock lives. #1703."""
    with paths.seated(paths.machine_home()):
        return fn()


def machine_holder() -> dict:
    """holder() of the machine's generation.lock, whichever home this process writes. #1703."""
    return _on_machine(holder)


def _taken(path: Path) -> bool:
    """Whether some process holds the lock at `path` now. Never waits."""
    try:
        fd = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return False
    try:
        if _take(fd):
            _release(fd)
            return False
        return True
    finally:
        os.close(fd)


def _conn():
    from harness import memory_store as ms
    return ms.connect()


class StoreDown(RuntimeError):
    """The store holding the gpu lease cannot be reached, so GPU work is refused. #1648."""


def refused_path() -> Path:
    return _dir() / REFUSED


def refusal() -> dict:
    """The first gpu refusal of the current store outage, {} when none stands. #1648."""
    return _read(refused_path()) if refused_path().exists() else {}


def _alert(kind: str, message: str) -> None:
    from harness import monitor
    with contextlib.suppress(Exception):
        monitor.alert(kind, {"MONIT_SERVICE": "gpu", "MONIT_DESCRIPTION": message})


class StoreSkewed(StoreDown):
    """The store answers but at a schema this code will not use: refused like an outage, logged, never alerted. #1793."""


def _chain(exc: BaseException | None):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _skewed(exc: BaseException) -> bool:
    from harness.memory_store.connection import LiveStoreRefused
    from harness.memory_store.migrations import NewerStore
    return any(isinstance(e, (LiveStoreRefused, NewerStore)) for e in _chain(exc))


def _cause(exc: BaseException) -> str:
    """The class of the failure under a refusal: a marker for one cause never hides an outage from another. #1793."""
    root = list(_chain(exc))[-1]
    return type(root).__qualname__


def owner() -> bool:
    """Whether this process speaks for its home's gpu refusals: in the live home only the deploy checkout does. #1793."""
    from harness import monitor
    return not monitor.live_home() or paths.runs_elsewhere() is None


def _mark(path: Path, record: dict, exclusive: bool) -> bool:
    """Write the refusal marker whole; exclusive, False when one already stands. #1793."""
    tmp = stale_temp.temp(path, "{name}.{pid}.{thread}")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    try:
        if not exclusive:
            replace(tmp, path)
            return True
        os.link(tmp, path)
        return True
    except FileExistsError:
        return False
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def refuse(who: str, exc: Exception) -> StoreDown:
    """The refusal to raise for `who`; the owner records and alerts the first of an outage once per cause. #1648, #1793."""
    reason = f"{who} refused: {exc}"
    if isinstance(exc, StoreSkewed):
        print(f"{time.strftime('%H:%M:%S')} {reason} (schema skew, not alerted)", file=sys.stderr, flush=True)
        return StoreSkewed(reason)
    if not owner():
        return StoreDown(reason)
    record = {"at": time.time(), "who": who, "pid": os.getpid(), "reason": reason,
              "writer": str(paths.REPO), "cause": _cause(exc)}
    try:
        if not _mark(refused_path(), record, exclusive=True):
            was = refusal()
            if was.get("writer") == record["writer"] and was.get("cause") == record["cause"]:
                return StoreDown(reason)
            _mark(refused_path(), record, exclusive=False)
    except OSError:
        return StoreDown(reason)
    _alert("gpu-refused", reason)
    return StoreDown(reason)


def _store():
    """A store connection; StoreDown naming why when none opens, StoreSkewed when it is at another schema. A connect ends a recorded refusal. #1648, #1793."""
    try:
        conn = _conn()
    except Exception as exc:  # noqa: BLE001 - any failure to open is the store being unreachable
        if _skewed(exc):
            raise StoreSkewed(f"the store answers at a schema this checkout ({paths.REPO}) will not use, "
                              f"so no gpu lease can be taken or checked: {exc}") from exc
        raise StoreDown(f"the store is unreachable, so no gpu lease can be taken or checked: {exc}") from exc
    if not refused_path().exists() or not owner():
        return conn
    try:
        os.unlink(refused_path())
    except OSError:
        return conn
    _alert("recovered", "the store is reachable again; gpu work is no longer refused")
    return conn


def _holder_alive(h: dict) -> bool:
    """Whether a gpu lease's holder lives: its process by pid, group and start time, or for a queued job's, the job's own process. #1619, #1772."""
    from harness import proc_identity
    from harness import workqueue as wq
    if h.get("pid"):
        same = proc_identity.same(h)
        if same or (same is None and wq.alive(int(h["pid"]))):
            return True
    return h.get("job_id") is not None and wq._pid_of(h["job_id"]) is not None


class IllegalMove(RuntimeError):
    """A gpu lease move MOVES does not allow from the row's state, refused before anything is written. #1732."""


class LeaseLost(RuntimeError):
    """The gpu lease a parent holds for this child (LEASE_ENV) is no longer in force. #1732."""


class WaitExpired(RuntimeError):
    """held() waited its whole bound for the GPU and gave up; alerted once. #1763."""


class _Wait:
    """One bound on held()'s whole wait, across the gpu lease, the flock and the batch lease. #1763."""

    def __init__(self, kind: str, seconds: float):
        self.kind, self.seconds, self.end = kind, float(seconds), time.monotonic() + float(seconds)

    def check(self, who: str) -> None:
        if time.monotonic() < self.end:
            return
        from harness import cuts
        reason = f"{self.kind} gave up waiting for the GPU after {self.seconds:.0f}s (gpu_wait), behind {who}"
        cuts.cut("gpu_wait", f"{self.kind}: waited for the GPU", value=self.seconds, kept=0, dropped=1)
        _alert("gpu-refused", reason)
        raise WaitExpired(reason)


def state_of(h: dict | None, now: float | None = None) -> str:
    """The state of one gpu lease row: a lapsed row whose holder still runs is LAPSED and still holds the GPU. #1732."""
    if h is None or h.get("released_at") is not None:
        return FREE
    if not _holder_alive(h):
        return ABANDONED
    if float(h["expires_at"]) <= (time.time() if now is None else now):
        return LAPSED
    return LOADING if h.get("state") else RESERVED


def _move(conn, h: dict | None, to: str, writer: str, kind: str = "", now: float | None = None) -> dict | None:
    """The one writer of gpu lease rows here: refuses a move MOVES does not list, else makes it compare-and-swap; the row after, None if it lost. #1732."""
    from harness import item_lease, resources
    now = time.time() if now is None else now
    was = state_of(h, now)
    if writer not in MOVES.get((was, to), ()):
        raise IllegalMove(f"gpu lease {h['id'] if h else '-'}: {writer} may not move it from {was} to {to}")
    if h is None:
        return item_lease.take(conn, resources.GPU, f"{kind} pid {os.getpid()}", state=kind, detail=kind, now=now,
                               fits=lambda held: not _lapsed(conn, now))
    if to == FREE:
        item_lease.release(conn, h["id"], now=now)
        return item_lease.row(conn, h["id"])
    state = kind if to == LOADING else ""
    if not item_lease.beat(conn, h["id"], now=now, expect=h.get("state") or "", state=state):
        return None
    return item_lease.row(conn, h["id"])


def _lapsed(conn, now: float) -> list[dict]:
    """Gpu lease rows past their TTL whose holder still runs: a taker waits behind them. #1732."""
    from harness import item_lease, resources
    return [h for h in item_lease.unreleased(conn, resources.GPU) if state_of(h, now) == LAPSED]


def _gpu_leases(conn) -> list[dict]:
    """The gpu lease rows that hold the GPU now: reserved, loading, or lapsed with the holder still running. #1732."""
    from harness import item_lease, resources
    if conn is None:
        return []
    now = time.time()
    rows = [(h, state_of(h, now)) for h in item_lease.unreleased(conn, resources.GPU)]
    rows = [(h, st) for h, st in rows if st in (RESERVED, LOADING, LAPSED)]
    live_jobs = {h["job_id"] for h, st in rows if h["job_id"] is not None and st != LAPSED}
    return [h for h, st in rows if not (st == LAPSED and h["job_id"] in live_jobs)]


@contextlib.contextmanager
def _machine():
    """A connection holding this machine's gpu leases, home() at its home: from a scratch eval home, the live one read-only. #1703."""
    there = paths.machine_home()
    if there == paths.home():
        conn = _store()
        try:
            yield conn
        finally:
            conn.close()
        return
    from harness import store
    with store.on_machine():
        try:
            conn = store.machine_ro()
        except Exception as exc:  # noqa: BLE001 - any failure to open is the machine's store being unreachable
            raise StoreDown(f"the machine's store in {there} is unreachable, so its gpu lease cannot be checked: {exc}") from exc
        try:
            yield conn
        except StoreDown:
            raise
        except Exception as exc:  # noqa: BLE001 - a lease ledger that cannot be read is one that cannot be checked
            raise StoreDown(f"the machine's gpu lease in {there} cannot be read: {exc}") from exc
        finally:
            if conn is not None:
                conn.close()


def _stop_hint(leases: list[dict]) -> str:
    """How the owner stops the queued jobs an install waits on, or "". #1675."""
    from harness import workqueue as wq
    jobs = [wq.label(h["job_id"]) for h in leases if h.get("job_id") is not None]
    if not jobs:
        return ""
    return (f" (to stop it for this deploy and resume it after: Ctrl-C, then LH_DEPLOY_DURING_SWEEP=1 "
            f"scripts/launchd.sh install; or end it: soh jobs cancel {' '.join(jobs)})")


def _reap(conn) -> None:
    """Release this machine's gpu leases whose holder is gone, lapsed ones too, so a killed holder frees the GPU at once. #1619, #1732."""
    from harness import item_lease, resources
    for h in item_lease.unreleased(conn, resources.GPU):
        if state_of(h) == ABANDONED:
            _move(conn, h, FREE, "reap")


def _own(conn) -> dict | None:
    """The gpu lease this process's queued job holds, or None. #1619."""
    from harness import item_lease, resources
    from harness import workqueue as wq
    key = wq._key(os.environ.get(wq.JOB_ENV, ""))
    got = item_lease.of_job(conn, key) if key is not None else None
    return got if got and got["resource"] == resources.GPU else None


def gpu_leases() -> int:
    """How many gpu leases live on this machine; StoreDown when the store will not open. #1619, #1648."""
    with _machine() as conn:
        leases = _gpu_leases(conn)
        return len(leases) + int(_outside(leases))


def _outside(leases: list[dict]) -> bool:
    """Whether another project's lockf holds generation.lock: taken while no lease here is a model-loading one. #1619."""
    return not any(h.get("state") for h in leases) and _taken(paths.home() / "queue" / LOCK)


def gpu_holder(as_is: bool = False) -> dict:
    """The holder record of the model-loading process on this machine's gpu lease, {} when none holds it; as_is from another checkout reads the live store unmigrated. #1619, #1719."""
    with (_as_is() if as_is and _elsewhere() else _machine()) as conn:
        return _holder(_gpu_leases(conn))


class Unread(RuntimeError):
    """The live store opened as it stands, but its gpu lease could not be read. #1719."""


def _elsewhere() -> bool:
    from harness import memory_store as ms
    return paths.live_from_elsewhere(ms.db_path())


@contextlib.contextmanager
def _as_is():
    """The live store as it stands, to read its gpu lease from a checkout that may not speak its schema: no DDL, no migration. #1719."""
    from harness import store
    try:
        conn = store.open_as_is()
    except Exception as exc:  # noqa: BLE001 - any failure to open is the store being unreachable
        raise StoreDown(f"the store is unreachable, so no gpu lease can be checked: {exc}") from exc
    try:
        yield conn
    except Exception as exc:  # noqa: BLE001 - a lease table this checkout cannot read is one it cannot check
        raise Unread(f"the live store's gpu lease could not be read as it stands: {exc}") from exc
    finally:
        conn.close()


def _holder(leases: list[dict]) -> dict:
    """Who holds the GPU, from the lease row; the holder record adds to it only when it names that lease. #1732."""
    from harness import workqueue as wq
    for h in leases:
        if not h.get("state"):
            continue
        rec = holder()
        lapsed = {"lapsed": True} if state_of(h) == LAPSED else {}
        if rec.get("lease") == h["id"] and rec.get("pid") and wq.alive(int(rec["pid"])):
            return {**rec, **lapsed}
        job = {"job": str(h["job_id"])} if h.get("job_id") is not None else {}
        return {"kind": h["state"], "pid": h["pid"], "since": h["taken_at"], **job, **lapsed}
    if _outside(leases):
        rec = holder()
        return rec if rec.get("pid") and wq.alive(int(rec["pid"])) else {"kind": "another project's lockf"}
    return {}


@contextlib.contextmanager
def _flock(announce, poll: float, wait: bool = True, bound: _Wait | None = None):
    """The flock on the machine's generation.lock, which other projects' lockf shares; yields (taken, waited)."""
    fd = os.open(_on_machine(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        waited, said = False, None
        while not (got := _take(fd)) and wait:
            waited = True
            record = machine_holder()
            if bound is not None:
                bound.check(describe(record))
            if announce and identity(record) != said:
                announce(f"waiting for {describe(record)} to finish")
                said = identity(record)
            time.sleep(poll)
        try:
            yield got, waited
        finally:
            if got:
                _release(fd)
    finally:
        os.close(fd)


def _lost(why: str) -> None:
    """Stop this holder: its lease is gone or about to lapse, and the GPU must not have two. #1732."""
    print(f"gpu lease lost ({why}); stopping this process so no second one takes the GPU under it",
          file=sys.stderr, flush=True)
    os.kill(os.getpid(), signal.SIGTERM)


def _beat(lease_id: int) -> bool:
    """One beat of a held lease; False when it is no longer this holder's to beat."""
    from harness import item_lease, resources
    conn = _conn()
    try:
        h = item_lease.row(conn, lease_id)
        if h is not None and h["resource"] != resources.GPU:
            return item_lease.beat(conn, lease_id, expect=h["state"])
        try:
            return _move(conn, h, LOADING, "beat", kind=(h or {}).get("state") or "") is not None
        except IllegalMove:
            return False
    finally:
        conn.close()


def _beating(lease_id: int, clock=time.monotonic):
    """Beat the lease every TTL_S/3; a holder whose beat says lost, or fails until TTL_S/3 is left, stops. #1732."""
    from harness import item_lease
    stop = threading.Event()

    def keep():
        ok_at, wait = clock(), item_lease.TTL_S / 3
        while not stop.wait(wait):
            try:
                if _beat(lease_id):
                    ok_at, wait = clock(), item_lease.TTL_S / 3
                    continue
                why = "its lease lapsed, was released or changed hands"
            except Exception as exc:  # noqa: BLE001 - a store that will not answer is retried until the deadline
                gone = clock() - ok_at
                why = f"no beat for {gone:.0f}s: {exc}"
                if gone < item_lease.TTL_S * 2 / 3:
                    wait = item_lease.TTL_S / 12
                    continue
            if not stop.is_set():
                _lost(why)
            return
    threading.Thread(target=keep, name="gpu-lease", daemon=True).start()
    return stop


@contextlib.contextmanager
def _gpu(kind: str, announce, poll: float, wait: bool = True, bound: _Wait | None = None):
    """The gpu lease, then the flock other projects' `lockf -k generation.lock` takes (DECISION #210); yields (taken, waited, lease id). #1619."""
    with _lease(kind, announce, poll, wait, bound) as (got, waited, lease):
        if not got:
            yield False, waited, None
            return
        with _flock(announce, poll, wait, bound) as (locked, lock_waited):
            yield locked, waited or lock_waited, lease


@contextlib.contextmanager
def _lease(kind: str, announce, poll: float, wait: bool = True, bound: _Wait | None = None):
    """This machine's gpu lease for `kind`: its job's own, else one taken, waiting; store down, only REPAIR runs. #1648."""
    from harness import item_lease, resources
    try:
        conn = _store()
    except StoreDown as exc:
        if kind not in REPAIR:
            raise refuse(kind, exc) from exc
        if announce:
            announce(f"no gpu lease ({exc}); {kind} holds the local lock only")
        yield True, False, None
        return
    try:
        own = _own(conn)
        try:
            own = own and _move(conn, own, LOADING, "own", kind=kind)
        except IllegalMove:
            own = None
        if own:
            stop = _beating(own["id"])
            try:
                yield True, False, own["id"]
            finally:
                stop.set()
                with contextlib.suppress(Exception):
                    _move(conn, item_lease.row(conn, own["id"]), RESERVED, "own")
            return
        waited, said = False, None
        while True:
            _reap(conn)
            got = _move(conn, None, LOADING, "take", kind=kind)
            if got is not None or not wait:
                break
            waited = True
            try:
                rec = gpu_holder()
            except StoreDown as exc:
                raise refuse(kind, exc) from exc
            leases = [] if rec else _gpu_leases(conn)
            who = describe(rec) if rec else "; ".join(item_lease.line(h) for h in leases) or "a gpu lease"
            if kind in REPAIR:
                who += _stop_hint(leases)
            if bound is not None:
                bound.check(who)
            if announce and who.split(" for ")[0] != said:
                announce(f"waiting for {who} to finish")
                said = who.split(" for ")[0]
            time.sleep(poll)
        if got is None:
            yield False, waited, None
            return
        stop = _beating(got["id"])
        try:
            yield True, waited, got["id"]
        finally:
            stop.set()
            with contextlib.suppress(Exception):
                _move(conn, item_lease.row(conn, got["id"]), FREE, "release")
    finally:
        conn.close()


@contextlib.contextmanager
def _node(node: str, kind: str, announce, poll: float, bound: _Wait | None = None):
    """The node's gpu lease, its job's own or one taken, waiting; this machine's lease and flock stay free. #778, #1689."""
    from harness import item_lease, resources
    from harness import workqueue as wq
    if not node:
        raise ValueError(f"{kind} names no node")
    if os.environ.get(NODE_HELD_ENV) == node:
        yield False
        return
    cls = resources.on(node)
    try:
        conn = _store()
    except StoreDown as exc:
        raise refuse(kind, exc) from exc
    try:
        key = wq._key(os.environ.get(wq.JOB_ENV, ""))
        own = item_lease.of_job(conn, key) if key is not None else None
        got = own if own and own["resource"] == cls and item_lease.beat(conn, own["id"], state=kind) else None
        waited, said = False, None
        while got is None:
            got = item_lease.take(conn, cls, f"{kind} pid {os.getpid()}", state=kind, detail=kind)
            if got is None:
                waited = True
                who = "; ".join(item_lease.line(h) for h in item_lease.live(conn, cls)) or f"a {cls} lease"
                if bound is not None:
                    bound.check(who)
                if announce and who.split(" for ")[0] != said:
                    announce(f"waiting for {who} to finish")
                    said = who.split(" for ")[0]
                time.sleep(poll)
        stop = None if got is own else _beating(got["id"])
        os.environ[NODE_HELD_ENV] = node
        try:
            yield waited
        finally:
            os.environ.pop(NODE_HELD_ENV, None)
            if stop is not None:
                stop.set()
                with contextlib.suppress(Exception):
                    item_lease.release(conn, got["id"])
    finally:
        conn.close()


@contextlib.contextmanager
def gpu_now(kind: str):
    """Hold this machine's gpu lease only if it is free now, or this process's job holds it; yields whether held. #1619."""
    if _inherited():
        yield True
        return
    with _gpu(kind, None, POLL_SECONDS, wait=False) as (got, _, _lease_id):
        yield got


def holders() -> list[dict]:
    """Each lock held on this machine now with its holder record: "gpu", then each "cloud" slot. #1135."""
    out = []
    got = gpu_holder()
    if got:
        out.append({**got, "lock": "gpu"})
    for slot in range(max(1, int(CLOUD_SLOTS))):
        if _taken(cloud_lock_path(slot)):
            out.append({**_read(cloud_holder_path(slot)), "lock": "cloud", "slot": slot})
    return out


def identity(record: dict) -> tuple:
    """WHAT is being waited on, with no clock in it.

    `describe` carries the elapsed seconds because a waiter wants to see them,
    and that made it useless for change detection: the string differs on every
    poll, so a caller comparing descriptions reprinted the same line once a
    second for the length of the wait. Measured 2026-09-12: 89 lines for one
    89-second wait behind an image.
    """
    return (record.get("kind"), record.get("pid"))


def describe(record: dict) -> str:
    kind = record.get("kind") or "something"
    pid = record.get("pid")
    since = record.get("since")
    for_ = f" for {time.time() - since:.0f}s" if isinstance(since, (int, float)) else ""
    return f"{kind}{for_}" + (f" (pid {pid})" if pid else "")


def _take(fd: int) -> bool:
    """Try to take the lock without blocking. True if taken."""
    if sys.platform == "win32":
        import msvcrt
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _release(fd: int) -> None:
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def alone(name: str, wait_s: float, poll_s: float = POLL_SECONDS):
    """Hold the lock file `name` across processes and threads, waiting up to wait_s; yields whether it was taken. #755."""
    fd = os.open(_dir() / name, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        end = time.monotonic() + wait_s
        got = _take(fd)
        while not got and time.monotonic() < end:
            time.sleep(poll_s)
            got = _take(fd)
        try:
            yield got
        finally:
            if got:
                _release(fd)
    finally:
        os.close(fd)


def remote(kind: str, environ=None) -> bool:
    """Whether `kind` loads another machine: a gateway batch whose gateway is not this machine. #769."""
    if kind not in GATEWAY_BATCH:
        return False
    from harness import batch, completion
    return not batch.is_here(completion.gateway_url(environ))


@contextlib.contextmanager
def _named():
    """This process and its children run under one batch id, which every gateway request names. #769."""
    from harness import batch
    if batch.current():
        yield batch.current()
        return
    os.environ[batch.ENV] = batch.new_id()
    try:
        yield os.environ[batch.ENV]
    finally:
        os.environ.pop(batch.ENV, None)


def _claim(mine: str, who: dict) -> dict:
    from harness import batch
    from harness import memory_store as ms
    from harness import workqueue as wq
    conn = ms.connect()
    try:
        return batch.claim(conn, batch.here(), mine, who=who, alive=wq.alive)
    finally:
        conn.close()


def _owner() -> dict:
    from harness import lease
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        return lease.owner(conn)
    finally:
        conn.close()


def _let_go(mine: str) -> None:
    from harness import batch
    from harness import memory_store as ms
    with contextlib.suppress(Exception):
        conn = ms.connect()
        try:
            batch.let_go_all(conn, mine)
        finally:
            conn.close()


@contextlib.contextmanager
def _renewing(mine: str, who: dict):
    """Keep this machine's batch lease while the block runs, then drop it."""
    import threading

    from harness import batch
    stop = threading.Event()

    def keep():
        while not stop.wait(batch.TTL_S / 3):
            with contextlib.suppress(Exception):
                _claim(mine, who)

    t = threading.Thread(target=keep, name="batch-lease", daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=5)
        _let_go(mine)


@contextlib.contextmanager
def _leased(announce, poll: float, bound: _Wait | None = None):
    """Hold this machine's serving lease, the one its gateway gives a remote batch, waiting while another has it. #769."""
    from harness import batch
    with _named() as mine:
        try:
            who = _owner()
        except Exception as exc:  # noqa: BLE001 - the flock still holds this machine
            if announce:
                announce(f"no batch lease (the store would not open: {exc}); holding the local lock only")
            yield False
            return
        waited, said = False, None
        while (got := _claim(mine, who)):
            waited = True
            if bound is not None:
                bound.check(batch.describe(got))
            if announce and got.get("batch") != said:
                announce(f"waiting for {batch.describe(got)} on this machine to finish")
                said = got.get("batch")
            time.sleep(poll)
        with _renewing(mine, who):
            yield waited


@contextlib.contextmanager
def held(kind: str, announce=None, poll: float = POLL_SECONDS, deadline_s: float | None = None, node: str = "",
         wait_s: float | None = None):
    """Hold the machine for `kind`, waiting if someone else has it, at most wait_s (GPU_WAIT_S), then WaitExpired.

    `announce` is called with a sentence the first time this has to wait, and
    again whenever what it is waiting behind changes. Waiting silently for
    forty minutes is indistinguishable from hanging.
    """
    bound = _Wait(kind, GPU_WAIT_S if wait_s is None else wait_s)
    if kind in CLOUD:
        with _cloud(kind, announce, poll, deadline_s, bound) as waited:
            yield waited
        return
    if kind in NODE:
        with _named(), _node(node, kind, announce, poll, bound) as waited:
            yield waited
        return
    if kind not in EXCLUSIVE | BATCH or _inherited():
        yield False
        return
    if remote(kind):
        # The serving gateway holds its machine for this batch; this machine is not loaded. #769.
        with _named():
            yield False
        return

    with _gpu(kind, announce, poll, bound=bound) as (_, waited, lease), _leased(announce, poll, bound) as lease_waited:
        _write_holder(kind, deadline_s, lease=lease)
        _hand_down(lease)
        try:
            yield waited or lease_waited
        finally:
            _hand_down(None, held=False)
            with contextlib.suppress(OSError):
                holder_path().unlink()


@contextlib.contextmanager
def _cloud(kind: str, announce, poll: float, deadline_s: float | None, bound: _Wait | None = None):
    """Hold one of CLOUD_SLOTS cloud slots, leaving the GPU lock and the batch lease free. #1135."""
    if os.environ.get(HELD_ENV) == "1" or os.environ.get(CLOUD_HELD_ENV) == "1":
        yield False
        return
    slots = max(1, int(CLOUD_SLOTS))
    fds = [os.open(cloud_lock_path(i), os.O_RDWR | os.O_CREAT, 0o644) for i in range(slots)]
    try:
        waited, said = False, None
        while (got := next((i for i, fd in enumerate(fds) if _take(fd)), None)) is None:
            waited = True
            records = [_read(cloud_holder_path(i)) for i in range(slots)]
            if bound is not None:
                bound.check(", ".join(describe(r) for r in records))
            who = tuple(identity(r) for r in records)
            if announce and who != said:
                announce(f"waiting for one of {slots} cloud evals to finish: "
                         + ", ".join(describe(r) for r in records))
                said = who
            time.sleep(poll)
        if waited:
            from harness import cuts
            cuts.cut("cloud_evals", f"{kind}: waited for a cloud slot")
        try:
            _write_holder(kind, deadline_s, path=cloud_holder_path(got))
            os.environ[CLOUD_HELD_ENV] = "1"
            try:
                yield waited
            finally:
                os.environ.pop(CLOUD_HELD_ENV, None)
                with contextlib.suppress(OSError):
                    cloud_holder_path(got).unlink()
        finally:
            _release(fds[got])
    finally:
        for fd in fds:
            os.close(fd)


@contextlib.contextmanager
def try_held(kind: str):
    """Hold the machine for `kind` only if it is free now; yields whether it is held."""
    if _inherited():
        yield True
        return
    with _gpu(kind, None, POLL_SECONDS, wait=False) as (got, _, lease):
        if not got:
            yield False
            return
        with _named() as mine:
            try:
                who = _owner()
                busy = _claim(mine, who)
            except Exception:  # noqa: BLE001 - the gpu lease still holds this machine
                who, busy = None, {}
            if busy:
                yield False
                return
            with _renewing(mine, who) if who else contextlib.nullcontext():
                _write_holder(kind, lease=lease)
                _hand_down(lease)
                try:
                    yield True
                finally:
                    _hand_down(None, held=False)
                    with contextlib.suppress(OSError):
                        holder_path().unlink()


def beat(now: float | None = None) -> None:
    """Stamp the GPU lock's holder record with a moment of progress, when this process or an ancestor holds it. #775."""
    if os.environ.get(HELD_ENV) != "1":
        return
    path = holder_path()
    record = _read(path)
    if not record:
        return
    record["beat"] = time.time() if now is None else float(now)
    tmp = stale_temp.temp(path, "{name}.{pid}.{thread}.tmp")
    with contextlib.suppress(OSError):
        tmp.write_text(json.dumps(record), encoding="utf-8")
        replace(tmp, path)


def _hand_down(lease: int | None, held: bool = True) -> None:
    """Tell children this process holds the GPU and under which lease (None: the flock alone), or no longer. #1732."""
    os.environ.pop(LEASE_ENV, None)
    if not held:
        os.environ.pop(HELD_ENV, None)
        return
    os.environ[HELD_ENV] = "1"
    if lease is not None:
        os.environ[LEASE_ENV] = str(lease)


def _inherited() -> bool:
    """Whether a parent holds the GPU for this process; LeaseLost when the lease it names is no longer in force. #1732."""
    if os.environ.get(HELD_ENV) != "1":
        return False
    lease = os.environ.get(LEASE_ENV, "").strip()
    if not lease.isdigit():
        return True
    from harness import item_lease
    try:
        with _machine() as conn:
            h = item_lease.row(conn, int(lease)) if conn is not None else None
    except StoreDown:
        return True
    if h is not None and state_of(h) in (RESERVED, LOADING):
        return True
    raise LeaseLost(f"the gpu lease {lease} this process was started under is {state_of(h)}, so it does not hold the GPU")


def _write_holder(kind: str, deadline_s: float | None = None, path: Path | None = None, lease: int | None = None) -> None:
    from harness import workqueue
    record = {"kind": kind, "pid": os.getpid(), "since": time.time()}
    if lease is not None:
        record["lease"] = int(lease)
    if hasattr(os, "getpgid"):
        record["pgid"] = os.getpgid(0)
    if os.environ.get(workqueue.JOB_ENV, "").strip():
        record["job"] = os.environ[workqueue.JOB_ENV].strip()
    if deadline_s:
        record["deadline_s"] = float(deadline_s)
    with contextlib.suppress(OSError):
        (path or holder_path()).write_text(json.dumps(record), encoding="utf-8")

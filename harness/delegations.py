"""Each delegated subtask and what became of its answer: reported, inferred from the caller's transcript, or expired. #829, #1158."""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from harness.atomic_file import replace

#: What a caller reports with `delegated`.
OUTCOMES = ("used", "edited", "discarded")
#: What close() infers, or writes once a call is past EXPIRY_H with no evidence.
ACCEPTED, REJECTED, UNKNOWN, PENDING = "accepted", "rejected", "unknown", "pending"
INFERRED = (ACCEPTED, REJECTED, UNKNOWN)
KINDS = (ACCEPTED, REJECTED, UNKNOWN, PENDING)
_KIND = {"used": ACCEPTED, "edited": ACCEPTED, ACCEPTED: ACCEPTED,
         "discarded": REJECTED, REJECTED: REJECTED, UNKNOWN: UNKNOWN}
GATEWAY, LOCAL = "gateway", "local"

#: Hours after a call with no evidence before its outcome becomes unknown.
EXPIRY_H = 24.0
#: An answer or prompt line shorter than this, whitespace collapsed, is not looked for.
SPAN_CHARS = 30
#: Share of the answer's own lines a later tool input must hold to count the answer accepted.
SPAN_SHARE = 0.25

#: The MCP tools whose result carries a call_id.
DELEGATING = ("local_complete", "local_decide")
#: A shell command running `soh local complete|decide`, whose output carries the call_id. #1687.
CLI_CALL = re.compile(r"\bsoh\b[^\n|;&]*?\blocal\s+(complete|decide)\b")
#: The footer `soh local` prints after the answer.
CLI_FOOTER = re.compile(r"^-- .*\bcall_id (\S+)$", re.M)


class UnknownCall(KeyError):
    """No delegation has this call id."""

    def __str__(self) -> str:
        return self.args[0]


def new_id() -> str:
    return "local-" + uuid.uuid4().hex


def _row(call_id: str, lane: str, spec: str = "", model: str = "", seconds=None, prompt_tokens=None,
         completion_tokens=None, id_source: str = LOCAL, at: float | None = None) -> dict:
    return {"call_id": call_id, "id_source": id_source, "at": time.time() if at is None else at, "lane": lane,
            "spec": spec, "model": model, "seconds": seconds, "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens}


def record(conn, call_id: str, lane: str, spec: str = "", model: str = "",
           seconds=None, prompt_tokens=None, completion_tokens=None,
           id_source: str = LOCAL, at: float | None = None) -> str:
    r = _row(call_id, lane, spec, model, seconds, prompt_tokens, completion_tokens, id_source, at)
    conn.execute(
        "INSERT OR REPLACE INTO delegations (call_id, id_source, at, lane, spec, model, "
        "seconds, prompt_tokens, completion_tokens, outcome, why, outcome_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '', NULL)", tuple(r.values()))
    conn.commit()
    return call_id


#: Why the live store was not written, once printed: one stderr line a process. #1717.
_SKIPPED: set = set()

#: Under the live home: one file per record a checkout at another schema could not write, until drain() lands it. #1789.
SPOOL = "delegations-spool"
#: What drain() made of a spooled record; a held one stays in the spool and is tried again next drain. #1789.
LANDED, DUPLICATE, HELD = "landed", "duplicate", "held"
SPOOL_STATES = (LANDED, DUPLICATE, HELD)
#: The record kinds, in the order drain() lands them: an outcome needs its delegation first.
SPOOLED_KINDS = ("delegation", "request", "outcome")


@contextmanager
def on_behalf(call_id: str):
    """Requests made meanwhile are delegation `call_id`'s: their rows go where it goes and carry its id. #1717, #1721."""
    from harness import purpose
    with purpose.delegating(call_id):
        yield


def behalf() -> str:
    """The call_id of the delegation the current requests are made for, else ""."""
    from harness import purpose
    return purpose.delegation()


class Spool:
    """The live store at another schema than this checkout's: its rows go to the spool instead. #1789."""

    def __init__(self, conn, have):
        self.conn, self.have = conn, have

    def close(self) -> None:
        self.conn.close()

    def put(self, kind: str, **body) -> str:
        return spool(kind, **body)

    def knows(self, call_id: str) -> bool:
        if any(r.get("kind") == "delegation" for r in spooled(call_id)):
            return True
        try:
            return self.conn.execute("SELECT 1 FROM delegations WHERE call_id = ?", (call_id,)).fetchone() is not None
        except Exception:  # noqa: BLE001 - unreadable at its schema: spool the outcome rather than lose it
            return True


@contextmanager
def ledger():
    """Where a delegation's rows go: usage.target(), else the live store as it stands, a Spool at another schema, or None. #1717, #1789."""
    from harness import paths, store, usage
    from harness import memory_store as ms
    path = usage.target()
    with contextlib.ExitStack() as held:
        if path is not None:
            conn = ms.connect(path)
        elif paths.evaluating():
            conn = None
        else:
            # The live store on the backend its store.json names, whatever LOCALHARNESS_STORE this process inherited. #1852.
            held.enter_context(store.pinned(_named()))
            conn = _live_as_is(ms.db_path())
        try:
            yield conn
        finally:
            if conn is not None:
                conn.close()


def _named(home=None) -> str:
    from harness import store
    got = str(store.marker(home).get("backend") or "").strip().lower()
    return store.POSTGRES if got == store.POSTGRES else store.SQLITE


def _live_label() -> str:
    from harness import paths, store
    if _named(paths.DEFAULT_HOME) == store.POSTGRES:
        return f"the live store, Postgres {store.pg_target(home=paths.DEFAULT_HOME)},"
    return f"the live store {paths.DEFAULT_HOME / 'discovery.db'}"


def _live_spool() -> Path | None:
    """The live home's spool when this process records in a store of its own and a deployed release drains it. #1852."""
    from harness import paths, store, usage
    target, live = usage.target(), paths.DEFAULT_HOME
    if target is None or paths.is_live(target) or paths.deploy_checkout() is None or store.guarded(live):
        return None
    return live / SPOOL if (live / store.MARKER).is_file() or (live / "discovery.db").is_file() else None


def _mirror(kind: str, **body) -> None:
    """A row written to a store of this process's own goes to the live ledger too, through its spool. #1852."""
    try:
        into = _live_spool()
        if into is not None:
            spool(kind, into=into, **body)
    except Exception as exc:  # noqa: BLE001 - the row is in this process's store; only the live copy is lost
        print(f"delegations: {kind} not spooled for the live ledger ({exc})", file=sys.stderr)


def _in_live(call_id: str) -> bool:
    """Is `call_id` a delegation in the live store, read-only from any home. #1852."""
    from harness import paths, store
    try:
        with paths.seated(paths.DEFAULT_HOME), store.pinned(_named(paths.DEFAULT_HOME)):
            conn = store.open_ro(paths.DEFAULT_HOME / "discovery.db")
            try:
                return conn.execute("SELECT 1 FROM delegations WHERE call_id = ?", (call_id,)).fetchone() is not None
            finally:
                conn.close()
    except Exception:  # noqa: BLE001 - unreadable: the outcome is refused, naming where it looked
        return False


def looked() -> str:
    """Where an outcome for a call id is looked for, as a refusal names it. #1852."""
    from harness import store, usage
    target = usage.target()
    if target is None:
        return f"{_live_label()} and its spool {spool_dir()}"
    where = f"Postgres {store.pg_target()}" if store.home_postgres(target) else str(target)
    live = _live_spool()
    return where + (f", {_live_label()} and its spool {live}" if live is not None else "")


def _once(line: str) -> None:
    if line not in _SKIPPED:
        _SKIPPED.add(line)
        print(line, file=sys.stderr)


def _skip(why: str):
    _once(f"delegations: not recorded in the live store ({why})")
    return None


def _live_as_is(path: Path):
    """The live store opened to append, never to migrate: no DDL; at another schema, a Spool. #1717, #1789."""
    from harness import store
    from harness.memory_store import connection as mc
    from harness.memory_store.schema import SCHEMA_VERSION
    if not store.exists(path):
        return _skip(f"no store at {path}")
    conn = store.open_as_is(path)
    try:
        have = mc._stored_schema(conn)
    except BaseException:
        conn.close()
        raise
    if have != SCHEMA_VERSION:
        _once(f"delegations: the live store is at schema {have}, this checkout speaks {SCHEMA_VERSION}: "
              f"spooled to {spool_dir()} for the deployed release to land")
        return Spool(conn, have)
    return conn


def note(got: dict, call_id: str, gateway: bool = False) -> dict:
    """Record a delegate.complete/decide result as delegation `call_id`; a store failure never fails the call."""
    try:
        with ledger() as conn:
            row = _row(call_id, got["lane"], spec=got.get("spec", ""), model=got.get("model", ""),
                       seconds=got.get("seconds"), prompt_tokens=got.get("prompt_tokens"),
                       completion_tokens=got.get("completion_tokens"), id_source=GATEWAY if gateway else LOCAL)
            if isinstance(conn, Spool):
                conn.put("delegation", call_id=call_id, row=row)
            elif conn is not None:
                record(conn, **row)
                _mirror("delegation", call_id=call_id, row=row)
    except Exception as exc:  # noqa: BLE001
        print(f"delegations: not recorded ({exc})", file=sys.stderr)
    return {**got, "call_id": call_id}


def request(row: dict) -> bool:
    """Write a delegation's own gateway_requests row where its delegations row goes; never raising. #1717."""
    try:
        from harness import usage
        with ledger() as conn:
            if conn is None:
                return False
            if isinstance(conn, Spool):
                bound = usage.bound(row)
                conn.put("request", call_id=bound["call_id"], row=bound)
            else:
                usage.append(conn, row)
                bound = usage.bound(row)
                _mirror("request", call_id=bound["call_id"], row=bound)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"delegations: request row not recorded ({exc})", file=sys.stderr)
        return False


def _what(what: str) -> str:
    what = (what or "").strip().lower()
    if what not in OUTCOMES:
        raise ValueError(f"outcome must be one of used, edited, discarded, not {what!r}")
    return what


def _unknown(call_id: str) -> UnknownCall:
    return UnknownCall(f"no delegation has call id {call_id!r} in {looked()}; local_complete, local_decide "
                       f"and `soh local` return it as call_id")


def outcome(conn, call_id: str, what: str, why: str = "", at: float | None = None) -> dict:
    """Set a delegation's outcome; re-recording overwrites and keeps the old one in `why`."""
    what, said = _what(what), why
    while True:
        row = conn.execute("SELECT outcome, why FROM delegations WHERE call_id = ?",
                           (call_id,)).fetchone()
        if row is None:
            raise _unknown(call_id)
        prev, prev_why = row["outcome"], row["why"]
        why, note_ = said, ""
        if prev is not None:
            why = f"{said} (was {prev}{': ' + prev_why if prev_why else ''})".strip()
            note_ = f"overwrote {prev}"
        if _set_outcome(conn, call_id, prev, what, why, time.time() if at is None else at):
            break
    conn.commit()
    return {"call_id": call_id, "outcome": what, "why": why, "previous": prev, "note": note_}


def _set_outcome(conn, call_id: str, frm: str | None, to: str, why: str, at: float) -> bool:
    """The one writer of a delegation's outcome: compare-and-swap on the outcome it leaves. #1739."""
    if frm is None:
        return conn.execute("UPDATE delegations SET outcome = ?, why = ?, outcome_at = ? "
                            "WHERE call_id = ? AND outcome IS NULL", (to, why, at, call_id)).rowcount == 1
    return conn.execute("UPDATE delegations SET outcome = ?, why = ?, outcome_at = ? WHERE call_id = ? AND outcome = ?",
                        (to, why, at, call_id, frm)).rowcount == 1


def tell(conn, call_id: str, what: str, why: str = "") -> dict:
    """outcome() on a store, also spooled for the live ledger when it is not the live store; on a Spool, checked then spooled. #1789, #1852."""
    what = _what(what)
    if not isinstance(conn, Spool):
        at = time.time()
        try:
            got = outcome(conn, call_id, what, why, at=at)
        except UnknownCall:
            return _told_elsewhere(call_id, what, why, at)
        _mirror("outcome", call_id=call_id, outcome=what, why=why, at=at)
        return got
    if not conn.knows(call_id):
        raise _unknown(call_id)
    conn.put("outcome", call_id=call_id, outcome=what, why=why, at=time.time())
    return {"call_id": call_id, "outcome": what, "why": why, "previous": None,
            "note": f"spooled: the live store is at schema {conn.have}; the deployed release lands it"}


def _told_elsewhere(call_id: str, what: str, why: str, at: float) -> dict:
    """An outcome for a call another store recorded: spooled beside its delegation in the live spool or store. #1852."""
    from harness import usage
    into = spool_dir() if usage.target() is None else _live_spool()
    known = into is not None and (any(r.get("kind") == "delegation" for r in spooled(call_id, into=into))
                                  or (into != spool_dir() and _in_live(call_id)))
    if not known:
        raise _unknown(call_id)
    spool("outcome", into=into, call_id=call_id, outcome=what, why=why, at=at)
    return {"call_id": call_id, "outcome": what, "why": why, "previous": None,
            "note": f"spooled to {into}: its delegation was recorded under another store; the deployed release lands it"}


# --- the spool a checkout at another schema writes and the deployed release drains (#1789) ---------

def spool_dir() -> Path:
    from harness import paths
    return Path(paths.home()) / SPOOL


def spool(kind: str, into: Path | None = None, **body) -> str:
    """Write one record as its own file in `into` (this home's spool), fsynced and renamed into place; its id."""
    from harness.memory_store.schema import SCHEMA_VERSION
    rec = {"id": uuid.uuid4().hex, "kind": kind, "schema": SCHEMA_VERSION, "spooled_at": time.time(), **body}
    d = into or spool_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}-{rec['id']}.json"
    part = d / f".{name}.part"
    with open(part, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    replace(part, d / name)
    with contextlib.suppress(OSError):
        fd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return rec["id"]


def _records(into: Path | None = None) -> list[tuple[Path, dict | None]]:
    d = into or spool_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = None
        out.append((p, rec if isinstance(rec, dict) else None))
    return out


def spooled(call_id: str | None = None, into: Path | None = None) -> list[dict]:
    """The readable spooled records, oldest first; only `call_id`'s when given."""
    return [r for _, r in _records(into) if r is not None and (call_id is None or r.get("call_id") == call_id)]


def _land(conn, rec: dict, known: dict) -> tuple[str, str]:
    from harness.memory_store.schema import _columns
    kind = rec.get("kind")
    if kind == "outcome":
        what, at = rec.get("outcome"), rec.get("at")
        row = conn.execute("SELECT outcome, outcome_at FROM delegations WHERE call_id = ?",
                           (rec.get("call_id"),)).fetchone()
        if row is None:
            return HELD, "its delegation is not in this store yet"
        if row["outcome"] == what and row["outcome_at"] == at:
            return DUPLICATE, ""
        outcome(conn, rec["call_id"], what, rec.get("why") or "", at=at)
        return LANDED, ""
    table = {"delegation": "delegations", "request": "gateway_requests"}.get(kind)
    row = rec.get("row")
    if table is None or not isinstance(row, dict):
        return HELD, f"a record of kind {kind!r} this release does not know"
    if table not in known:
        known[table] = _columns(conn, table) - {"id"}
    unknown = sorted(set(row) - known[table])
    if unknown:
        return HELD, f"columns {table} does not have here: {', '.join(unknown)}"
    if table == "delegations":
        seen = conn.execute("SELECT 1 FROM delegations WHERE call_id = ?", (row.get("call_id"),)).fetchone()
    else:
        seen = conn.execute("SELECT 1 FROM gateway_requests WHERE call_id = ? AND at = ?",
                            (row.get("call_id") or "", row.get("at"))).fetchone()
    if seen is not None:
        return DUPLICATE, ""
    cols = sorted(row)
    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                 tuple(row[c] for c in cols))
    conn.commit()
    return LANDED, ""


def drain(conn) -> dict:
    """Land the spool's records in `conn`'s store once each, keyed by call_id, with no DDL; one it cannot land stays held. #1789."""
    got: dict = {s: 0 for s in SPOOL_STATES} | {"held_records": []}
    recs = _records()
    kinds = list(SPOOLED_KINDS)
    recs.sort(key=lambda pr: (kinds.index(k) if (k := (pr[1] or {}).get("kind")) in kinds else len(kinds), pr[0].name))
    known: dict = {}
    for path, rec in recs:
        if rec is None:
            state, why = HELD, "not a JSON record"
        else:
            try:
                state, why = _land(conn, rec, known)
            except Exception as exc:  # noqa: BLE001 - this store will not take it: keep it for a release that will
                with contextlib.suppress(Exception):
                    conn.rollback()
                state, why = HELD, f"{type(exc).__name__}: {exc}"
        got[state] += 1
        if state == HELD:
            got["held_records"].append({"file": path.name, "kind": (rec or {}).get("kind"),
                                        "call_id": (rec or {}).get("call_id"), "why": why})
        else:
            path.unlink(missing_ok=True)
    return got


def kind(outcome) -> str:
    """accepted, rejected, unknown, or pending for a NULL outcome."""
    return _KIND.get(outcome or "", PENDING)


def instruction(call_id: str, cli: bool = False) -> str:
    """The sentence every local_complete / local_decide result carries; `cli` names `soh delegated`. #1158, #1687."""
    how = (f"run `soh delegated {call_id} used|edited|discarded \"why\"`" if cli
           else f"call delegated with call_id {call_id!r} and that outcome")
    return (f"Once you have used, edited or discarded this answer, {how}. Unreported, it is inferred from this "
            f"session's later tool inputs, or recorded unknown after {EXPIRY_H:g} h.")


def rows(conn, call_id: str) -> dict:
    """Delegation `call_id`'s own row (or None) and every gateway_requests row carrying its id, oldest first. #1721."""
    d = conn.execute("SELECT * FROM delegations WHERE call_id = ?", (call_id,)).fetchone()
    got = conn.execute("SELECT at, alias, lane, client, purpose, prompt_tokens, completion_tokens, error_class "
                       "FROM gateway_requests WHERE call_id = ? ORDER BY at", (call_id,)).fetchall()
    return {"call_id": call_id, "delegation": dict(d) if d else None, "requests": [dict(r) for r in got]}


def report(conn, since: float, now: float | None = None) -> list[dict]:
    """Per lane over the last `since` seconds: count, reported rate and rates, closed kinds, median seconds."""
    now = time.time() if now is None else now
    rows = conn.execute("SELECT lane, outcome, seconds FROM delegations WHERE at >= ?",
                        (now - since,)).fetchall()
    by_lane: dict[str, list] = {}
    for r in rows:
        by_lane.setdefault(r["lane"], []).append(r)
    out = []
    for lane in sorted(by_lane):
        items = by_lane[lane]
        said = [i["outcome"] for i in items if i["outcome"] in OUTCOMES]
        secs = [i["seconds"] for i in items if i["seconds"] is not None]
        kinds = [kind(i["outcome"]) for i in items]
        out.append({
            "lane": lane, "count": len(items), "recorded": len(said),
            "recorded_rate": len(said) / len(items),
            **{f"{o}_rate": (said.count(o) / len(said) if said else None) for o in OUTCOMES},
            **{k: kinds.count(k) for k in KINDS},
            "median_seconds": round(statistics.median(secs), 3) if secs else None,
        })
    return out


# --- closing outcomes from the caller's transcript (#1158) -----------------------------------------

def _norm(text: str) -> str:
    return " ".join(text.split())


def spans(text: str, floor: int | None = None) -> set[str]:
    """The text's lines and sentences, whitespace collapsed, of at least `floor` characters."""
    floor = SPAN_CHARS if floor is None else floor
    out = set()
    for line in (text or "").splitlines():
        for part in re.split(r"(?<=[.!?])\s+", line):
            n = _norm(part)
            if len(n) >= floor:
                out.add(n)
    return out


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return []


def _short(name: str) -> str:
    return name.rsplit("__", 1)[-1]


def _answer(name: str, body: dict) -> str:
    if _short(name) == "local_decide":
        return json.dumps(body.get("answers") or {}, sort_keys=True)
    return str(body.get("text") or "")


def _asked(name: str, given: dict) -> str:
    keys = ("question", "context") if _short(name) == "local_decide" else ("prompt", "question", "system")
    return "\n".join(str(given.get(k) or "") for k in keys)


def cli_result(text: str) -> dict:
    """`soh local` output as the MCP result's fields: its --json object, else the answer above its footer."""
    for line in reversed(text.splitlines()):
        if line.startswith("{"):
            try:
                got = json.loads(line)
            except ValueError:
                continue
            if isinstance(got, dict) and got.get("call_id"):
                return got
    foot = list(CLI_FOOTER.finditer(text))
    if not foot:
        return {}
    answer = text[:foot[-1].start()].rstrip("\n")
    try:
        answers = json.loads(answer)
    except ValueError:
        answers = None
    return {"call_id": foot[-1].group(1), "text": answer, "answers": answers if isinstance(answers, dict) else {}}


def calls(path: Path, wanted) -> list[dict]:
    """Each delegation in `wanted` this transcript returned: its answer, its prompt, and every later tool input."""
    from harness.context_report import result_text
    wanted = set(wanted)
    with open(path, encoding="utf-8", errors="ignore") as fh:
        lines = [ln for ln in fh if '"tool_use"' in ln or '"tool_result"' in ln]
    if not any(c in ln for ln in lines for c in wanted):
        return []
    uses: dict = {}
    order: list[tuple] = []
    found: list[dict] = []
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        content = (d.get("message") or {}).get("content") if isinstance(d, dict) else None
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                name = str(c.get("name") or "")
                given = c.get("input") if isinstance(c.get("input"), dict) else {}
                uses[c.get("id")] = (name, given)
                order.append((name, "\n".join(_strings(given))))
            elif c.get("type") == "tool_result" and not c.get("is_error"):
                name, given = uses.get(c.get("tool_use_id"), ("", {}))
                verb = CLI_CALL.search(str(given.get("command") or "")) if name == "Bash" else None
                if verb:
                    name, given = f"local_{verb.group(1)}", {"prompt": given["command"]}
                    body = cli_result(result_text(c.get("content")))
                elif _short(name) not in DELEGATING:
                    continue
                else:
                    try:
                        body = json.loads(result_text(c.get("content")))
                    except ValueError:
                        continue
                call_id = body.get("call_id") if isinstance(body, dict) else None
                if call_id in wanted:
                    found.append({"call_id": call_id, "tool": _short(name), "answer": _answer(name, body),
                                  "prompt": _asked(name, given), "after": len(order)})
    for f in found:
        f["later"] = order[f.pop("after"):]
    return found


def judge(answer: str, prompt: str, later, floor: int | None = None,
          share: float | None = None, near: list | None = None) -> tuple[str, str] | None:
    """(accepted|rejected, why) from the first later tool input that shows it, else None; `near` gets a miss under the share."""
    share = SPAN_SHARE if share is None else share
    asked = spans(prompt, floor)
    mine = spans(answer, floor) - asked
    need, again = max(1, math.ceil(share * len(mine))), max(1, math.ceil(share * len(asked)))
    from harness.context_report import SPAWN_TOOLS
    under = False
    for name, text in later:
        if _short(name) in DELEGATING or (name == "Bash" and CLI_CALL.search(text)):
            continue
        flat = _norm(text)
        hit = sum(1 for s in mine if s in flat)
        if mine and hit >= need:
            return ACCEPTED, f"{hit} of {len(mine)} answer lines in a later {_short(name)} input"
        if name in SPAWN_TOOLS and asked and sum(1 for s in asked if s in flat) >= again:
            return REJECTED, f"the task was asked again of a cloud {name}"
        under = under or hit > 0
    if under and near is not None:
        near.append(answer)
    return None


def _session(path: Path) -> str:
    return hashlib.sha256(path.stem.encode()).hexdigest()[:12]


def close(conn, root: Path | None = None, now: float | None = None, expiry_h: float | None = None) -> dict:
    """Infer each pending delegation's outcome from its caller's transcript; past expiry_h with none, unknown."""
    from harness import context_report as cr
    now = time.time() if now is None else now
    expiry_s = (EXPIRY_H if expiry_h is None else expiry_h) * 3600
    pending = {r["call_id"]: r["at"] for r in conn.execute(
        "SELECT call_id, at FROM delegations WHERE outcome IS NULL")}
    got = {k: 0 for k in INFERRED} | {PENDING: 0, "transcripts": 0}
    if not pending:
        return got
    root = cr.default_root() if root is None else Path(root)
    seen: dict = {}
    if root.is_dir():
        for path in cr.transcripts(root, newer_than=min(pending.values()) - 60):
            got["transcripts"] += 1
            for f in calls(path, set(pending) - set(seen)):
                seen[f["call_id"]] = (path, f)
    near: list = []
    expired = short = 0
    for call_id, at in sorted(pending.items()):
        what = why = None
        path, f = seen.get(call_id, (None, None))
        if f is not None:
            verdict = judge(f["answer"], f["prompt"], f["later"], near=near)
            if verdict:
                what, why = verdict[0], f"inferred from session {_session(path)}: {verdict[1]}"
        if what is None and now - at >= expiry_s:
            reason = ("no transcript under the projects root returned it" if f is None
                      else "no later tool input held the answer" if spans(f["answer"])
                      else "the answer has no line long enough to look for")
            what, why = UNKNOWN, f"expired after {expiry_s / 3600:g} h: {reason}"
            expired += 1
            short += f is not None and bool(f["answer"].strip()) and not spans(f["answer"])
        if what is None:
            got[PENDING] += 1
            continue
        got[what] += _set_outcome(conn, call_id, None, what, why, now)
    from harness import cuts
    if expired:
        cuts.cut("delegation_expiry", "delegations closed unknown at expiry", value=expiry_s / 3600,
                 dropped=expired, conn=conn)
    if short:
        cuts.cut("delegation_span_chars", "delegation answers with no line long enough to look for", dropped=short,
                 conn=conn)
    if near:
        cuts.cut("delegation_span_share", "delegation answers seen in later input below the share",
                 dropped=len(near), conn=conn)
    conn.commit()
    return got

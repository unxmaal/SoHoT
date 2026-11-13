"""Hypothesis drives each declared lifecycle's one writer with random moves and two actors on one store. #1766."""
import itertools
import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule, run_state_machine_as_test

from harness import adopt, adoption_state as ads, candidates, deploy, deploy_state as dps, download_state as dls
from harness import exclusive as ex, gateway_switch_state as gss, item_lease, job_state as js, paused, store, sweeps
from harness import memory_store as ms
from harness import workqueue as wq
from tests.racing import race

ACTORS = st.sampled_from((0, 1))
BOGUS = "bogus"
#: Every draw has one shape whatever the store holds, since which racer won is the threads' choice.
INDEX = st.integers(0, 2**16)


def _pick(data, seq):
    i = data.draw(INDEX)
    return seq[i % len(seq)] if seq else None


def _settle(conns):
    """A step that raised leaves its actor's transaction open, which would lock the next example out."""
    for c in conns:
        c.rollback()


def _triples(moves) -> list[tuple]:
    return sorted(((f, t, lb) for (f, t), labels in moves.items() for lb in labels), key=repr)


def _labels(moves) -> tuple:
    return tuple(sorted({lb for labels in moves.values() for lb in labels})) + (BOGUS,)


class Lifecycle(RuleBasedStateMachine):
    """Rows of one table and their modelled state; a subclass names the table's writer and its births."""
    actors: list = []
    MOVES: dict = {}
    STATES: tuple = ()
    LABELS: tuple = ("",)
    KEYS: tuple = ("",)
    ERROR: type = Exception
    #: Births of one key exclude each other, so two at once leave one row.
    UNIQUE = False
    #: Self-moves the writer makes exclusive by a compare-and-swap beyond the state.
    EXCLUSIVE_SELF: frozenset = frozenset()
    #: States a legal move out of is a birth, not a move of an existing row.
    UNBORN: tuple = ()

    def __init__(self):
        super().__init__()
        self.rows: dict[int, dict] = {}
        self.n = 0
        _settle(self.actors)
        self.reset(self.actors[0])
        self.actors[0].commit()

    def teardown(self):
        _settle(self.actors)

    def reset(self, conn): raise NotImplementedError
    def birth(self, conn, key, tag=0): raise NotImplementedError
    def write(self, conn, rid, frm, to, label, tag=0): raise NotImplementedError
    def stored(self, conn, rid): raise NotImplementedError

    def triples(self) -> list[tuple]:
        return _triples(self.MOVES)

    def legal(self, frm, to, label) -> bool:
        return label in self.MOVES.get((frm, to), ())

    def born_as(self, key):
        return key

    def wins(self, rid, frm, to, label) -> bool:
        return self.rows[rid]["state"] == frm

    def moved(self, rid, to, label, tag=0):
        self.rows[rid]["state"] = to

    def check(self, conn):
        pass

    def _born(self, rid, key, tag=0):
        self.rows[int(rid)] = {"key": key, "state": self.born_as(key)}

    @rule(actor=ACTORS, data=st.data())
    def born(self, actor, data):
        key = data.draw(st.sampled_from(self.KEYS))
        want = self.born_as(key)
        self.n += 1
        got = self.birth(self.actors[actor], key)
        assert (got is not None) == (want is not None), f"birth of {key}: got {got}, the model says {want}"
        if got is not None:
            self._born(got, key)

    @rule(data=st.data())
    def born_at_once(self, data):
        key = data.draw(st.sampled_from(self.KEYS))
        want = self.born_as(key)
        got = {}

        def racer(i):
            def go(start):
                conn = ms.connect()
                try:
                    start()
                    got[i] = self.birth(conn, key, tag=i)
                finally:
                    conn.close()
            return go
        self.n += 1
        race([racer(0), racer(1)])
        won = [rid for rid in got.values() if rid is not None]
        assert len(won) == (0 if want is None else 1 if self.UNIQUE else 2), f"two births of {key} at once: {got}"
        for i, rid in got.items():
            if rid is not None:
                self._born(rid, key, tag=i)

    def illegal(self) -> list[tuple]:
        return sorted(((f, t, lb) for f in self.STATES for t in self.STATES for lb in self.LABELS
                       if not self.legal(f, t, lb)), key=repr)

    @rule(actor=ACTORS, data=st.data())
    def refuse(self, actor, data):
        rid = _pick(data, sorted(self.rows))
        frm, to, label = data.draw(st.sampled_from(self.illegal()))
        if rid is None:
            return
        conn = self.actors[actor]
        with pytest.raises(self.ERROR):
            self.write(conn, rid, frm, to, label)
        conn.rollback()

    @rule(actor=ACTORS, data=st.data(), current=st.booleans())
    def move(self, actor, data, current):
        rid = _pick(data, sorted(self.rows))
        state = rid is not None and self.rows[rid]["state"]
        if current:
            frm, to, label = _pick(data, [m for m in self.triples() if m[0] == state]) or (None, None, None)
        else:
            frm, to, label = data.draw(st.sampled_from(self.triples()))
        if rid is None or to is None:
            return
        conn = self.actors[actor]
        if frm in self.UNBORN:
            return
        want = self.wins(rid, frm, to, label)
        assert self.write(conn, rid, frm, to, label) == want, f"{rid} {frm!r}->{to!r} for {label}: model {want}"
        if want:
            self.moved(rid, to, label)

    def _races(self) -> list[tuple]:
        out = []
        for rid, row in sorted(self.rows.items()):
            if any(f == row["state"] and (f != t or (f, t) in self.EXCLUSIVE_SELF) for f, t, _ in self.triples()):
                out.append((rid, row["state"]))
        return out

    @rule(data=st.data())
    def two_actors_race_one_row(self, data):
        got = _pick(data, self._races())
        frm = got and got[1]
        moves = [(t, lb) for f, t, lb in self.triples() if f == frm and (f != t or (f, t) in self.EXCLUSIVE_SELF)]
        picked = [_pick(data, moves), _pick(data, moves)]
        if got is None:
            return
        rid = got[0]
        won = {}

        def racer(i):
            def go(start):
                conn = ms.connect()
                try:
                    start()
                    won[i] = self.write(conn, rid, frm, *picked[i], tag=i)
                finally:
                    conn.close()
            return go
        race([racer(0), racer(1)])
        assert sorted(won.values()) == [False, True], f"{rid} from {frm!r} raced by {picked}: {won}"
        i = 0 if won[0] else 1
        self.moved(rid, picked[i][0], picked[i][1], tag=i)

    @invariant()
    def the_store_holds_what_the_model_says(self):
        conn = self.actors[0]
        got = {rid: self.stored(conn, rid) for rid in self.rows}
        self.check(conn)
        conn.rollback()
        assert got == {rid: row["state"] for rid, row in self.rows.items()}


class Jobs(Lifecycle):
    MOVES = js.MOVES
    STATES = (js.PENDING, js.RUNNING, js.DONE, js.FAILED, js.CANCELLED, js.PAUSED)
    LABELS = _labels(js.MOVES)
    KEYS = (js.PENDING,)
    ERROR = js.IllegalMove

    def reset(self, conn):
        conn.execute("DELETE FROM jobs")

    def birth(self, conn, key, tag=0):
        return int(wq.add(["soh-batch-job"], title="stateful", conn=conn)["id"])

    def write(self, conn, rid, frm, to, label, tag=0):
        won = js.move(conn, rid, frm, to, label)
        conn.commit()
        return won

    def stored(self, conn, rid):
        return conn.execute("SELECT state FROM jobs WHERE id = ?", (rid,)).fetchone()[0]


class Downloads(Lifecycle):
    MOVES = dls.MOVES
    STATES = (dls.NONE, *dls.STATES)
    LABELS = _labels(dls.MOVES)
    KEYS = (dls.FETCHING, dls.REMOVED)
    ERROR = dls.IllegalMove

    def reset(self, conn):
        conn.execute("DELETE FROM downloads")

    def birth(self, conn, key, tag=0):
        reason = dls.STARTED if key == dls.FETCHING else dls.HISTORY
        rid = dls.born(conn, key, reason, kind="hub", path=f"/hf/models--o--m{self.n}-{tag}", repo="o/m")
        conn.commit()
        return int(rid)

    def write(self, conn, rid, frm, to, label, tag=0):
        won = dls.move(conn, rid, frm, to, label)
        conn.commit()
        return won

    def stored(self, conn, rid):
        state, complete = conn.execute("SELECT state, complete FROM downloads WHERE id = ?", (rid,)).fetchone()
        assert bool(complete) == (state == dls.COMPLETE)
        return state


class Switches(Lifecycle):
    MOVES = gss.MOVES
    STATES = (gss.NONE, *gss.STATES)
    LABELS = _labels(gss.MOVES)
    KEYS = (gss.REQUESTED,)
    ERROR = gss.IllegalMove
    UNIQUE = True

    def reset(self, conn):
        conn.execute("DELETE FROM gateway_switch_runs")

    def born_as(self, key):
        return None if any(r["state"] in gss.LIVE for r in self.rows.values()) else gss.REQUESTED

    def birth(self, conn, key, tag=0):
        try:
            return int(gss.claim(conn, now=1.0, requested_at=1.0))
        except gss.Lost:
            return None

    def write(self, conn, rid, frm, to, label, tag=0):
        return gss.move(conn, rid, frm, to, label, now=2.0)

    def stored(self, conn, rid):
        return conn.execute("SELECT state FROM gateway_switch_runs WHERE id = ?", (rid,)).fetchone()[0]

    def check(self, conn):
        live = [r[0] for r in conn.execute("SELECT id FROM gateway_switch_runs WHERE live = 1")]
        assert live == [rid for rid, r in sorted(self.rows.items()) if r["state"] in gss.LIVE]


class Deploys(Lifecycle):
    MOVES = dps.MOVES
    STATES = (dps.NEW, *dps.STAGES)
    LABELS = (dps.JOB, dps.SWITCH, dps.SETTLE, BOGUS)
    KEYS = (dps.BUILDING,)
    ERROR = dps.IllegalMove

    def triples(self):
        return _triples({k: sorted(v) for k, v in self.MOVES.items()})

    def reset(self, conn):
        conn.execute("DELETE FROM deploys")

    def birth(self, conn, key, tag=0):
        return deploy._insert(conn, "a" * 40, None, Path("/releases/prev"), "b" * 40, 1.0)

    def write(self, conn, rid, frm, to, label, tag=0):
        return deploy.move(conn, rid, frm, to, label)

    def stored(self, conn, rid):
        stage, outcome = conn.execute("SELECT stage, outcome FROM deploys WHERE id = ?", (rid,)).fetchone()
        assert outcome == (stage if stage in dps.OUTCOMES else ""), (stage, outcome)
        return stage


INC = "llamacpp:Inc"


class Pauses(Lifecycle):
    MOVES = {m: ("",) for m in paused.MOVES}
    STATES = (None, *paused.STATES)
    KEYS = ("org/a", "org/b")
    ERROR = paused.IllegalMove
    UNBORN = (None,)
    UNIQUE = True

    def legal(self, frm, to, label):
        return frm is not None and (frm, to) in paused.MOVES

    def reset(self, conn):
        conn.execute("DELETE FROM paused_runs")

    def born_as(self, key):
        live = any(r["key"] == key and r["state"] == paused.PAUSED for r in self.rows.values())
        return None if live else paused.PAUSED

    def _save(self, conn, key, **kw):
        return paused.save(conn, lane="code", inc_spec=INC, spec=key, proposal=key, out=f"/runs/{key}", ident={},
                           plan={}, total=4, looks=[], **{"done": 1, **kw})

    def birth(self, conn, key, tag=0):
        try:
            return self._save(conn, key)
        except paused.IllegalMove:
            return None

    def write(self, conn, rid, frm, to, label, tag=0):
        return paused._move(conn, rid, frm, to, why="stateful")

    def stored(self, conn, rid):
        return conn.execute("SELECT state FROM paused_runs WHERE id = ?", (rid,)).fetchone()[0]

    @rule(actor=ACTORS, data=st.data())
    def save_again(self, actor, data):
        rid = _pick(data, sorted(self.rows))
        if rid is None:
            return
        conn, row = self.actors[actor], self.rows[rid]
        if row["state"] != paused.PAUSED:
            with pytest.raises(paused.IllegalMove):
                self._save(conn, row["key"], pause_id=rid, done=2)
            return
        assert self._save(conn, row["key"], pause_id=rid, done=2) == rid

    def check(self, conn):
        twice = conn.execute("SELECT challenger FROM paused_runs WHERE state = ? GROUP BY lane, challenger, machine_id "
                             "HAVING COUNT(*) > 1", (paused.PAUSED,)).fetchall()
        assert not twice, [r[0] for r in twice]


JOB_IDS = itertools.count(1)


def _sweep(spec, rid=None, jobs="[]"):
    return {"id": rid, "knob": "reply_budget", "lane": "code", "spec": spec, "candidate_id": None,
            "machine_id": None, "jobs": jobs}


class Sweeps(Lifecycle):
    MOVES = sweeps.MOVES
    STATES = (None, sweeps.OPEN, *sweeps.SETTLED, *sweeps.FOUND)
    LABELS = _labels(sweeps.MOVES)
    KEYS = tuple((spec, sweeps.OPEN, "") for spec in ("a", "b")) + tuple(
        (spec, to, detail) for spec in ("a", "b") for to in sweeps.FOUND for detail in ("d1", "d2"))
    ERROR = sweeps.IllegalMove
    UNIQUE = True
    EXCLUSIVE_SELF = frozenset({(sweeps.OPEN, sweeps.OPEN)})
    UNBORN = (None,)

    def reset(self, conn):
        self.jobs = {}
        conn.execute("DELETE FROM knob_sweeps")

    def born_as(self, key):
        spec, to, detail = key
        mine = [r for r in self.rows.values() if r["key"][0] == spec]
        if any(r["state"] == sweeps.OPEN for r in mine):
            return None
        if to in sweeps.FOUND and any(r["state"] in sweeps.FOUND and r["key"][2] == detail for r in mine):
            return None
        return to

    def birth(self, conn, key, tag=0):
        spec, to, detail = key
        reason = sweeps.QUEUED if to == sweeps.OPEN else sweeps.RECORDED
        return sweeps._move(conn, _sweep(spec), None, to, reason, queued_at=1.0, detail=detail)

    def _born(self, rid, key, tag=0):
        super()._born(rid, key, tag)
        self.rows[int(rid)]["jobs"] = "[]"

    def write(self, conn, rid, frm, to, label, tag=0):
        row = self.rows[rid]
        # A resume points the sweep at a new job, so no jobs list ever comes back.
        self.jobs[tag] = json.dumps([[tag, next(JOB_IDS)]])
        cols = {"jobs": self.jobs[tag]} if label == sweeps.RESUMED else {}
        return sweeps._move(conn, _sweep(row["key"][0], rid, row["jobs"]), frm, to, label, **cols) is not None

    def moved(self, rid, to, label, tag=0):
        super().moved(rid, to, label, tag)
        if label == sweeps.RESUMED:
            self.rows[rid]["jobs"] = self.jobs[tag]

    def stored(self, conn, rid):
        outcome, jobs = conn.execute("SELECT outcome, jobs FROM knob_sweeps WHERE id = ?", (rid,)).fetchone()
        assert jobs == self.rows[rid]["jobs"]
        return outcome

    @rule(actor=ACTORS, data=st.data(), to=st.sampled_from((sweeps.OPEN, *sweeps.SETTLED)))
    def leave_open_on_a_stale_read(self, actor, data, to):
        rid = _pick(data, sorted(self.rows))
        if rid is None:
            return
        sw = _sweep(self.rows[rid]["key"][0], rid, jobs="[[9, 9]]")
        reason = sweeps.RESUMED if to == sweeps.OPEN else sweeps.JUDGED
        assert sweeps._move(self.actors[actor], sw, sweeps.OPEN, to, reason) is None

    def check(self, conn):
        twice = conn.execute("SELECT spec FROM knob_sweeps WHERE outcome = ? GROUP BY knob, lane, spec, machine_id "
                             "HAVING COUNT(*) > 1", (sweeps.OPEN,)).fetchall()
        assert not twice, [r[0] for r in twice]


LANES, SPECS = ("code", "svg"), ("org/a", "org/b")


class Adoptions(RuleBasedStateMachine):
    """Each lane's chain of adoption moves on this machine: a stale head loses, two writers of one head, one wins."""
    actors: list = []

    def __init__(self):
        super().__init__()
        conn = self.actors[0]
        _settle(self.actors)
        conn.execute("DELETE FROM adoptions")
        conn.commit()
        self.mid = ms.remember_machine(conn)
        self.cids = {s: candidates.ensure(conn, s, lane=lane) for lane in LANES for s in SPECS}
        conn.commit()
        self.lanes = {lane: {"state": ads.NONE, "serves": None, "heads": [0]} for lane in LANES}

    def teardown(self):
        _settle(self.actors)

    def _move(self, conn, lane, kind, spec, head):
        return ads.move(conn, lane, kind, self.cids.get(spec, self.cids[SPECS[0]]), how=adopt.MEASURED,
                        machine_id=self.mid, head=head)

    def _refused(self, lane, kind, spec) -> bool:
        m = self.lanes[lane]
        if (m["state"], kind) not in ads.MOVES:
            return True
        return kind == ads.WITHDRAW and self.cids[spec] != m["serves"]

    def _moved(self, lane, kind, spec, rid):
        m = self.lanes[lane]
        m["state"] = ads.MOVES[(m["state"], kind)]
        m["serves"] = self.cids[spec] if kind == ads.ADOPT else None
        m["heads"].append(int(rid))

    @rule(actor=ACTORS, lane=st.sampled_from(LANES), kind=st.sampled_from((*ads.KINDS, BOGUS)),
          spec=st.sampled_from(SPECS), stale=st.booleans())
    def move(self, actor, lane, kind, spec, stale):
        m, conn = self.lanes[lane], self.actors[actor]
        head = m["heads"][-2] if stale and len(m["heads"]) > 1 else m["heads"][-1]
        if kind not in ads.KINDS:
            with pytest.raises(ads.IllegalMove):
                self._move(conn, lane, kind, spec, head)
        elif head != m["heads"][-1]:
            with pytest.raises(ads.Lost):
                self._move(conn, lane, kind, spec, head)
        elif self._refused(lane, kind, spec):
            with pytest.raises(ads.IllegalMove):
                self._move(conn, lane, kind, spec, head)
        else:
            self._moved(lane, kind, spec, self._move(conn, lane, kind, spec, head))
        conn.rollback()

    @rule(lane=st.sampled_from(LANES), specs=st.tuples(st.sampled_from(SPECS), st.sampled_from(SPECS)))
    def two_adopt_one_head(self, lane, specs):
        head = self.lanes[lane]["heads"][-1]
        got = {}

        def racer(i):
            def go(start):
                conn = ms.connect()
                try:
                    start()
                    try:
                        got[i] = self._move(conn, lane, ads.ADOPT, specs[i], head)
                    except ads.Lost:
                        got[i] = None
                finally:
                    conn.close()
            return go
        race([racer(0), racer(1)])
        won = [i for i, rid in got.items() if rid is not None]
        assert len(won) == 1, f"two adopts of {lane} leaving {head}: {got}"
        self._moved(lane, ads.ADOPT, specs[won[0]], got[won[0]])

    @invariant()
    def each_lane_serves_what_its_chain_says(self):
        conn = self.actors[0]
        for lane, m in self.lanes.items():
            got = ads.serving(conn, lane, machine=self.mid, typed={})
            chain = [r["id"] for r in ads.chains(conn, lane).get(lane, [])]
            assert (got.state, got.candidate_id, [0, *chain]) == (m["state"], m["serves"], m["heads"]), lane
        assert not ads.off_chain(conn)
        conn.rollback()


TTL = item_lease.TTL_S
WRITERS = tuple(sorted({w for ws in ex.MOVES.values() for w in ws})) + (BOGUS,)
LEASE_STATES = (ex.FREE, ex.RESERVED, ex.LOADING, ex.LAPSED, ex.ABANDONED)


class GpuLease(RuleBasedStateMachine):
    """The gpu lease rows under a fake clock and a fake liveness: at most one holder at any step."""
    actors: list = []
    current = None

    def __init__(self):
        super().__init__()
        GpuLease.current = self
        self.now, self.dead, self.rows, self.seen = 1000.0, set(), {}, ({}, {})
        _settle(self.actors)
        self.actors[0].execute("DELETE FROM leases")
        self.actors[0].commit()

    def teardown(self):
        _settle(self.actors)

    def state(self, h: dict) -> str:
        if h is None or h["released_at"] is not None:
            return ex.FREE
        if int(h["id"]) in self.dead:
            return ex.ABANDONED
        if float(h["expires_at"]) <= self.now:
            return ex.LAPSED
        return ex.LOADING if h["state"] else ex.RESERVED

    def takes(self) -> bool:
        return all(r["released_at"] is not None or (rid in self.dead and r["expires_at"] <= self.now)
                   for rid, r in self.rows.items())

    def _took(self, got, kind):
        if got is not None:
            self.rows[int(got["id"])] = {"id": int(got["id"]), "released_at": None, "expires_at": self.now + TTL,
                                         "state": kind}

    @rule(dt=st.sampled_from((1.0, TTL / 3, TTL + 1)))
    def tick(self, dt):
        self.now += dt

    @rule(data=st.data())
    def die(self, data):
        rid = _pick(data, sorted(rid for rid, r in self.rows.items() if r["released_at"] is None and rid not in self.dead))
        if rid is not None:
            self.dead.add(rid)

    @rule(actor=ACTORS, to=st.sampled_from((ex.LOADING, ex.RESERVED)), writer=st.sampled_from(WRITERS),
          legal=st.booleans())
    def take(self, actor, to, writer, legal):
        kind = "image" if to == ex.LOADING else ""
        writer = min(ex.MOVES[(ex.FREE, to)]) if legal else writer
        if writer not in ex.MOVES[(ex.FREE, to)]:
            with pytest.raises(ex.IllegalMove):
                ex._move(self.actors[actor], None, to, writer, kind=kind, now=self.now)
            return
        got = ex._move(self.actors[actor], None, to, writer, kind=kind, now=self.now)
        assert (got is not None) == self.takes(), f"take at {self.now}: {got}, model {self.rows} dead {self.dead}"
        self._took(got, kind)
        if got is not None:
            self.seen[actor][int(got["id"])] = got

    @rule(kind=st.sampled_from(("image", "")))
    def two_take_at_once(self, kind):
        want, got = self.takes(), {}
        to, writer = (ex.LOADING, "take") if kind else (ex.RESERVED, "workqueue")

        def racer(i):
            def go(start):
                conn = ms.connect()
                try:
                    start()
                    got[i] = ex._move(conn, None, to, writer, kind=kind, now=self.now)
                finally:
                    conn.close()
            return go
        race([racer(0), racer(1)])
        won = [g for g in got.values() if g is not None]
        assert len(won) == int(want), f"two takers at {self.now}: {got}"
        for g in won:
            self._took(g, kind)

    @rule(actor=ACTORS, data=st.data())
    def read(self, actor, data):
        rid = _pick(data, sorted(self.rows))
        if rid is not None:
            self.seen[actor][rid] = item_lease.row(self.actors[actor], rid)

    @rule(actor=ACTORS, data=st.data(), to=st.sampled_from(LEASE_STATES), writer=st.sampled_from(WRITERS),
          stale=st.booleans(), legal=st.booleans())
    def move(self, actor, data, to, writer, stale, legal):
        rid = _pick(data, sorted(self.rows))
        conn = self.actors[actor]
        h = rid and ((self.seen[actor].get(rid) if stale else None) or item_lease.row(conn, rid))
        was = h and self.state(h)
        if legal:
            to, writer = _pick(data, sorted((t, w) for (f, t), ws in ex.MOVES.items() if f == was for w in ws)) or (to, writer)
        if rid is None:
            return
        if writer not in ex.MOVES.get((was, to), ()):
            with pytest.raises(ex.IllegalMove):
                ex._move(conn, h, to, writer, kind="image", now=self.now)
            return
        got = ex._move(conn, h, to, writer, kind="image", now=self.now)
        self.seen[actor][rid] = got or h
        row = self.rows[rid]
        if to == ex.FREE:
            assert got is not None
            row["released_at"] = row["released_at"] or self.now
            return
        beats = row["released_at"] is None and row["expires_at"] > self.now and row["state"] == (h["state"] or "")
        assert (got is not None) == beats, f"{writer} {was}->{to} of {rid} from {h}: {got}, model {row}"
        if beats:
            row["expires_at"], row["state"] = self.now + TTL, "image" if to == ex.LOADING else ""

    @rule(actor=ACTORS)
    def reap(self, actor):
        ex._reap(self.actors[actor])
        for rid in self.dead:
            self.rows[rid]["released_at"] = self.rows[rid]["released_at"] or self.now

    @invariant()
    def at_most_one_holder(self):
        conn = self.actors[0]
        stored = {r["id"]: r for r in (item_lease.row(conn, rid) for rid in self.rows)}
        conn.rollback()
        holders = [rid for rid, h in stored.items() if ex.state_of(h, self.now) in (ex.RESERVED, ex.LOADING, ex.LAPSED)]
        assert len(holders) <= 1, f"{len(holders)} hold the GPU at {self.now}: {[stored[r] for r in holders]}"
        for rid, row in self.rows.items():
            h = stored[rid]
            assert (h["released_at"] is None) == (row["released_at"] is None), (h, row)
            assert (float(h["expires_at"]), h["state"] or "") == (row["expires_at"], row["state"]), (h, row)


@pytest.fixture
def actors():
    conns = [ms.connect(), ms.connect()]
    yield conns
    for c in conns:
        c.close()


def _run(machine, conns, times=1):
    machine.actors = conns
    # A Postgres connect costs ten times a SQLite one, and each race opens two.
    n = max(1, int(settings.default.max_examples * times / (4 if store.backend() == store.POSTGRES else 1)))
    run_state_machine_as_test(machine, settings=settings(deadline=None, suppress_health_check=list(HealthCheck),
                                                         max_examples=n))


@pytest.mark.parametrize("machine", [Jobs, Downloads, Switches, Deploys, Pauses, Sweeps], ids=lambda m: m.__name__)
def test_a_lifecycle_refuses_illegal_moves_and_one_racer_wins(machine, actors):
    _run(machine, actors)


def test_an_adoption_chain_has_one_head_and_a_stale_writer_loses(actors):
    _run(Adoptions, actors, times=0.5)


def test_the_gpu_lease_has_at_most_one_holder_under_a_fake_clock(actors, monkeypatch):
    monkeypatch.setattr(ex, "_holder_alive", lambda h: int(h["id"]) not in GpuLease.current.dead)
    _run(GpuLease, actors, times=4)


def test_a_judge_that_read_the_jobs_before_a_resume_loses_to_it(actors):
    a, b = actors
    a.execute("DELETE FROM knob_sweeps")
    rid = sweeps._move(a, _sweep("a"), None, sweeps.OPEN, sweeps.QUEUED, queued_at=1.0)
    read = _sweep("a", rid)
    assert sweeps._move(b, dict(read), sweeps.OPEN, sweeps.OPEN, sweeps.RESUMED, jobs="[[1, 2]]") == rid
    assert sweeps._move(a, read, sweeps.OPEN, sweeps.UNINFORMATIVE, sweeps.JUDGED, settled_at=2.0) is None
    assert tuple(a.execute("SELECT outcome, jobs FROM knob_sweeps WHERE id = ?", (rid,)).fetchone()) == ("", "[[1, 2]]")


def test_a_move_from_a_stale_view_of_a_gpu_lease_loses(actors, monkeypatch):
    a, b = actors
    monkeypatch.setattr(ex, "_holder_alive", lambda h: True)
    a.execute("DELETE FROM leases")
    a.commit()
    seen = ex._move(a, None, ex.RESERVED, "workqueue", now=1000.0)
    assert ex._move(b, item_lease.row(b, seen["id"]), ex.LOADING, "own", kind="image", now=1001.0) is not None
    assert ex._move(a, seen, ex.LOADING, "own", kind="image", now=1002.0) is None
    assert ex._move(a, seen, ex.RESERVED, "workqueue", now=1002.0) is None
    assert item_lease.row(a, seen["id"])["state"] == "image"

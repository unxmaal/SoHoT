"""The knob backlog ranks by binding evidence, and every limit a funnel or fetch reason quotes is a registered knob (#1085)."""
import json
import sqlite3

import pytest

from harness import knob_backlog as kb
from harness import knobs
from tests.test_knob_merge import git

REPO = knobs.REPO
FILES = ("harness/funnel.py", "harness/fetching.py")
DISCOVER_TOP = "scripts/serve-discover.sh:DISCOVER_TOP"
DOWNLOAD_BUDGET = "scripts/serve-discover.sh:DISCOVER_BUDGET_GIB"
#: Per file, each name a reason's hole reads that resolves to no site: the limit it carries, or "" for a measured value.
CARRIES = {
    "harness/funnel.py": {"p": "", "position": "", "said": "", "skipped": "", "top": DISCOVER_TOP, "when": ""},
    "harness/fetching.py": {
        "attachment": "", "backlog": "", "budget": DOWNLOAD_BUDGET, "dep": "", "exc": "", "gap": "", "have": "",
        "lane": "", "name": "", "names": "", "needs": "", "other": "", "p.why": "", "row": "", "size": "",
        "spent": "", "spent_now": "", "status": "", "top": DISCOVER_TOP, "until": "", "what": "", "when": "", "whose": ""},
}


def _reads(rel: str) -> dict:
    """name -> the inventory sites it resolves to (empty when it resolves to none), per hole of each f-string."""
    found = set(knobs.inventory(REPO))
    out: dict[str, set] = {}
    for q in kb.quotes((REPO / rel).read_text(encoding="utf-8"), rel, REPO):
        for name, got in q.reads:
            if not got or any(s in found for s in got):
                out.setdefault(name, set()).update(s for s in got if s in found)
    return out


def _limits() -> dict:
    """(file, name) -> the sites of the limit a reason quotes there."""
    out = {}
    for rel in FILES:
        for name, sites in _reads(rel).items():
            carried = CARRIES[rel].get(name, "")
            got = sites | ({carried} if carried else set())
            if got:
                out[(rel, name)] = got
    return out


@pytest.mark.parametrize("rel", FILES)
def test_every_name_a_funnel_or_fetch_reason_quotes_resolves_to_a_site_or_is_named_here(rel):
    unresolved = {name for name, sites in _reads(rel).items() if not sites}
    assert unresolved == set(CARRIES[rel]), (f"{rel}: name what each hole carries in CARRIES; "
                                             f"new {sorted(unresolved - set(CARRIES[rel]))}, "
                                             f"gone {sorted(set(CARRIES[rel]) - unresolved)}")


def test_every_limit_a_funnel_or_fetch_reason_quotes_is_a_registered_knob():
    limits = _limits()
    assert ("harness/fetching.py", "floor") in limits and ("harness/fetching.py", "cap") in limits
    known = knobs.registered()
    loose = sorted(f"{rel}: {{{name}}} quotes {s}" for (rel, name), sites in limits.items()
                   for s in sites if s not in known)
    assert not loose, "register these in an area of harness/knobs/:\n  " + "\n  ".join(loose)


def test_the_cap_a_sweep_downloads_at_most_is_a_registered_knob():
    quoted = {key for key, sites in _limits().items() if DISCOVER_TOP in sites}
    assert ("harness/funnel.py", "top") in quoted
    assert DISCOVER_TOP in knobs.registered()


def test_a_hole_resolves_through_a_default_a_local_an_import_and_a_field(tmp_path):
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "other.py").write_text("ATTEMPTS = 3\n", encoding="utf-8")
    src = ("from harness import other\nfrom harness.other import ATTEMPTS as TRIES\nFLOOR = 5\n"
           "def plan(size, floor=FLOOR, cap=9):\n"
           "    room = FLOOR * 2\n"
           "    return f'{size} under {floor} or {cap} or {room} after {other.ATTEMPTS} or {TRIES} {len(size)}'\n"
           "class C:\n    budget = 4\n    def go(self):\n        return f'over {self.budget}'\n")
    got = [q.reads for q in kb.quotes(src, "harness/m.py", tmp_path)]
    assert got == [(("size", ()), ("floor", ("harness/m.py:FLOOR",)), ("cap", ("harness/m.py:plan(cap)",)),
                    ("room", ("harness/m.py:FLOOR",)), ("other.ATTEMPTS", ("harness/other.py:ATTEMPTS",)),
                    ("TRIES", ("harness/other.py:ATTEMPTS",)), ("size", ()), ),
                   (("self.budget", ("harness/m.py:C.budget",)),)]


def _repo(tmp_path, backlog: list[str]):
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "fixture.py").write_text(
        "FLOOR_GIB = 5\nMAX_SEEN = 2\n"
        "def plan(size, floor=FLOOR_GIB):\n"
        "    return f'{size} GiB would leave under the {floor} GiB floor'\n"
        "def seen(n):\n    return f'seen {n} of at most {MAX_SEEN} times'\n"
        "def short():\n    return f'{MAX_SEEN} GiB'\n", encoding="utf-8")
    d = tmp_path / kb.DIR
    d.mkdir(parents=True)
    (d / "harness.txt").write_text("\n".join(backlog) + "\n", encoding="utf-8")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    return tmp_path


def _store(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE verdicts (tier TEXT, outcome TEXT, detail TEXT, until TEXT, decided_at REAL)")
    conn.executemany("INSERT INTO verdicts VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    return conn


def test_backlog_sites_rank_by_the_declines_a_reason_quoting_them_wrote(tmp_path):
    root = _repo(tmp_path, ["harness/fixture.py:FLOOR_GIB", "harness/fixture.py:MAX_SEEN",
                            "harness/fixture.py:plan(other)"])
    conn = _store([
        ("fetch", "queued", "waiting on 3.0 GiB would leave under the 5 GiB floor", "", 100.0),
        ("fetch", "declined", "", "9 GiB would leave under the 5 GiB floor", 200.0),
        ("fetch", "measured", "1 GiB would leave under the 5 GiB floor", "", 300.0),
        ("inspect", "queued", "seen 4 of at most 2 times", "", 400.0),
        ("inspect", "queued", "2 GiB", "", 500.0),
    ])
    got = {r["site"]: r for r in kb.by_binding(conn, root)}
    assert [r["site"] for r in kb.by_binding(conn, root)] == [
        "harness/fixture.py:FLOOR_GIB", "harness/fixture.py:MAX_SEEN", "harness/fixture.py:plan(other)"]
    assert got["harness/fixture.py:FLOOR_GIB"]["hits"] == 2 and got["harness/fixture.py:FLOOR_GIB"]["tiers"] == {"fetch": 2}
    assert got["harness/fixture.py:MAX_SEEN"]["hits"] == 1
    assert got["harness/fixture.py:plan(other)"] ["hits"] == 0
    assert [r["hits"] for r in kb.by_binding(conn, root, since=150.0)][:2] == [1, 1]


def test_soh_knobs_backlog_ranks_from_a_store_it_only_reads(tmp_path, capsys):
    from harness import cli
    q = next(q for q in kb.all_quotes() if q.sites(set(kb.sites())) and q.pattern() is not None)
    site = sorted(q.sites(set(kb.sites())))[0]
    path = tmp_path / "discovery.db"
    conn = _store([("fetch", "declined", q.text.replace("{}", "7"), "", 1.0)])
    conn.execute(f"VACUUM INTO '{path}'")
    conn.close()
    before = path.read_bytes()
    assert cli.main(["knobs", "backlog", "--by-binding", "--store", str(path), "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["ok"] and got["added"] == kb.added() and got["sites"] == kb.sites()
    assert got["by_binding"][0]["hits"] == 1 and site in {r["site"] for r in got["by_binding"] if r["hits"]}
    assert path.read_bytes() == before

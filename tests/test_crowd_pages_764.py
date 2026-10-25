"""The crowd reads a registered number of star pages, and `soh discover-why` says where a repo fell out. #764."""
import json

import pytest

from harness import cli, github, knobs, neighbors as nb, probes

SEEDS = ("org/seed",)


class PagedAPI:
    """A GitHub whose star lists come in pages of PER_PAGE, newest first."""

    def __init__(self, starred, *, fail=()):
        self.starred = starred
        self.fail = set(fail)
        self.pages = []

    def __call__(self, path):
        head, _, query = path.partition("?")
        if head == "repos/org/seed/contributors":
            return json.dumps([{"login": u} for u in self.starred])
        if head.endswith("/following"):
            return "[]"
        if head.startswith("users/") and head.endswith("/starred"):
            login = head[len("users/"):-len("/starred")]
            page = int(dict(kv.split("=") for kv in query.split("&"))["page"])
            if (login, page) in self.fail:
                raise github.GitHubError("network")
            self.pages.append((login, page))
            rows = self.starred[login][(page - 1) * github.PER_PAGE:page * github.PER_PAGE]
            return json.dumps([{"full_name": r} for r in rows])
        if head.startswith("repos/"):
            return json.dumps({"stargazers_count": 10, "pushed_at": "2026-10-01"})
        raise github.GitHubError(f"unexpected {path}")


def stars(n, tag):
    return [f"{tag}/r{i}" for i in range(n)]


@pytest.fixture
def api():
    return PagedAPI({"a": stars(250, "a"), "b": stars(100, "b"), "c": stars(40, "c")})


def _client(api, tmp_path, **kw):
    return github.Client(cache=tmp_path / "c", runner=api, budget=kw.pop("budget", 10_000), **kw)


def test_the_crowd_reads_the_configured_pages_and_stops_at_a_short_page(api, tmp_path):
    counts, asked = nb.crowd(["a", "b", "c"], _client(api, tmp_path), pages=3)
    assert asked == 3
    assert sorted(api.pages) == [("a", 1), ("a", 2), ("a", 3), ("b", 1), ("b", 2), ("c", 1)]
    assert counts["a/r249"] == 1 and counts["b/r99"] == 1 and counts["c/r39"] == 1


def test_the_default_depth_is_the_registered_knob(api, tmp_path, monkeypatch):
    k = knobs.KNOBS["crowd_star_pages"]
    assert k.default() == nb.STAR_PAGES == 1
    assert k.unit == "pages" and tuple(k.values) == (1, 2, 3, 5, 10) and k.probe in probes.PROBES
    monkeypatch.setattr(nb, "STAR_PAGES", 2)
    nb.crowd(["a"], _client(api, tmp_path))
    assert sorted(api.pages) == [("a", 1), ("a", 2)]


def test_a_deeper_page_that_fails_keeps_the_pages_already_read(tmp_path):
    api = PagedAPI({"a": stars(250, "a")}, fail={("a", 2)})
    counts, asked = nb.crowd(["a"], _client(api, tmp_path), pages=2)
    assert asked == 1 and counts["a/r0"] == 1 and "a/r150" not in counts


def test_a_deeper_page_over_budget_keeps_the_pages_already_read(tmp_path):
    api = PagedAPI({"a": stars(250, "a"), "b": stars(10, "b")})
    counts, asked = nb.crowd(["b", "a"], _client(api, tmp_path, budget=2), pages=2)
    assert asked == 2 and counts["a/r0"] == 1 and counts["b/r0"] == 1


def test_members_the_page_cap_cuts_short_are_recorded(api, tmp_path):
    from harness import memory_store as ms
    conn = ms.connect()
    nb.crowd(["a", "b", "c"], _client(api, tmp_path), pages=1)
    rows = [dict(r) for r in conn.execute("SELECT knob, value, kept, dropped FROM limit_cuts")]
    conn.close()
    assert rows == [{"knob": "crowd_star_pages", "value": 1.0, "kept": 1, "dropped": 2}]


def _why_api():
    """Six members; one starred the repo at position 354 from their newest, one at 3."""
    lists = {f"m{i}": stars(120, f"m{i}") for i in range(4)}
    deep = stars(500, "d")
    deep[353] = "x/target"
    lists["deep"] = deep
    lists["near"] = stars(30, "n")
    lists["near"].insert(2, "x/target")
    return PagedAPI(lists)


def test_discover_why_reports_where_a_repo_fell_out(tmp_path):
    client = _client(_why_api(), tmp_path)
    got = nb.why("x/target", nb.cohort(SEEDS, client), client, depths=(1, 2, 3, 4, 5))
    assert got["crowd"] == 6 and got["positions"] == [3, 354]
    assert got["by_depth"] == {1: 1, 2: 1, 3: 1, 4: 2, 5: 2}
    assert got["sweep_pages"] == nb.STAR_PAGES and got["min_shared"] == nb.MIN_SHARED
    assert got["reached_at"] is None
    assert "falls out at the crowd" in got["verdict"] and "2 of 6" in got["verdict"]


def test_discover_why_names_the_depth_that_would_reach_a_repo(tmp_path):
    client = _client(_why_api(), tmp_path)
    got = nb.why("x/target", nb.cohort(SEEDS, client), client, depths=(1, 4), min_shared=2)
    assert got["reached_at"] == 4 and "4 pages" in got["verdict"]


def test_discover_why_reads_only_the_cache_and_writes_nothing(tmp_path):
    api = _why_api()
    live = _client(api, tmp_path)
    nb.why("x/target", nb.cohort(SEEDS, live), live, depths=(1, 2))
    sent = len(api.pages)
    cached = github.CacheOnly(cache=tmp_path / "c", runner=api)
    got = nb.why("x/target", nb.cohort(SEEDS, cached), cached, depths=(1, 2, 5))
    assert len(api.pages) == sent and cached.spent == 0
    assert got["by_depth"][2] == 1 and got["unread"] == 1


def test_discover_why_names_no_crowd_member(tmp_path, monkeypatch, capsys):
    api = _why_api()
    from harness.commands import discover_why
    monkeypatch.setattr(discover_why, "_client", lambda budget: _client(api, tmp_path, budget=budget))
    monkeypatch.setattr(nb, "DEFAULT_SEEDS", SEEDS)
    rc = cli.main(["discover-why", "x/target", "--budget", "1000", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    got = json.loads(out[out.index("{"):])
    assert got["crowd"]["positions"] == [3, 354]
    for login in api.starred:
        assert f'"{login}"' not in out and f" {login} " not in out


def test_discover_why_reads_the_store_sightings_read_only(tmp_path, monkeypatch, capsys):
    from harness import memory_store as ms
    from harness.commands import discover_why
    db = tmp_path / "s.db"
    conn = ms.connect(db)
    ms.record(conn, ms.Seen(name="x/target", source="github-crowd", kind="repo", registry=ms.GITHUB,
                            url="https://github.com/x/target", resolved="x/target"))
    conn.close()
    before = db.read_bytes()
    api = _why_api()
    monkeypatch.setattr(discover_why, "_client", lambda budget: _client(api, tmp_path, budget=budget))
    monkeypatch.setattr(nb, "DEFAULT_SEEDS", SEEDS)
    assert cli.main(["discover-why", "x/target", "--db", str(db), "--budget", "1000", "--json"]) == 0
    out = capsys.readouterr().out
    got = json.loads(out[out.index("{"):])["store"]
    assert got["found"] and got["sightings"] == {"github-crowd": 1} and got["registry"] == ms.GITHUB
    assert db.read_bytes() == before

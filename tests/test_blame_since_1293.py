"""#1293: `soh blame sample --since` draws only verdicts decided after a date; the report names its window and compares."""
import calendar
import json

import pytest

from harness import blame_audit as ba, cli
from harness import memory_store as ms

#: (tier, outcome, reason, how many) decided before the window, and after it.
BEFORE = [("screen", "declined", "runtime", 4), ("inspect", "declined", "machine", 20)]
AFTER = [("screen", "declined", "runtime", 3), ("adopt", "declined", "candidate", 2),
         ("inspect", "declined", "machine", 30), ("fetch", "declined", "candidate", 9)]
EDGE = calendar.timegm((2026, 10, 18, 0, 0, 0))
UNTIL = {"runtime": "version:mlx-lm>0.32.0", "machine": "ceiling_gb:>70"}


def _decided(conn, prefix, strata, when):
    for tier, outcome, reason, n in strata:
        for i in range(n):
            name = f"org/{prefix}-{tier}-{reason}-{i}"
            ms.record(conn, ms.Seen(name=name, source="s", kind="candidate", registry=ms.HUGGINGFACE,
                                    lane="code", resolved=name))
            ms.decide(conn, name, "queued", tier="inspect", detail="fits")
            ms.decide(conn, name, outcome, tier=tier, reason=reason, until=UNTIL.get(reason, ""))
            vid = conn.execute("SELECT state_verdict_id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
            conn.execute("UPDATE verdicts SET decided_at = ? WHERE id = ?", (when + i, vid))
    conn.commit()


@pytest.fixture
def store():
    conn = ms.connect()
    _decided(conn, "old", BEFORE, EDGE - 86400)
    _decided(conn, "new", AFTER, EDGE + 3600)
    # Exactly on the edge is not after it.
    _decided(conn, "edge", [("screen", "declined", "runtime", 1)], EDGE)
    yield conn
    conn.close()


def test_a_blame_sample_since_a_date_draws_only_verdicts_decided_after_it(store):
    rows, sizes = ba.sample(store, 1293, since=ba.since("2026-10-18"))
    assert sizes == {"adopt/candidate": 2, "fetch/candidate": 9, "inspect/machine": 30, "screen/runtime": 3}
    assert rows and all(r["name"].startswith("org/new-") for r in rows), [r["name"] for r in rows]
    assert all(r["decided_at"] > EDGE for r in rows)
    whole, _ = ba.sample(store, 1293)
    assert any(r["name"].startswith("org/old-") for r in whole)


def test_since_takes_a_date_or_a_utc_time_and_refuses_anything_else():
    assert ba.since("2026-10-18") == EDGE
    assert ba.since("2026-10-18 21:00") == EDGE + 21 * 3600
    with pytest.raises(ValueError):
        ba.since("last tuesday")


def test_the_key_records_the_window_and_each_rows_decision_time(store, tmp_path):
    got = ba.build(store, 1293, since=ba.since("2026-10-18"))
    assert got["header"]["since"] == "2026-10-18 00:00 UTC"
    ba.write(got, tmp_path)
    header, key = ba.read_csv(tmp_path / "key.csv")
    assert header["since"] == "2026-10-18 00:00 UTC"
    assert all(k["decided_at"] > "2026-10-18" for k in key if k["role"] == "sample"), key


def _label_all(path, key, label_of):
    with path.open("w", encoding="utf-8") as f:
        f.write("verdict_id,label,evidence\n")
        for k in key:
            f.write(f"{k['verdict_id']},{label_of(k)},sql\n")


def test_the_blame_report_names_the_window_it_covers(store, tmp_path):
    got = ba.build(store, 1293, since=ba.since("2026-10-18"))
    ba.write(got, tmp_path)
    _label_all(tmp_path / "labels.csv", got["key"], lambda k: ba.MODEL)
    text = ba.report_text(ba.report(tmp_path / "key.csv", tmp_path / "labels.csv"))
    assert "window: state verdicts decided after 2026-10-18 00:00 UTC" in text
    whole = tmp_path / "whole"
    ba.write(ba.build(store, 1293), whole)
    _, key = ba.read_csv(whole / "key.csv")
    _label_all(whole / "labels.csv", key, lambda k: ba.MODEL)
    assert "window: every terminal state verdict" in ba.report_text(ba.report(whole / "key.csv", whole / "labels.csv"))


def _audit(store, out, since, harness_strata):
    got = ba.build(store, 1293, since=since)
    ba.write(got, out)
    _label_all(out / "labels.csv", got["key"],
               lambda k: ba.HARNESS if k["stratum"] in harness_strata else ba.MODEL)
    return ba.report(out / "key.csv", out / "labels.csv")


def test_the_blame_report_against_an_earlier_audit_says_whether_the_share_moved(store, tmp_path):
    old = _audit(store, tmp_path / "old", None, {"screen/runtime", "inspect/machine"})
    new = _audit(store, tmp_path / "new", ba.since("2026-10-18"), set())
    cmp = ba.compare(new, old)
    assert cmp["moved"] is True and cmp["population"]["new"][2] < cmp["population"]["old"][1], cmp
    by = {r["stratum"]: r for r in cmp["strata"]}
    assert by["screen/runtime"]["old"]["share"] == 1.0 and by["screen/runtime"]["new"]["share"] == 0.0
    assert by["adopt/candidate"]["old"]["share"] == 0.0
    text = ba.compare_text(cmp)
    assert "moved: yes" in text and "screen/runtime" in text
    same = ba.compare(old, old)
    assert same["moved"] is False and "moved: no" in ba.compare_text(same)
    # A lower point estimate whose interval still reaches the earlier one has not moved.
    lower = {"header": {"since": "2026-10-18 00:00 UTC"}, "strata": [], "population": [0.2, 0.1, 0.3]}
    earlier = {"header": {}, "strata": [], "population": [0.4, 0.27, 0.54]}
    assert ba.compare(lower, earlier)["moved"] is False
    assert ba.compare({**lower, "population": [0.2, 0.1, 0.26]}, earlier)["moved"] is True


def test_soh_blame_since_and_against_on_the_command_line(store, tmp_path, capsys):
    store.close()
    old, new = tmp_path / "old", tmp_path / "new"
    assert cli.main(["blame", "sample", "--seed", "918", "--dir", str(old), "--json"]) == 0
    capsys.readouterr()
    assert cli.main(["blame", "sample", "--seed", "1293", "--since", "2026-10-18", "--dir", str(new), "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["header"]["since"] == "2026-10-18 00:00 UTC"
    for d in (old, new):
        _, key = ba.read_csv(d / "key.csv")
        _label_all(d / "labels.csv", key, lambda k: ba.MODEL)
    assert cli.main(["blame", "report", "--dir", str(new), "--against", str(old)]) == 0
    out = capsys.readouterr().out
    assert "window: state verdicts decided after 2026-10-18 00:00 UTC" in out and "moved: no" in out
    assert cli.main(["blame", "sample", "--since", "soon", "--dir", str(new)]) != 0

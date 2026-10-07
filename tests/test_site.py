"""The public site: a front page, the lane report and the benchmarks, from the exports. #561."""
import copy
import json
import re
import shlex
from pathlib import Path

import pytest

from harness import lanes, privacy, publish, site

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "site"
PAGES = ("index.html", "reports/index.html", "benchmarks/index.html")
NOW = 1.7598e9
USER = "patq"  # privacy-ok: a planted username the scan must catch


def _machines():
    return publish.load(FIXTURES)


def _second(doc):
    other = copy.deepcopy(doc)
    other["machine"].update(label="RTX 4070 (Linux)", slug="rtx-4070-linux",
                            os="Linux 6.8", arch="x86_64")
    other["generated_at"] = "2026-10-07T08:00:00Z"
    return other


def _stat(page: str, key: str) -> str:
    m = re.search(rf'data-stat="{key}".*?<b class="num">([^<]*)</b>', page, re.S)
    assert m, f"no stat {key}"
    return m.group(1)


def _workflow_step(verb: str) -> list[str]:
    wf = (ROOT / ".github" / "workflows" / publish.WORKFLOW).read_text(encoding="utf-8")
    line = next(l for l in wf.splitlines() if f"python -m {verb}" in l)
    words = shlex.split(line.split("run:", 1)[-1])
    return words[words.index(verb) + 1:]


def test_render_writes_the_front_page_the_report_and_the_benchmarks(tmp_path):
    out = tmp_path / "site"
    assert publish.main(["render", "--data", str(FIXTURES), "--out", str(out)]) == 0
    for rel in PAGES:
        assert (out / rel).is_file(), rel
    assert (out / "reports" / "index.html").read_text(encoding="utf-8").count(
        "<section id=") == 1


def test_the_front_page_links_the_report_and_the_benchmarks():
    pages = site.render(_machines(), now=NOW)
    front = pages["index.html"]
    assert 'href="reports/"' in front and 'href="benchmarks/"' in front
    for rel in ("reports/index.html", "benchmarks/index.html"):
        assert 'href="../"' in pages[rel]


def test_a_stat_on_the_front_page_changes_when_the_export_changes():
    machines = _machines()
    before = site.render(machines, now=NOW)["index.html"]
    changed = copy.deepcopy(machines)
    for lane in changed[0]["lanes"]:
        lane["adopted"] = True
        lane["comparison"] = lane["comparison"] + [dict(lane["comparison"][0], candidate="x")] \
            if lane["comparison"] else [{"candidate": "x", "pass_rate": 1.0}]
    changed[0]["generated_at"] = "2026-11-02T00:00:00Z"
    after = site.render(changed, now=NOW)["index.html"]
    for key in ("adopted", "compared", "latest"):
        assert _stat(before, key) != _stat(after, key), key
    assert _stat(site.render(machines + [_second(machines[0])], now=NOW)["index.html"],
                 "machines") != _stat(before, "machines")


def test_every_stat_carries_the_machine_and_the_date_it_came_from():
    machines = _machines()
    label = machines[0]["machine"]["label"]
    for s in site.stats(machines):
        assert label in s["where"], s
        assert re.search(r"\d{4}-\d{2}-\d{2}", s["where"]), s


def test_no_stat_is_claimed_when_nothing_has_published():
    front = site.render([], now=NOW)["index.html"]
    assert "No machine has published yet." in front
    for s in site.stats([]):
        assert s["value"] in ("0", "--")


def test_the_lanes_on_the_front_page_come_from_the_exports_and_the_lane_table():
    machines = _machines()
    machines[0]["lanes"].append({"lane": "holo", "serves": "h", "comparison": []})
    front = site.render(machines, now=NOW)["index.html"]
    for lane in lanes.ALL + ("holo",):
        assert f">{lane}<" in front, lane


def test_benchmarks_have_each_lanes_latest_table_with_its_machine_and_date():
    machines = _machines()
    machines.append(_second(machines[0]))
    bench = site.render(machines, now=NOW)["benchmarks/index.html"]
    for lane in machines[0]["lanes"]:
        if not lane["comparison"]:
            continue
        assert f'id="lane-{lane["lane"]}"' in bench
        for d in machines:
            caption = f'{d["machine"]["label"]} &middot; run {lane["last_run_at"][:10]}'
            assert caption in bench, caption
        for row in lane["comparison"]:
            assert row["candidate"] in bench
    for head in ("candidate", "pass", "median s", "first s", "peak GB", "metrics"):
        assert f"<th>{head}</th>" in bench


def test_every_page_is_self_contained_and_reads_as_one_site():
    for rel, page in site.render(_machines(), now=NOW).items():
        assert "<script" not in page, rel
        assert 'name="viewport"' in page, rel
        assert "prefers-color-scheme: dark" in page, rel
        assert "—" not in page, rel
        for url in re.findall(r'<link[^>]+href="([^"]+)"', page):
            assert url.startswith(("https://fonts.googleapis.com/",
                                   "https://fonts.gstatic.com")), (rel, url)
        assert privacy.scan(page, rel) == [], rel
        assert re.search(r'class="win[ "]', page), rel


def test_the_workflow_privacy_scan_covers_every_file_under_site(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    render = _workflow_step("harness.publish")
    render[render.index("--data") + 1] = str(FIXTURES)
    assert publish.main(render) == 0
    scan = _workflow_step("harness.privacy")
    assert privacy.main(scan) == 0
    bench = tmp_path / "site" / "benchmarks" / "index.html"
    bench.write_text(bench.read_text(encoding="utf-8")
                     + f"<p>/Users/{USER}/runs</p>", encoding="utf-8")  # privacy-ok
    assert privacy.main(scan) == 1

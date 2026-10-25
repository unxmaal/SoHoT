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
PAGES = ("index.html", "reports/index.html", "benchmarks/index.html", "trends/index.html")
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
    for rel in ("reports/index.html", "benchmarks/index.html", "trends/index.html"):
        assert 'href="../"' in pages[rel] and 'href="../trends/"' in pages[rel]


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


def test_each_feature_card_carries_its_own_text_under_its_title():
    front = site.render(_machines(), now=NOW)["index.html"]
    cards = dict(re.findall(r'<h2>([^<]+)</h2></div><div class="body">(.*?)</div></div>',
                            front, re.S))
    assert "paired test" in cards["The paired adopt gate"]
    assert '<li class="chip">code</li>' in cards["Lanes"]
    assert "sohot-code" in cards["One gateway, stable names"]


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


def test_a_scan_of_a_directory_with_nothing_in_it_is_refused_not_passed(tmp_path):
    (tmp_path / "site").mkdir()
    with pytest.raises(FileNotFoundError):
        privacy.main(["--files", str(tmp_path / "site")])
    with pytest.raises(FileNotFoundError):
        privacy.main(["--files", str(tmp_path / "nowhere")])


def _outside_motion_query(css: str) -> str:
    out, i, key = [], 0, "@media (prefers-reduced-motion: no-preference)"
    while (j := css.find(key, i)) >= 0:
        out.append(css[i:j])
        depth, k = 0, css.index("{", j)
        while True:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
            if depth == 0:
                break
        i = k
    return "".join(out) + css[i:]


def test_the_ticker_says_what_each_adopted_lane_serves_and_on_which_machine():
    machines = _machines()
    front = site.render(machines, now=NOW)["index.html"]
    ticker = re.search(r'<div class="ticker".*?</div>', front, re.S).group(0)
    label = machines[0]["machine"]["label"]
    for lane in machines[0]["lanes"]:
        if lane.get("adopted"):
            assert f"{lane['lane']} serves {lane['serves']} on {label}" in ticker
    assert machines[0]["generated_at"][:10] in ticker


def test_all_motion_is_off_for_people_who_ask_for_less():
    rest = _outside_motion_query(site.CSS)
    assert "@media (prefers-reduced-motion: no-preference)" in site.CSS
    assert "animation" not in rest and "@keyframes" not in rest


def _rules(css: str, selector: str) -> list[str]:
    return [m.group(1) for m in re.finditer(rf"(?:^|[}}\s]){re.escape(selector)}\s*\{{([^}}]*)\}}", css)]


def _window(page: str, title: str) -> str:
    m = re.search(rf'<h2>{re.escape(title)}</h2></div><div class="body">(.*?)</div></(?:div|section)>',
                  page, re.S)
    assert m, f"no window {title}"
    return m.group(1)


def _text(fragment: str) -> str:
    import html
    spaced = re.sub(r"</?(?:span|li|p|div|br)\b[^>]*>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", spaced)))


def test_the_intro_names_every_lane_by_what_it_does():
    assert set(site.LANE_WORDS) == set(lanes.ALL)
    intro = _text(_window(site.render(_machines(), now=NOW)["index.html"], "What is SoHoT?"))
    assert f"{len(lanes.ALL)} jobs" in intro
    for lane in lanes.ALL:
        assert site.LANE_WORDS[lane] in intro, lane


def test_the_ticker_accounts_for_every_lane_with_no_adopted_winner():
    machines = _machines()
    front = site.render(machines, now=NOW)["index.html"]
    ticker = _text(re.search(r'<div class="ticker".*?</div></div>', front, re.S).group(0))
    doc = machines[0]
    exported = {l["lane"] for l in doc["lanes"]}
    idle = [l["lane"] for l in doc["lanes"] if not l.get("adopted")]
    assert idle, "the fixture needs a lane with no winner"
    for lane in site.lane_names(machines):
        if lane in idle or lane not in exported:
            assert re.search(rf"\b{lane}\b", ticker), lane
    assert "starting default" in ticker
    everything = copy.deepcopy(machines)
    for l in everything[0]["lanes"]:
        l["adopted"] = True
    everything[0]["lanes"] += [{"lane": n, "adopted": True, "serves": "x", "comparison": []}
                               for n in lanes.ALL if n not in exported]
    assert "starting default" not in site.render(everything, now=NOW)["index.html"]


def test_the_stats_say_what_they_count():
    machines = _machines()
    by = {s["key"]: s for s in site.stats(machines)}
    compared = [l for l in machines[0]["lanes"] if l.get("comparison")]
    assert by["compared"]["value"] == str(sum(len(l["comparison"]) for l in compared))
    assert f"summed over {len(compared)} lanes" in by["compared"]["label"]
    assert f"of {len(site.lane_names(machines))}" in by["adopted"]["label"]


def _quick_start_lines() -> list[str]:
    import html
    win = _window(site.render(_machines(), now=NOW)["index.html"], "Quick start")
    blocks = re.findall(r"<pre><code>(.*?)</code></pre>", win, re.S)
    return [re.split(r"\s+#\s", line)[0].strip()
            for b in blocks for line in html.unescape(b).splitlines()]


def test_every_quick_start_script_exists():
    scripts = [m for line in _quick_start_lines() for m in re.findall(r"\./scripts/([\w.-]+)", line)]
    assert {"launchd.sh", "serve-gateway.sh", "serve-eval.sh", "serve-tts.sh"} <= set(scripts)
    for name in scripts:
        assert (ROOT / "scripts" / name).is_file(), name


def test_every_soh_command_in_the_quick_start_parses():
    from harness import cli
    commands = [c for line in _quick_start_lines()
                for c in ([line] if line.startswith("soh ") else re.findall(r"\$\((soh [^)]*)\)", line))]
    assert any(c.startswith("soh gateway key") for c in commands), commands
    assert any(c.startswith("soh lane-feed") for c in commands), commands
    for c in commands:
        argv = shlex.split(c)[1:]
        try:
            cli.build_parser().parse_args(argv)
        except SystemExit as exc:
            raise AssertionError(f"soh {argv} does not parse") from exc


def test_the_mcp_tools_on_the_page_are_the_servers_own():
    mcp_server = pytest.importorskip("harness.mcp_server",
                                     reason="needs the `mcp` group: uv run --group mcp pytest")
    served = {t.name for t in mcp_server.SERVER._tool_manager.list_tools()}
    assert set(site.mcp_tools()) == served
    card = _text(_window(site.render(_machines(), now=NOW)["index.html"], "Other tools can use it"))
    for name in served:
        assert name in card, name
    assert "soh://lanes/{lane}" in card


def test_the_numbers_in_the_prose_are_the_module_constants():
    from harness import adopt, gateway_switch
    from harness.memory_store import transitions
    front = _text(site.render(_machines(), now=NOW)["index.html"])
    assert f"at least {adopt.MIN_VOTES} votes" in front
    assert f"after {transitions.RETEST_AFTER_SECONDS / 86400:.0f} days" in front
    assert f"up to {transitions.RETESTS} times" in front
    assert f"after {gateway_switch.MAX_WAIT_S / 60:.0f} minutes" in front
    assert f"idle for {gateway_switch.IDLE_S:.0f} seconds" in front
    assert re.search(r'DISCOVER_BUDGET_GIB:-(\d+)', (ROOT / "scripts" / "serve-discover.sh")
                     .read_text(encoding="utf-8")).group(1) + " GiB" in front


def test_a_changed_constant_changes_the_page(monkeypatch):
    from harness import adopt
    monkeypatch.setattr(adopt, "MIN_VOTES", 77)
    read, default = site.constant, site.shell_default
    monkeypatch.setattr(site, "constant", lambda rel, name: 3000.0 if name == "MAX_WAIT_S" else read(rel, name))
    monkeypatch.setattr(site, "shell_default", lambda rel, var: "99" if var == "DISCOVER_BUDGET_GIB"
                        else "4123" if var == "GATEWAY_PORT" else default(rel, var))
    front = _text(site.render(_machines(), now=NOW)["index.html"])
    assert "at least 77 votes" in front
    assert "after 50 minutes" in front and "99 GiB" in front and "<host>:4123" in front


def test_constants_read_from_source_match_the_imported_modules():
    from harness import gateway_switch
    for name in ("IDLE_S", "MAX_WAIT_S"):
        assert site.constant("harness/gateway_switch.py", name) == getattr(gateway_switch, name)
    with pytest.raises(KeyError):
        site.constant("harness/gateway_switch.py", "NO_SUCH_NAME")


def test_the_front_page_renders_without_the_projects_dependencies():
    import subprocess
    import sys
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from harness import publish, site; "
            "print(len(site.front(publish.load(sys.argv[2]))))")
    got = subprocess.run([sys.executable, "-S", "-c", code, str(ROOT), str(FIXTURES)],
                         capture_output=True, text=True, timeout=120)
    assert got.returncode == 0, got.stderr[-2000:]


def test_the_ticker_is_one_line_with_or_without_motion():
    css = site.CSS
    reduce = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    assert not re.search(r"white-space\s*:\s*normal", reduce), "reduced motion wraps the ticker"
    track = " ".join(_rules(css, ".ticker .tape"))
    assert re.search(r"white-space\s*:\s*nowrap", track), "the ticker track can wrap"
    ticker = " ".join(_rules(css, ".ticker"))
    assert re.search(r"overflow\s*:\s*hidden", ticker), "a static ticker is not clipped"

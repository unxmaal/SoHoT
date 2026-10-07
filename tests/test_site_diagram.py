"""The front page's "How it works" diagram, drawn from the Archify model. #584."""
import copy
import html
import json
import re
from pathlib import Path

from harness import privacy, publish, repo, site

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "site"
NOW = 1.7598e9
BLOB = f"{site.REPO_URL}/blob/"


def _model():
    return json.loads(site.MODEL.read_text(encoding="utf-8"))


def _front(model=None):
    return site.front(publish.load(FIXTURES), now=NOW, model=model)


def _diagram_window(page: str) -> str:
    m = re.search(r'<div id="how-it-works" class="win[^"]*">.*?</svg></div></div>', page, re.S)
    assert m, "no How it works window"
    return m.group(0)


def test_the_diagram_window_sits_between_the_hero_and_what_is_sohot():
    page = _front()
    hero = page.index('class="win butter hero"')
    how = page.index('id="how-it-works"')
    what = page.index("<h2>What is SoHoT?</h2>")
    assert hero < how < what
    assert "<h2>How it works</h2>" in _diagram_window(page)


def test_every_node_label_in_the_model_is_drawn_in_both_layouts():
    win = _diagram_window(_front())
    for layout in ("wide", "tall"):
        svg = re.search(rf'<svg class="flow {layout}".*?</svg>', win, re.S)
        assert svg, layout
        text = html.unescape(re.sub(r"<[^>]+>", " ", svg.group(0)))
        flat = " ".join(text.split())
        for node in _model()["nodes"]:
            assert node["label"] in flat, (layout, node["label"])


def test_the_drawing_changes_when_the_model_changes():
    model = _model()
    model["nodes"][0]["label"] = "Carrier pigeons"
    assert "Carrier pigeons" in _diagram_window(_front(model))
    assert "Carrier pigeons" not in _diagram_window(_front())


def test_every_edge_in_the_model_is_drawn_in_both_layouts():
    win = _diagram_window(_front())
    edges = {e["id"] for e in _model()["edges"]}
    for layout in ("wide", "tall"):
        svg = re.search(rf'<svg class="flow {layout}".*?</svg>', win, re.S).group(0)
        assert set(re.findall(r'data-edge="([^"]+)"', svg)) == edges, layout


def test_every_link_in_the_diagram_is_a_github_blob_at_the_pinned_commit():
    model = _model()
    rev = model["meta"]["repository"]["revision"]
    links = re.findall(r'href="([^"]+)"', _diagram_window(_front()))
    assert len(links) >= len(model["nodes"])
    for url in links:
        assert url.startswith(f"{BLOB}{rev}/"), url
        assert "/Users/" not in url and "file:" not in url and "localhost" not in url, url


def test_a_node_with_a_local_path_is_refused_not_drawn():
    model = copy.deepcopy(_model())
    model["nodes"][0]["sources"][0]["path"] = "/home/someone/feeds.py"  # privacy-ok
    try:
        site.diagram(model)
    except ValueError:
        return
    raise AssertionError("an absolute source path was drawn as a link")


def test_a_model_pointing_at_another_repository_is_refused():
    model = copy.deepcopy(_model())
    model["meta"]["repository"]["url"] = "https://example.com/elsewhere"
    try:
        site.diagram(model)
    except ValueError:
        return
    raise AssertionError("a non-GitHub repository was drawn as links")


def test_the_model_and_the_rendered_site_pass_the_privacy_scan():
    assert privacy.scan(site.MODEL.read_text(encoding="utf-8"), "model") == []
    for rel, page in site.render(publish.load(FIXTURES), now=NOW).items():
        assert privacy.scan(page, rel) == [], rel


def test_the_model_is_not_stale_every_cited_file_and_line_exists():
    model = _model()
    assert model["meta"]["repository"]["url"] == site.REPO_URL
    assert re.fullmatch(r"[0-9a-f]{40}", model["meta"]["repository"]["revision"])
    shipped = {p.relative_to(ROOT).as_posix() for p in repo.publishable(ROOT)}
    for node in model["nodes"]:
        assert node.get("sources"), node["id"]
        for src in node["sources"]:
            assert src["path"] in shipped, (node["id"], src["path"])
            lines = (ROOT / src["path"]).read_text(encoding="utf-8").count("\n") + 1
            assert src.get("end_line", src["line"]) <= lines, (node["id"], src)


def test_the_diagram_reflows_for_a_phone_and_follows_the_theme():
    css = site.CSS
    assert re.search(r"@media \(max-width:\s*\d+px\)\s*\{[^}]*\.flow\.wide\s*\{\s*display:\s*none",
                     css), "the wide layout is not hidden on a phone"
    win = _diagram_window(_front())
    assert "#" not in "".join(re.findall(r'(?:fill|stroke)="([^"]+)"', win)), \
        "a hard-coded colour ignores the dark scheme"
    wide = re.search(r'<svg class="flow wide"[^>]*viewBox="0 0 (\d+) ', win).group(1)
    tall = re.search(r'<svg class="flow tall"[^>]*viewBox="0 0 (\d+) ', win).group(1)
    assert int(tall) <= 360 < int(wide)

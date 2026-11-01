"""The web lane's `structure` assertion, read from the parsed page, never by a judge. #603."""
import pytest
import yaml

from evals import core
from harness.checks import html

PAGE = """<!doctype html>
<html><head><title>Harbor stock</title></head>
<body>
<h1>Harbor stock</h1>
<nav><a href="#counts">Counts</a> <a href="#order">Order form</a></nav>
<section id="counts"><h2>Counts</h2>
<table><caption>Crates on hand</caption>
<thead><tr><th>Item</th><th>Count</th></tr></thead>
<tbody><tr><td>rope</td><td>12</td></tr><tr><td>sail</td><td> 7 </td></tr>
<tr><td>Total</td><td>19</td></tr></tbody></table>
<ol><li>Unload <ul><li>bow</li><li>stern</li></ul></li><li>Count</li></ol>
<dl><dt>rope</dt><dd>hemp line</dd></dl>
<article><h2>North pier</h2><p>Open at dawn.</p></article>
</section>
<section id="order"><h2>Order form</h2>
<form><label for="q">Quantity</label><input id="q" name="quantity" type="number" required>
<label>Notes <textarea name="notes"></textarea></label>
<button type="submit">Send order</button></form>
</section>
</body></html>"""

SPEC = {
    "title": "Harbor stock",
    "headings": [[1, "Harbor stock"], [2, "Counts"], [2, "North pier"], [2, "Order form"]],
    "tables": [{"caption": "Crates on hand", "head": ["Item", "Count"],
                "rows": [["rope", "12"], ["sail", "7"], ["Total", "19"]]}],
    "nav": [["Counts", "#counts"], ["Order form", "#order"]],
    "sections": {"counts": "Counts", "order": "Order form"},
    "lists": [{"ordered": True, "items": [["Unload", ["bow", "stern"]], "Count"]}],
    "dl": [["rope", "hemp line"]],
    "articles": [["North pier", "Open at dawn."]],
    "form": {"fields": [{"label": "Quantity", "name": "quantity", "type": "number", "required": True},
                        {"label": "Notes", "name": "notes", "type": "textarea", "required": False}],
             "submit": "Send order"},
    "self_contained": True,
}


def test_a_page_with_every_asserted_property_passes_the_structure_check():
    assert html.structure(PAGE, SPEC) == ""


@pytest.mark.parametrize("key,broken,said", [
    ("title", "Harbour stock", "title"),
    ("headings", [[1, "Harbor stock"], [2, "Order form"], [2, "Counts"], [2, "North pier"]], "headings"),
    ("tables", [{"caption": "Crates on hand", "head": ["Item", "Count"],
                 "rows": [["sail", "7"], ["rope", "12"], ["Total", "19"]]}], "row 1"),
    ("tables", [{"caption": "Crates on hand", "head": ["Item", "Count"],
                 "rows": [["rope", "12"], ["sail", "7"], ["Total", "20"]]}], "row 3"),
    ("tables", [{"caption": "Crates in hold", "head": ["Item"], "rows": []}], "no table captioned"),
    ("nav", [["Counts", "#counts"], ["Order", "#order"]], "nav"),
    ("sections", {"counts": "Counts", "missing": "Gone"}, "missing"),
    ("lists", [{"ordered": True, "items": [["Unload", ["stern", "bow"]], "Count"]}], "list"),
    ("lists", [{"ordered": False, "items": [["Unload", ["bow", "stern"]], "Count"]}], "list"),
    ("dl", [["rope", "manila line"]], "definition"),
    ("articles", [["North pier", "Open at dawn."], ["South pier", "Closed."]], "article"),
    ("form", {"fields": [{"label": "Quantity", "name": "quantity", "type": "text", "required": True}],
              "submit": "Send order"}, "quantity"),
    ("form", {"fields": [{"label": "Notes", "name": "notes", "type": "textarea", "required": True}],
              "submit": "Send order"}, "required"),
    ("form", {"fields": [{"label": "How many", "name": "quantity", "type": "number", "required": True}],
              "submit": "Send order"}, "label"),
    ("form", {"fields": [], "submit": "Submit"}, "submit"),
])
def test_one_broken_asserted_property_is_named(key, broken, said):
    missed = html.structure(PAGE, {**SPEC, key: broken})
    assert missed and said in missed


def test_a_page_loading_a_remote_script_is_not_self_contained():
    page = PAGE.replace("</head>", '<script src="https://cdn.example.org/x.js"></script></head>')
    assert "self-contained" in html.structure(page, {"self_contained": True})
    linked = PAGE.replace("<h1>", '<a href="https://example.org/">site</a><h1>')
    assert html.structure(linked, {"self_contained": True}) == ""
    for tag in ('<link rel="stylesheet" href="//fonts.example.org/a.css">', '<input type="image" src="http://x.org/b.png">',
                '<track src="https://x.org/c.vtt">', '<style>@import "https://x.org/d.css";</style>'):
        assert "self-contained" in html.structure(PAGE.replace("<h1>", tag + "<h1>"), {"self_contained": True}), tag


def test_a_label_wrapping_its_control_and_a_submit_input_both_count():
    page = ('<html><body><form><label>Email <input name="email" type="email"></label>'
            '<input type="submit" value="Join"></form></body></html>')
    spec = {"form": {"fields": [{"label": "Email", "name": "email", "type": "email", "required": False}],
                     "submit": "Join"}}
    assert html.structure(page, spec) == ""


def test_an_unknown_structure_key_is_refused():
    with pytest.raises(ValueError, match="colour"):
        html.validate_structure({"colour": "red"})


def _case(tmp_path, structure):
    raw = {"id": "web-x", "modality": "web", "prompt": "a page", "assert": {"structure": structure}}
    path = tmp_path / "web-x.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_a_web_case_with_an_unknown_structure_key_is_refused_at_load(tmp_path):
    with pytest.raises(ValueError, match="colour"):
        core.load_case(_case(tmp_path, {"colour": "red"}))


def test_a_web_case_misses_its_structure_before_any_browser_renders_it(tmp_path, monkeypatch):
    case = core.load_case(_case(tmp_path, {"title": "Other"}))
    monkeypatch.setattr(core.render_check, "check_html",
                        lambda *a, **k: pytest.fail("rendered a page that missed its structure"))
    r = core.CHECKERS["web"](PAGE, case)
    assert not r.ok and "title" in r.reason

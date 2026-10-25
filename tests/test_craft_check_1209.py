"""The craft exam's checker: requirements over a normalized document, each named, each pass or fail (#1209)."""
from __future__ import annotations

import pytest

from evals import craft_check as cc


def box(id_, name, x, y, w=160, h=80, parent="g", fill="#ffffff"):
    return {"id": id_, "type": "rect", "name": name, "parent": parent, "x": x, "y": y, "w": w, "h": h, "fill": fill}


def doc():
    return [
        {"id": "g", "type": "group", "name": "Pipeline", "parent": None, "x": 40, "y": 100, "w": 560, "h": 80},
        box("a", "Box A", 40, 100), box("b", "Box B", 240, 100), box("c", "Box C", 440, 100),
        {"id": "ta", "type": "text", "name": "Label A", "parent": "g", "text": "Ingest",
         "x": 60, "y": 125, "w": 80, "h": 24, "font_size": 20},
        {"id": "l1", "type": "line", "name": "A to B", "parent": "g", "points": [[200, 140], [240, 140]],
         "x": 200, "y": 140, "w": 40, "h": 0},
    ]


REQS = [
    {"id": "three-boxes", "count": {"type": "rect"}, "equals": 3},
    {"id": "box-a-size", "node": {"name": "Box A"}, "expect": {"type": "rect", "w": 160, "h": 80, "fill": "#FFFFFF"}},
    {"id": "label-a", "node": {"name": "Label A"}, "expect": {"text": "Ingest", "font_size": 20}},
    {"id": "tops-aligned", "aligned": {"names": ["Box A", "Box B", "Box C"], "edge": "top"}},
    {"id": "evenly-spaced", "distributed": {"names": ["Box A", "Box B", "Box C"], "axis": "x"}},
    {"id": "grouped", "grouped": {"group": "Pipeline", "members": ["Box A", "Box B", "Box C"]}},
    {"id": "a-to-b", "connects": {"line": "A to B", "from": "Box A", "to": "Box B"}},
    {"id": "label-in-box", "inside": {"inner": "Label A", "outer": "Box A"}},
]


def test_a_document_meeting_every_requirement_passes_each_by_name():
    got = cc.check(REQS, doc(), tolerance=1.0)
    assert got["passed"] and got["met"] == got["total"] == len(REQS)
    assert [r["id"] for r in got["requirements"]] == [r["id"] for r in REQS]


def test_an_empty_document_fails_every_requirement():
    got = cc.check(REQS, [], tolerance=1.0)
    assert not got["passed"] and got["met"] == 0


def test_one_wrong_label_fails_only_that_requirement():
    nodes = doc()
    nodes[4]["text"] = "Ingress"
    got = cc.check(REQS, nodes, tolerance=1.0)
    assert not got["passed"]
    assert [r["id"] for r in got["requirements"] if not r["passed"]] == ["label-a"]
    assert "Ingress" in next(r for r in got["requirements"] if r["id"] == "label-a")["detail"]


def test_one_box_out_of_alignment_fails_alignment():
    nodes = doc()
    nodes[2]["y"] = 112
    got = cc.check(REQS, nodes, tolerance=1.0)
    failed = {r["id"] for r in got["requirements"] if not r["passed"]}
    assert "tops-aligned" in failed and "box-a-size" not in failed


def test_geometry_inside_the_tolerance_passes_and_outside_fails():
    nodes = doc()
    nodes[2]["y"] = 100.8
    assert cc.check(REQS[3:4], nodes, tolerance=1.0)["passed"]
    nodes[2]["y"] = 101.5
    assert not cc.check(REQS[3:4], nodes, tolerance=1.0)["passed"]


def test_a_size_off_by_more_than_the_tolerance_fails_the_node():
    nodes = doc()
    nodes[1]["w"] = 162
    got = cc.check(REQS[1:2], nodes, tolerance=1.0)
    assert not got["passed"] and "w is 162" in got["requirements"][0]["detail"]


def test_uneven_spacing_fails_distribution():
    nodes = doc()
    nodes[3]["x"] = 460
    assert not cc.check(REQS[4:5], nodes, tolerance=1.0)["passed"]


def test_a_box_outside_the_group_fails_grouping():
    nodes = doc()
    nodes[3]["parent"] = None
    got = cc.check(REQS[5:6], nodes, tolerance=1.0)
    assert not got["passed"] and "Box C" in got["requirements"][0]["detail"]


def test_a_connector_that_misses_its_target_fails():
    nodes = doc()
    nodes[5]["points"] = [[200, 140], [300, 300]]
    assert not cc.check(REQS[6:7], nodes, tolerance=1.0)["passed"]


def test_two_nodes_answering_one_selector_fail_rather_than_pick_one():
    nodes = doc() + [box("a2", "Box A", 40, 300)]
    got = cc.check(REQS[1:2], nodes, tolerance=1.0)
    assert not got["passed"] and "2 nodes" in got["requirements"][0]["detail"]


def test_nested_fields_and_ratios_are_compared():
    nodes = [{"id": "f", "type": "frame", "name": "Card", "parent": None, "x": 0, "y": 0, "w": 320, "h": 400,
              "layout": {"mode": "vertical", "gap": 12, "padding": 16}},
             {"id": "i", "type": "image", "name": "Photo", "parent": "f", "x": 16, "y": 16, "w": 288, "h": 216,
              "image": {"fit": "crop"}}]
    reqs = [{"id": "auto-layout", "node": {"name": "Card"}, "expect": {"layout.mode": "vertical", "layout.gap": 12}},
            {"id": "photo-4x3", "node": {"name": "Photo"}, "expect": {"image.fit": "crop"}, "aspect": [4, 3]}]
    assert cc.check(reqs, nodes, tolerance=1.0)["passed"]
    nodes[1]["h"] = 162
    got = cc.check(reqs, nodes, tolerance=1.0)
    assert [r["id"] for r in got["requirements"] if not r["passed"]] == ["photo-4x3"]


def test_order_along_an_axis_is_checked():
    req = [{"id": "left-to-right", "ordered": {"names": ["Box A", "Box B", "Box C"], "axis": "x"}}]
    assert cc.check(req, doc(), tolerance=1.0)["passed"]
    nodes = doc()
    nodes[1]["x"], nodes[2]["x"] = nodes[2]["x"], nodes[1]["x"]
    assert not cc.check(req, nodes, tolerance=1.0)["passed"]


def test_an_exported_file_is_checked_in_the_working_folder_only(tmp_path):
    req = [{"id": "exported", "file": {"path": "diagram.svg", "magic": "<svg"}}]
    assert not cc.check(req, doc(), tolerance=1.0, root=tmp_path)["passed"]
    (tmp_path / "diagram.svg").write_text("<?xml version='1.0'?><svg/>", encoding="utf-8")
    assert cc.check(req, doc(), tolerance=1.0, root=tmp_path)["passed"]
    (tmp_path / "diagram.svg").write_text("not an svg", encoding="utf-8")
    assert not cc.check(req, doc(), tolerance=1.0, root=tmp_path)["passed"]
    assert not cc.check(req, doc(), tolerance=1.0)["passed"]
    with pytest.raises(ValueError, match="working folder"):
        cc.validate([{"id": "x", "file": {"path": "../escape.svg", "magic": "<svg"}}])


@pytest.mark.parametrize("bad, why", [
    ({"id": "x"}, "one of"),
    ({"count": {"type": "rect"}, "equals": 3}, "id"),
    ({"id": "x", "count": {"type": "rect"}}, "equals"),
    ({"id": "x", "aligned": {"names": ["A"], "edge": "diagonal"}}, "edge"),
    ({"id": "x", "node": {"name": "A"}, "count": {"type": "rect"}, "equals": 1}, "one of"),
])
def test_a_malformed_requirement_is_refused_at_load(bad, why):
    with pytest.raises(ValueError, match=why):
        cc.validate([bad])


def test_duplicate_requirement_ids_are_refused():
    with pytest.raises(ValueError, match="twice"):
        cc.validate([REQS[0], REQS[0]])


def test_identical_renders_differ_by_nothing_and_a_blank_one_by_a_lot(tmp_path):
    from PIL import Image, ImageDraw
    a = Image.new("RGBA", (64, 48), "white")
    ImageDraw.Draw(a).rectangle([8, 8, 40, 30], fill="black")
    a.save(tmp_path / "a.png")
    a.save(tmp_path / "b.png")
    Image.new("RGBA", (64, 48), (0, 0, 0, 0)).save(tmp_path / "blank.png")
    assert cc.render_difference(tmp_path / "a.png", tmp_path / "b.png") == 0.0
    assert cc.render_difference(tmp_path / "a.png", tmp_path / "blank.png") > 0.1
    Image.new("RGBA", (32, 48), "white").save(tmp_path / "small.png")
    assert cc.render_difference(tmp_path / "a.png", tmp_path / "small.png") == 1.0

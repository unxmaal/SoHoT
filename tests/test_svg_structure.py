"""The svg structure assertion: every property is read from the markup, deterministically. #1050."""
import pytest

from evals.core import Case, load_case, score
from harness.checks import svg

NS = 'xmlns="http://www.w3.org/2000/svg"'


def doc(body: str, vb: str = "0 0 100 100") -> str:
    return f'<svg {NS} viewBox="{vb}">{body}</svg>'


DOTS = '<circle cx="20" cy="50" r="5" fill="#E63946"/><circle cx="60" cy="50" r="5" fill="rgb(230,57,70)"/>'


@pytest.mark.parametrize("spec", [
    {"viewbox": [0, 0, 100, 100]},
    {"count": {"circle": 2}},
    {"marks": 2},
    {"tally": {"#e63946": 2}},
    {"fill": {"circle": "#e63946", "*": "#e63946"}},
    {"order": {"tag": "circle", "axis": "x", "fills": ["#e63946", "#e63946"]}},
    {"inside": True},
])
def test_a_drawing_that_meets_its_spec_passes(spec):
    assert svg.structure(doc(DOTS), spec) == ""


@pytest.mark.parametrize("spec,why", [
    ({"viewbox": [0, 0, 200, 100]}, "viewBox"),
    ({"count": {"circle": 3}}, "exactly 3 <circle>"),
    ({"count": {"rect": 1}}, "exactly 1 <rect>"),
    ({"marks": 1}, "visible shapes"),
    ({"tally": {"#e63946": 1}}, "filled #e63946"),
    ({"fill": {"circle": "#457b9d"}}, "expected #457b9d"),
    ({"order": {"tag": "circle", "axis": "x", "fills": ["#e63946", "#457b9d"]}}, "in order"),
])
def test_one_property_off_is_refused_and_named(spec, why):
    assert why in svg.structure(doc(DOTS), spec)


def test_fill_is_inherited_from_a_group_and_style_beats_the_attribute():
    body = '<g fill="#457b9d"><circle cx="5" cy="5" r="2"/><circle cx="9" cy="5" r="2" style="fill:#e63946"/></g>'
    assert svg.structure(doc(body), {"tally": {"#457b9d": 1, "#e63946": 1}}) == ""
    assert "#000000" in svg.structure(doc('<circle cx="5" cy="5" r="2"/>'), {"fill": {"circle": "#457b9d"}})


def test_shapes_in_defs_and_shapes_with_no_extent_are_not_counted():
    body = '<defs><circle id="d" cx="1" cy="1" r="1"/></defs><circle cx="5" cy="5" r="0"/><circle cx="5" cy="5" r="2"/>'
    assert svg.structure(doc(body), {"count": {"circle": 1}}) == ""


def test_a_grid_is_read_row_by_row():
    cells = "".join(f'<rect x="{x}" y="{y}" width="10" height="10" fill="{f}"/>'
                    for y, x, f in ((10, 10, "#000001"), (0, 10, "#000002"), (0, 0, "#000003"), (10, 0, "#000004")))
    want = ["#000003", "#000002", "#000004", "#000001"]
    assert svg.structure(doc(cells), {"order": {"tag": "rect", "axis": "yx", "fills": want}}) == ""
    assert svg.structure(doc(cells), {"order": {"tag": "rect", "axis": "x", "fills": want}})


def test_labels_are_the_text_elements_as_a_multiset():
    body = '<text x="1" y="9">alpha</text><text x="5" y="9"><tspan>v1.2</tspan> </text>'
    assert svg.structure(doc(body), {"labels": ["v1.2", "alpha"]}) == ""
    assert "text reads" in svg.structure(doc(body), {"labels": ["alpha"]})
    assert "text reads" in svg.structure(doc(body), {"labels": ["alpha", "v1.2", "v1.2"]})


def test_closed_paths_need_every_subpath_closed():
    good = '<path d="M1,1 L9,1 L5,9 Z" fill="#000001"/><path d="M1 1 L2 2 z M3 3 L4 4 Z"/>'
    assert svg.structure(doc(good), {"closed": 2}) == ""
    open_one = '<path d="M1,1 L9,1 L5,9 Z"/><path d="M1 1 L2 2 Z M3 3 L4 4"/>'
    assert "1 closed" in svg.structure(doc(open_one), {"closed": 2})


def test_a_group_holds_exactly_what_it_should():
    body = '<g id="a"><circle cx="5" cy="5" r="2"/></g><g id="b"><rect x="1" y="1" width="2" height="2"/></g>'
    assert svg.structure(doc(body), {"groups": {"a": {"circle": 1, "rect": 0}, "b": {"rect": 1}}}) == ""
    assert "holds 0 <circle>" in svg.structure(doc(body), {"groups": {"b": {"circle": 1}}})
    assert "no <g id='c'>" in svg.structure(doc(body), {"groups": {"c": {"circle": 1}}})


def test_bars_stand_on_the_baseline_at_the_given_scale():
    bars = '<rect x="10" y="60" width="5" height="30"/><rect x="20" y="70" width="5" height="20"/>'
    want = {"values": [3, 2], "unit": 10, "base": 90}
    assert svg.structure(doc(bars), {"heights": want}) == ""
    hanging = '<rect x="10" y="90" width="5" height="30"/><rect x="20" y="70" width="5" height="20"/>'
    assert "standing on y=90" in svg.structure(doc(hanging), {"heights": want})
    assert "standing on y=90" in svg.structure(doc(bars), {"heights": {**want, "unit": 11}})


def test_a_shape_past_the_viewbox_edge_is_refused():
    assert "spills" in svg.structure(doc('<circle cx="98" cy="50" r="5"/>'), {"inside": True})
    assert "spills" in svg.structure(doc('<line x1="0" y1="0" x2="120" y2="5" stroke="#000001"/>'), {"inside": True})
    assert "no viewBox" in svg.structure(f'<svg {NS}><circle cx="5" cy="5" r="2"/></svg>', {"inside": True})


def test_a_ring_starts_at_the_top_and_runs_clockwise_in_any_document_order():
    dots = ['<circle cx="50" cy="20" r="2"/>', '<circle cx="80" cy="50" r="2"/>',
            '<circle cx="50" cy="80" r="2"/>', '<circle cx="20" cy="50" r="2"/>']
    want = {"cx": 50, "cy": 50, "r": 30, "n": 4}
    assert svg.structure(doc("".join(reversed(dots))), {"ring": want}) == ""
    assert "position 2" in svg.structure(doc("".join(dots[:3])), {"ring": {**want, "n": 3}})
    tilted = dots[:1] + ['<circle cx="78" cy="58" r="2"/>'] + dots[2:]
    assert "position 2" in svg.structure(doc("".join(tilted)), {"ring": want})


def test_clock_hands_are_told_apart_by_length_and_read_clockwise_from_twelve():
    # 3:30: hour hand at 105 degrees, minute hand straight down.
    hour = '<line x1="50" y1="50" x2="69.32" y2="55.18" stroke="#000001"/>'
    minute = '<line x1="50" y1="50" x2="50" y2="85" stroke="#000001"/>'
    want = {"cx": 50, "cy": 50, "hour": 105, "minute": 180}
    assert svg.structure(doc(minute + hour), {"hands": want}) == ""
    on_the_three = '<line x1="50" y1="50" x2="70" y2="50" stroke="#000001"/>'
    assert "hour hand points at 90" in svg.structure(doc(minute + on_the_three), {"hands": want})
    off_centre = '<line x1="55" y1="50" x2="70" y2="50" stroke="#000001"/>'
    assert "centre" in svg.structure(doc(minute + off_centre), {"hands": want})


def test_concentric_circles_must_be_painted_largest_first():
    big, small = '<circle cx="50" cy="50" r="30" fill="#000001"/>', '<circle cx="50" cy="50" r="10" fill="#000002"/>'
    want = {"cx": 50, "cy": 50, "radii": [30, 10], "fills": ["#000001", "#000002"]}
    assert svg.structure(doc(big + small), {"stack": want}) == ""
    assert "drawing order" in svg.structure(doc(small + big), {"stack": want})


def test_a_transform_is_refused_where_positions_are_read():
    body = '<g transform="translate(5,0)"><circle cx="20" cy="50" r="5"/></g>'
    assert "transform" in svg.structure(doc(body), {"inside": True})
    assert svg.structure(doc(body), {"count": {"circle": 1}}) == ""


def test_an_unknown_structure_key_or_axis_is_refused():
    with pytest.raises(ValueError, match="unknown structure key"):
        svg.structure(doc(DOTS), {"colour": "#000001"})
    with pytest.raises(ValueError, match="axis"):
        svg.validate_structure({"order": {"tag": "rect", "axis": "diagonal", "fills": []}})


def test_a_case_with_a_bad_structure_key_fails_to_load(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("id: bad\nmodality: svg\nprompt: x\nassert:\n  structure:\n    colour: red\n",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="bad.yaml: unknown structure key"):
        load_case(path)


def test_score_applies_the_structure_before_the_rasterizer():
    case = Case(id="s", modality="svg", prompt="two dots", assertions={"structure": {"count": {"circle": 3}}})
    r = score(case, doc(DOTS))
    assert not r.passed and "exactly 3 <circle>" in r.detail

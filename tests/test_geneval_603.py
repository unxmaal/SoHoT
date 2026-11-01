"""GenEval prompts as image staging cases, judged by the pinned detector's boxes. #603."""
import hashlib
import json
from collections import Counter

import pytest

from evals import core, importers
from harness import holdout, staging_controls
from harness.checks import staging


def _mod():
    from evals.importers import geneval
    return geneval


def _box(label, x0, y0, x1, y1, score=0.9, **probes):
    return staging.Box(label, score, x0, y0, x1, y1, probes)


def _ok(spec, boxes):
    return [v.ok for v in staging.evaluate(spec, boxes, uncounted=())]


# --- the requirement shapes GenEval needs ----------------------------------

def test_count_min_counts_at_least():
    spec = {"objects": {"cup": "a cup"}, "require": [{"type": "count", "object": "cup", "min": 2}]}
    two = [_box("cup", 0.1, 0.1, 0.2, 0.2), _box("cup", 0.5, 0.5, 0.6, 0.6)]
    assert _ok(spec, two) == [True]
    assert _ok(spec, two + [_box("cup", 0.7, 0.1, 0.8, 0.2)]) == [True]
    assert _ok(spec, two[:1]) == [False]


def test_left_of_follows_genevals_margin():
    cat, dog = _box("cat", 0.05, 0.4, 0.25, 0.6), _box("dog", 0.7, 0.4, 0.9, 0.6)
    assert staging.left_of(cat, dog)
    assert not staging.left_of(dog, cat)
    close = _box("cat", 0.45, 0.4, 0.65, 0.6)
    assert not staging.left_of(close, _box("dog", 0.5, 0.4, 0.7, 0.6))
    above = _box("cat", 0.4, 0.0, 0.5, 0.1)
    assert not staging.left_of(above, _box("dog", 0.45, 0.8, 0.55, 0.9))
    spec = {"objects": {"cat": "a cat", "dog": "a dog"},
            "require": [{"type": "left_of", "object": "cat", "of": "dog"}]}
    assert _ok(spec, [cat, dog]) == [True]
    assert _ok(spec, [_box("cat", 0.7, 0.4, 0.9, 0.6), _box("dog", 0.05, 0.4, 0.25, 0.6)]) == [False]
    assert _ok(spec, [cat]) == [False]


def test_attribute_against_several_contrasts_needs_the_highest():
    spec = {"objects": {"car": "a car"},
            "require": [{"type": "attribute", "object": "car", "is": "a red car",
                         "not": ["a blue car", "a green car"]}]}
    assert staging.probes(spec) == ["a red car", "a blue car", "a green car"]
    red = {"a red car": 0.6, "a blue car": 0.2, "a green car": 0.3}
    assert _ok(spec, [_box("car", 0.1, 0.1, 0.5, 0.5, **red)]) == [True]
    greenish = {"a red car": 0.6, "a blue car": 0.2, "a green car": 0.7}
    assert _ok(spec, [_box("car", 0.1, 0.1, 0.5, 0.5, **greenish)]) == [False]


@pytest.mark.parametrize("bad,why", [
    ({"type": "count", "object": "cup", "n": 1, "min": 1}, "one of n or min"),
    ({"type": "count", "object": "cup", "min": -1}, "whole number"),
    ({"type": "left_of", "object": "cup"}, "of"),
    ({"type": "attribute", "object": "cup", "is": "a red cup", "not": []}, "is and not"),
])
def test_a_malformed_geneval_requirement_is_refused(bad, why):
    with pytest.raises(ValueError, match=why):
        staging.validate({"objects": {"cup": "a cup", "mug": "a mug"}, "require": [bad]})


def test_the_new_shapes_have_drawn_controls_with_planted_breaks():
    rows = {r["scene"]: r for r in staging_controls.run(detector=False)}
    assert rows["relations"]["expected"] == [] and rows["relations"]["ok"]
    broken = [r for name, r in rows.items() if name.startswith("relations-")]
    assert sorted(i for r in broken for i in r["expected"]) == list(range(len(staging_controls.RELATIONS["require"])))
    assert all(r["ok"] for r in broken)


# --- the importer ----------------------------------------------------------

def test_the_recorded_metadata_matches_its_pinned_digest():
    mod = _mod()
    data = mod.RECORDED.read_bytes()
    assert hashlib.sha256(data).hexdigest() == mod.SHA256
    assert len(mod.fetch()) == 553


def test_every_geneval_tag_maps_to_staging_requirements():
    mod = _mod()
    by_tag = {}
    for row in mod.fetch():
        by_tag.setdefault(row["tag"], row)
    count = mod.convert(by_tag["counting"]).case["assert"]["staging"]["require"]
    assert [r["type"] for r in count] == ["count"] and "n" in count[0] and "min" not in count[0]
    single = mod.convert(by_tag["single_object"]).case["assert"]["staging"]["require"]
    assert single == [{"type": "count", "object": single[0]["object"], "min": 1}]
    colours = mod.convert(by_tag["colors"]).case["assert"]["staging"]["require"]
    attr = next(r for r in colours if r["type"] == "attribute")
    assert len(attr["not"]) == len(mod.COLORS) - 1 and attr["is"] not in attr["not"]
    for row in mod.fetch():
        if row["tag"] != "position":
            continue
        req = mod.convert(row).case["assert"]["staging"]["require"]
        rel = row["include"][1]["position"][0]
        me, other = (row["include"][i]["class"].replace(" ", "_") for i in (1, row["include"][1]["position"][1]))
        want = {"above": {"type": "above", "object": me, "over": other},
                "below": {"type": "above", "object": other, "over": me},
                "left of": {"type": "left_of", "object": me, "of": other},
                "right of": {"type": "left_of", "object": other, "of": me}}[rel]
        assert [r for r in req if r["type"] != "count"] == [want], row["prompt"]


def test_every_case_is_attributed_to_geneval_at_the_pinned_revision():
    mod = _mod()
    assert mod.LICENSE == "MIT" and mod.LICENSE in importers.ALLOWED_LICENSES and len(mod.REVISION) == 40
    for row in mod.fetch()[:20]:
        case = mod.convert(row).case
        att = case["attribution"]
        assert att["revision"] == mod.REVISION and att["license"] == "MIT" and att["date"] == mod.ITEM_DATE
        assert att["tag"] == row["tag"] and case["prompt"] == row["prompt"]


def test_the_committed_cases_are_what_the_importer_writes():
    mod = _mod()
    want = {f"{m.case['id']}.yaml": importers._dump(mod, m.case) for m in map(mod.convert, mod.fetch())}
    out = importers.CASES / mod.LANE / "geneval"
    have = {p.name: p.read_text(encoding="utf-8") for p in out.glob("*.yaml")}
    assert set(have) == set(want)
    assert all(have[k] == v for k, v in want.items())


def _committed():
    return core.load_cases(importers.CASES / "image" / "geneval")


def _tag(case):
    import yaml
    return yaml.load(case.source.read_text(encoding="utf-8"), Loader=core._LOADER)["attribution"]["tag"]


def test_the_negative_control_separates_reference_boxes_from_empty_and_another_case():
    mod = _mod()
    cases = _committed()
    got = importers.negative_control(cases, mod.RESPONDERS, mod.passes)
    assert {k: v[0] for k, v in got.items()} == {"reference": 553, "empty": 0, "other-case": 0}


def test_each_reference_fails_once_one_box_is_dropped():
    mod = _mod()
    for c in _committed()[::7]:
        boxes = mod.reference_boxes(c.assertions["staging"])
        assert not mod.passes(c, boxes[1:]), c.id


def test_the_cases_cover_every_tag_and_split_by_content_digest():
    cases = _committed()
    assert Counter(_tag(c) for c in cases) == Counter(
        {"position": 100, "color_attr": 100, "two_object": 99, "colors": 94, "single_object": 80, "counting": 80})
    split = holdout.for_lane("image")
    assert len(split.holdout) >= 130
    assert len({c.id for c in cases} & set(split.holdout)) == len(
        [c for c in cases if holdout._draw(c) < holdout.FRACTION])


def test_staging_queries_are_the_geneval_class_names():
    for c in _committed():
        objects = c.assertions["staging"]["objects"]
        assert all(q == f"a {name.replace('_', ' ')}" for name, q in objects.items()), c.id
        json.dumps(objects)
